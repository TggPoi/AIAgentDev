from typing import Literal, NotRequired, TypedDict

from fast_app.domain.rag_models import RagContext, RetrievedDoc
from fast_app.schemas.rag_chat_schema import RagChatRequest
from fast_app.services.knowledge.knowledge_permission_policy import (
    merge_permission_scope_into_filter_dict,
)


RagMode = Literal["vector", "keyword", "hybrid"]
GraphRagOperation = Literal["run", "stream", "stream_events"]
GraphRagRoute = Literal["retrieve", "direct_answer"]


class GraphRagState(TypedDict):
    # 用户请求输入：这些字段来自 RagChatRequest，是 Graph 执行的起点。
    query: str
    mode: RagMode
    top_k: int
    candidate_k: int | None
    min_score: float
    filters: dict[str, object]

    # Graph 运行上下文：用于区分 run / stream / stream_events 等执行入口。
    operation: NotRequired[GraphRagOperation]
    need_retrieval: bool | None
    route: GraphRagRoute | None
    route_reason: str | None
    tool_name: str | None
    tool_result_count: int | None
    tool_error: str | None

    # 节点执行结果：后续节点通过这些字段读取上游产物。
    docs: list[RetrievedDoc]
    context: RagContext | None
    answer: str | None


def build_graph_initial_state(
    req: RagChatRequest,
    operation: GraphRagOperation,
) -> GraphRagState:
    return {
        "query": req.query,
        "mode": req.mode,
        "top_k": req.top_k,
        "candidate_k": req.candidate_k,
        "min_score": req.min_score,
        "filters": merge_permission_scope_into_filter_dict(
            filters=req.filters.model_dump(),
            permission_scope=req._retrieval_permission_scope,
        ),
        "operation": operation,
        "need_retrieval": None,
        "route": None,
        "route_reason": None,
        "tool_name": None,
        "tool_result_count": None,
        "tool_error": None,
        "docs": [],
        "context": None,
        "answer": None,
    }
