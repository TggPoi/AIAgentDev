from typing import Literal, NotRequired, TypedDict

from fast_app.agents.agent_error_policy import AgentErrorDecision
from fast_app.agents.agent_loop_control import AgentLoopDecision
from fast_app.domain.rag_models import RagContext, RetrievedDoc
from fast_app.schemas.rag_chat_schema import RagChatRequest


RagAgentMode = Literal["vector", "keyword", "hybrid"]
RagAgentOperation = Literal["run", "stream", "stream_events"]
# 这里的 route 不是 HTTP route，而是 Agent graph 内部的“下一步动作”。
# 后续 conditional_edges 会读取这个字段决定走哪个节点。
RagAgentRoute = Literal[
    "direct_answer",
    "knowledge_retrieval",
    "final_error_answer",
    "fail_request",
]


class RagAgentState(TypedDict):
    # 用户请求输入：来自 RagChatRequest，是 Agent graph 的起点。
    # 这组字段保持和普通 RAG 请求一致，方便复用已有检索、rerank 和 response 转换逻辑。
    session_id: str | None
    original_query: str
    query: str
    rewritten_query: str | None
    history_window_text: str | None
    query_rewrite_reason: str | None
    mode: RagAgentMode
    top_k: int
    candidate_k: int | None
    min_score: float
    filters: dict[str, object]

    # Agent 执行上下文：用于区分 run / stream / stream_events。
    # 同一套 Agent 节点会被三种入口复用，但 trace step index 和流式行为会不同。
    operation: NotRequired[RagAgentOperation]
    route: RagAgentRoute | None
    route_reason: str | None
    final_reason: str | None

    # Agent 控制状态：记录步骤数、工具调用数、循环决策和错误决策。
    # 13-11 目前最多调用一次 knowledge_retrieval (所以目前 Agent 决策轮次 step_count=1)，但仍提前把 loop/error 状态放入 state，
    # 这样后续扩展多工具循环时不需要重新设计状态结构。
    step_count: int
    tool_call_count: int
    loop_decision: AgentLoopDecision | None
    error_decision: AgentErrorDecision | None

    # 工具与 RAG 中间产物：后续节点通过这些字段读取上游结果。
    tool_name: str | None
    tool_error: str | None
    docs: list[RetrievedDoc]
    context: RagContext | None
    answer: str | None


def build_rag_agent_initial_state(
    req: RagChatRequest,
    operation: RagAgentOperation,
) -> RagAgentState:
    # LangGraph 要求每次请求都从一份新的 state 开始，避免跨请求共享 docs/context/answer。
    # 这里集中初始化所有字段，比在各个 node 里临时补默认值更容易排查状态流转。
    return {
        "session_id": req.session_id,
        "original_query": req.query,
        "query": req.query,
        "rewritten_query": None,
        "history_window_text": None,
        "query_rewrite_reason": None,
        "mode": req.mode,
        "top_k": req.top_k,
        "candidate_k": req.candidate_k,
        "min_score": req.min_score,
        "filters": req.filters.model_dump(),
        "operation": operation,
        "route": None,
        "route_reason": None,
        "final_reason": None,
        "step_count": 0,
        "tool_call_count": 0,
        "loop_decision": None,
        "error_decision": None,
        "tool_name": None,
        "tool_error": None,
        "docs": [],
        "context": None,
        "answer": None,
    }
