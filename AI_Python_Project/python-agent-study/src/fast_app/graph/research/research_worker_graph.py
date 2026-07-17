"""一个 Research Worker 的显式 LangGraph 状态机。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from fast_app.domain.agent_task_plan import (
    AgentTaskSubQuestionResult,
    AgentTaskToolCallTrace,
    ResearchEvidenceEvaluation,
)


class ResearchWorkerGraphState(TypedDict):
    """一次子问题研究在多轮工具调用和证据评估间流转的完整状态。"""

    request: Any
    attempt: int
    used_tool_calls: int
    all_tool_calls: list[AgentTaskToolCallTrace]
    all_evidence: list[dict[str, Any]]
    force_web: bool
    web_missing_points: list[str]
    attempts: list[dict[str, Any]]
    last_result: AgentTaskSubQuestionResult
    evaluation: ResearchEvidenceEvaluation | None
    evaluator_error: str | None
    next_action: Literal["complete", "retry", "limited"]
    final_warning: str | None
    final_result: AgentTaskSubQuestionResult | None


WorkerNode = Callable[[ResearchWorkerGraphState], Awaitable[dict[str, Any]]]
WorkerRouter = Callable[
    [ResearchWorkerGraphState], Literal["complete", "retry", "limited"]
]


def build_research_worker_graph(
    *,
    run_attempt: WorkerNode,
    evaluate_evidence: WorkerNode,
    route_evaluation: WorkerNode,
    choose_route: WorkerRouter,
    prepare_retry: WorkerNode,
    complete: WorkerNode,
    finalize_limited: WorkerNode,
):
    """把 Worker 的纠正循环显式组装成可观察、可测试的子图。"""

    graph = StateGraph(ResearchWorkerGraphState)
    graph.add_node("run_attempt", run_attempt)
    graph.add_node("evaluate_evidence", evaluate_evidence)
    graph.add_node("route_evaluation", route_evaluation)
    graph.add_node("prepare_retry", prepare_retry)
    graph.add_node("complete", complete)
    graph.add_node("finalize_limited", finalize_limited)
    graph.add_edge(START, "run_attempt")
    graph.add_edge("run_attempt", "evaluate_evidence")
    graph.add_edge("evaluate_evidence", "route_evaluation")
    graph.add_conditional_edges(
        "route_evaluation",
        choose_route,
        {
            "complete": "complete",
            "retry": "prepare_retry",
            "limited": "finalize_limited",
        },
    )
    graph.add_edge("prepare_retry", "run_attempt")
    graph.add_edge("complete", END)
    graph.add_edge("finalize_limited", END)
    return graph.compile()


__all__ = ["ResearchWorkerGraphState", "build_research_worker_graph"]
