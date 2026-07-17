"""Research TaskPlan 的波次调度、快照和最终综合。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig

from fast_app.components.llms.base import BaseLLMClient
from fast_app.core.config import Settings
from fast_app.domain.agent_task_plan import AgentResearchPolicy, AgentTaskPlan, AgentTaskPlanStatus, AgentTaskSubQuestion, AgentTaskSubQuestionResult
from fast_app.domain.rag_models import RagContext, RetrievalFilters
from fast_app.domain.user_context import CurrentUserContext
from fast_app.graph.research.agentic_research_graph import ResearchExecutionCancelled, build_agentic_research_graph
from fast_app.services.agent_tasks.agent_task_plan_store import AgentTaskPlanStore
from fast_app.services.exceptions import AppServiceError, ToolPermissionDeniedError
from fast_app.services.research.research_tool_loop import merge_evidence
from fast_app.services.research.research_worker_agent import ResearchWorkerAgent, ResearchWorkerRequest

LangChainConfigFactory = Callable[[str], RunnableConfig]


class _TaskPlanPersistenceError(AppServiceError):
    """研究进度快照无法持久化。"""


class AgenticResearchExecutor:
    """执行整个只读 Research TaskPlan，不承担单 Worker 工具细节。"""

    def __init__(self, settings: Settings, llm_client: BaseLLMClient, task_plan_store: AgentTaskPlanStore, worker_agent: ResearchWorkerAgent) -> None:
        self._settings = settings
        self._llm_client = llm_client
        self._task_plan_store = task_plan_store
        self._worker_agent = worker_agent

    def _sync_cancelled_state(self, plan: AgentTaskPlan) -> bool:
        """把控制 API 写入的 cancelled 快照同步到当前执行对象。"""

        # 执行协程与 cancel API 不共享内存；以文件快照作为它们之间的取消信号。
        latest = self._task_plan_store.load(plan.task_plan_id)
        if latest.status != AgentTaskPlanStatus.CANCELLED:
            return False
        plan.status = latest.status
        plan.steps = latest.steps
        plan.final_output = {**plan.final_output, **latest.final_output}
        plan.error = None
        return True

    async def _generate_with_trace(
        self,
        query: str,
        context: RagContext,
        langchain_config: RunnableConfig | None = None,
    ) -> str:
        """调用 LLM；兼容测试中仍使用旧签名的 fake client。"""

        try:
            # 真实 LangChain client 使用 langchain_config 透传 LangSmith 子 run 名称。
            answer = await self._llm_client.generate(
                query=query,
                context=context,
                langchain_config=langchain_config,
            )
            return _as_text(answer)
        except TypeError as exc:
            if "langchain_config" not in str(exc):
                raise
            answer = await self._llm_client.generate(query=query, context=context)
            return _as_text(answer)

    async def execute_question_decomposition_plan(
        self,
        plan: AgentTaskPlan,
        user: CurrentUserContext,
        mode: str,
        top_k: int,
        candidate_k: int | None,
        min_score: float,
        filters: RetrievalFilters,
        langchain_config_factory: LangChainConfigFactory | None = None,
        resume: bool = False,
    ) -> AgentTaskPlan:
        """用 LangGraph 按依赖波次并行执行研究 Worker，再统一综合结果。"""

        if plan.task_kind != "question_decomposition":
            raise AppServiceError(f"不支持的问题拆解 task kind: {plan.task_kind}")
        if len(plan.sub_questions) > self._settings.agent_research_max_sub_questions:
            plan.status = AgentTaskPlanStatus.FAILED
            plan.error = (
                "研究子问题数量超过上限: "
                f"{len(plan.sub_questions)}>{self._settings.agent_research_max_sub_questions}"
            )
            plan.final_output = {"status": plan.status.value}
            self._task_plan_store.save(plan)
            raise AppServiceError(plan.error)

        plan.user_id = plan.user_id or user.user_id
        plan.status = AgentTaskPlanStatus.RUNNING
        retained_results: list[AgentTaskSubQuestionResult] = []
        if resume:
            # 重试只复用已完成结果；failed/partial 会重新执行，避免把不足证据当成最终事实。
            retained_results = [
                AgentTaskSubQuestionResult.model_validate(item)
                for item in plan.final_output.get("sub_question_results", [])
                if isinstance(item, dict) and item.get("status") == "completed"
            ]
        plan.final_output = {
            "research_progress": {"current_wave": 0, "workers": {}, "events": []},
            "sub_question_results": [
                item.model_dump(mode="json") for item in retained_results
            ],
            "failed_sub_questions": [],
            "skipped_sub_questions": [],
            "warnings": [],
            "used_tools": sorted(
                {tool for item in retained_results for tool in _result_used_tools(item)}
            ),
            "sources": _collect_result_sources(retained_results),
        }
        self._task_plan_store.save(plan)
        # 多个 Worker 可同时上报事件；这把“更新内存快照 + 落盘”串行化，防止字段互相覆盖。
        snapshot_lock = asyncio.Lock()

        def save_research_snapshot() -> None:
            # 持久化失败会中断整个研究图，而非伪装成某个 Worker 的局部失败；否则 SSE
            # 与后续 resume 会读取到不完整的事实快照。
            try:
                self._task_plan_store.save(plan)
            except Exception as exc:
                raise _TaskPlanPersistenceError(
                    f"无法持久化 TaskPlan 快照: {type(exc).__name__}: {exc}"
                ) from exc

        async def append_progress_event(event: str, payload: dict[str, Any]) -> None:
            # Worker 只提交事件负载；此回调负责把它转换成 API/SSE 可观察的统一进度结构。
            async with snapshot_lock:
                progress = plan.final_output["research_progress"]
                progress["events"].append({"event": event, **payload})
                worker_id = str(payload.get("sub_question_id") or "")
                if worker_id:
                    worker = progress["workers"].setdefault(worker_id, {})
                    worker.update(
                        {
                            key: value
                            for key, value in payload.items()
                            if key in {"status", "wave", "attempt", "evaluation", "error"}
                        }
                    )
                save_research_snapshot()

        async def on_wave_started(wave: int, sub_question_ids: list[str]) -> None:
            # 先把本波次所有 Worker 标为 running，再启动实际协程，避免极快完成时页面漏掉开始态。
            async with snapshot_lock:
                progress = plan.final_output["research_progress"]
                progress["current_wave"] = wave
                progress["events"].append(
                    {
                        "event": "agent_task_research_wave_started",
                        "wave": wave,
                        "sub_question_ids": sub_question_ids,
                    }
                )
                for item_id in sub_question_ids:
                    progress["workers"][item_id] = {
                        "status": "running",
                        "wave": wave,
                        "attempt": 1,
                        "evaluation": None,
                        "error": None,
                    }
                save_research_snapshot()

        merged_by_id = {item.sub_question_id: item for item in retained_results}

        async def on_wave_merged(
            wave: int,
            wave_results: list[AgentTaskSubQuestionResult],
        ) -> None:
            async with snapshot_lock:
                # LangGraph 并行节点的返回顺序不可预测；按 id 覆盖后统一排序，快照才稳定。
                for item in wave_results:
                    merged_by_id[item.sub_question_id] = item
                    plan.final_output["research_progress"]["workers"].setdefault(
                        item.sub_question_id, {}
                    ).update(
                        {
                            "status": item.status,
                            "wave": wave,
                            "attempt": item.attempt_count,
                            "evaluation": (
                                item.evaluation.model_dump(mode="json")
                                if item.evaluation is not None
                                else None
                            ),
                            "error": item.error,
                        }
                    )
                ordered = _sort_results(plan, list(merged_by_id.values()))
                plan.final_output["sub_question_results"] = [
                    item.model_dump(mode="json") for item in ordered
                ]
                plan.final_output["used_tools"] = sorted(
                    {tool for item in ordered for tool in _result_used_tools(item)}
                )
                plan.final_output["sources"] = _collect_result_sources(ordered)
                save_research_snapshot()

        def should_stop() -> bool:
            # Graph 和每个 Worker 复用同一取消探针，在派发新波次前以及长操作边界检查。
            return self._sync_cancelled_state(plan)

        async def worker_runner(
            sub_question: AgentTaskSubQuestion,
            dependency_results: list[AgentTaskSubQuestionResult],
            wave: int,
        ) -> AgentTaskSubQuestionResult:
            try:
                # Worker 超时限制在单子问题；一个慢工具不应阻塞同波次的其他研究结果。
                return await asyncio.wait_for(
                    self._worker_agent.run(
                        ResearchWorkerRequest(
                            plan=plan,
                            sub_question=sub_question,
                            dependency_results=dependency_results,
                            policy=plan.research_policy
                            or AgentResearchPolicy(
                                mode=mode,
                                top_k=top_k,
                                candidate_k=candidate_k,
                                min_score=min_score,
                                source_path=filters.source_path,
                                section_path=filters.section_path,
                                web_policy="disabled",
                            ),
                            filters=filters,
                            wave=wave,
                            on_progress=append_progress_event,
                            should_stop=should_stop,
                            langchain_config_factory=langchain_config_factory,
                        )
                    ),
                    timeout=self._settings.agent_research_worker_timeout_seconds,
                )
            except ResearchExecutionCancelled:
                raise
            except ToolPermissionDeniedError:
                raise
            except _TaskPlanPersistenceError:
                raise
            except TimeoutError:
                return _failed_research_result(
                    sub_question, "WORKER_TIMEOUT", "Worker 执行超时。"
                )
            except Exception as exc:
                return _failed_research_result(
                    sub_question,
                    f"{type(exc).__name__}: {exc}",
                    "Worker 局部异常已隔离。",
                )

        try:
            graph = build_agentic_research_graph(
                worker_runner=worker_runner,
                on_wave_started=on_wave_started,
                on_wave_merged=on_wave_merged,
                should_stop=should_stop,
            )
            graph_result = await graph.ainvoke(
                {
                    "sub_questions": plan.sub_questions,
                    "results": retained_results,
                    "current_wave": 0,
                    "batch_ids": [],
                    "max_parallel_workers": self._settings.agent_research_max_parallel_workers,
                }
            )
            # 图已经把依赖失败转换成 skipped；Executor 在图外只负责汇总、综合与最终状态。
            results = _sort_results(plan, graph_result.get("results", []))
            if self._sync_cancelled_state(plan):
                self._task_plan_store.save(plan)
                return plan
            usable = [item for item in results if item.status in {"completed", "partial"}]
            failed = [item.sub_question_id for item in results if item.status == "failed"]
            skipped = [item.sub_question_id for item in results if item.status == "skipped"]
            warnings = [warning for item in results for warning in item.warnings]
            warnings.extend(
                f"{item.sub_question_id}: {item.status} - {item.error or '证据不足'}"
                for item in results
                if item.status in {"failed", "skipped"} and not item.warnings
            )
            workers = plan.final_output["research_progress"]["workers"]
            for item in results:
                workers.setdefault(item.sub_question_id, {}).update(
                    {
                        "status": item.status,
                        "attempt": item.attempt_count,
                        "evaluation": (
                            item.evaluation.model_dump(mode="json")
                            if item.evaluation is not None
                            else None
                        ),
                        "error": item.error,
                    }
                )
            plan.final_output.update(
                {
                    "sub_question_results": [
                        item.model_dump(mode="json") for item in results
                    ],
                    "failed_sub_questions": failed,
                    "skipped_sub_questions": skipped,
                    "warnings": warnings,
                    "sources": _collect_result_sources(usable),
                    "used_tools": sorted(
                        {tool for item in results for tool in _result_used_tools(item)}
                    ),
                }
            )
            if not usable:
                # 没有任何可用证据时不能请求综合模型，避免生成看似完整但无依据的答案。
                plan.status = AgentTaskPlanStatus.FAILED
                plan.error = "所有子问题均 failed/skipped，没有可综合的证据。"
                plan.final_output["status"] = plan.status.value
                self._task_plan_store.save(plan)
                return plan
            final_answer = await self._synthesize_final_answer(
                plan,
                usable,
                failed_sub_questions=failed,
                skipped_sub_questions=skipped,
                langchain_config_factory=langchain_config_factory,
            )
            plan.status = (
                AgentTaskPlanStatus.COMPLETED
                if all(item.status == "completed" for item in results)
                else AgentTaskPlanStatus.COMPLETED_WITH_WARNINGS
            )
            plan.final_output.update(
                {
                    "final_answer": final_answer,
                    "status": plan.status.value,
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            )
            self._task_plan_store.save(plan)
            return plan
        except ResearchExecutionCancelled:
            self._sync_cancelled_state(plan)
            self._task_plan_store.save(plan)
            return plan
        except Exception as exc:
            plan.status = AgentTaskPlanStatus.FAILED
            plan.error = f"{type(exc).__name__}: {exc}"
            plan.final_output["status"] = plan.status.value
            self._task_plan_store.save(plan)
            raise
    async def _synthesize_final_answer(
        self,
        plan: AgentTaskPlan,
        results: list[AgentTaskSubQuestionResult],
        failed_sub_questions: list[str] | None = None,
        skipped_sub_questions: list[str] | None = None,
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> str:
        """把所有子问题答案和证据整合成面向用户的最终回答。"""

        context = RagContext(
            query=plan.original_query,
            docs=[],
            context_text=_format_sub_question_results(results),
        )
        # 综合模型只读取序列化后的已完成结果，不能凭空补全 failed/skipped 子问题。
        answer = await self._generate_with_trace(
            query=(
                f"请回答原始复杂问题：{plan.original_query}\n"
                f"最终目标：{plan.objective}\n"
                f"整合要求：{plan.final_synthesis_instruction}\n"
                f"失败子问题：{failed_sub_questions or []}\n"
                f"跳过子问题：{skipped_sub_questions or []}\n"
                "只能使用 completed/partial 结果和实际证据；不得推测失败问题，"
                "必须明确说明未完成、证据不足和冲突内容。"
            ),
            context=context,
            langchain_config=(
                langchain_config_factory("research.final_synthesis")
                if langchain_config_factory is not None
                else None
            ),
        )
        return answer.strip() or _fallback_final_answer(plan, results)

def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return str(value or "")


def _failed_research_result(sub_question: AgentTaskSubQuestion, error: str, warning: str | None = None) -> AgentTaskSubQuestionResult:
    return AgentTaskSubQuestionResult(
        sub_question_id=sub_question.sub_question_id,
        question=sub_question.question,
        selected_tool="none",
        status="failed",
        error=error,
        warnings=[warning] if warning else [],
    )


def _sort_results(plan: AgentTaskPlan, results: list[AgentTaskSubQuestionResult]) -> list[AgentTaskSubQuestionResult]:
    order_by_id = {item.sub_question_id: item.order for item in plan.sub_questions}
    by_id = {item.sub_question_id: item for item in results}
    return sorted(by_id.values(), key=lambda item: (order_by_id.get(item.sub_question_id, 0), item.sub_question_id))


def _collect_result_sources(results: list[AgentTaskSubQuestionResult]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for result in results:
        if result.status in {"completed", "partial"}:
            sources = merge_evidence(sources, result.evidence)
    return sources


def _result_used_tools(result: AgentTaskSubQuestionResult) -> list[str]:
    if result.tool_calls:
        return [item.tool_name for item in result.tool_calls if item.status == "completed" and item.tool_name and item.tool_name != "none"]
    return [result.selected_tool] if result.selected_tool and result.selected_tool != "none" else []


def _fallback_final_answer(
    plan: AgentTaskPlan,
    results: list[AgentTaskSubQuestionResult],
) -> str:
    """最终综合为空时，只拼接 completed/partial 的已有答案。"""

    lines = [
        f"# {plan.objective}",
        "",
        "最终综合模型没有返回有效正文，以下为基于子问题结果生成的兜底答案。",
    ]
    for item in results:
        if item.status not in {"completed", "partial"} or not item.answer.strip():
            continue
        lines.extend(["", f"## {item.question}", "", item.answer.strip()])
    return "\n".join(lines)


def _format_sub_question_results(
    results: list[AgentTaskSubQuestionResult],
) -> str:
    """保留状态、工具、证据和评估，供最终综合模型追溯。"""

    import json

    lines: list[str] = []
    for result in results:
        lines.append(
            "\n".join(
                [
                    f"子问题 {result.sub_question_id}: {result.question}",
                    f"状态: {result.status}",
                    f"工具: {result.selected_tool}",
                    f"工具调用: {json.dumps([call.model_dump(mode='json') for call in result.tool_calls], ensure_ascii=False)}",
                    f"回答: {result.answer}",
                    f"证据: {json.dumps(result.evidence, ensure_ascii=False)}",
                    f"评估: {json.dumps(result.evaluation.model_dump(mode='json') if result.evaluation else None, ensure_ascii=False)}",
                    f"警告: {json.dumps(result.warnings, ensure_ascii=False)}",
                    f"错误: {result.error or ''}",
                ]
            )
        )
    return "\n\n".join(lines)


__all__ = ["AgenticResearchExecutor"]
