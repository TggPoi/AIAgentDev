from collections.abc import AsyncGenerator
from time import perf_counter

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.rerankers.base import BaseReranker
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.core.langsmith import (
    build_rag_langchain_child_config,
    build_rag_langchain_pipeline_child_config,
    rag_langsmith_pipeline_trace,
    sanitize_langsmith_payload,
)
from fast_app.core.latency import log_slow_operation
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.conversation_models import ConversationMessage, ConversationRole
from fast_app.domain.rag_stream_models import RagStreamEvent
from fast_app.graph.rag_agent.rag_agent_builder import build_rag_agent_graph
from fast_app.graph.rag_agent.rag_agent_nodes import (
    build_rag_agent_answer_query,
    build_rag_agent_step_inputs,
    create_agent_build_context_node,
    create_agent_clarification_node,
    create_agent_error_answer_node,
    create_agent_fail_request_node,
    create_call_knowledge_retrieval_node,
    create_call_nl2sql_query_node,
    create_check_loop_limits_node,
    create_execute_task_plan_node,
    create_next_action_decision_node,
    create_rag_agent_direct_answer_node,
    create_agent_rerank_node,
    rag_agent_langsmith_step_trace,
    route_after_loop_check,
    route_after_tool_call,
)
from fast_app.graph.rag_agent.rag_agent_state import (
    RagAgentOperation,
    RagAgentState,
    build_rag_agent_initial_state,
)
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse
from fast_app.services.conversation.conversation_history import (
    build_conversation_memory_context,
    load_recent_history_window,
)
from fast_app.services.conversation.conversation_memory import ConversationMemoryStore
from fast_app.services.conversation.conversation_persistence import ConversationPersistenceService
from fast_app.services.conversation.conversation_scope import (
    get_request_external_session_id,
    get_request_user_id,
)
from fast_app.services.conversation.conversation_summary import ConversationSummaryService
from fast_app.services.exceptions import ExternalServiceError
from fast_app.services.agent_tasks.agent_task_executor import AgentTaskExecutor
from fast_app.services.agent_tasks.agent_task_planner import AgentTaskPlanner
from fast_app.services.agent_tasks.agent_task_router import AgentTaskRouter
from fast_app.services.rag.guarded_streaming import (
    GuardedStreamState,
    guarded_answer_delta_events,
    text_to_async_tokens,
)
from fast_app.services.rag.prompt_guard_service import PromptGuardService
from fast_app.services.rag.markdown_parent_context import MarkdownParentContextExpander
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.conversation.query_rewrite import ConversationQueryRewriter
from fast_app.services.rag.rag_pipeline_service import docs_to_sources
from fast_app.services.nl2sql.service import Nl2SqlService


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
        prompt_guard: PromptGuardService | None = None,
        current_user: CurrentUserContext | None = None,
        task_router: AgentTaskRouter | None = None,
        task_planner: AgentTaskPlanner | None = None,
        task_executor: AgentTaskExecutor | None = None,
        parent_expander: MarkdownParentContextExpander | None = None,
        nl2sql_service: Nl2SqlService | None = None,
    ):
        """保存依赖并构建非流式图与流式路径共用的 Agent 节点。"""
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
        self.prompt_guard = prompt_guard
        self.current_user = current_user
        self.task_router = task_router
        self.task_planner = task_planner
        self.task_executor = task_executor
        self.parent_expander = parent_expander
        self.nl2sql_service = nl2sql_service
        # run() 使用 compiled graph，完整展示 LangGraph Agent 状态机。
        self.graph = build_rag_agent_graph(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            llm_client=llm_client,
            reranker=reranker,
            rerank_top_k=settings.rerank_top_k,
            prompt_guard=prompt_guard,
            task_router=task_router,
            task_planner=task_planner,
            task_executor=task_executor,
            parent_expander=parent_expander,
            nl2sql_service=nl2sql_service,
        )

        # stream / stream_events 需要在生成阶段逐 token yield。
        # compiled graph 的 ainvoke 更适合一次性拿 final_state，所以这里额外保留节点函数，
        # 让流式入口可以手动按同样顺序推进 state，但不改变 pipeline.stream() 的 token-only 协议。
        self.decide_next_action_node = create_next_action_decision_node(
            settings=settings,
            task_router=task_router,
            task_planner=task_planner,
        )
        self.check_loop_limits_node = create_check_loop_limits_node(settings=settings)
        self.direct_answer_node = create_rag_agent_direct_answer_node(
            settings=settings
        )
        self.clarification_node = create_agent_clarification_node(settings=settings)
        self.call_knowledge_retrieval_node = create_call_knowledge_retrieval_node(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
        )
        self.call_nl2sql_query_node = create_call_nl2sql_query_node(
            settings=settings,
            nl2sql_service=nl2sql_service,
        )
        self.execute_task_plan_node = (
            create_execute_task_plan_node(
                settings=settings,
                task_executor=task_executor,
            )
            if task_executor is not None
            else None
        )
        self.rerank_node = create_agent_rerank_node(
            settings=settings,
            reranker=reranker,
            rerank_top_k=settings.rerank_top_k,
        )
        self.build_context_node = create_agent_build_context_node(
            settings=settings,
            prompt_guard=prompt_guard,
            parent_expander=parent_expander,
        )
        self.error_answer_node = create_agent_error_answer_node(settings=settings)
        self.fail_request_node = create_agent_fail_request_node(settings=settings)

    async def _ensure_query_allowed(self, query: str, *, source: str) -> None:
        """在启用 Prompt Guard 时校验指定边界上的用户查询。"""
        if self.prompt_guard is not None:
            await self.prompt_guard.ensure_user_input_allowed(query, source=source)

    async def _audit_stream_output(self, answer: str, *, source: str) -> None:
        """在 legacy token 流结束后审计完整回答内容。"""
        if self.prompt_guard is not None:
            await self.prompt_guard.audit_stream_output(answer, source=source)

    def _langsmith_trace(self, req: RagChatRequest, operation: str):
        """为一次 pipeline 调用创建统一的 LangSmith 顶层 trace 上下文。"""
        # pipeline 级 trace 记录一次完整请求；节点级 trace 在 rag_agent_nodes.py 中完成。
        return rag_langsmith_pipeline_trace(
            self.settings,
            req,
            "rag_agent",
            operation,
        )

    def _build_initial_state(
        self,
        req: RagChatRequest,
        operation: RagAgentOperation,
    ) -> RagAgentState:
        """根据请求、操作类型和当前用户创建所有入口共用的初始状态。"""
        # 所有入口统一走同一个 initial_state builder，避免 run/stream/events 初始字段不一致。
        return build_rag_agent_initial_state(
            req=req,
            operation=operation,
            current_user=self.current_user or req._current_user_context,
        )

    async def _prepare_initial_state(
        self,
        req: RagChatRequest,
        operation: RagAgentOperation,
    ) -> RagAgentState:
        """校验原始查询、加载一次会话快照并改写查询后返回初始 Agent 状态。"""

        state = self._build_initial_state(req=req, operation=operation)

        # 检查用户的初始query是否存在恶意注入
        await self._ensure_query_allowed(
            req.query,
            source="rag_agent.query_rewrite.raw_input",
        )

        async with rag_agent_langsmith_step_trace(
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
                        sanitize_langsmith_payload(
                            self.settings,
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
                            },
                        )
                    )
                return state

            if self.conversation_memory_store is None or self.query_rewriter is None:
                state["query_rewrite_reason"] = "memory_or_rewriter_unavailable"
                if trace_run is not None:
                    trace_run.add_outputs(
                        sanitize_langsmith_payload(
                            self.settings,
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
                            },
                        )
                    )
                return state

            # 读取之前的对话历史记录，用于rewrite query的上下文
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
                langchain_config=build_rag_langchain_child_config(
                    settings=self.settings,
                    state=state,
                    pipeline_provider="rag_agent",
                    operation=operation,
                    step_name="query_rewrite",
                    step_index=0,
                    child_name="query_rewrite.llm",
                    run_name=f"rag_agent_pipeline.{operation}.query_rewrite.llm",
                ),
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

            # rewrite完成后，prompt_guard 再一次检测是否存在恶意注入
            await self._ensure_query_allowed(
                state["query"],
                source="rag_agent.query_rewrite.rewritten_query",
            )

            if trace_run is not None:
                trace_run.add_outputs(
                    sanitize_langsmith_payload(
                        self.settings,
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
                        },
                    )
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
            "user_id": get_request_user_id(req),
            "external_session_id": get_request_external_session_id(req),
            "scoped_session_id": req.session_id,
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
                    user_id=get_request_user_id(req),
                    session_id=req.session_id,
                    external_session_id=get_request_external_session_id(req),
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
                    user_id=get_request_user_id(req),
                    session_id=req.session_id,
                    external_session_id=get_request_external_session_id(req),
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
            "user_id": get_request_user_id(req),
            "external_session_id": get_request_external_session_id(req),
            "scoped_session_id": req.session_id,
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
                user_id=get_request_user_id(req),
            )
            logger.info(
                "rag_agent_persistence %s",
                format_log_fields(
                    event="rag_agent.persistence.turn_saved",
                    user_id=get_request_user_id(req),
                    session_id=req.session_id,
                    external_session_id=get_request_external_session_id(req),
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
                    user_id=get_request_user_id(req),
                    session_id=req.session_id,
                    external_session_id=get_request_external_session_id(req),
                    operation=operation,
                    error_type=type(exc).__name__,
                ),
            )
            if raise_on_error:
                raise

    async def run(self, req: RagChatRequest) -> RagChatResponse:
        """执行完整 LangGraph，并返回包含回答、来源和任务状态的非流式响应。"""
        # 非流式入口可以直接运行 compiled graph，最后把 final_state 转成 API response。
        async with self._langsmith_trace(req, "run"):
            return await self._run(req)

    async def _run(self, req: RagChatRequest) -> RagChatResponse:
        """实现非流式主链路：准备状态、运行图、保存会话并组装 API 响应。"""
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
            # 构造初始State，prompt_guard 检查用户的初始query，执行rewrite后再执行一次 prompt_guard
            initial_state = await self._prepare_initial_state(req, operation="run")

            # graph.ainvoke 会按 rag_agent_builder.py 中定义的边执行到 END。
            final_state = await self.graph.ainvoke(
                initial_state,
                config=build_rag_langchain_pipeline_child_config(
                    settings=self.settings,
                    pipeline_provider="rag_agent",
                    operation="run",
                    child_name="langgraph",
                    run_name="rag_agent_pipeline.run.langgraph",
                ),
            )
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
            clarification_required=final_state.get(
                "clarification_required",
                False,
            ),
            clarification_code=final_state.get("clarification_code"),
            clarification_question=final_state.get("clarification_question"),
            route_intent=final_state.get("route_intent"),
            route_confidence=final_state.get("route_confidence"),
            route_source=final_state.get("route_source"),
            agent_task_plan_id=final_state.get("agent_task_plan_id"),
            agent_task_status=(
                final_state["agent_task_plan"].status.value
                if final_state.get("agent_task_plan") is not None
                else None
            ),
            agent_task_plan=(
                final_state["agent_task_plan"].model_dump(mode="json")
                if final_state.get("agent_task_plan") is not None
                else None
            ),
            task_confirmation_required=final_state.get("requires_confirmation", False),
            task_confirm_endpoint=(
                f"/agent/task-plans/{final_state['agent_task_plan_id']}/confirm"
                if final_state.get("requires_confirmation", False)
                and final_state.get("agent_task_plan_id") is not None
                else None
            ),
            nl2sql_result=final_state.get("nl2sql_result"),
        )

    async def _prepare_stream_state(
        self,
        req: RagChatRequest,
        operation: RagAgentOperation,
    ) -> RagAgentState:
        """手动推进流式入口的前置 Agent 节点，并在构建上下文前返回状态。"""
        # 流式入口和 run 共享前半段 Agent 决策链路：
        # decide -> loop check -> direct/error/tool -> rerank。
        # 这里停在 build_context 之前，是为了让 stream_events 可以先发 sources。
        state = await self._prepare_initial_state(req, operation=operation)

        decision_update = await self.decide_next_action_node(state)
        # 手写流式路径需要显式 state.update，模拟 LangGraph partial state merge。
        state.update(decision_update)

        loop_update = await self.check_loop_limits_node(state)
        state.update(loop_update)

        next_route = route_after_loop_check(state)
        if next_route == "direct_answer":
            # 直接回答路径没有 sources，也不需要进入检索和 LLM。
            direct_update = await self.direct_answer_node(state)
            state.update(direct_update)
            return state

        if next_route == "clarification_required":
            clarification_update = await self.clarification_node(state)
            state.update(clarification_update)
            return state

        if next_route == "final_error_answer":
            # loop limit 等可解释错误在 Agent 内部转成最终回答。
            error_update = await self.error_answer_node(state)
            state.update(error_update)
            return state

        if next_route == "execute_task_plan":
            if self.execute_task_plan_node is None:
                raise ExternalServiceError("RAG Agent 多步骤任务执行节点尚未初始化")
            task_update = await self.execute_task_plan_node(state)
            state.update(task_update)
            return state

        if next_route == "structured_data_query":
            nl2sql_update = await self.call_nl2sql_query_node(state)
            state.update(nl2sql_update)
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
        """提供兼容旧接口的 token-only 流，并包裹整次调用的顶层 trace。"""
        # 对外契约：pipeline.stream() 只能 yield str token。
        # SSE 的 event/data 包装仍由 API 层负责。
        async with self._langsmith_trace(req, "stream"):
            async for token in self._stream(req):
                yield token

    async def _stream(
        self,
        req: RagChatRequest,
    ) -> AsyncGenerator[str, None]:
        """实现 legacy token 流：处理提前回答或流式生成，再保存并审计完整回答。"""
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
            await self._audit_stream_output(
                answer,
                source="rag_agent.stream.output",
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
        async with rag_agent_langsmith_step_trace(
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
            async for token in self.llm_client.stream(
                build_rag_agent_answer_query(state),
                context,
                langchain_config=build_rag_langchain_child_config(
                    settings=self.settings,
                    state=state,
                    pipeline_provider="rag_agent",
                    operation="stream",
                    step_name="stream_generate",
                    step_index=6,
                    child_name="stream_generate.llm",
                    run_name="rag_agent_pipeline.stream.stream_generate.llm",
                ),
            ):
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
        await self._audit_stream_output(
            answer,
            source="rag_agent.stream.output",
        )
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
        """提供 React 主链路使用的结构化 RAG SSE 业务事件流。"""
        # 结构化流式入口仍只产生业务事件 sources/token。
        # done/error 继续由 API SSE 包装层处理，保持和现有协议一致。
        async with self._langsmith_trace(req, "stream_events"):
            async for event in self._stream_events(req):
                yield event

    async def _stream_events(
        self,
        req: RagChatRequest,
    ) -> AsyncGenerator[RagStreamEvent, None]:
        """实现结构化事件流：先发送任务或来源事件，再发送受 Guard 保护的回答增量。"""
        start_time = perf_counter()
        state = await self._prepare_stream_state(req, operation="stream_events")

        yield RagStreamEvent(
            event="agent_route_selected",
            data={
                "intent": state.get("route_intent"),
                "source": state.get("route_source"),
                "confidence": state.get("route_confidence"),
                "reason": state.get("route_reason"),
            },
        )

        if state.get("answer") is not None:
            nl2sql_result = state.get("nl2sql_result")
            if nl2sql_result is not None:
                yield RagStreamEvent(
                    event="nl2sql_sql_generated",
                    data={
                        "query_id": nl2sql_result.query_id,
                        "dataset_id": nl2sql_result.dataset_id,
                        "parameterized_sql": nl2sql_result.parameterized_sql,
                        "attempt_count": nl2sql_result.attempt_count,
                    },
                )
                yield RagStreamEvent(
                    event="nl2sql_result",
                    data=nl2sql_result.model_dump(mode="json"),
                )
            # 澄清是正常业务结果，先发送专用状态，再走空 sources 和安全正文通道。
            if state.get("clarification_required", False):
                yield RagStreamEvent(
                    event="agent_route_clarification_required",
                    data={
                        "code": state.get("clarification_code"),
                        "question": state.get("clarification_question"),
                        "confidence": state.get("route_confidence"),
                    },
                )
            # 直接回答、澄清或错误回答没有检索来源，但协议仍会发送 sources。
            task_plan = state.get("agent_task_plan")
            if task_plan is not None:
                # Agent task plan 是 React 前端需要单独渲染的结构化状态，
                # 所以先发 agent_task_plan_created，再继续 answer_delta。
                yield RagStreamEvent(
                    event="agent_task_plan_created",
                    data={
                        "task_plan_id": task_plan.task_plan_id,
                        "task_kind": task_plan.task_kind,
                        "task_type": task_plan.task_type,
                        "objective": task_plan.objective,
                        "status": task_plan.status.value,
                        "target_path": task_plan.target_path,
                        "source_query": task_plan.source_query,
                        "research_policy": (
                            getattr(task_plan, "research_policy").model_dump(mode="json")
                            if getattr(task_plan, "research_policy", None) is not None
                            else None
                        ),
                        "sub_questions": [
                            item.model_dump(mode="json")
                            for item in task_plan.sub_questions
                        ],
                        "final_synthesis_instruction": task_plan.final_synthesis_instruction,
                        "steps": [
                            item.model_dump(mode="json") for item in task_plan.steps
                        ],
                    },
                )
                document_progress = task_plan.final_output.get(
                    "document_progress", {}
                )
                document_events = (
                    document_progress.get("events", [])
                    if isinstance(document_progress, dict)
                    else []
                )
                if isinstance(document_events, list):
                    for document_event in document_events:
                        if not isinstance(document_event, dict):
                            continue
                        event_name = str(document_event.get("event") or "")
                        if not event_name.startswith("agent_task_document_"):
                            continue
                        yield RagStreamEvent(
                            event=event_name,
                            data={
                                "task_plan_id": task_plan.task_plan_id,
                                **{
                                    key: value
                                    for key, value in document_event.items()
                                    if key != "event"
                                },
                            },
                        )
                for step in task_plan.steps:
                    if step.status.value in {
                        "running",
                        "completed",
                        "waiting_confirmation",
                        "failed",
                    }:
                        yield RagStreamEvent(
                            event="agent_task_step_started",
                            data={
                                "task_plan_id": task_plan.task_plan_id,
                                "step_id": step.step_id,
                                "tool_name": step.tool_name,
                            },
                        )
                    if step.status.value == "completed":
                        yield RagStreamEvent(
                            event="agent_task_step_completed",
                            data={
                                "task_plan_id": task_plan.task_plan_id,
                                "step_id": step.step_id,
                                "tool_name": step.tool_name,
                                "output": step.output,
                            },
                        )
                    if step.status.value == "waiting_confirmation":
                        yield RagStreamEvent(
                            event="agent_task_waiting_confirmation",
                            data={
                                "task_plan_id": task_plan.task_plan_id,
                                "step_id": step.step_id,
                                "tool_name": step.tool_name,
                                "confirm_endpoint": f"/agent/task-plans/{task_plan.task_plan_id}/confirm",
                            },
                        )
                if (
                    task_plan.task_kind == "question_decomposition"
                    and task_plan.status.value == "waiting_confirmation"
                ):
                    yield RagStreamEvent(
                        event="agent_task_waiting_confirmation",
                        data={
                            "task_plan_id": task_plan.task_plan_id,
                            "confirm_endpoint": f"/agent/task-plans/{task_plan.task_plan_id}/confirm",
                        },
                    )
                document_tool_calls = task_plan.final_output.get("tool_calls", [])
                if (
                    task_plan.task_kind == "knowledge_document_management"
                    and isinstance(document_tool_calls, list)
                ):
                    for call in document_tool_calls:
                        if not isinstance(call, dict):
                            continue
                        common = {
                            "task_plan_id": task_plan.task_plan_id,
                            "call_id": call.get("call_id"),
                            "round": call.get("round"),
                            "tool_name": call.get("tool_name"),
                        }
                        yield RagStreamEvent(
                            event="agent_task_tool_call_started",
                            data={**common, "tool_input": call.get("tool_input", {})},
                        )
                        yield RagStreamEvent(
                            event=(
                                "agent_task_tool_call_completed"
                                if call.get("status") == "completed"
                                else "agent_task_tool_call_failed"
                            ),
                            data={
                                **common,
                                "tool_output": call.get("tool_output", {}),
                                "error": call.get("error"),
                            },
                        )
                sub_question_results = task_plan.final_output.get(
                    "sub_question_results",
                    [],
                )
                if isinstance(sub_question_results, list):
                    for result in sub_question_results:
                        if not isinstance(result, dict):
                            continue
                        yield RagStreamEvent(
                            event="agent_task_sub_question_started",
                            data={
                                "task_plan_id": task_plan.task_plan_id,
                                "sub_question_id": result.get("sub_question_id"),
                                "question": result.get("question"),
                            },
                        )
                        yield RagStreamEvent(
                            event="agent_task_tool_selected",
                            data={
                                "task_plan_id": task_plan.task_plan_id,
                                "sub_question_id": result.get("sub_question_id"),
                                "selected_tool": result.get("selected_tool"),
                                "tool_input": result.get("tool_input", {}),
                            },
                        )
                        tool_calls = result.get("tool_calls", [])
                        if isinstance(tool_calls, list):
                            for call in tool_calls:
                                if not isinstance(call, dict):
                                    continue
                                yield RagStreamEvent(
                                    event="agent_task_tool_call_started",
                                    data={
                                        "task_plan_id": task_plan.task_plan_id,
                                        "sub_question_id": result.get("sub_question_id"),
                                        "call_id": call.get("call_id"),
                                        "round": call.get("round"),
                                        "tool_name": call.get("tool_name"),
                                        "tool_input": call.get("tool_input", {}),
                                        "reason": call.get("reason", ""),
                                    },
                                )
                                yield RagStreamEvent(
                                    event=(
                                        "agent_task_tool_call_completed"
                                        if call.get("status") == "completed"
                                        else "agent_task_tool_call_failed"
                                    ),
                                    data={
                                        "task_plan_id": task_plan.task_plan_id,
                                        "sub_question_id": result.get("sub_question_id"),
                                        "call_id": call.get("call_id"),
                                        "round": call.get("round"),
                                        "tool_name": call.get("tool_name"),
                                        "tool_output": call.get("tool_output", {}),
                                        "error": call.get("error"),
                                    },
                                )
                        yield RagStreamEvent(
                            event="agent_task_sub_question_completed",
                            data={
                                "task_plan_id": task_plan.task_plan_id,
                                "sub_question_id": result.get("sub_question_id"),
                                "status": result.get("status"),
                                "answer": result.get("answer"),
                                "evidence": result.get("evidence", []),
                                "error": result.get("error"),
                            },
                        )
            async with rag_agent_langsmith_step_trace(
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

            answer = state["answer"] or ""
            stream_state = GuardedStreamState()
            async for event in guarded_answer_delta_events(
                text_to_async_tokens(answer),
                prompt_guard=self.prompt_guard,
                source="rag_agent.stream_events.output",
                # answer 已完整生成，整段检查一次即可，避免按字符模拟流造成重复分类。
                mode="buffer_then_emit",
                max_chars=self.settings.prompt_guard_stream_chunk_max_chars,
                state=stream_state,
            ):
                yield event

            if task_plan is not None:
                final_answer = task_plan.final_output.get("final_answer")
                if isinstance(final_answer, str) and final_answer.strip():
                    yield RagStreamEvent(
                        event="agent_task_final_synthesis_completed",
                        data={
                            "task_plan_id": task_plan.task_plan_id,
                            "status": task_plan.status.value,
                            "used_tools": task_plan.final_output.get("used_tools", []),
                        },
                    )

            token_count = stream_state.raw_token_count
            answer = stream_state.answer

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

        build_context_update = await self.build_context_node(state)
        state.update(build_context_update)
        docs = state["docs"]
        context = state["context"]
        # 检索路径先把 sources 发给前端，再开始 token 流。
        # 这和现有 LangGraphRagPipeline.stream_events 的用户体验保持一致。
        async with rag_agent_langsmith_step_trace(
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

        if context is None:
            raise ExternalServiceError(
                "RAG Agent Stream Events 上下文为空，无法流式生成回答"
            )

        token_count = 0
        async with rag_agent_langsmith_step_trace(
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
            stream_state = GuardedStreamState()
            async for event in guarded_answer_delta_events(
                self.llm_client.stream(
                    build_rag_agent_answer_query(state),
                    context,
                    langchain_config=build_rag_langchain_child_config(
                        settings=self.settings,
                        state=state,
                        pipeline_provider="rag_agent",
                        operation="stream_events",
                        step_name="stream_generate",
                        step_index=7,
                        child_name="stream_generate.llm",
                        run_name="rag_agent_pipeline.stream_events.stream_generate.llm",
                    ),
                ),
                prompt_guard=self.prompt_guard,
                source="rag_agent.stream_events.output",
                mode=self.settings.prompt_guard_stream_output_mode,
                max_chars=self.settings.prompt_guard_stream_chunk_max_chars,
                state=stream_state,
            ):
                yield event

            token_count = stream_state.raw_token_count
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "token_count": token_count,
                        "source_count": len(context.docs),
                        "blocked_by_prompt_guard": stream_state.blocked,
                        "emitted_answer_length": len(stream_state.answer),
                    }
                )

        answer = stream_state.answer
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
