from collections.abc import AsyncGenerator
from time import perf_counter
from typing import Any

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.rerankers.base import BaseReranker
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.core.langsmith import (
    rag_langsmith_pipeline_trace,
    rag_langsmith_request_step_trace,
)
from fast_app.core.latency import log_slow_operation
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.agents.rag_agent_factory import build_rag_agent
from fast_app.graph.rag_graph_state import (
    GraphRagOperation,
    GraphRagState,
    build_graph_initial_state,
)
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse

from fast_app.services.rag_pipeline_service import docs_to_sources

from fast_app.graph.rag_graph_nodes import (
    create_build_context_node,
    create_direct_answer_node,
    create_retrieve_node,
    create_rerank_node,
    create_route_query_node,
)
from fast_app.services.exceptions import ExternalServiceError
from fast_app.services.guarded_streaming import (
    GuardedStreamState,
    guarded_answer_delta_events,
    text_to_async_tokens,
)
from fast_app.services.prompt_guard_service import PromptGuardService

from fast_app.domain.rag_stream_models import RagStreamEvent


logger = get_logger(__name__)

# FastAPI 请求模型和LangGraph final_state之间的适配层。
class LangGraphRagPipeline:

    def __init__(
        self,
        settings: Settings,
        vector_retriever: BaseRetriever,
        keyword_retriever: BaseRetriever,
        llm_client: BaseLLMClient,
        reranker: BaseReranker,
        prompt_guard: PromptGuardService | None = None,
    ):
        self.settings = settings
        self.vector_retriever = vector_retriever
        self.keyword_retriever = keyword_retriever
        self.llm_client = llm_client
        self.reranker = reranker
        self.prompt_guard = prompt_guard
        self.rerank_node = create_rerank_node(
            settings=settings,
            reranker=reranker,
            rerank_top_k=settings.rerank_top_k,
        )
        
        # Graph 结构是固定的，所以只在构造 pipeline 时装配一次。每次请求变化的是 initial_state。
        self.graph = build_rag_agent(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            llm_client=llm_client,
            reranker=reranker,
            mode="explicit_graph", #设置使用graph还是 create Agent[未实现]模式
            prompt_guard=prompt_guard,
        )

        self.retrieve_node = create_retrieve_node(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
        )
        self.build_context_node = create_build_context_node(
            settings=settings,
            prompt_guard=prompt_guard,
        )
        self.route_query_node = create_route_query_node(settings=settings)
        self.direct_answer_node = create_direct_answer_node(settings=settings)

    # 构造langsmith 追踪
    def _langsmith_trace(self, req: RagChatRequest, operation: str):
        return rag_langsmith_pipeline_trace(
            self.settings,
            req,
            "langgraph",
            operation,
        )

    async def _ensure_query_allowed(self, query: str, *, source: str) -> None:
        if self.prompt_guard is not None:
            await self.prompt_guard.ensure_user_input_allowed(query, source=source)

    async def _audit_stream_output(self, answer: str, *, source: str) -> None:
        if self.prompt_guard is not None:
            await self.prompt_guard.audit_stream_output(answer, source=source)

    async def _filter_docs_with_prompt_guard(
        self,
        docs: list,
        *,
        source: str,
    ) -> list:
        if self.prompt_guard is None:
            return docs

        return await self.prompt_guard.filter_retrieved_docs(docs, source=source)

    def _langsmith_step_trace(
        self,
        req: RagChatRequest,
        operation: str,
        step_name: str,
        step_index: int,
        run_type: str,
        inputs: dict[str, object],
    ):
        return rag_langsmith_request_step_trace(
            self.settings,
            req,
            "langgraph",
            operation,
            step_name,
            step_index,
            run_type,
            inputs,
        )



    async def run(self, req: RagChatRequest) -> RagChatResponse:
        with self._langsmith_trace(req, "run"):
            return await self._run(req)

    async def _run(self, req: RagChatRequest) -> RagChatResponse:
        start_time = perf_counter()
        logger.info(
            "rag_pipeline %s",
            format_log_fields(
                event="rag.pipeline.start",
                pipeline_provider="langgraph",
                query=req.query,
                mode=req.mode,
                top_k=req.top_k,
                candidate_k=req.candidate_k,
                min_score=req.min_score,
            ),
        )

        try:
            await self._ensure_query_allowed(req.query, source="langgraph.run.input")
            initial_state = self._build_initial_state(req, operation="run")

            final_state = await self.graph.ainvoke(initial_state)

            answer = final_state.get("answer") or ""
            docs = final_state.get("docs") or []

            logger.info(
                "LangGraph RAG Pipeline 执行完成: docs_count=%s, answer_length=%s",
                len(docs),
                len(answer),
            )
        except Exception as exc:
            latency_ms = (perf_counter() - start_time) * 1000
            logger.exception(
                "rag_pipeline %s",
                format_log_fields(
                    event="rag.pipeline.failed",
                    pipeline_provider="langgraph",
                    query=req.query,
                    mode=req.mode,
                    top_k=req.top_k,
                    candidate_k=req.candidate_k,
                    min_score=req.min_score,
                    latency_ms=round(latency_ms, 2),
                ),
            )
            log_slow_operation(
                logger=logger,
                event="rag.pipeline.slow",
                latency_ms=latency_ms,
                threshold_ms=self.settings.slow_rag_pipeline_threshold_ms,
                slow_component="pipeline",
                pipeline_provider="langgraph",
                status="failed",
                query=req.query,
                mode=req.mode,
                top_k=req.top_k,
                error_type=type(exc).__name__,
            )
            raise

        latency_ms = (perf_counter() - start_time) * 1000
        logger.info(
            "rag_pipeline %s",
            format_log_fields(
                event="rag.pipeline.finish",
                pipeline_provider="langgraph",
                query=req.query,
                mode=req.mode,
                top_k=req.top_k,
                candidate_k=req.candidate_k,
                min_score=req.min_score,
                latency_ms=round(latency_ms, 2),
                source_count=len(docs),
                answer_length=len(answer),
            ),
        )
        log_slow_operation(
            logger=logger,
            event="rag.pipeline.slow",
            latency_ms=latency_ms,
            threshold_ms=self.settings.slow_rag_pipeline_threshold_ms,
            slow_component="pipeline",
            pipeline_provider="langgraph",
            status="success",
            query=req.query,
            mode=req.mode,
            top_k=req.top_k,
            source_count=len(docs),
            answer_length=len(answer),
        )

        return RagChatResponse(
            query=final_state["query"],
            answer=answer,
            sources=docs_to_sources(docs),
        )
    

    def _build_initial_state(
        self,
        req: RagChatRequest,
        operation: GraphRagOperation,
    ) -> GraphRagState:
        return build_graph_initial_state(
            req=req,
            operation=operation,
        )
    
    # 只产生token的流式接口
    async def stream(
        self,
        req: RagChatRequest,
    ) -> AsyncGenerator[str, None]:
        with self._langsmith_trace(req, "stream"):
            async for token in self._stream(req):
                yield token

    async def _stream(
        self,
        req: RagChatRequest,
    ) -> AsyncGenerator[str, None]:
        start_time = perf_counter()
        logger.info(
            "开始执行 LangGraph RAG Stream Pipeline: query=%s, mode=%s, top_k=%s, min_score=%s",
            req.query,
            req.mode,
            req.top_k,
            req.min_score,
        )
        await self._ensure_query_allowed(
            req.query,
            source="langgraph.stream.input",
        )

        state = self._build_initial_state(req, operation="stream")

        route_update = await self.route_query_node(state)
        state.update(route_update)

        if state.get("route") == "direct_answer":
            direct_answer_update = await self.direct_answer_node(state)
            state.update(direct_answer_update)

            answer = state.get("answer") or ""
            token_count = 0
            for token in answer:
                token_count += 1
                yield token

            logger.info(
                "LangGraph RAG Stream Pipeline 直接回答完成: token_count=%s",
                token_count,
            )
            latency_ms = (perf_counter() - start_time) * 1000
            log_slow_operation(
                logger=logger,
                event="rag.stream.slow",
                latency_ms=latency_ms,
                threshold_ms=self.settings.slow_rag_pipeline_threshold_ms,
                slow_component="pipeline_stream",
                pipeline_provider="langgraph",
                query=req.query,
                mode=req.mode,
                top_k=req.top_k,
                token_count=token_count,
                route=state.get("route"),
                route_reason=state.get("route_reason"),
            )
            return

        retrieve_update = await self.retrieve_node(state)
        state.update(retrieve_update)

        rerank_update = await self.rerank_node(state)
        state.update(rerank_update)

        build_context_update = await self.build_context_node(state)
        state.update(build_context_update)

        context = state["context"]

        if context is None:
            raise ExternalServiceError("LangGraph RAG Stream 上下文为空，无法流式生成回答")

        token_count = 0

        with self._langsmith_step_trace(
            req=req,
            operation="stream",
            step_name="stream_generate",
            step_index=5,
            run_type="chain",
            inputs={
                "query": req.query,
                "context_doc_count": len(context.docs),
                "context_length": len(context.context_text),
            },
        ) as trace_run:
            answer_parts: list[str] = []
            async for token in self.llm_client.stream(
                query=req.query,
                context=context,
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

        await self._audit_stream_output(
            "".join(answer_parts),
            source="langgraph.stream.output",
        )
        logger.info(
            "LangGraph RAG Stream Pipeline 执行完成: token_count=%s",
            token_count,
        )
        latency_ms = (perf_counter() - start_time) * 1000
        log_slow_operation(
            logger=logger,
            event="rag.stream.slow",
            latency_ms=latency_ms,
            threshold_ms=self.settings.slow_rag_pipeline_threshold_ms,
            slow_component="pipeline_stream",
            pipeline_provider="langgraph",
            query=req.query,
            mode=req.mode,
            top_k=req.top_k,
            token_count=token_count,
        )

    # 流式事件的接口，事件包括：sources（检索结果）和token（生成的回答token）
    async def stream_events(
        self,
        req: RagChatRequest,
    ) -> AsyncGenerator[RagStreamEvent, None]:
        with self._langsmith_trace(req, "stream_events"):
            async for event in self._stream_events(req):
                yield event

    async def _stream_events(
        self,
        req: RagChatRequest,
    ) -> AsyncGenerator[RagStreamEvent, None]:
        start_time = perf_counter()
        logger.info(
            "开始执行 LangGraph RAG Stream Events Pipeline: query=%s, mode=%s, top_k=%s, min_score=%s",
            req.query,
            req.mode,
            req.top_k,
            req.min_score,
        )
        await self._ensure_query_allowed(
            req.query,
            source="langgraph.stream_events.input",
        )

        state = self._build_initial_state(req, operation="stream_events")

        route_update = await self.route_query_node(state)
        state.update(route_update)

        if state.get("route") == "direct_answer":
            direct_answer_update = await self.direct_answer_node(state)
            state.update(direct_answer_update)

            with self._langsmith_step_trace(
                req=req,
                operation="stream_events",
                step_name="emit_sources",
                step_index=4,
                run_type="chain",
                inputs={
                    "doc_count": 0,
                    "top_doc_ids": [],
                    "route": state.get("route"),
                    "route_reason": state.get("route_reason"),
                },
            ) as trace_run:
                sources = []
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "source_count": 0,
                            "top_source_ids": [],
                        }
                    )

            yield RagStreamEvent(
                event="sources",
                data={
                    "sources": sources,
                },
            )

            answer = state.get("answer") or ""
            stream_state = GuardedStreamState()
            async for event in guarded_answer_delta_events(
                text_to_async_tokens(answer),
                prompt_guard=self.prompt_guard,
                source="langgraph.stream_events.output",
                mode=self.settings.prompt_guard_stream_output_mode,
                max_chars=self.settings.prompt_guard_stream_chunk_max_chars,
                state=stream_state,
            ):
                yield event
            token_count = stream_state.raw_token_count

            logger.info(
                "LangGraph RAG Stream Events Pipeline 直接回答完成: token_count=%s",
                token_count,
            )
            latency_ms = (perf_counter() - start_time) * 1000
            log_slow_operation(
                logger=logger,
                event="rag.stream_events.slow",
                latency_ms=latency_ms,
                threshold_ms=self.settings.slow_rag_pipeline_threshold_ms,
                slow_component="pipeline_stream_events",
                pipeline_provider="langgraph",
                query=req.query,
                mode=req.mode,
                top_k=req.top_k,
                token_count=token_count,
                source_count=0,
                route=state.get("route"),
                route_reason=state.get("route_reason"),
            )
            return

        retrieve_update = await self.retrieve_node(state)
        state.update(retrieve_update)

        rerank_update = await self.rerank_node(state)
        state.update(rerank_update)

        docs = state["docs"]
        docs = await self._filter_docs_with_prompt_guard(
            docs,
            source="langgraph.stream_events.documents",
        )
        state["docs"] = docs

        with self._langsmith_step_trace(
            req=req,
            operation="stream_events",
            step_name="emit_sources",
            step_index=4,
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
            data={
                "sources": sources,
            },
        )

        build_context_update = await self.build_context_node(state)
        state.update(build_context_update)

        context = state["context"]

        if context is None:
            raise ExternalServiceError("LangGraph RAG Stream Events 上下文为空，无法流式生成回答")

        token_count = 0

        with self._langsmith_step_trace(
            req=req,
            operation="stream_events",
            step_name="stream_generate",
            step_index=6,
            run_type="chain",
            inputs={
                "query": req.query,
                "context_doc_count": len(context.docs),
                "context_length": len(context.context_text),
            },
        ) as trace_run:
            stream_state = GuardedStreamState()
            async for event in guarded_answer_delta_events(
                self.llm_client.stream(query=req.query, context=context),
                prompt_guard=self.prompt_guard,
                source="langgraph.stream_events.output",
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

        logger.info(
            "LangGraph RAG Stream Events Pipeline 执行完成: token_count=%s",
            token_count,
        )
        latency_ms = (perf_counter() - start_time) * 1000
        log_slow_operation(
            logger=logger,
            event="rag.stream_events.slow",
            latency_ms=latency_ms,
            threshold_ms=self.settings.slow_rag_pipeline_threshold_ms,
            slow_component="pipeline_stream_events",
            pipeline_provider="langgraph",
            query=req.query,
            mode=req.mode,
            top_k=req.top_k,
            token_count=token_count,
            source_count=len(context.docs),
        )
