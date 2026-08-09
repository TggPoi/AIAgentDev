"""ResearchTaskPlan v2 的波次调度、Evidence 单写者和最终综合。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from langchain_core.runnables import RunnableConfig

from fast_app.components.llms.base import BaseLLMClient
from fast_app.core.config import Settings
from fast_app.domain.agent_task_plan import (
    AgentResearchPolicy,
    AgentTaskPlanStatus,
    AgentTaskSubQuestionResult,
)
from fast_app.domain.rag_models import RagContext, RetrievalFilters
from fast_app.domain.research_task_plan import (
    ResearchProgressEvent,
    ResearchTaskFinalOutput,
    ResearchTaskPlan,
    ResearchTaskSubQuestion,
    ResearchTaskSubQuestionResult,
    ResearchWorkerCheckpoint,
    ResearchWorkerCheckpointUpdate,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.graph.research.agentic_research_graph import (
    ResearchExecutionCancelled,
    build_agentic_research_graph,
)
from fast_app.services.agent_tasks.agent_task_plan_store import AgentTaskPlanStore
from fast_app.services.exceptions import (
    AgentTaskEvidenceStateInvalidError,
    AppServiceError,
    ToolPermissionDeniedError,
)
from fast_app.services.rag.prompt_guard_service import PromptGuardService
from fast_app.services.research.requirement_evidence_service import (
    AgentTaskRequirementEvidenceService,
)
from fast_app.services.research.research_worker_agent import (
    ResearchWorkerAgent,
    ResearchWorkerRequest,
)
from fast_app.services.research.research_tool_loop import merge_evidence


LangChainConfigFactory = Callable[[str], RunnableConfig]


class _TaskPlanPersistenceError(AppServiceError):
    """Research JSON 快照无法原子持久化。"""


class AgenticResearchExecutor:
    """执行只读 ResearchTaskPlan；Worker 从不直接修改 Evidence Registry。"""

    def __init__(
        self,
        settings: Settings,
        llm_client: BaseLLMClient,
        task_plan_store: AgentTaskPlanStore,
        worker_agent: ResearchWorkerAgent,
        *,
        prompt_guard: PromptGuardService | None = None,
        evidence_service: AgentTaskRequirementEvidenceService | None = None,
    ) -> None:
        self._settings = settings
        self._llm_client = llm_client
        self._task_plan_store = task_plan_store
        self._worker_agent = worker_agent
        self._prompt_guard = prompt_guard
        self._evidence_service = evidence_service or AgentTaskRequirementEvidenceService()

    def _sync_cancelled_state(self, plan: ResearchTaskPlan) -> bool:
        latest = self._task_plan_store.load(plan.task_plan_id)
        if not isinstance(latest, ResearchTaskPlan) or latest.status != AgentTaskPlanStatus.CANCELLED:
            return False
        plan.status = latest.status
        plan.error_code = None
        plan.error_message = None
        return True

    async def execute_question_decomposition_plan(
        self,
        plan: ResearchTaskPlan,
        user: CurrentUserContext,
        mode: str,
        top_k: int,
        candidate_k: int | None,
        min_score: float,
        filters: RetrievalFilters,
        langchain_config_factory: LangChainConfigFactory | None = None,
        resume: bool = False,
    ) -> ResearchTaskPlan:
        """按 DAG 波次执行 Worker，并在每个 Wave 后一次性提交 Evidence 和状态。"""

        if plan.schema_version != 2 or plan.task_kind != "question_decomposition":
            raise AppServiceError("Research Executor 只接受 ResearchTaskPlan v2")
        registry_ids = set(plan.evidence_registry.evidence_by_id)
        if any(
            not set(item.evidence_ids).issubset(registry_ids)
            for item in plan.sub_question_results
        ):
            raise AgentTaskEvidenceStateInvalidError(
                "SubQuestion Result 引用了 Registry 中不存在的 Evidence"
            )
        plan.status = AgentTaskPlanStatus.RUNNING
        if not resume:
            plan.sub_question_results = []
            plan.evidence_registry.evidence_by_id.clear()
            plan.worker_checkpoints.clear()
        retained = [item for item in plan.sub_question_results if item.status == "completed"]
        plan.sub_question_results = retained
        plan.final_output = None
        self._save(plan)
        snapshot_lock = asyncio.Lock()
        formal_by_id = {item.sub_question_id: item for item in plan.sub_questions}
        merged_results = {item.sub_question_id: item for item in retained}

        def apply_progress_event(event: str, payload: dict[str, object]) -> None:
            sub_question_id = str(payload.get("sub_question_id") or "") or None
            raw_active_operations = payload.get("active_operations")
            active_operations = (
                [str(item) for item in raw_active_operations if isinstance(item, str)]
                if isinstance(raw_active_operations, list)
                else []
            )
            plan.progress.events.append(
                ResearchProgressEvent(
                    event=event,
                    sub_question_id=sub_question_id,
                    wave=_as_int(payload.get("wave")),
                    status=(str(payload.get("status")) if payload.get("status") else None),
                    reason_code=(str(payload.get("error")) if payload.get("error") else None),
                    attempt=_as_int(payload.get("attempt")),
                    stage=(str(payload.get("stage")) if payload.get("stage") else None),
                    active_operations=active_operations,
                    tool_call_count=_as_int(payload.get("tool_call_count")),
                    evidence_count=_as_int(payload.get("evidence_count")),
                    last_tool_name=(
                        str(payload.get("last_tool_name"))
                        if payload.get("last_tool_name")
                        else None
                    ),
                )
            )
            if not sub_question_id or sub_question_id not in plan.progress.workers:
                return
            worker = plan.progress.workers[sub_question_id]
            if payload.get("status") in {
                "pending",
                "running",
                "completed",
                "partial",
                "failed",
                "skipped",
            }:
                worker.status = str(payload["status"])
            worker.wave = _as_int(payload.get("wave")) or worker.wave
            worker.attempt = _as_int(payload.get("attempt")) or worker.attempt
            if payload.get("stage"):
                worker.stage = str(payload["stage"])
            if isinstance(raw_active_operations, list):
                worker.active_operations = active_operations
            tool_call_count = _as_int(payload.get("tool_call_count"))
            if tool_call_count is not None:
                worker.tool_call_count = tool_call_count
            evidence_count = _as_int(payload.get("evidence_count"))
            if evidence_count is not None:
                worker.evidence_count = evidence_count
            if payload.get("last_tool_name"):
                worker.last_tool_name = str(payload["last_tool_name"])
            if payload.get("error"):
                worker.error_code = str(payload["error"])

        async def append_progress_event(event: str, payload: dict[str, object]) -> None:
            async with snapshot_lock:
                apply_progress_event(event, payload)
                self._save(plan)

        async def save_worker_checkpoint(
            sub_question: ResearchTaskSubQuestion,
            wave: int,
            update: ResearchWorkerCheckpointUpdate,
        ) -> None:
            async with snapshot_lock:
                checkpoint = plan.worker_checkpoints.setdefault(
                    sub_question.sub_question_id,
                    ResearchWorkerCheckpoint(),
                )
                checkpoint.stage = update.stage
                checkpoint.attempt = update.attempt
                if update.operation is not None and update.operation_status == "started":
                    checkpoint.active_operations.append(update.operation)
                elif update.operation is not None:
                    try:
                        checkpoint.active_operations.remove(update.operation)
                    except ValueError:
                        pass
                if update.tool_call is not None:
                    calls_by_id = {item.call_id: item for item in checkpoint.tool_calls}
                    calls_by_id[update.tool_call.call_id] = update.tool_call
                    checkpoint.tool_calls = list(calls_by_id.values())
                    checkpoint.last_tool_name = update.tool_call.tool_name
                checkpoint.evidence = merge_evidence(
                    checkpoint.evidence,
                    update.evidence,
                )
                apply_progress_event(
                    "agent_task_research_worker_progress",
                    {
                        "sub_question_id": sub_question.sub_question_id,
                        "wave": wave,
                        "attempt": checkpoint.attempt,
                        "status": "running",
                        "stage": checkpoint.stage,
                        "active_operations": sorted(set(checkpoint.active_operations)),
                        "tool_call_count": len(checkpoint.tool_calls),
                        "evidence_count": len(checkpoint.evidence),
                        "last_tool_name": checkpoint.last_tool_name,
                    },
                )
                self._save(plan)

        async def mark_worker_timed_out(
            sub_question: ResearchTaskSubQuestion,
            wave: int,
        ) -> None:
            checkpoint = plan.worker_checkpoints.get(sub_question.sub_question_id)
            await append_progress_event(
                "agent_task_research_worker_timed_out",
                {
                    "sub_question_id": sub_question.sub_question_id,
                    "wave": wave,
                    "attempt": checkpoint.attempt if checkpoint else 1,
                    "status": "failed",
                    "error": "WORKER_TIMEOUT",
                    "stage": checkpoint.stage if checkpoint else "starting",
                    "active_operations": (
                        sorted(set(checkpoint.active_operations)) if checkpoint else []
                    ),
                    "tool_call_count": len(checkpoint.tool_calls) if checkpoint else 0,
                    "evidence_count": len(checkpoint.evidence) if checkpoint else 0,
                    "last_tool_name": checkpoint.last_tool_name if checkpoint else None,
                },
            )

        async def on_wave_started(wave: int, sub_question_ids: list[str]) -> None:
            async with snapshot_lock:
                plan.progress.current_wave = wave
                plan.progress.events.append(
                    ResearchProgressEvent(event="agent_task_research_wave_started", wave=wave)
                )
                for item_id in sub_question_ids:
                    worker = plan.progress.workers[item_id]
                    worker.status = "running"
                    worker.wave = wave
                    worker.attempt = max(worker.attempt, 1)
                self._save(plan)

        async def on_wave_merged(
            wave: int,
            wave_results: list[AgentTaskSubQuestionResult],
        ) -> None:
            async with snapshot_lock:
                completed_ids = {
                    item.sub_question_id
                    for item in merged_results.values()
                    if item.status in {"completed", "partial"}
                }
                for legacy in wave_results:
                    sub_question = formal_by_id[legacy.sub_question_id]
                    successful_calls = {
                        call.call_id: call.tool_name
                        for call in legacy.tool_calls
                        if call.status == "completed" and call.tool_name
                    }
                    candidates, invalid_refs, build_reason_codes = (
                        self._evidence_service.build_candidates(
                        task_plan_id=plan.task_plan_id,
                        sub_question=sub_question,
                        answer=legacy.answer,
                        legacy_evidence=legacy.evidence,
                        successful_tool_calls=successful_calls,
                        )
                    )
                    validation, valid = self._evidence_service.validate_sub_question_evidence(
                        sub_question=sub_question,
                        candidates=candidates,
                        successful_tool_calls=successful_calls,
                        completed_result_ids=completed_ids,
                        invalid_evidence_refs=invalid_refs,
                        initial_reason_codes=build_reason_codes,
                    )
                    plan.evidence_registry = self._evidence_service.merge_registry(
                        plan.evidence_registry,
                        valid,
                    )
                    converted = _to_research_result(legacy, validation)
                    merged_results[converted.sub_question_id] = converted
                    if converted.status in {"completed", "partial"}:
                        completed_ids.add(converted.sub_question_id)
                    worker = plan.progress.workers[converted.sub_question_id]
                    worker.status = converted.status
                    worker.wave = wave
                    worker.attempt = converted.attempt_count
                    worker.error_code = converted.error_code
                    if converted.error_code != "WORKER_TIMEOUT":
                        plan.worker_checkpoints.pop(converted.sub_question_id, None)
                plan.sub_question_results = _sort_results(plan, list(merged_results.values()))
                plan.requirement_evidence_statuses = self._evidence_service.aggregate(
                    requirements=plan.requirements,
                    sub_questions=plan.sub_questions,
                    results=plan.sub_question_results,
                    registry=plan.evidence_registry,
                )
                self._save(plan)

        def should_stop() -> bool:
            return self._sync_cancelled_state(plan)

        async def worker_runner(
            sub_question: ResearchTaskSubQuestion,
            dependency_results: list[AgentTaskSubQuestionResult],
            wave: int,
        ) -> AgentTaskSubQuestionResult:
            if sub_question.information_source_hint == "none":
                await save_worker_checkpoint(
                    sub_question,
                    wave,
                    ResearchWorkerCheckpointUpdate(
                        stage="answer_generation",
                        attempt=1,
                        operation="derived_synthesis",
                        operation_status="started",
                    ),
                )
                try:
                    result = await asyncio.wait_for(
                        self._run_derived_sub_question(
                            sub_question,
                            dependency_results,
                            langchain_config_factory=langchain_config_factory,
                        ),
                        timeout=self._settings.agent_research_worker_timeout_seconds,
                    )
                except TimeoutError:
                    await mark_worker_timed_out(sub_question, wave)
                    return _timeout_legacy_result(
                        sub_question,
                        plan.worker_checkpoints.get(sub_question.sub_question_id),
                    )
                await save_worker_checkpoint(
                    sub_question,
                    wave,
                    ResearchWorkerCheckpointUpdate(
                        stage="completed",
                        attempt=1,
                        operation="derived_synthesis",
                        operation_status="finished",
                    ),
                )
                return result
            web_policy = {
                "direct": "required",
                "fallback_on_insufficient_evidence": "fallback",
                "not_used": "disabled",
            }[sub_question.web_usage]
            policy = AgentResearchPolicy(
                mode=mode,
                top_k=top_k,
                candidate_k=candidate_k,
                min_score=min_score,
                source_path=filters.source_path,
                section_path=filters.section_path,
                web_policy=web_policy,
                dataset_id=plan.research_policy.dataset_id,
                nl2sql_action=plan.research_policy.nl2sql_action,
            )
            async def on_checkpoint(update: ResearchWorkerCheckpointUpdate) -> None:
                await save_worker_checkpoint(sub_question, wave, update)

            try:
                return await asyncio.wait_for(
                    self._worker_agent.run(
                        ResearchWorkerRequest(
                            plan=plan,
                            sub_question=sub_question,
                            dependency_results=dependency_results,
                            policy=policy,
                            filters=filters,
                            wave=wave,
                            on_progress=append_progress_event,
                            on_checkpoint=on_checkpoint,
                            should_stop=should_stop,
                            user=user,
                            langchain_config_factory=langchain_config_factory,
                        )
                    ),
                    timeout=self._settings.agent_research_worker_timeout_seconds,
                )
            except (ResearchExecutionCancelled, ToolPermissionDeniedError, _TaskPlanPersistenceError):
                raise
            except TimeoutError:
                await mark_worker_timed_out(sub_question, wave)
                return _timeout_legacy_result(
                    sub_question,
                    plan.worker_checkpoints.get(sub_question.sub_question_id),
                )
            except Exception as exc:
                return _failed_legacy_result(sub_question, type(exc).__name__)

        try:
            graph = build_agentic_research_graph(
                worker_runner=worker_runner,
                on_wave_started=on_wave_started,
                on_wave_merged=on_wave_merged,
                should_stop=should_stop,
            )
            retained_legacy = [_to_legacy_result(item, formal_by_id[item.sub_question_id]) for item in retained]
            graph_result = await graph.ainvoke(
                {
                    "sub_questions": plan.sub_questions,
                    "results": retained_legacy,
                    "current_wave": 0,
                    "batch_ids": [],
                    "max_parallel_workers": self._settings.agent_research_max_parallel_workers,
                }
            )
            uncommitted = [
                item
                for item in graph_result.get("results", [])
                if item.sub_question_id not in merged_results
            ]
            if uncommitted:
                await on_wave_merged(plan.progress.current_wave, uncommitted)
            if self._sync_cancelled_state(plan):
                self._save(plan)
                return plan
            plan.requirement_evidence_statuses = self._evidence_service.aggregate(
                requirements=plan.requirements,
                sub_questions=plan.sub_questions,
                results=plan.sub_question_results,
                registry=plan.evidence_registry,
            )
            requirement_failed = any(
                item.status == "failed" for item in plan.requirement_evidence_statuses
            )
            if requirement_failed or any(
                item.status == "pending" for item in plan.requirement_evidence_statuses
            ):
                plan.status = AgentTaskPlanStatus.FAILED
                plan.error_code = "AGENT_TASK_REQUIREMENT_FAILED"
                plan.error_message = "至少一个 Requirement 未满足证据契约。"
                self._save(plan)
                return plan
            partial = any(item.status == "partially_satisfied" for item in plan.requirement_evidence_statuses)
            answer, included_ids, evidence_ids = await self._synthesize_final_answer(
                plan,
                langchain_config_factory=langchain_config_factory,
            )
            guard_action = "allow"
            guard_reasons: list[str] = []
            if self._prompt_guard is not None:
                guard = await self._prompt_guard.classify_output(
                    answer,
                    source="research.final_synthesis.output",
                )
                self._prompt_guard.audit_guard_result(
                    result=guard,
                    source="research.final_synthesis.output",
                )
                guard_action = guard.action.value
                guard_reasons = list(guard.categories)
                if guard.should_sanitize and guard.sanitized_text is not None:
                    answer = guard.sanitized_text
                elif guard.should_block:
                    answer = self._prompt_guard.build_safe_refusal_answer()
            plan.status = (
                AgentTaskPlanStatus.COMPLETED_WITH_WARNINGS
                if partial
                else AgentTaskPlanStatus.COMPLETED
            )
            plan.final_output = ResearchTaskFinalOutput(
                answer=answer,
                included_requirement_ids=included_ids,
                evidence_ids=evidence_ids,
                used_tools=sorted(
                    {
                        call.tool_name
                        for item in plan.sub_question_results
                        for call in item.tool_calls
                        if call.status == "completed" and call.tool_name != "none"
                    }
                ),
                warnings=[
                    f"{item.requirement_id}: {', '.join(item.reason_codes)}"
                    for item in plan.requirement_evidence_statuses
                    if item.status == "partially_satisfied"
                ],
                guard_action=guard_action,
                guard_reason_codes=guard_reasons,
                completed_at=datetime.now(UTC),
            )
            self._save(plan)
            return plan
        except ResearchExecutionCancelled:
            self._sync_cancelled_state(plan)
            self._save(plan)
            return plan
        except Exception as exc:
            plan.status = AgentTaskPlanStatus.FAILED
            plan.error_code = type(exc).__name__
            plan.error_message = str(exc)
            self._save(plan)
            raise

    async def _synthesize_final_answer(
        self,
        plan: ResearchTaskPlan,
        *,
        langchain_config_factory: LangChainConfigFactory | None,
    ) -> tuple[str, list[str], list[str]]:
        allowed_statuses = {"satisfied", "partially_satisfied"}
        allowed_requirements = [
            item for item in plan.requirement_evidence_statuses if item.status in allowed_statuses
        ]
        allowed_evidence = sorted({value for item in allowed_requirements for value in item.evidence_refs})
        allowed_sub_questions = {
            value for item in allowed_requirements for value in item.covering_sub_question_ids
        }
        result_lines = []
        for item in plan.sub_question_results:
            valid_ids = [value for value in item.evidence_ids if value in allowed_evidence]
            if item.sub_question_id not in allowed_sub_questions or not valid_ids:
                continue
            result_lines.append(
                f"sub_question_id={item.sub_question_id}\n"
                f"evidence_ids={valid_ids}\nanswer={item.answer or ''}"
            )
        limitations = [
            f"{item.requirement_id}: missing={item.missing_source_types}, reasons={item.reason_codes}"
            for item in allowed_requirements
            if item.status == "partially_satisfied"
        ]
        context = RagContext(
            query=plan.source_query,
            docs=[],
            context_text="\n\n".join(result_lines),
        )
        answer = await self._generate_with_trace(
            query=(
                f"回答任务：{plan.source_query}\n"
                f"综合约束：{plan.final_synthesis_instruction}\n"
                f"允许使用的 Requirement：{[item.requirement_id for item in allowed_requirements]}\n"
                f"证据限制：{limitations}\n"
                "只能使用上下文中的合法 Evidence 支撑结论；若有部分满足，必须明确说明限制。"
            ),
            context=context,
            langchain_config=(
                langchain_config_factory("research.final_synthesis")
                if langchain_config_factory is not None
                else None
            ),
        )
        if not answer.strip():
            answer = "\n\n".join(result_lines)
        return (
            answer.strip(),
            [item.requirement_id for item in allowed_requirements],
            allowed_evidence,
        )

    async def _run_derived_sub_question(
        self,
        sub_question: ResearchTaskSubQuestion,
        dependency_results: list[AgentTaskSubQuestionResult],
        *,
        langchain_config_factory: LangChainConfigFactory | None,
    ) -> AgentTaskSubQuestionResult:
        """综合已完成依赖；该路径不调用外部事实 Tool。"""

        usable = [
            item
            for item in dependency_results
            if item.status in {"completed", "partial"} and item.answer.strip()
        ]
        if not usable:
            return _failed_legacy_result(sub_question, "DEPENDENCY_EVIDENCE_UNAVAILABLE")
        has_partial_dependency = any(
            item.status == "partial" for item in dependency_results
        )
        context = RagContext(
            query=sub_question.question,
            docs=[],
            context_text="\n\n".join(
                f"sub_question_id={item.sub_question_id}\n{item.answer}" for item in usable
            ),
        )
        answer = await self._generate_with_trace(
            query=(
                f"只基于依赖子问题结果完成综合：{sub_question.question}\n"
                "不得补充上下文之外的新事实；证据不足时明确说明。"
            ),
            context=context,
            langchain_config=(
                langchain_config_factory("research.sub_question.derived_synthesis")
                if langchain_config_factory is not None
                else None
            ),
        )
        if not answer.strip():
            return _failed_legacy_result(sub_question, "DERIVED_SYNTHESIS_EMPTY")
        return AgentTaskSubQuestionResult(
            sub_question_id=sub_question.sub_question_id,
            question=sub_question.question,
            selected_tool="none",
            status="partial" if has_partial_dependency else "completed",
            answer=answer.strip(),
            attempt_count=1,
            warnings=(
                ["至少一个前置子问题仅部分完成，派生综合结果不能标记为完整。"]
                if has_partial_dependency
                else []
            ),
        )

    async def _generate_with_trace(
        self,
        *,
        query: str,
        context: RagContext,
        langchain_config: RunnableConfig | None,
    ) -> str:
        try:
            value = await self._llm_client.generate(
                query=query,
                context=context,
                langchain_config=langchain_config,
            )
        except TypeError as exc:
            if "langchain_config" not in str(exc):
                raise
            value = await self._llm_client.generate(query=query, context=context)
        return str(value or "")

    def _save(self, plan: ResearchTaskPlan) -> None:
        try:
            self._task_plan_store.save(plan)
        except Exception as exc:
            raise _TaskPlanPersistenceError(
                f"无法持久化 Research TaskPlan: {type(exc).__name__}: {exc}"
            ) from exc


def _to_research_result(legacy, validation) -> ResearchTaskSubQuestionResult:
    return ResearchTaskSubQuestionResult(
        sub_question_id=legacy.sub_question_id,
        status=legacy.status,
        answer=legacy.answer,
        attempt_count=legacy.attempt_count,
        tool_calls=legacy.tool_calls,
        evidence_ids=validation.valid_evidence_refs,
        evidence_validation=validation,
        evaluation=legacy.evaluation,
        warnings=legacy.warnings,
        error_code=(str(legacy.error).split(":", 1)[0] if legacy.error else None),
        error_message=legacy.error,
    )


def _to_legacy_result(result, sub_question) -> AgentTaskSubQuestionResult:
    return AgentTaskSubQuestionResult(
        sub_question_id=result.sub_question_id,
        question=sub_question.question,
        selected_tool="none",
        status=result.status,
        answer=result.answer or "",
        attempt_count=result.attempt_count,
        tool_calls=result.tool_calls,
        evidence=[],
        evaluation=result.evaluation,
        warnings=result.warnings,
        error=result.error_message,
    )


def _failed_legacy_result(sub_question, error: str) -> AgentTaskSubQuestionResult:
    return AgentTaskSubQuestionResult(
        sub_question_id=sub_question.sub_question_id,
        question=sub_question.question,
        selected_tool="none",
        status="failed",
        answer="",
        attempt_count=0,
        error=error,
        warnings=["Worker 未产生可验证 Evidence。"],
    )


def _timeout_legacy_result(
    sub_question: ResearchTaskSubQuestion,
    checkpoint: ResearchWorkerCheckpoint | None,
) -> AgentTaskSubQuestionResult:
    tool_calls = list(checkpoint.tool_calls) if checkpoint else []
    last_call = tool_calls[-1] if tool_calls else None
    return AgentTaskSubQuestionResult(
        sub_question_id=sub_question.sub_question_id,
        question=sub_question.question,
        selected_tool=last_call.tool_name if last_call else "none",
        status="failed",
        answer="",
        attempt_count=checkpoint.attempt if checkpoint else 1,
        tool_calls=tool_calls,
        evidence=[],
        error="WORKER_TIMEOUT",
        warnings=[
            "Worker 在返回完整结果前超时；内部检查点保留了最后阶段和已完成调用。"
        ],
    )


def _sort_results(plan, results):
    order = {item.sub_question_id: item.order for item in plan.sub_questions}
    return sorted(results, key=lambda item: (order[item.sub_question_id], item.sub_question_id))


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


__all__ = ["AgenticResearchExecutor"]
