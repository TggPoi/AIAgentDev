from collections.abc import AsyncGenerator
from time import perf_counter

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.rerankers.base import BaseReranker
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.core.langsmith import (
    build_rag_langsmith_inputs,
    build_rag_langsmith_metadata,
    build_rag_langsmith_tags,
    rag_langsmith_trace,
)
from fast_app.core.latency import log_slow_operation
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.conversation_models import ConversationMessage, ConversationRole
from fast_app.domain.rag_stream_models import RagStreamEvent
from fast_app.graph.rag_agent_builder import build_rag_agent_graph
from fast_app.graph.rag_agent_nodes import (
    build_rag_agent_step_inputs,
    create_agent_build_context_node,
    create_agent_error_answer_node,
    create_agent_fail_request_node,
    create_call_knowledge_retrieval_node,
    create_check_loop_limits_node,
    create_plan_next_action_node,
    create_rag_agent_direct_answer_node,
    create_agent_rerank_node,
    rag_agent_langsmith_step_trace,
    route_after_loop_check,
    route_after_tool_call,
)
from fast_app.graph.rag_agent_state import (
    RagAgentOperation,
    RagAgentState,
    build_rag_agent_initial_state,
)
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse
from fast_app.services.conversation_history import (
    build_conversation_memory_context,
    load_recent_history_window,
)
from fast_app.services.conversation_memory import ConversationMemoryStore
from fast_app.services.conversation_persistence import ConversationPersistenceService
from fast_app.services.conversation_summary import ConversationSummaryService
from fast_app.services.exceptions import ExternalServiceError
from fast_app.services.query_rewrite import ConversationQueryRewriter
from fast_app.services.rag_pipeline_service import docs_to_sources


logger = get_logger(__name__)


class RagAgentPipeline:
    """显式 LangGraph RAG Agent 的 FastAPI pipeline 适配层。"""

    def __init__(
        self,
        settings: Settings,
        vector_retriever: BaseRetriever,
        keyword_retriever: BaseRetriever,
        llm_client: BaseLLMClient,
        reranker: BaseReranker,
        conversation_memory_store: ConversationMemoryStore | None = None,
        query_rewriter: ConversationQueryRewriter | None = None,
        conversation_persistence: ConversationPersistenceService | None = None,
        conversation_summary_service: ConversationSummaryService | None = None,
    ):
        # 保存底层组件引用，方便非流式 graph 和流式手写路径复用同一批依赖。
        self.settings = settings
        self.vector_retriever = vector_retriever
        self.keyword_retriever = keyword_retriever
        self.llm_client = llm_client
        self.reranker = reranker
        self.conversation_memory_store = conversation_memory_store
        self.query_rewriter = query_rewriter
        self.conversation_persistence = conversation_persistence
        self.conversation_summary_service = conversation_summary_service
        # run() 使用 compiled graph，完整展示 LangGraph Agent 状态机。
        self.graph = build_rag_agent_graph(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            llm_client=llm_client,
            reranker=reranker,
            rerank_top_k=settings.rerank_top_k,
        )

        # stream / stream_events 需要在生成阶段逐 token yield。
        # compiled graph 的 ainvoke 更适合一次性拿 final_state，所以这里额外保留节点函数，
        # 让流式入口可以手动按同样顺序推进 state，但不改变 pipeline.stream() 的 token-only 协议。
        self.plan_next_action_node = create_plan_next_action_node(settings=settings)
        self.check_loop_limits_node = create_check_loop_limits_node(settings=settings)
        self.direct_answer_node = create_rag_agent_direct_answer_node(
            settings=settings
        )
        self.call_knowledge_retrieval_node = create_call_knowledge_retrieval_node(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
        )
        self.rerank_node = create_agent_rerank_node(
            settings=settings,
            reranker=reranker,
            rerank_top_k=settings.rerank_top_k,
        )
        self.build_context_node = create_agent_build_context_node(settings=settings)
        self.error_answer_node = create_agent_error_answer_node(settings=settings)
        self.fail_request_node = create_agent_fail_request_node(settings=settings)

    def _langsmith_trace(self, req: RagChatRequest, operation: str):
        # pipeline 级 trace 记录一次完整请求；节点级 trace 在 rag_agent_nodes.py 中完成。
        return rag_langsmith_trace(
            settings=self.settings,
            name=f"rag_agent_pipeline.{operation}",
            inputs=build_rag_langsmith_inputs(req),
            metadata=build_rag_langsmith_metadata(
                settings=self.settings,
                req=req,
                pipeline_provider="rag_agent",
            ),
            tags=build_rag_langsmith_tags(
                settings=self.settings,
                pipeline_provider="rag_agent",
                operation=operation,
            ),
        )

    def _build_initial_state(
        self,
        req: RagChatRequest,
        operation: RagAgentOperation,
    ) -> RagAgentState:
        # 所有入口统一走同一个 initial_state builder，避免 run/stream/events 初始字段不一致。
        return build_rag_agent_initial_state(req=req, operation=operation)

    async def _prepare_initial_state(
        self,
        req: RagChatRequest,
        operation: RagAgentOperation,
    ) -> RagAgentState:
        """构造 Agent 初始 state，并在进入 graph 前完成 query rewrite。"""

        state = self._build_initial_state(req=req, operation=operation)

        with rag_agent_langsmith_step_trace(
            settings=self.settings,
            state=state,
            step_name="query_rewrite",
            run_type="chain",
            inputs=build_rag_agent_step_inputs(
                state,
                max_history_turns=self.settings.memory_history_max_turns,
                query_rewrite_enabled=self.settings.query_rewrite_enabled,
                summary_memory_enabled=self.settings.summary_memory_enabled,
            ),
        ) as trace_run:
            if req.session_id is None:
                state["query_rewrite_reason"] = "session_id_empty"
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "original_query": req.query,
                            "rewritten_query": req.query,
                            "effective_query": state["query"],
                            "used_history": False,
                            "query_rewrite_reason": state["query_rewrite_reason"],
                            "history_message_count": 0,
                            "summary_used": False,
                            "summary_version": None,
                            "summary_source_message_count": 0,
                        }
                    )
                return state

            if self.conversation_memory_store is None or self.query_rewriter is None:
                state["query_rewrite_reason"] = "memory_or_rewriter_unavailable"
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "original_query": req.query,
                            "rewritten_query": req.query,
                            "effective_query": state["query"],
                            "used_history": False,
                            "query_rewrite_reason": state["query_rewrite_reason"],
                            "history_message_count": 0,
                            "summary_used": False,
                            "summary_version": None,
                            "summary_source_message_count": 0,
                        }
                    )
                return state

            history_window = await load_recent_history_window(
                store=self.conversation_memory_store,
                conversation_id=req.session_id,
                max_turns=self.settings.memory_history_max_turns,
            )

            # 获取summary上下文
            summary = None
            if self.conversation_summary_service is not None:
                summary = await self.conversation_summary_service.maybe_update_summary(
                    conversation_id=req.session_id,
                    recent_window=history_window,
                )
                memory_context = self.conversation_summary_service.build_memory_context(
                    conversation_id=req.session_id,
                    recent_window=history_window,
                    summary=summary,
                )

            else:
                memory_context = build_conversation_memory_context(
                    conversation_id=req.session_id,
                    recent_window=history_window,
                )

            # 将上下文用于 query rewrite
            rewrite_result = await self.query_rewriter.rewrite(
                query=req.query,
                memory_context=memory_context,
            )

            state["history_window_text"] = history_window.formatted_text
            state["summary_text"] = memory_context.summary_text
            state["summary_used"] = memory_context.summary_text is not None
            state["summary_version"] = memory_context.summary_version
            state["summary_source_message_count"] = (
                memory_context.summary_source_message_count
            )
            state["summary_source_message_ids"] = (
                memory_context.summary_source_message_ids
            )
            state["rewritten_query"] = rewrite_result.rewritten_query
            state["query_rewrite_reason"] = rewrite_result.reason
            state["query"] = rewrite_result.rewritten_query

            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "original_query": rewrite_result.original_query,
                        "rewritten_query": rewrite_result.rewritten_query,
                        "effective_query": state["query"],
                        "used_history": rewrite_result.used_history,
                        "query_rewrite_reason": rewrite_result.reason,
                        "history_message_count": len(history_window.messages),
                        "history_window_chars": len(history_window.formatted_text),
                        "summary_used": state["summary_used"],
                        "summary_version": state["summary_version"],
                        "summary_source_message_count": state[
                            "summary_source_message_count"
                        ],
                    }
                )

            logger.info(
                "rag_agent_query_rewrite %s",
                format_log_fields(
                    event="rag_agent.query_rewrite.applied",
                    session_id=req.session_id,
                    original_query=rewrite_result.original_query,
                    rewritten_query=rewrite_result.rewritten_query,
                    used_history=rewrite_result.used_history,
                    used_summary=state["summary_used"],
                    summary_version=state["summary_version"],
                    reason=rewrite_result.reason,
                    history_message_count=len(history_window.messages),
                ),
            )

        return state

    async def _save_conversation_turn(
        self,
        req: RagChatRequest,
        state: RagAgentState,
        answer: str,
        source_count: int,
    ) -> None:
        """把当前轮 user / assistant 消息写入短期 memory，供下一轮 rewrite 使用。"""

        if req.session_id is None or self.conversation_memory_store is None:
            return

        metadata = {
            "rewritten_query": state.get("rewritten_query"),
            "query_rewrite_reason": state.get("query_rewrite_reason"),
            "source_count": source_count,
            "summary_used": state.get("summary_used", False),
            "summary_version": state.get("summary_version"),
            "summary_source_message_count": state.get(
                "summary_source_message_count",
                0,
            ),
        }

        try:
            await self.conversation_memory_store.append_message(
                ConversationMessage(
                    conversation_id=req.session_id,
                    role=ConversationRole.USER,
                    content=state.get("original_query") or req.query,
                    metadata=metadata,
                )
            )
            await self.conversation_memory_store.append_message(
                ConversationMessage(
                    conversation_id=req.session_id,
                    role=ConversationRole.ASSISTANT,
                    content=answer,
                    metadata=metadata,
                )
            )
            logger.info(
                "rag_agent_memory %s",
                format_log_fields(
                    event="rag_agent.memory.turn_saved",
                    session_id=req.session_id,
                    answer_length=len(answer),
                    source_count=source_count,
                    query_rewrite_reason=state.get("query_rewrite_reason"),
                    summary_used=state.get("summary_used", False),
                    summary_version=state.get("summary_version"),
                ),
            )
        except Exception as exc:
            logger.exception(
                "rag_agent_memory %s",
                format_log_fields(
                    event="rag_agent.memory.turn_save_failed",
                    session_id=req.session_id,
                    error_type=type(exc).__name__,
                ),
            )

    async def _persist_conversation_turn(
        self,
        req: RagChatRequest,
        state: RagAgentState,
        answer: str,
        source_count: int,
        operation: RagAgentOperation,
        raise_on_error: bool,
    ) -> None:
        """把当前轮 user / assistant 消息持久化到 PostgreSQL。

        非流式 run 在响应返回前完成持久化，失败时继续抛错。
        流式入口通常已经把 token 发给客户端，持久化失败只记录日志，避免破坏
        已经完成的 token-only / stream_events SSE 协议。
        """

        if req.session_id is None or self.conversation_persistence is None:
            return

        metadata = {
            "pipeline_provider": "rag_agent",
            "operation": operation,
            "original_query": state.get("original_query") or req.query,
            "effective_query": state.get("query"),
            "rewritten_query": state.get("rewritten_query"),
            "query_rewrite_reason": state.get("query_rewrite_reason"),
            "source_count": source_count,
            "final_reason": state.get("final_reason"),
            "summary_used": state.get("summary_used", False),
            "summary_version": state.get("summary_version"),
            "summary_source_message_count": state.get(
                "summary_source_message_count",
                0,
            ),
        }

        try:
            await self.conversation_persistence.save_turn(
                conversation_id=req.session_id,
                user_content=state.get("original_query") or req.query,
                assistant_content=answer,
                metadata=metadata,
            )
            logger.info(
                "rag_agent_persistence %s",
                format_log_fields(
                    event="rag_agent.persistence.turn_saved",
                    session_id=req.session_id,
                    operation=operation,
                    source_count=source_count,
                    query_rewrite_reason=state.get("query_rewrite_reason"),
                    summary_used=state.get("summary_used", False),
                    summary_version=state.get("summary_version"),
                ),
            )
        except Exception as exc:
            logger.exception(
                "rag_agent_persistence %s",
                format_log_fields(
                    event="rag_agent.persistence.turn_save_failed",
                    session_id=req.session_id,
                    operation=operation,
                    error_type=type(exc).__name__,
                ),
            )
            if raise_on_error:
                raise

    async def run(self, req: RagChatRequest) -> RagChatResponse:
        # 非流式入口可以直接运行 compiled graph，最后把 final_state 转成 API response。
        with self._langsmith_trace(req, "run"):
            return await self._run(req)

    async def _run(self, req: RagChatRequest) -> RagChatResponse:
        start_time = perf_counter()
        logger.info(
            "rag_agent_pipeline %s",
            format_log_fields(
                event="rag_agent.pipeline.start",
                pipeline_provider="rag_agent",
                query=req.query,
                mode=req.mode,
                top_k=req.top_k,
                candidate_k=req.candidate_k,
                min_score=req.min_score,
            ),
        )

        try:
            initial_state = await self._prepare_initial_state(req, operation="run")
            # graph.ainvoke 会按 rag_agent_builder.py 中定义的边执行到 END。
            final_state = await self.graph.ainvoke(initial_state)
            answer = final_state.get("answer") or ""
            docs = final_state.get("docs") or []

            # redis写入
            await self._save_conversation_turn(
                req=req,
                state=final_state,
                answer=answer,
                source_count=len(docs),
            )

            # postgreSQL写入
            await self._persist_conversation_turn(
                req=req,
                state=final_state,
                answer=answer,
                source_count=len(docs),
                operation="run",
                raise_on_error=True,
            )
        except Exception as exc:
            latency_ms = (perf_counter() - start_time) * 1000
            logger.exception(
                "rag_agent_pipeline %s",
                format_log_fields(
                    event="rag_agent.pipeline.failed",
                    pipeline_provider="rag_agent",
                    query=req.query,
                    mode=req.mode,
                    top_k=req.top_k,
                    candidate_k=req.candidate_k,
                    min_score=req.min_score,
                    latency_ms=round(latency_ms, 2),
                    error_type=type(exc).__name__,
                ),
            )
            log_slow_operation(
                logger=logger,
                event="rag_agent.pipeline.slow",
                latency_ms=latency_ms,
                threshold_ms=self.settings.slow_rag_pipeline_threshold_ms,
                slow_component="pipeline",
                pipeline_provider="rag_agent",
                status="failed",
                query=req.query,
                mode=req.mode,
                top_k=req.top_k,
                error_type=type(exc).__name__,
            )
            raise

        latency_ms = (perf_counter() - start_time) * 1000
        logger.info(
            "rag_agent_pipeline %s",
            format_log_fields(
                event="rag_agent.pipeline.finish",
                pipeline_provider="rag_agent",
                query=req.query,
                mode=req.mode,
                top_k=req.top_k,
                candidate_k=req.candidate_k,
                min_score=req.min_score,
                effective_query=final_state.get("query"),
                original_query=final_state.get("original_query"),
                rewritten_query=final_state.get("rewritten_query"),
                query_rewrite_reason=final_state.get("query_rewrite_reason"),
                summary_used=final_state.get("summary_used", False),
                summary_version=final_state.get("summary_version"),
                latency_ms=round(latency_ms, 2),
                source_count=len(docs),
                answer_length=len(answer),
                final_reason=final_state.get("final_reason"),
            ),
        )
        log_slow_operation(
            logger=logger,
            event="rag_agent.pipeline.slow",
            latency_ms=latency_ms,
            threshold_ms=self.settings.slow_rag_pipeline_threshold_ms,
            slow_component="pipeline",
            pipeline_provider="rag_agent",
            status="success",
            query=req.query,
            mode=req.mode,
            top_k=req.top_k,
            source_count=len(docs),
            answer_length=len(answer),
        )

        return RagChatResponse(
            # RagChatResponse 仍保持普通 RAG API 的 answer + sources 结构。
            query=final_state["query"],
            answer=answer,
            sources=docs_to_sources(docs),
        )

    async def _prepare_stream_state(
        self,
        req: RagChatRequest,
        operation: RagAgentOperation,
    ) -> RagAgentState:
        # 流式入口和 run 共享前半段 Agent 决策链路：
        # plan -> loop check -> direct/error/tool -> rerank。
        # 这里停在 build_context 之前，是为了让 stream_events 可以先发 sources。
        state = await self._prepare_initial_state(req, operation=operation)

        plan_update = await self.plan_next_action_node(state)
        # 手写流式路径需要显式 state.update，模拟 LangGraph partial state merge。
        state.update(plan_update)

        loop_update = await self.check_loop_limits_node(state)
        state.update(loop_update)

        next_route = route_after_loop_check(state)
        if next_route == "direct_answer":
            # 直接回答路径没有 sources，也不需要进入检索和 LLM。
            direct_update = await self.direct_answer_node(state)
            state.update(direct_update)
            return state

        if next_route == "final_error_answer":
            # loop limit 等可解释错误在 Agent 内部转成最终回答。
            error_update = await self.error_answer_node(state)
            state.update(error_update)
            return state

        tool_update = await self.call_knowledge_retrieval_node(state)
        state.update(tool_update)

        tool_route = route_after_tool_call(state)
        if tool_route == "final_error_answer":
            # 例如 NoSearchResultError：请求整体成功，但回答说明知识库无可靠资料。
            error_update = await self.error_answer_node(state)
            state.update(error_update)
            return state

        if tool_route == "fail_request":
            # 外部服务失败等不可恢复错误继续抛给 API 层，由现有错误响应/SSE error 包装处理。
            await self.fail_request_node(state)
            raise ExternalServiceError("RAG Agent 请求失败")

        rerank_update = await self.rerank_node(state)
        # 成功检索后，stream 和 stream_events 都先完成 rerank，再由各自入口决定何时构造上下文。
        state.update(rerank_update)

        return state

    async def stream(
        self,
        req: RagChatRequest,
    ) -> AsyncGenerator[str, None]:
        # 对外契约：pipeline.stream() 只能 yield str token。
        # SSE 的 event/data 包装仍由 API 层负责。
        with self._langsmith_trace(req, "stream"):
            async for token in self._stream(req):
                yield token

    async def _stream(
        self,
        req: RagChatRequest,
    ) -> AsyncGenerator[str, None]:
        start_time = perf_counter()
        state = await self._prepare_stream_state(req, operation="stream")

        if state.get("answer") is not None:
            # direct answer / final error answer 已经有完整文本。
            # 为了保持 token-only，这里按字符 yield，和 mock LLM 的字符流行为保持一致。
            token_count = 0
            answer = state["answer"] or ""
            for token in answer:
                token_count += 1
                yield token

            await self._save_conversation_turn(
                req=req,
                state=state,
                answer=answer,
                source_count=len(state.get("docs") or []),
            )
            await self._persist_conversation_turn(
                req=req,
                state=state,
                answer=answer,
                source_count=len(state.get("docs") or []),
                operation="stream",
                raise_on_error=False,
            )

            latency_ms = (perf_counter() - start_time) * 1000
            log_slow_operation(
                logger=logger,
                event="rag_agent.stream.slow",
                latency_ms=latency_ms,
                threshold_ms=self.settings.slow_rag_pipeline_threshold_ms,
                slow_component="pipeline_stream",
                pipeline_provider="rag_agent",
                query=state["query"],
                original_query=state.get("original_query"),
                rewritten_query=state.get("rewritten_query"),
                mode=req.mode,
                top_k=req.top_k,
                token_count=token_count,
                final_reason=state.get("final_reason"),
            )
            return

        build_context_update = await self.build_context_node(state)
        state.update(build_context_update)
        context = state["context"]

        if context is None:
            raise ExternalServiceError("RAG Agent Stream 上下文为空，无法流式生成回答")

        token_count = 0
        with rag_agent_langsmith_step_trace(
            settings=self.settings,
            state=state,
            step_name="stream_generate",
            run_type="chain",
            inputs={
                "query": req.query,
                "effective_query": state["query"],
                "context_doc_count": len(context.docs),
                "context_length": len(context.context_text),
            },
        ) as trace_run:
            # 真正需要知识库回答时，仍然使用 LLM client 的 stream 能力逐 token 输出。
            answer_parts: list[str] = []
            async for token in self.llm_client.stream(state["query"], context):
                token_count += 1
                answer_parts.append(token)
                yield token

            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "token_count": token_count,
                        "source_count": len(context.docs),
                    }
                )

        answer = "".join(answer_parts)
        await self._save_conversation_turn(
            req=req,
            state=state,
            answer=answer,
            source_count=len(context.docs),
        )
        await self._persist_conversation_turn(
            req=req,
            state=state,
            answer=answer,
            source_count=len(context.docs),
            operation="stream",
            raise_on_error=False,
        )

        latency_ms = (perf_counter() - start_time) * 1000
        log_slow_operation(
            logger=logger,
            event="rag_agent.stream.slow",
            latency_ms=latency_ms,
            threshold_ms=self.settings.slow_rag_pipeline_threshold_ms,
            slow_component="pipeline_stream",
            pipeline_provider="rag_agent",
            query=state["query"],
            original_query=state.get("original_query"),
            rewritten_query=state.get("rewritten_query"),
            mode=req.mode,
            top_k=req.top_k,
            token_count=token_count,
            source_count=len(context.docs),
        )

    async def stream_events(
        self,
        req: RagChatRequest,
    ) -> AsyncGenerator[RagStreamEvent, None]:
        # 结构化流式入口仍只产生业务事件 sources/token。
        # done/error 继续由 API SSE 包装层处理，保持和现有协议一致。
        with self._langsmith_trace(req, "stream_events"):
            async for event in self._stream_events(req):
                yield event

    async def _stream_events(
        self,
        req: RagChatRequest,
    ) -> AsyncGenerator[RagStreamEvent, None]:
        start_time = perf_counter()
        state = await self._prepare_stream_state(req, operation="stream_events")

        if state.get("answer") is not None:
            # 直接回答或错误回答没有检索来源，但 stream_events 协议仍先发 sources。
            with rag_agent_langsmith_step_trace(
                settings=self.settings,
                state=state,
                step_name="emit_sources",
                run_type="chain",
                inputs={
                    "doc_count": 0,
                    "top_doc_ids": [],
                    "final_reason": state.get("final_reason"),
                },
            ) as trace_run:
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "source_count": 0,
                            "top_source_ids": [],
                        }
                    )

            yield RagStreamEvent(
                event="sources",
                data={"sources": []},
            )

            token_count = 0
            answer = state["answer"] or ""
            for token in answer:
                token_count += 1
                yield RagStreamEvent(
                    event="token",
                    data={"token": token},
                )

            await self._save_conversation_turn(
                req=req,
                state=state,
                answer=answer,
                source_count=0,
            )
            await self._persist_conversation_turn(
                req=req,
                state=state,
                answer=answer,
                source_count=0,
                operation="stream_events",
                raise_on_error=False,
            )

            latency_ms = (perf_counter() - start_time) * 1000
            log_slow_operation(
                logger=logger,
                event="rag_agent.stream_events.slow",
                latency_ms=latency_ms,
                threshold_ms=self.settings.slow_rag_pipeline_threshold_ms,
                slow_component="pipeline_stream_events",
                pipeline_provider="rag_agent",
                query=state["query"],
                original_query=state.get("original_query"),
                rewritten_query=state.get("rewritten_query"),
                mode=req.mode,
                top_k=req.top_k,
                token_count=token_count,
                source_count=0,
                final_reason=state.get("final_reason"),
            )
            return

        docs = state["docs"]
        # 检索路径先把 sources 发给前端，再开始 token 流。
        # 这和现有 LangGraphRagPipeline.stream_events 的用户体验保持一致。
        with rag_agent_langsmith_step_trace(
            settings=self.settings,
            state=state,
            step_name="emit_sources",
            run_type="chain",
            inputs={
                "doc_count": len(docs),
                "top_doc_ids": [doc.id for doc in docs[:5]],
            },
        ) as trace_run:
            sources = docs_to_sources(docs)
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "source_count": len(sources),
                        "top_source_ids": [source.id for source in sources[:5]],
                    }
                )

        yield RagStreamEvent(
            event="sources",
            data={"sources": sources},
        )

        build_context_update = await self.build_context_node(state)
        state.update(build_context_update)
        context = state["context"]

        if context is None:
            raise ExternalServiceError(
                "RAG Agent Stream Events 上下文为空，无法流式生成回答"
            )

        token_count = 0
        with rag_agent_langsmith_step_trace(
            settings=self.settings,
            state=state,
            step_name="stream_generate",
            run_type="chain",
            inputs={
                "query": req.query,
                "effective_query": state["query"],
                "context_doc_count": len(context.docs),
                "context_length": len(context.context_text),
            },
        ) as trace_run:
            # stream_events 的 token 事件包装在 pipeline 层完成；
            # API 层只负责把 RagStreamEvent 转成 SSE 文本。
            answer_parts: list[str] = []
            async for token in self.llm_client.stream(state["query"], context):
                token_count += 1
                answer_parts.append(token)
                yield RagStreamEvent(
                    event="token",
                    data={"token": token},
                )

            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "token_count": token_count,
                        "source_count": len(context.docs),
                    }
                )

        answer = "".join(answer_parts)
        await self._save_conversation_turn(
            req=req,
            state=state,
            answer=answer,
            source_count=len(context.docs),
        )
        await self._persist_conversation_turn(
            req=req,
            state=state,
            answer=answer,
            source_count=len(context.docs),
            operation="stream_events",
            raise_on_error=False,
        )

        latency_ms = (perf_counter() - start_time) * 1000
        log_slow_operation(
            logger=logger,
            event="rag_agent.stream_events.slow",
            latency_ms=latency_ms,
            threshold_ms=self.settings.slow_rag_pipeline_threshold_ms,
            slow_component="pipeline_stream_events",
            pipeline_provider="rag_agent",
            query=state["query"],
            original_query=state.get("original_query"),
            rewritten_query=state.get("rewritten_query"),
            mode=req.mode,
            top_k=req.top_k,
            token_count=token_count,
            source_count=len(context.docs),
        )
