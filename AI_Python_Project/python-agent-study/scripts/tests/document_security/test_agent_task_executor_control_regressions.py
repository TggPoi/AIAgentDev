from __future__ import annotations

"""Agent TaskPlan 控制协议的无外部服务回归。"""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fast_app.domain.agent_task_execution import TaskPlanLease, require_task_plan_lease
from fast_app.domain.agent_task_plan import AgentTaskPlan, AgentTaskPlanStatus
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_tasks.agent_task_executor import AgentTaskExecutor
from fast_app.services.agent_tasks.document_task_executor import DocumentTaskExecutor
from fast_app.services.agent_tasks.agent_task_lease_manager import (
    AgentTaskLeaseManager,
)
from fast_app.services.agent_tasks.deep_document_agent import (
    _DocumentCoordinatorProgressMiddleware,
)
from fast_app.services.exceptions import AgentTaskPlanLeaseLostError, AppServiceError


def build_plan(
    task_plan_id: str,
    *,
    status: AgentTaskPlanStatus,
    final_output: dict | None = None,
    failure_phase: str | None = None,
) -> AgentTaskPlan:
    now = datetime.now(UTC)
    return AgentTaskPlan(
        task_plan_id=task_plan_id,
        task_kind="knowledge_document_management",
        user_id="control_regression_user",
        original_query="控制协议回归",
        objective="控制协议回归",
        task_type="analysis",
        goal="控制协议回归",
        sub_questions=[],
        research_policy=None,
        final_synthesis_instruction="不调用真实模型",
        source_query="控制协议回归",
        target_path=None,
        report_title="控制协议回归",
        status=status,
        failure_phase=failure_phase,
        steps=[],
        final_output=final_output or {},
        created_at=now,
        updated_at=now,
        error=None,
    )


class CancelWonRepository:
    async def finish_success(self, *, lease: TaskPlanLease, **_kwargs) -> None:
        lease.lost.set()
        raise AgentTaskPlanLeaseLostError("cancel 已使旧 fence token 失效")

    async def finish_failure(self, **_kwargs) -> None:
        raise AssertionError("已收敛的 cancel 不应再写入失败命令")


class CancelWonStore:
    def __init__(self, running: AgentTaskPlan, cancelled: AgentTaskPlan) -> None:
        self.repository = CancelWonRepository()
        self._loads = [running, cancelled]

    async def load(self, _task_plan_id: str) -> AgentTaskPlan:
        return self._loads.pop(0)

    async def begin_operation(self, **kwargs) -> TaskPlanLease:
        return TaskPlanLease(
            task_plan_id=kwargs["task_plan_id"],
            operation=kwargs["operation"],
            owner=kwargs["worker_id"],
            fence_token=1,
            record_version=1,
            command_id="test_cancel_convergence_command",
            idempotency_key=kwargs["idempotency_key"],
            workload_type=kwargs["workload_type"],
            capacity_slot_no=1,
            capacity_fence_token=1,
        )

    @staticmethod
    def from_snapshot(payload: dict) -> AgentTaskPlan:
        return AgentTaskPlan.model_validate(payload)


class AsyncRecordingStore:
    def __init__(self, plan: AgentTaskPlan) -> None:
        self.plan = plan
        self.saved: list[AgentTaskPlan] = []

    async def load(self, _task_plan_id: str) -> AgentTaskPlan:
        return self.plan.model_copy(deep=True)

    async def save(self, plan: AgentTaskPlan) -> AgentTaskPlan:
        self.saved.append(plan.model_copy(deep=True))
        self.plan = plan.model_copy(deep=True)
        return plan


class RecordingDocumentExecutor:
    def __init__(self) -> None:
        self.resume_calls = 0
        self.confirm_calls = 0

    async def resume(self, *, plan: AgentTaskPlan, **_kwargs) -> AgentTaskPlan:
        self.resume_calls += 1
        return plan

    async def confirm(self, *, plan: AgentTaskPlan, **_kwargs) -> AgentTaskPlan:
        self.confirm_calls += 1
        return plan


async def test_cancel_winner_is_returned_as_authoritative_result() -> None:
    task_plan_id = "task_plan_control_cancel_convergence"
    running = build_plan(
        task_plan_id, status=AgentTaskPlanStatus.PREPARING_CONFIRMATION
    )
    completed = build_plan(task_plan_id, status=AgentTaskPlanStatus.COMPLETED)
    cancelled = build_plan(task_plan_id, status=AgentTaskPlanStatus.CANCELLED)
    store = CancelWonStore(running, cancelled)
    executor = object.__new__(AgentTaskExecutor)
    executor._task_plan_store = store
    executor._lease_manager = AgentTaskLeaseManager(
        settings=SimpleNamespace(
            agent_research_global_concurrency=1,
            agent_document_global_concurrency=1,
            agent_task_lease_seconds=60,
            agent_task_heartbeat_seconds=3600,
        ),
        store=store,
    )

    async def runner(_current: AgentTaskPlan) -> AgentTaskPlan:
        return completed

    result = await executor._run_with_database_lease(
        task_plan_id=task_plan_id,
        operation="execute",
        idempotency_key="cancel-convergence-key",
        request_payload={},
        allowed_statuses={AgentTaskPlanStatus.PREPARING_CONFIRMATION},
        workload_type="document",
        runner=runner,
    )
    assert result.status == AgentTaskPlanStatus.CANCELLED


async def test_heartbeat_lease_loss_converges_to_cancelled_result() -> None:
    task_plan_id = "task_plan_control_cancel_heartbeat"
    running = build_plan(
        task_plan_id, status=AgentTaskPlanStatus.EXECUTING_CONFIRMED
    )
    completed = build_plan(task_plan_id, status=AgentTaskPlanStatus.COMPLETED)
    cancelled = build_plan(task_plan_id, status=AgentTaskPlanStatus.CANCELLED)
    store = CancelWonStore(running, cancelled)
    executor = object.__new__(AgentTaskExecutor)
    executor._task_plan_store = store
    executor._lease_manager = AgentTaskLeaseManager(
        settings=SimpleNamespace(
            agent_research_global_concurrency=1,
            agent_document_global_concurrency=1,
            agent_task_lease_seconds=60,
            agent_task_heartbeat_seconds=3600,
        ),
        store=store,
    )

    async def runner(_current: AgentTaskPlan) -> AgentTaskPlan:
        require_task_plan_lease(task_plan_id).lost.set()
        return completed

    result = await executor._run_with_database_lease(
        task_plan_id=task_plan_id,
        operation="execute",
        idempotency_key="cancel-heartbeat-key",
        request_payload={},
        allowed_statuses={AgentTaskPlanStatus.EXECUTING_CONFIRMED},
        workload_type="document",
        runner=runner,
    )
    assert result.status == AgentTaskPlanStatus.CANCELLED


async def test_resume_awaits_owned_plan_before_dispatch() -> None:
    task_plan_id = "task_plan_control_retry_await"
    plan = build_plan(
        task_plan_id,
        status=AgentTaskPlanStatus.FAILED,
        final_output={"checkpoint": {"completed": False}},
    )
    user = CurrentUserContext(
        user_id=plan.user_id or "control_regression_user",
        is_authenticated=True,
        auth_source="jwt",
    )
    document_executor = RecordingDocumentExecutor()
    executor = object.__new__(AgentTaskExecutor)
    executor._settings = SimpleNamespace(
        rag_default_top_k=8,
        rag_default_min_score=0.0,
    )
    executor._document_executor = document_executor

    async def load_owned_plan(
        _task_plan_id: str,
        _user: CurrentUserContext,
    ) -> AgentTaskPlan:
        return plan

    executor._load_owned_plan = load_owned_plan
    result = await executor._resume_locked(
        task_plan_id,
        user,
        langchain_config_factory=None,
    )
    assert result is plan
    assert document_executor.resume_calls == 1


async def test_deep_document_progress_awaits_async_store() -> None:
    task_plan_id = "task_plan_control_deep_progress"
    plan = build_plan(
        task_plan_id, status=AgentTaskPlanStatus.PREPARING_CONFIRMATION
    )
    store = AsyncRecordingStore(plan)
    middleware = _DocumentCoordinatorProgressMiddleware(
        store,
        task_plan_id,
        deliverable_ids=(),
        max_revision_rounds=1,
    )
    await middleware._append_event({"event": "worker_started"})
    assert len(store.saved) == 1
    events = store.saved[0].final_output["document_progress"]["events"]
    assert events == [{"event": "worker_started"}]


async def test_confirmed_document_failure_resumes_confirmed_execution() -> None:
    task_plan_id = "task_plan_control_confirmed_retry"
    plan = build_plan(
        task_plan_id,
        status=AgentTaskPlanStatus.FAILED,
        failure_phase=AgentTaskPlanStatus.EXECUTING_CONFIRMED.value,
    )
    user = CurrentUserContext(
        user_id=plan.user_id or "control_regression_user",
        is_authenticated=True,
        auth_source="jwt",
    )
    store = AsyncRecordingStore(plan)
    document_executor = RecordingDocumentExecutor()
    executor = object.__new__(AgentTaskExecutor)
    executor._task_plan_store = store
    executor._document_executor = document_executor

    async def load_owned_plan(
        _task_plan_id: str,
        _user: CurrentUserContext,
    ) -> AgentTaskPlan:
        return store.plan.model_copy(deep=True)

    executor._load_owned_plan = load_owned_plan
    result = await executor._resume_locked(
        task_plan_id,
        user,
        langchain_config_factory=None,
    )
    assert result.status == AgentTaskPlanStatus.EXECUTING_CONFIRMED
    assert result.failure_phase is None
    assert document_executor.confirm_calls == 1
    assert document_executor.resume_calls == 0


async def test_document_confirm_rejects_unconfirmed_status() -> None:
    plan = build_plan(
        "task_plan_control_unconfirmed_write",
        status=AgentTaskPlanStatus.WAITING_CONFIRMATION,
    )
    executor = object.__new__(DocumentTaskExecutor)
    user = CurrentUserContext(
        user_id=plan.user_id or "control_regression_user",
        is_authenticated=True,
        auth_source="jwt",
    )
    try:
        await executor.confirm(plan=plan, user=user)
        raise AssertionError("waiting_confirmation 不得直接进入真实文档写入")
    except AppServiceError as exc:
        assert "executing_confirmed" in str(exc)


async def main() -> None:
    await test_cancel_winner_is_returned_as_authoritative_result()
    await test_heartbeat_lease_loss_converges_to_cancelled_result()
    await test_resume_awaits_owned_plan_before_dispatch()
    await test_deep_document_progress_awaits_async_store()
    await test_confirmed_document_failure_resumes_confirmed_execution()
    await test_document_confirm_rejects_unconfirmed_status()
    print("agent_task_executor_control_regressions=passed")


if __name__ == "__main__":
    asyncio.run(main())
