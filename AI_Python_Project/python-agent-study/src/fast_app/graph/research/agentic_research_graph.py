"""按依赖波次并行派发 Research Worker 的 LangGraph 子图。"""

from __future__ import annotations

import operator
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from fast_app.domain.agent_task_plan import (
    AgentTaskSubQuestionResult,
)
from fast_app.domain.research_task_plan import ResearchTaskSubQuestion


ResearchWorkerRunner = Callable[
    [ResearchTaskSubQuestion, list[AgentTaskSubQuestionResult], int],
    Awaitable[AgentTaskSubQuestionResult],
]
WaveCallback = Callable[[int, list[str]], Awaitable[None]]
MergeCallback = Callable[[int, list[AgentTaskSubQuestionResult]], Awaitable[None]]
StopChecker = Callable[[], bool]


class ResearchExecutionCancelled(RuntimeError):
    """控制 API 已取消研究任务，图不得继续派发外部调用。

    执行器捕获此异常后会将 TaskPlan 收口为取消状态，而不是把取消误记为 Worker 失败。
    """


class ResearchGraphState(TypedDict):
    # 整个 TaskPlan 中等待按依赖关系研究的全部子问题。
    sub_questions: list[ResearchTaskSubQuestion]
    # 已完成或因依赖失败跳过的结果；Annotated/operator.add 让并行 Worker 的结果追加合并。
    results: Annotated[list[AgentTaskSubQuestionResult], operator.add]
    # 已完成的依赖波次数；每次派发非空批次时递增。
    current_wave: int
    # 当前波次被派发给 Worker 的 sub_question_id，用于合并本批结果。
    batch_ids: list[str]
    # 单个波次最多可同时派发的 Worker 数量，限制外部工具并发。
    max_parallel_workers: int


class ResearchWorkerState(TypedDict):
    # 当前 Worker 唯一负责研究的子问题。
    sub_question: ResearchTaskSubQuestion
    # 当前子问题已完成的前置结果；只传递 declared depends_on 中的结果。
    dependency_results: list[AgentTaskSubQuestionResult]
    # 当前 Worker 所属依赖波次，供 trace、进度事件和执行记录标识。
    wave: int


def validate_research_dependencies(
    sub_questions: list[ResearchTaskSubQuestion],
) -> list[list[str]]:
    """校验 ID 和依赖图，并用 Kahn 算法返回稳定执行波次。

    返回值用于验证和测试；运行中的图会根据已完成结果动态选择下一波，因而不会直接
    使用这份预计算波次，才能正确处理某个 Worker 失败后的级联跳过。
    """

    # 先建立 id 索引；依赖关系和后续排序都以 sub_question_id 为准。
    by_id: dict[str, ResearchTaskSubQuestion] = {}
    for item in sub_questions:
        if item.sub_question_id in by_id:
            raise ValueError(f"重复 sub_question_id: {item.sub_question_id}")
        by_id[item.sub_question_id] = item
    if not by_id:
        raise ValueError("研究计划没有子问题")

    # indegree 表示“还差几个前置问题”，children 反向记录某个结果会解锁哪些子问题。
    indegree = {item_id: 0 for item_id in by_id}
    children: dict[str, list[str]] = {item_id: [] for item_id in by_id}
    for item in sub_questions:
        for dependency_id in item.depends_on:
            if dependency_id == item.sub_question_id:
                raise ValueError(f"子问题不能依赖自身: {item.sub_question_id}")
            if dependency_id not in by_id:
                raise ValueError(
                    f"子问题 {item.sub_question_id} 依赖不存在的 {dependency_id}"
                )
            indegree[item.sub_question_id] += 1
            children[dependency_id].append(item.sub_question_id)

    # 同一波没有依赖先后，但仍按计划 order 和 id 固定排序，保证 trace/测试可复现。
    key = lambda item_id: (by_id[item_id].order, item_id)
    ready = sorted((item_id for item_id, value in indegree.items() if value == 0), key=key)
    waves: list[list[str]] = []
    visited = 0
    while ready:
        # 本轮所有入度为零的问题可并行；移除它们后才计算下一轮可解锁的问题。
        wave = ready
        waves.append(wave)
        visited += len(wave)
        next_ready: list[str] = []
        for item_id in wave:
            for child_id in children[item_id]:
                indegree[child_id] -= 1
                if indegree[child_id] == 0:
                    next_ready.append(child_id)
        ready = sorted(next_ready, key=key)
    if visited != len(by_id):
        # 仍有未访问节点意味着它们互相等待，无法形成任何合法执行顺序。
        raise ValueError("子问题依赖图存在循环依赖")
    return waves


def build_agentic_research_graph(
    *,
    worker_runner: ResearchWorkerRunner,
    on_wave_started: WaveCallback,
    on_wave_merged: MergeCallback,
    should_stop: StopChecker,
):
    """构造可复用的研究子图；业务工具、Evaluator 与快照由执行器回调实现。

    该图只负责编排依赖、波次和并发，不知道如何检索、评估或持久化；这些业务动作由
    传入的回调完成，使图保持为可复用的调度层。
    """

    async def validate_dependencies(state: ResearchGraphState) -> dict[str, Any]:
        """图的首节点：在任何 Worker 启动前拒绝重复、缺失或循环依赖。"""

        validate_research_dependencies(state["sub_questions"])
        # 此节点只验证，不修改 state；空字典让 LangGraph 原样保留输入状态。
        return {}

    async def select_ready_wave(state: ResearchGraphState) -> dict[str, Any]:
        """根据已合并结果选出下一批依赖已满足、可并行研究的子问题。"""

        if should_stop():
            # 每次准备派发新 Worker 前检查取消，避免取消后继续产生外部调用。
            raise ResearchExecutionCancelled("TaskPlan 已取消")
        # results 是跨波次累积列表；转换为字典后可按依赖 id 快速查找状态。
        by_id = {item.sub_question_id: item for item in state["sub_questions"]}
        result_by_id = {item.sub_question_id: item for item in state["results"]}
        pending = [
            item for item in state["sub_questions"] if item.sub_question_id not in result_by_id
        ]

        # 失败依赖会级联为 skipped；例如 A 失败导致 B 跳过，B 又会导致 C 跳过。
        # 因此要循环到没有新 skipped 项为止，不能只检查一层依赖。
        skipped: list[AgentTaskSubQuestionResult] = []
        changed = True
        while changed:
            changed = False
            # known 包含历史结果和本轮刚推导出的 skipped 结果，供下一层级联继续使用。
            known = {**result_by_id, **{item.sub_question_id: item for item in skipped}}
            for item in pending:
                if item.sub_question_id in known:
                    continue
                failed_dependencies = [
                    dependency_id
                    for dependency_id in item.depends_on
                    if dependency_id in known
                    and known[dependency_id].status in {"failed", "skipped"}
                ]
                if failed_dependencies:
                    skipped.append(
                        AgentTaskSubQuestionResult(
                            sub_question_id=item.sub_question_id,
                            question=item.question,
                            selected_tool="none",
                            status="skipped",
                            error="DEPENDENCY_FAILED: " + ", ".join(failed_dependencies),
                            attempt_count=0,
                            warnings=["前置子问题失败，当前子问题未执行。"],
                        )
                    )
                    changed = True

        # 只有所有前置问题都 completed 或 partial，当前问题才可以安全开始。
        known = {**result_by_id, **{item.sub_question_id: item for item in skipped}}
        ready = [
            item
            for item in pending
            if item.sub_question_id not in known
            and all(
                dependency_id in known
                and known[dependency_id].status in {"completed", "partial"}
                for dependency_id in item.depends_on
            )
        ]
        # 排序后再截断，保证并发槽位有限时优先执行规划顺序靠前的问题。
        ready.sort(key=lambda item: (item.order, item.sub_question_id))
        ready = ready[: state["max_parallel_workers"]]
        wave = state["current_wave"] + (1 if ready else 0)
        batch_ids = [item.sub_question_id for item in ready]
        if ready:
            # 回调负责把“本波已开始”写入 TaskPlan 快照并通知 SSE；图本身不持久化。
            await on_wave_started(wave, batch_ids)
        return {
            "results": skipped,
            "current_wave": wave,
            "batch_ids": batch_ids,
        }

    def dispatch_wave(state: ResearchGraphState):
        """把当前波次扇出为多个 LangGraph Send，每个 Send 对应一个独立 Worker。"""

        if not state["batch_ids"]:
            # 没有可运行项时，所有子问题已经有终态结果（完成、失败或跳过）。
            return "finish"
        by_id = {item.sub_question_id: item for item in state["sub_questions"]}
        result_by_id = {item.sub_question_id: item for item in state["results"]}
        # Send 会为每个子问题创建独立的 ResearchWorkerState；并行 Worker 只返回自己的
        # results 项，由 State 的 operator.add reducer 安全汇总到全局 results。
        return [
            Send(
                "research_worker",
                {
                    "sub_question": by_id[item_id],
                    # 只暴露 declared depends_on 的结果，不让 Worker 隐式依赖无关子问题。
                    "dependency_results": [
                        result_by_id[dependency_id]
                        for dependency_id in by_id[item_id].depends_on
                        if dependency_id in result_by_id
                    ],
                    "wave": state["current_wave"],
                },
            )
            for item_id in state["batch_ids"]
        ]

    async def research_worker(state: ResearchWorkerState) -> dict[str, Any]:
        """执行一个子问题，并把单个结果交回全局 results reducer。"""

        if should_stop():
            # Worker 开始外部检索/联网前再次检查取消，缩小取消请求的竞态窗口。
            raise ResearchExecutionCancelled("TaskPlan 已取消")
        result = await worker_runner(
            state["sub_question"], state["dependency_results"], state["wave"]
        )
        return {"results": [result]}

    async def merge_wave(state: ResearchGraphState) -> dict[str, Any]:
        """收集当前波次所有 Worker 结果，持久化进度后清空 batch 标记。"""

        if should_stop():
            raise ResearchExecutionCancelled("TaskPlan 已取消")
        # batch_ids 冻结了本轮派发集合，避免把早前波次的累积结果重复交给合并回调。
        batch = set(state["batch_ids"])
        merged = [item for item in state["results"] if item.sub_question_id in batch]
        # Worker 实际结束顺序不可预测；回调前排序使快照和 SSE 展示保持稳定。
        merged.sort(key=lambda item: (by_order(state, item.sub_question_id), item.sub_question_id))
        await on_wave_merged(state["current_wave"], merged)
        # 清空后回到 select_ready_wave；下一轮只会派发新解锁的问题。
        return {"batch_ids": []}

    async def finish(_: ResearchGraphState) -> dict[str, Any]:
        """所有子问题均已有终态时的无副作用终止节点。"""

        return {}

    # 图结构固定为“校验 → 选择波次 → 扇出 Worker → 合并 → 再选择”；
    # 唯一循环位于 merge_wave_results 回到 select_ready_wave。
    graph = StateGraph(ResearchGraphState)
    graph.add_node("validate_dependencies", validate_dependencies)
    graph.add_node("select_ready_wave", select_ready_wave)
    graph.add_node("research_worker", research_worker)
    graph.add_node("merge_wave_results", merge_wave)
    graph.add_node("finish", finish)
    graph.add_edge(START, "validate_dependencies")
    graph.add_edge("validate_dependencies", "select_ready_wave")
    graph.add_conditional_edges(
        "select_ready_wave",
        dispatch_wave,
        ["research_worker", "finish"],
    )
    graph.add_edge("research_worker", "merge_wave_results")
    graph.add_edge("merge_wave_results", "select_ready_wave")
    graph.add_edge("finish", END)
    return graph.compile()


def by_order(state: ResearchGraphState, sub_question_id: str) -> int:
    """按 sub_question_id 查询规划顺序，供合并波次结果时恢复稳定展示顺序。"""

    for item in state["sub_questions"]:
        if item.sub_question_id == sub_question_id:
            return item.order
    # 理论上不会发生：batch_ids 来自 sub_questions；保留兜底值避免排序辅助函数抛异常。
    return 0


__all__ = [
    "ResearchExecutionCancelled",
    "build_agentic_research_graph",
    "validate_research_dependencies",
]
