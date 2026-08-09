from collections.abc import Callable
from time import perf_counter

from fast_app.agents.tools.rag_agent_tools import (
    KNOWLEDGE_RETRIEVAL_TOOL_NAME,
    retrieve_knowledge_docs,
)
from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.core.langsmith import rag_langsmith_state_step_trace
from fast_app.core.latency import log_slow_operation
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.rag_models import RagContext, RetrievalFilters, RetrievedDoc
from fast_app.evaluation.pipeline.snapshot_capture import (
    record_snapshot_retrieval_stage,
)
from fast_app.graph.rag.rag_graph_state import GraphRagRoute, GraphRagState
from fast_app.services.exceptions import ExternalServiceError
from fast_app.services.knowledge.knowledge_permission_policy import (
    build_retrieval_filters_from_mapping,
)
from fast_app.services.rag.rag_pipeline_service import (
    build_top_doc_ids,
)
from fast_app.services.rag.markdown_parent_context import MarkdownParentContextExpander
from fast_app.services.rag.rag_context_assembler import assemble_rag_context
from fast_app.services.rag.rag_context_assembler import build_context_observation
from fast_app.services.rag.prompt_guard_service import PromptGuardService

from fast_app.components.rerankers.base import BaseReranker


logger = get_logger(__name__)


GraphNode = Callable[[GraphRagState], dict]

DIRECT_ANSWER_TEXT = (
    "你好，我是一个 RAG Agent 后端示例。"
    "当问题需要知识库信息时，我会执行检索、重排序、构造上下文并生成回答；"
    "如果只是问候、感谢或询问系统能力，我会直接回答。"
)
# 通过规则过滤可以直接回答的query
DIRECT_QUERY_EXACT_MATCHES = {
    "你好",
    "您好",
    "hi",
    "hello",
    "hey",
    "谢谢",
    "感谢",
    "thanks",
    "thankyou",
    "你是谁",
    "你能做什么",
    "你可以做什么",
    "你会做什么",
}

DIRECT_QUERY_PATTERNS = (
    "你能帮我做什么",
    "你可以帮我做什么",
    "你的能力",
    "有什么能力",
    "介绍一下你自己",
)

def get_graph_operation(state: GraphRagState) -> str:
    return state.get("operation", "run")


def get_graph_step_index(operation: str, step_name: str) -> int:
    if operation == "stream_events":
        indexes = {
            "route_query": 1,
            "retrieve": 2,
            "direct_answer": 2,
            "rerank": 3,
            "emit_sources": 4,
            "build_context": 5,
            "stream_generate": 6,
            "generate": 6,
        }
        return indexes[step_name]

    indexes = {
        "route_query": 1,
        "retrieve": 2,
        "direct_answer": 2,
        "rerank": 3,
        "build_context": 4,
        "generate": 5,
        "stream_generate": 5,
    }
    return indexes[step_name]


def build_graph_step_inputs(
    state: GraphRagState,
    **extra: object,
) -> dict[str, object]:
    return {
        "query": state["query"],
        "mode": state["mode"],
        "top_k": state["top_k"],
        "candidate_k": state.get("candidate_k"),
        "min_score": state["min_score"],
        "filters": state.get("filters", {}),
        **extra,
    }


def graph_langsmith_step_trace(
    settings: Settings,
    state: GraphRagState,
    step_name: str,
    run_type: str,
    inputs: dict[str, object],
):
    operation = get_graph_operation(state)
    return rag_langsmith_state_step_trace(
        settings,
        state,
        "langgraph",
        operation,
        step_name,
        get_graph_step_index(operation, step_name),
        run_type,
        inputs,
    )


def normalize_route_query(query: str) -> str:
    return "".join(query.lower().split()).strip("，。！？!?.,;；：:")

# 通过固定的规则过滤当前query能不能直接回答
def should_retrieve_for_query(query: str) -> tuple[bool, str]:
    normalized_query = normalize_route_query(query)

    if not normalized_query:
        return False, "empty_query_direct_answer"

    if normalized_query in DIRECT_QUERY_EXACT_MATCHES:
        return False, "matched_direct_query_exact"

    for pattern in DIRECT_QUERY_PATTERNS:
        if pattern in normalized_query:
            return False, "matched_direct_query_pattern"

    return True, "default_retrieve"


def route_from_state(state: GraphRagState) -> GraphRagRoute:
    route = state.get("route")
    if route in ("retrieve", "direct_answer"):
        return route

    return "retrieve"


def create_route_query_node(
    settings: Settings,
) -> Callable[[GraphRagState], dict[str, object]]:

    async def route_query_node(state: GraphRagState) -> dict[str, object]:
        query = state["query"]

        with graph_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="route_query",
            run_type="chain",
            inputs=build_graph_step_inputs(state),
        ) as trace_run:
            need_retrieval, route_reason = should_retrieve_for_query(query)
            route: GraphRagRoute = "retrieve" if need_retrieval else "direct_answer"

            logger.info(
                "rag_route %s",
                format_log_fields(
                    event="rag.route_query.finish",
                    pipeline_provider="langgraph",
                    query=query,
                    route=route,
                    need_retrieval=need_retrieval,
                    route_reason=route_reason,
                ),
            )

            result = {
                "need_retrieval": need_retrieval,
                "route": route,
                "route_reason": route_reason,
            }

            if trace_run is not None:
                trace_run.add_outputs(result)

            return result

    return route_query_node

# 返回固定能力说明，不调用llm回答
def create_direct_answer_node(
    settings: Settings,
) -> Callable[[GraphRagState], dict[str, str]]:

    async def direct_answer_node(state: GraphRagState) -> dict[str, str]:
        with graph_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="direct_answer",
            run_type="chain",
            inputs=build_graph_step_inputs(
                state,
                route=state.get("route"),
                route_reason=state.get("route_reason"),
            ),
        ) as trace_run:
            logger.info(
                "rag_direct_answer %s",
                format_log_fields(
                    event="rag.direct_answer.finish",
                    pipeline_provider="langgraph",
                    query=state["query"],
                    answer_length=len(DIRECT_ANSWER_TEXT),
                    route_reason=state.get("route_reason"),
                ),
            )

            result = {"answer": DIRECT_ANSWER_TEXT}
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "answer_length": len(DIRECT_ANSWER_TEXT),
                        "source_count": 0,
                    }
                )

            return result

    return direct_answer_node


# 重排序节点 只处理 rerank 只接收和返回 docs
def create_rerank_node(
    settings: Settings,
    reranker: BaseReranker,
    rerank_top_k: int,
) -> Callable[[GraphRagState], object]:

    async def rerank_node(state: GraphRagState) -> dict[str, list[RetrievedDoc]]:
        docs = state["docs"]

        with graph_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="rerank",
            run_type="chain",
            inputs=build_graph_step_inputs(
                state,
                input_doc_count=len(docs),
                top_doc_ids=build_top_doc_ids(docs),
            ),
        ) as trace_run:
            if not docs:
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "output_doc_count": 0,
                            "top_doc_ids": [],
                        }
                    )
                record_snapshot_retrieval_stage(
                    "rerank",
                    [],
                    query=state["query"],
                )
                return {"docs": []}

            start_time = perf_counter()
            top_k = min(rerank_top_k, len(docs))
            logger.info(
                "rag_rerank %s",
                format_log_fields(
                    event="rag.rerank.start",
                    pipeline_provider="langgraph",
                    candidate_count=len(docs),
                    top_k=top_k,
                    top_doc_ids=build_top_doc_ids(docs),
                ),
            )

            try:
                reranked_docs = await reranker.rerank(
                    query=state["query"],
                    docs=docs,
                    top_k=top_k,
                )
                latency_ms = (perf_counter() - start_time) * 1000
                logger.info(
                    "rag_rerank %s",
                    format_log_fields(
                        event="rag.rerank.finish",
                        pipeline_provider="langgraph",
                        candidate_count=len(docs),
                        result_count=len(reranked_docs),
                        top_k=top_k,
                        latency_ms=round(latency_ms, 2),
                        fallback=False,
                        top_doc_ids=build_top_doc_ids(reranked_docs),
                    ),
                )
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "output_doc_count": len(reranked_docs),
                            "top_doc_ids": build_top_doc_ids(reranked_docs),
                        }
                    )
                log_slow_operation(
                    logger=logger,
                    event="rag.rerank.slow",
                    latency_ms=latency_ms,
                    threshold_ms=settings.slow_rerank_threshold_ms,
                    slow_component="rerank",
                    pipeline_provider="langgraph",
                    candidate_count=len(docs),
                    result_count=len(reranked_docs),
                    top_k=top_k,
                    fallback=False,
                )
                record_snapshot_retrieval_stage(
                    "rerank",
                    reranked_docs,
                    query=state["query"],
                )
                return {"docs": reranked_docs}

            except ExternalServiceError as exc:
                fallback_docs = docs[:rerank_top_k]
                latency_ms = (perf_counter() - start_time) * 1000
                logger.warning(
                    "rag_rerank %s",
                    format_log_fields(
                        event="rag.rerank.fallback",
                        pipeline_provider="langgraph",
                        candidate_count=len(docs),
                        result_count=len(fallback_docs),
                        top_k=top_k,
                        latency_ms=round(latency_ms, 2),
                        fallback=True,
                        error_type=type(exc).__name__,
                        top_doc_ids=build_top_doc_ids(fallback_docs),
                    ),
                )
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "output_doc_count": len(fallback_docs),
                            "top_doc_ids": build_top_doc_ids(fallback_docs),
                            "fallback": True,
                        }
                    )
                log_slow_operation(
                    logger=logger,
                    event="rag.rerank.slow",
                    latency_ms=latency_ms,
                    threshold_ms=settings.slow_rerank_threshold_ms,
                    slow_component="rerank",
                    pipeline_provider="langgraph",
                    candidate_count=len(docs),
                    result_count=len(fallback_docs),
                    top_k=top_k,
                    fallback=True,
                    error_type=type(exc).__name__,
                )
                record_snapshot_retrieval_stage(
                    "rerank",
                    fallback_docs,
                    query=state["query"],
                )
                return {"docs": fallback_docs}

    return rerank_node

# 构造检索过滤条件
def build_graph_retrieval_filters(state: GraphRagState) -> RetrievalFilters:
    raw_filters = state.get("filters", {})
    filters = raw_filters if isinstance(raw_filters, dict) else None
    return build_retrieval_filters_from_mapping(filters)

# Node Factory **如果直接在 node 里 new，vector_retriever = MockVectorRetriever() **就破坏了阶段 4-7 的可替换组件设计。
# 外层函数接收组件依赖。内层函数才是真正的 LangGraph node。内层 node 通过闭包使用外层传入的组件。

# 这里的返回值使用模糊的Object 因为 精确标注会涉及 Awaitable / Mapping / Partial State 等类型，目前先用 object 代替，后续可以根据实际情况细化类型标注
def create_retrieve_node(
    settings: Settings,
    vector_retriever: BaseRetriever,
    keyword_retriever: BaseRetriever,
) -> Callable[[GraphRagState], object]:

    # 构造node需要的 partial<State> update
    async def retrieve_node(state: GraphRagState) -> dict[str, object]:
        # 调用检索的封装逻辑
        docs = await retrieve_knowledge_docs(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            query=state["query"],
            mode=state["mode"],
            top_k=state["top_k"],
            candidate_k=state.get("candidate_k"),
            min_score=state["min_score"],
            filters=build_graph_retrieval_filters(state),
            pipeline_provider="langgraph",
        )

        return {
            "docs": docs,
            "tool_name": KNOWLEDGE_RETRIEVAL_TOOL_NAME,
            "tool_result_count": len(docs),
            "tool_error": None,
        }

    async def traced_retrieve_node(
        state: GraphRagState,
    ) -> dict[str, object]:
        with graph_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="retrieve",
            run_type="retriever",
            inputs=build_graph_step_inputs(
                state,
                tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
            ),
        ) as trace_run:
            try:
                result = await retrieve_node(state)
            except Exception as exc:
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "tool_name": KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                            "tool_error": type(exc).__name__,
                        }
                    )
                raise

            docs = result["docs"]
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "tool_name": result["tool_name"],
                        "tool_result_count": result["tool_result_count"],
                        "tool_error": result["tool_error"],
                        "doc_count": len(docs),
                        "top_doc_ids": build_top_doc_ids(docs),
                    }
                )
            return result

    return traced_retrieve_node


def create_build_context_node(
    settings: Settings,
    prompt_guard: PromptGuardService | None = None,
    parent_expander: MarkdownParentContextExpander | None = None,
) -> Callable[[GraphRagState], dict[str, object]]:

    async def build_context_node(state: GraphRagState) -> dict[str, object]:
        docs = state["docs"]

        logger.info("LangGraph 开始构造上下文: docs_count=%s", len(docs))

        context = await assemble_rag_context(
            settings=settings,
            query=state["query"],
            docs=docs,
            filters=state["filters"],
            source="langgraph.build_context",
            parent_expander=(
                parent_expander
                if state.get("operation", "run") != "stream"
                else None
            ),
            prompt_guard=prompt_guard,
        )
        docs = context.docs

        logger.info(
            "LangGraph 上下文构造完成: context_docs_count=%s",
            len(context.docs),
        )

        return {
            "docs": docs,
            "context": context,
        }

    async def traced_build_context_node(
        state: GraphRagState,
    ) -> dict[str, object]:
        docs = state["docs"]
        with graph_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="build_context",
            run_type="chain",
            inputs=build_graph_step_inputs(
                state,
                doc_count=len(docs),
                top_doc_ids=build_top_doc_ids(docs),
            ),
        ) as trace_run:
            result = await build_context_node(state)
            context = result["context"]
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "context_doc_count": len(context.docs),
                        "context_length": len(context.context_text),
                        **build_context_observation(context),
                    }
                )
            return result

    return traced_build_context_node


def create_generate_node(
    settings: Settings,
    llm_client: BaseLLMClient,
    prompt_guard: PromptGuardService | None = None,
) -> Callable[[GraphRagState], object]:

    async def generate_node(state: GraphRagState) -> dict[str, str]:
        query = state["query"]
        context = state["context"]

        if context is None:
            raise ExternalServiceError("上下文为空，无法生成回答")

        logger.info("LangGraph 开始生成回答: query=%s", query)

        answer = await llm_client.generate(
            query=query,
            context=context,
        )
        if prompt_guard is not None:
            answer = await prompt_guard.ensure_output_allowed(
                answer,
                source="langgraph.generate",
            )

        logger.info("LangGraph 回答生成完成: answer_length=%s", len(answer))

        return {"answer": answer}

    async def traced_generate_node(state: GraphRagState) -> dict[str, str]:
        context = state["context"]
        context_doc_count = len(context.docs) if context is not None else 0
        context_length = len(context.context_text) if context is not None else 0
        with graph_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="generate",
            run_type="chain",
            inputs=build_graph_step_inputs(
                state,
                context_doc_count=context_doc_count,
                context_length=context_length,
            ),
        ) as trace_run:
            result = await generate_node(state)
            answer = result["answer"]
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "answer_length": len(answer),
                        "source_count": context_doc_count,
                    }
                )
            return result

    return traced_generate_node
