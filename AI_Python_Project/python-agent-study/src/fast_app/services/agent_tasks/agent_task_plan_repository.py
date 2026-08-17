"""Agent TaskPlan 数据库租约、原子 CAS 与幂等命令的唯一并发 SQL 入口。

所有跨进程一致性的条件 UPDATE / SELECT FOR UPDATE / CAS 都必须写在本模块，
业务层不得自行拼接并发 SQL。每个方法自开短 Session：SQLAlchemy AsyncSession
不支持并发使用，心跳任务与主执行协程不能共享同一个 Session。
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, exists, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fast_app.db.agent_task_plan_tables import (
    AgentTaskCapacitySlotTable,
    AgentTaskPlanCommandTable,
    AgentTaskPlanRuntimeRecordTable,
    AgentTaskPlanTable,
)
from fast_app.domain.agent_task_execution import (
    TaskPlanCommandReplay,
    TaskPlanLease,
    TaskPlanOperation,
    TaskPlanWorkloadType,
    allowed_source_status_values,
)
from fast_app.domain.agent_task_plan import AgentTaskPlanStatus
from fast_app.services.exceptions import (
    AgentTaskCapacityExceededError,
    AgentTaskPlanBusyError,
    AgentTaskPlanIdempotencyConflictError,
    AgentTaskPlanLeaseLostError,
    AgentTaskPlanVersionConflictError,
    AppServiceError,
    DocumentAgentCheckpointConflictError,
    DocumentAgentCheckpointUnavailableError,
    ToolPermissionDeniedError,
)


SnapshotMutator = Callable[[dict[str, Any]], dict[str, Any]]


def _deadline(seconds: int):
    # seconds 来自带上下界的 Settings，不接受请求文本，因此可安全形成固定 interval。
    return func.now() + text(f"INTERVAL '{int(seconds)} seconds'")


def _as_datetime(value: Any) -> datetime:
    """把 model_dump(mode="json") 产生的 ISO 字符串还原为带时区时间。"""
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise AppServiceError("持久化时间必须包含时区")
    return parsed


class AgentTaskPlanRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def ensure_capacity_slots(self, *, workload_type: str, count: int) -> None:
        values = [
            {"workload_type": workload_type, "slot_no": slot_no}
            for slot_no in range(1, count + 1)
        ]
        async with self._session_factory() as session, session.begin():
            await session.execute(
                pg_insert(AgentTaskCapacitySlotTable)
                .values(values)
                .on_conflict_do_nothing(
                    index_elements=["workload_type", "slot_no"]
                )
            )

    async def create_plan(self, snapshot: dict[str, Any]) -> int:
        task_plan_id = str(snapshot["task_plan_id"])
        owner_user_id = snapshot.get("user_id")
        if not isinstance(owner_user_id, str) or not owner_user_id:
            raise AppServiceError("TaskPlan 缺少有效 owner user_id")
        schema_version = int(snapshot.get("schema_version", 1))
        stmt = (
            pg_insert(AgentTaskPlanTable)
            .values(
                task_plan_id=task_plan_id,
                schema_version=schema_version,
                task_kind=str(snapshot["task_kind"]),
                status=str(snapshot["status"]),
                owner_user_id=owner_user_id,
                record_version=1,
                snapshot_json=snapshot,
                created_at=_as_datetime(snapshot["created_at"]),
                updated_at=func.now(),
            )
            .on_conflict_do_nothing(index_elements=["task_plan_id"])
            .returning(AgentTaskPlanTable.record_version)
        )
        async with self._session_factory() as session, session.begin():
            version = (await session.execute(stmt)).scalar_one_or_none()
        if version is None:
            raise AgentTaskPlanVersionConflictError(
                "相同 task_plan_id 已存在，拒绝覆盖创建"
            )
        return int(version)

    async def load_snapshot(self, task_plan_id: str) -> tuple[dict[str, Any], int]:
        async with self._session_factory() as session:
            row = await session.get(AgentTaskPlanTable, task_plan_id)
            if row is None:
                raise AppServiceError("Agent task plan 不存在")
            return dict(row.snapshot_json), int(row.record_version)

    async def begin_operation(
        self,
        *,
        task_plan_id: str,
        operation: TaskPlanOperation,
        idempotency_key: str,
        request_hash: str,
        worker_id: str,
        allowed_statuses: Collection[AgentTaskPlanStatus],
        workload_type: TaskPlanWorkloadType,
        capacity_limit: int,
        lease_seconds: int,
    ) -> TaskPlanLease | TaskPlanCommandReplay:
        command_id = f"agent_cmd_{uuid4().hex}"
        capacity_missing = False
        lease: TaskPlanLease | None = None

        async with self._session_factory() as session, session.begin():
            inserted = (
                await session.execute(
                    pg_insert(AgentTaskPlanCommandTable)
                    .values(
                        command_id=command_id,
                        task_plan_id=task_plan_id,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        status="running",
                        updated_at=func.now(),
                    )
                    .on_conflict_do_nothing(
                        constraint="uq_agent_task_plan_command_idempotency"
                    )
                    .returning(AgentTaskPlanCommandTable.command_id)
                )
            ).scalar_one_or_none() # 取第一行第一列的单值：没有 → None，多于一行 → 报错。

            if inserted is None:
                existing = await session.scalar(
                    select(AgentTaskPlanCommandTable)
                    .where(
                        AgentTaskPlanCommandTable.task_plan_id == task_plan_id,
                        AgentTaskPlanCommandTable.operation == operation,
                        AgentTaskPlanCommandTable.idempotency_key == idempotency_key,
                    )
                    .with_for_update()
                )
                if existing is None:
                    raise AgentTaskPlanIdempotencyConflictError(
                        "幂等记录并发读取失败"
                    )
                if existing.request_hash != request_hash:
                    raise AgentTaskPlanIdempotencyConflictError(
                        "相同 Idempotency-Key 被用于不同请求"
                    )
                if existing.status == "succeeded" and existing.response_json is not None:
                    return TaskPlanCommandReplay(
                        task_plan_id=task_plan_id,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        response_json=dict(existing.response_json),
                    )
                if existing.status == "running":
                    # 修订：进程崩溃可能留下 running 命令而其租约已经过期。同键重试
                    # 必须复活这种孤儿命令，而不是永远返回 busy。判断依据是任务行
                    # 当前是否仍有属于该命令的有效租约。
                    task_state = (
                        await session.execute(
                            select(
                                AgentTaskPlanTable.lease_owner,
                                AgentTaskPlanTable.lease_until,
                                AgentTaskPlanTable.lease_fence_token,
                            ).where(
                                AgentTaskPlanTable.task_plan_id == task_plan_id
                            )
                        )
                    ).one_or_none() # 取第一行：没有 → None，多于一行 → 报错。
                    still_owned = (
                        task_state is not None
                        and task_state.lease_owner is not None
                        and task_state.lease_until is not None
                        and task_state.lease_until > datetime.now(UTC)
                        and existing.lease_fence_token
                        == task_state.lease_fence_token
                    )
                    if still_owned:
                        raise AgentTaskPlanBusyError("同一幂等控制请求仍在执行")
                    command_id = existing.command_id
                else:
                    # 修订：rejected（租约/容量临时拒绝）与 failed（上一次执行失败）
                    # 都允许同键复活重试：这是前端在 429、超时后复用同一 key 的正常
                    # 动作。真实写副作用仍由下游业务幂等键（GitLab MR、(task_plan_id,
                    # source_id) 唯一约束）保证。
                    command_id = existing.command_id
                existing.status = "running"
                existing.lease_fence_token = None
                existing.response_json = None
                existing.error_code = None
                existing.error_message = None
                existing.completed_at = None
                existing.updated_at = datetime.now(UTC)
            # 重新"领取"租约 + 延长租约状态，共用下面这一段代码
            task_row = (
                await session.execute(
                    update(AgentTaskPlanTable)
                    .where(
                        AgentTaskPlanTable.task_plan_id == task_plan_id,
                        AgentTaskPlanTable.status.in_(
                            [item.value for item in allowed_statuses]
                        ),
                        or_(
                            AgentTaskPlanTable.lease_until.is_(None),
                            AgentTaskPlanTable.lease_until <= func.now(),
                        ),
                    )
                    .values(
                        lease_owner=worker_id,
                        lease_until=_deadline(lease_seconds),
                        lease_fence_token=AgentTaskPlanTable.lease_fence_token + 1,
                        active_operation=operation,
                        started_at=func.coalesce(
                            AgentTaskPlanTable.started_at, func.now()
                        ),
                        updated_at=func.now(),
                    )
                    .returning(
                        AgentTaskPlanTable.lease_fence_token,
                        AgentTaskPlanTable.record_version,
                    )
                )
            ).one_or_none()
            if task_row is None: # 续租失败，命令表中的状态无法更新到 TaskPlan 信息，Command 表中的状态也无法更新
                command = await session.get(AgentTaskPlanCommandTable, command_id)
                if command is not None:
                    command.status = "rejected"
                    command.error_code = "AGENT_TASK_PLAN_BUSY"
                    command.error_message = "TaskPlan 状态不允许执行或租约仍被占用"
                    command.completed_at = datetime.now(UTC)
                capacity_missing = False
            else:
                slot = await session.scalar(
                    select(AgentTaskCapacitySlotTable)
                    .where(
                        AgentTaskCapacitySlotTable.workload_type == workload_type,
                        AgentTaskCapacitySlotTable.slot_no <= capacity_limit,
                        or_(
                            AgentTaskCapacitySlotTable.lease_until.is_(None),
                            AgentTaskCapacitySlotTable.lease_until <= func.now(),
                        ),
                    )
                    .order_by(AgentTaskCapacitySlotTable.slot_no)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if slot is None:
                    await session.execute(
                        update(AgentTaskPlanTable)
                        .where(
                            AgentTaskPlanTable.task_plan_id == task_plan_id,
                            AgentTaskPlanTable.lease_owner == worker_id,
                            AgentTaskPlanTable.lease_fence_token
                            == int(task_row.lease_fence_token),
                        )
                        .values(
                            lease_owner=None,
                            lease_until=None,
                            active_operation=None,
                        )
                    )
                    command = await session.get(AgentTaskPlanCommandTable, command_id)
                    if command is not None:
                        command.status = "rejected"
                        command.error_code = "AGENT_CAPACITY_EXCEEDED"
                        command.error_message = "复杂 Agent 全局容量槽已用尽"
                        command.completed_at = datetime.now(UTC)
                    capacity_missing = True
                else:
                    slot_row = (
                        await session.execute(
                            update(AgentTaskCapacitySlotTable)
                            .where(
                                AgentTaskCapacitySlotTable.workload_type == workload_type,
                                AgentTaskCapacitySlotTable.slot_no == slot.slot_no,
                            )
                            .values(
                                lease_owner=worker_id,
                                lease_until=_deadline(lease_seconds),
                                lease_fence_token=(
                                    AgentTaskCapacitySlotTable.lease_fence_token + 1
                                ),
                                task_plan_id=task_plan_id,
                                updated_at=func.now(),
                            )
                            .returning(
                                AgentTaskCapacitySlotTable.lease_fence_token
                            )
                        )
                    ).one() # 取第一行：没有 → 报错，多于一行 → 报错。 和 one_or_none() 不同，slot 已经 SELECT FOR UPDATE 锁定，必然只有一行。
                    await session.execute(
                        update(AgentTaskPlanTable)
                        .where(
                            AgentTaskPlanTable.task_plan_id == task_plan_id,
                            AgentTaskPlanTable.lease_owner == worker_id,
                            AgentTaskPlanTable.lease_fence_token
                            == int(task_row.lease_fence_token),
                        )
                        .values(
                            capacity_workload_type=workload_type,
                            capacity_slot_no=slot.slot_no,
                        )
                    ) # 租约成功续租后，更新Command表中的fence快照
                    command = await session.get(AgentTaskPlanCommandTable, command_id)
                    if command is not None:
                        command.lease_fence_token = int(task_row.lease_fence_token)
                    lease = TaskPlanLease(
                        task_plan_id=task_plan_id,
                        operation=operation,
                        owner=worker_id,
                        fence_token=int(task_row.lease_fence_token),
                        record_version=int(task_row.record_version),
                        command_id=command_id,
                        idempotency_key=idempotency_key,
                        workload_type=workload_type,
                        capacity_slot_no=int(slot.slot_no),
                        capacity_fence_token=int(slot_row.lease_fence_token),
                    )

        if lease is not None:
            return lease
        if capacity_missing:
            raise AgentTaskCapacityExceededError(
                "复杂 Agent 当前已达到全局并发上限",
                retry_after_seconds=lease_seconds,
            )
        raise AgentTaskPlanBusyError(
            "Agent TaskPlan 状态不允许执行或数据库租约仍被占用"
        )

    async def renew_lease(self, lease: TaskPlanLease, *, lease_seconds: int) -> None:
        lease.assert_active()
        async with self._session_factory() as session, session.begin():
            task_result = await session.execute(
                update(AgentTaskPlanTable)
                .where(
                    AgentTaskPlanTable.task_plan_id == lease.task_plan_id,
                    AgentTaskPlanTable.lease_owner == lease.owner,
                    AgentTaskPlanTable.lease_fence_token == lease.fence_token,
                    AgentTaskPlanTable.lease_until > func.now(),
                    AgentTaskPlanTable.status != AgentTaskPlanStatus.CANCELLED.value,
                )
                .values(lease_until=_deadline(lease_seconds), updated_at=func.now())
            )
            slot_result = await session.execute(
                update(AgentTaskCapacitySlotTable)
                .where(
                    AgentTaskCapacitySlotTable.workload_type == lease.workload_type,
                    AgentTaskCapacitySlotTable.slot_no == lease.capacity_slot_no,
                    AgentTaskCapacitySlotTable.lease_owner == lease.owner,
                    AgentTaskCapacitySlotTable.lease_fence_token
                    == lease.capacity_fence_token,
                    AgentTaskCapacitySlotTable.lease_until > func.now(),
                    AgentTaskCapacitySlotTable.task_plan_id == lease.task_plan_id,
                )
                .values(lease_until=_deadline(lease_seconds), updated_at=func.now())
            )
            if task_result.rowcount != 1 or slot_result.rowcount != 1:
                raise AgentTaskPlanLeaseLostError("TaskPlan 或容量槽续租失败")

    async def save_snapshot(
        self,
        *,
        snapshot: dict[str, Any],
        lease: TaskPlanLease,
    ) -> int:
        lease.assert_active()
        target_status = AgentTaskPlanStatus(str(snapshot["status"]))
        stmt = (
            update(AgentTaskPlanTable)
            .where(
                AgentTaskPlanTable.task_plan_id == lease.task_plan_id,
                AgentTaskPlanTable.record_version == lease.record_version,
                AgentTaskPlanTable.lease_owner == lease.owner,
                AgentTaskPlanTable.lease_fence_token == lease.fence_token,
                AgentTaskPlanTable.lease_until > func.now(),
                AgentTaskPlanTable.status.in_(
                    allowed_source_status_values(target_status)
                ),
            )
            .values(
                status=target_status.value,
                snapshot_json=snapshot,
                record_version=AgentTaskPlanTable.record_version + 1,
                updated_at=func.now(),
                finished_at=(
                    func.now()
                    if target_status
                    in {
                        AgentTaskPlanStatus.COMPLETED,
                        AgentTaskPlanStatus.COMPLETED_WITH_WARNINGS,
                        AgentTaskPlanStatus.FAILED,
                    }
                    else None
                ),
            )
            .returning(AgentTaskPlanTable.record_version)
        )
        async with self._session_factory() as session, session.begin():
            version = (await session.execute(stmt)).scalar_one_or_none()
        if version is None:
            raise AgentTaskPlanVersionConflictError(
                "TaskPlan 版本、租约或状态转换发生冲突"
            )
        lease.record_version = int(version)
        return lease.record_version

    async def finish_success(
        self,
        *,
        lease: TaskPlanLease,
        response_json: dict[str, Any],
    ) -> None:
        lease.assert_active()
        task_conditions = [
            AgentTaskPlanTable.task_plan_id == lease.task_plan_id,
            AgentTaskPlanTable.lease_owner == lease.owner,
            AgentTaskPlanTable.lease_fence_token == lease.fence_token,
            AgentTaskPlanTable.lease_until > func.now(),
        ]
        expected_status = response_json.get("status")
        if isinstance(expected_status, str):
            # execute/confirm/retry 的返回快照必须与数据库当前状态一致。
            # cleanup 响应没有 status，因此只验证租约。
            task_conditions.append(AgentTaskPlanTable.status == expected_status)
        async with self._session_factory() as session, session.begin():
            task_result = await session.execute(
                update(AgentTaskPlanTable)
                .where(*task_conditions)
                .values(
                    lease_owner=None,
                    lease_until=None,
                    active_operation=None,
                    capacity_workload_type=None,
                    capacity_slot_no=None,
                    updated_at=func.now(),
                )
            )
            slot_result = await session.execute(
                update(AgentTaskCapacitySlotTable)
                .where(
                    AgentTaskCapacitySlotTable.workload_type == lease.workload_type,
                    AgentTaskCapacitySlotTable.slot_no == lease.capacity_slot_no,
                    AgentTaskCapacitySlotTable.lease_owner == lease.owner,
                    AgentTaskCapacitySlotTable.lease_fence_token
                    == lease.capacity_fence_token,
                    AgentTaskCapacitySlotTable.task_plan_id == lease.task_plan_id,
                )
                .values(
                    lease_owner=None,
                    lease_until=None,
                    task_plan_id=None,
                    updated_at=func.now(),
                )
            )
            command_result = await session.execute(
                update(AgentTaskPlanCommandTable)
                .where(
                    AgentTaskPlanCommandTable.command_id == lease.command_id,
                    AgentTaskPlanCommandTable.status == "running",
                )
                .values(
                    status="succeeded",
                    response_json=response_json,
                    completed_at=func.now(),
                    updated_at=func.now(),
                )
            )
            if (
                task_result.rowcount != 1
                or slot_result.rowcount != 1
                or command_result.rowcount != 1
            ):
                raise AgentTaskPlanLeaseLostError(
                    "完成 TaskPlan 时租约、容量槽或命令状态已经失效"
                )

    async def finish_failure(
        self,
        *,
        lease: TaskPlanLease,
        error_code: str,
        error_message: str,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(AgentTaskPlanTable)
                .where(
                    AgentTaskPlanTable.task_plan_id == lease.task_plan_id,
                    AgentTaskPlanTable.lease_owner == lease.owner,
                    AgentTaskPlanTable.lease_fence_token == lease.fence_token,
                )
                .values(
                    lease_owner=None,
                    lease_until=None,
                    active_operation=None,
                    capacity_workload_type=None,
                    capacity_slot_no=None,
                    updated_at=func.now(),
                )
            )
            await session.execute(
                update(AgentTaskCapacitySlotTable)
                .where(
                    AgentTaskCapacitySlotTable.workload_type == lease.workload_type,
                    AgentTaskCapacitySlotTable.slot_no == lease.capacity_slot_no,
                    AgentTaskCapacitySlotTable.lease_owner == lease.owner,
                    AgentTaskCapacitySlotTable.lease_fence_token
                    == lease.capacity_fence_token,
                    AgentTaskCapacitySlotTable.task_plan_id == lease.task_plan_id,
                )
                .values(
                    lease_owner=None,
                    lease_until=None,
                    task_plan_id=None,
                    updated_at=func.now(),
                )
            )
            await session.execute(
                update(AgentTaskPlanCommandTable)
                .where(
                    AgentTaskPlanCommandTable.command_id == lease.command_id,
                    AgentTaskPlanCommandTable.status == "running",
                )
                .values(
                    status="failed",
                    error_code=error_code,
                    error_message=error_message[:2000],
                    completed_at=func.now(),
                    updated_at=func.now(),
                )
            )

    async def cancel_atomic(
        self,
        *,
        task_plan_id: str,
        actor_user_id: str,
        can_manage_all: bool,
        idempotency_key: str,
        request_hash: str,
        mutate_snapshot: SnapshotMutator,
    ) -> dict[str, Any]:
        command_id = f"agent_cmd_{uuid4().hex}"
        async with self._session_factory() as session, session.begin():
            inserted = (
                await session.execute(
                    pg_insert(AgentTaskPlanCommandTable)
                    .values(
                        command_id=command_id,
                        task_plan_id=task_plan_id,
                        operation="cancel",
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        status="running",
                    )
                    .on_conflict_do_nothing(
                        constraint="uq_agent_task_plan_command_idempotency"
                    )
                    .returning(AgentTaskPlanCommandTable.command_id)
                )
            ).scalar_one_or_none()
            if inserted is None:
                existing = await session.scalar(
                    select(AgentTaskPlanCommandTable).where(
                        AgentTaskPlanCommandTable.task_plan_id == task_plan_id,
                        AgentTaskPlanCommandTable.operation == "cancel",
                        AgentTaskPlanCommandTable.idempotency_key == idempotency_key,
                    )
                )
                if existing is None or existing.request_hash != request_hash:
                    raise AgentTaskPlanIdempotencyConflictError(
                        "cancel 的 Idempotency-Key 与已有请求冲突"
                    )
                if existing.status == "succeeded" and existing.response_json is not None:
                    return dict(existing.response_json)
                raise AgentTaskPlanBusyError("相同 cancel 请求仍在执行或已经失败")

            row = await session.scalar(
                select(AgentTaskPlanTable)
                .where(AgentTaskPlanTable.task_plan_id == task_plan_id)
                .with_for_update()
            )
            if row is None:
                raise AppServiceError("Agent task plan 不存在")
            if row.owner_user_id != actor_user_id and not can_manage_all:
                raise ToolPermissionDeniedError("只能取消自己创建的 Agent task plan")
            if row.status in {
                AgentTaskPlanStatus.COMPLETED.value,
                AgentTaskPlanStatus.COMPLETED_WITH_WARNINGS.value,
            }:
                raise AppServiceError("已完成的 Agent TaskPlan 不能取消")

            if row.status == AgentTaskPlanStatus.CANCELLED.value:
                cancelled = dict(row.snapshot_json)
            else:
                old_lease_owner = row.lease_owner
                old_workload = row.capacity_workload_type
                old_slot = row.capacity_slot_no
                cancelled = mutate_snapshot(dict(row.snapshot_json))
                row.status = AgentTaskPlanStatus.CANCELLED.value
                row.snapshot_json = cancelled
                row.record_version += 1
                row.lease_fence_token += 1
                row.lease_owner = None
                row.lease_until = None
                row.active_operation = None
                row.capacity_workload_type = None
                row.capacity_slot_no = None
                row.finished_at = datetime.now(UTC)
                row.updated_at = datetime.now(UTC)
                if old_workload is not None and old_slot is not None:
                    await session.execute(
                        update(AgentTaskCapacitySlotTable)
                        .where(
                            AgentTaskCapacitySlotTable.workload_type == old_workload,
                            AgentTaskCapacitySlotTable.slot_no == old_slot,
                            AgentTaskCapacitySlotTable.lease_owner == old_lease_owner,
                            AgentTaskCapacitySlotTable.task_plan_id == task_plan_id,
                        )
                        .values(
                            lease_owner=None,
                            lease_until=None,
                            task_plan_id=None,
                            updated_at=func.now(),
                        )
                    )
                await session.execute(
                    update(AgentTaskPlanCommandTable)
                    .where(
                        AgentTaskPlanCommandTable.task_plan_id == task_plan_id,
                        AgentTaskPlanCommandTable.command_id != command_id,
                        AgentTaskPlanCommandTable.status == "running",
                    )
                    .values(
                        status="cancelled",
                        error_code="AGENT_TASK_PLAN_CANCELLED",
                        completed_at=func.now(),
                        updated_at=func.now(),
                    )
                )

            command = await session.get(AgentTaskPlanCommandTable, command_id)
            if command is None:
                raise AgentTaskPlanIdempotencyConflictError("cancel 命令记录丢失")
            command.status = "succeeded"
            command.response_json = cancelled
            command.completed_at = datetime.now(UTC)
            command.updated_at = datetime.now(UTC)
            return cancelled

    async def create_runtime_record(
        self,
        *,
        snapshot: dict[str, Any],
        lease: TaskPlanLease,
    ) -> None:
        lease.assert_active()
        async with self._session_factory() as session, session.begin():
            parent = await session.scalar(
                select(AgentTaskPlanTable)
                .where(
                    AgentTaskPlanTable.task_plan_id == lease.task_plan_id,
                    AgentTaskPlanTable.lease_owner == lease.owner,
                    AgentTaskPlanTable.lease_fence_token == lease.fence_token,
                    AgentTaskPlanTable.lease_until > func.now(),
                )
                .with_for_update()
            )
            if parent is None:
                raise AgentTaskPlanLeaseLostError(
                    "创建 RuntimeRecord 前 TaskPlan 租约已丢失"
                )
            inserted = (
                await session.execute(
                    pg_insert(AgentTaskPlanRuntimeRecordTable)
                    .values(
                        task_plan_id=lease.task_plan_id,
                        schema_version=int(snapshot["schema_version"]),
                        record_version=int(snapshot["record_version"]),
                        snapshot_json=snapshot,
                        expires_at=_as_datetime(snapshot["expires_at"]),
                        updated_at=func.now(),
                    )
                    .on_conflict_do_nothing(index_elements=["task_plan_id"])
                    .returning(AgentTaskPlanRuntimeRecordTable.task_plan_id)
                )
            ).scalar_one_or_none()
            if inserted is None:
                raise DocumentAgentCheckpointConflictError(
                    "Deep Agent RuntimeRecord 已存在"
                )

    async def load_runtime_record(self, task_plan_id: str) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            row = await session.get(AgentTaskPlanRuntimeRecordTable, task_plan_id)
            return None if row is None else dict(row.snapshot_json)

    async def update_runtime_record(
        self,
        *,
        task_plan_id: str,
        expected_version: int,
        snapshot: dict[str, Any],
        lease: TaskPlanLease,
    ) -> int:
        lease.assert_active()
        owned = exists(
            select(1).where(
                AgentTaskPlanTable.task_plan_id == task_plan_id,
                AgentTaskPlanTable.lease_owner == lease.owner,
                AgentTaskPlanTable.lease_fence_token == lease.fence_token,
                AgentTaskPlanTable.lease_until > func.now(),
                AgentTaskPlanTable.status != AgentTaskPlanStatus.CANCELLED.value,
            )
        )
        stmt = (
            update(AgentTaskPlanRuntimeRecordTable)
            .where(
                AgentTaskPlanRuntimeRecordTable.task_plan_id == task_plan_id,
                AgentTaskPlanRuntimeRecordTable.record_version == expected_version,
                owned,
            )
            .values(
                record_version=AgentTaskPlanRuntimeRecordTable.record_version + 1,
                snapshot_json=snapshot,
                expires_at=_as_datetime(snapshot["expires_at"]),
                updated_at=func.now(),
            )
            .returning(AgentTaskPlanRuntimeRecordTable.record_version)
        )
        async with self._session_factory() as session, session.begin():
            version = (await session.execute(stmt)).scalar_one_or_none()
        if version is None:
            raise DocumentAgentCheckpointConflictError(
                "RuntimeRecord 版本冲突或 TaskPlan 租约已失效"
            )
        return int(version)

    async def delete_runtime_record(
        self,
        task_plan_id: str,
        *,
        lease: TaskPlanLease,
    ) -> None:
        lease.assert_active()
        owned = exists(
            select(1).where(
                AgentTaskPlanTable.task_plan_id == task_plan_id,
                AgentTaskPlanTable.lease_owner == lease.owner,
                AgentTaskPlanTable.lease_fence_token == lease.fence_token,
                AgentTaskPlanTable.lease_until > func.now(),
            )
        )
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                delete(AgentTaskPlanRuntimeRecordTable).where(
                    AgentTaskPlanRuntimeRecordTable.task_plan_id == task_plan_id,
                    owned,
                )
            )
            if result.rowcount != 1:
                # 记录已不存在时按幂等成功处理（旧 Store 的 delete 对缺失 key 是
                # 空操作）；记录仍存在但未删除成功，说明父租约已经失效。
                remaining = await session.scalar(
                    select(AgentTaskPlanRuntimeRecordTable.task_plan_id).where(
                        AgentTaskPlanRuntimeRecordTable.task_plan_id == task_plan_id
                    )
                )
                if remaining is not None:
                    raise AgentTaskPlanLeaseLostError(
                        "删除 RuntimeRecord 时租约失效或记录不存在"
                    )

    async def list_expired_runtime_task_ids(self, *, limit: int = 100) -> list[str]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(AgentTaskPlanRuntimeRecordTable.task_plan_id)
                .where(AgentTaskPlanRuntimeRecordTable.expires_at < func.now())
                .order_by(AgentTaskPlanRuntimeRecordTable.expires_at)
                .limit(limit)
            )
            return list(rows.all())

    # 修订新增：把超过保留期仍未结束的 running 命令按崩溃孤儿收敛为 failed，
    # 否则同键重试永远 AGENT_TASK_PLAN_BUSY，且 delete_commands_before 只删终态命令，
    # 命令表会无限增长。由维护脚本在 delete_commands_before 之前调用。
    async def expire_stale_running_commands(self, cutoff: datetime) -> int:
        active_parent_lease = exists(
            select(1).where(
                AgentTaskPlanTable.task_plan_id
                == AgentTaskPlanCommandTable.task_plan_id,
                AgentTaskPlanTable.lease_owner.is_not(None),
                AgentTaskPlanTable.lease_until > func.now(),
                AgentTaskPlanTable.lease_fence_token
                == AgentTaskPlanCommandTable.lease_fence_token,
            )
        )
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                update(AgentTaskPlanCommandTable)
                .where(
                    AgentTaskPlanCommandTable.status == "running",
                    AgentTaskPlanCommandTable.created_at < cutoff,
                    ~active_parent_lease,
                )
                .values(
                    status="failed",
                    error_code="AGENT_TASK_PLAN_COMMAND_ORPHANED",
                    error_message="命令超出保留期仍未结束，按崩溃孤儿收敛",
                    completed_at=func.now(),
                    updated_at=func.now(),
                )
            )
            return int(result.rowcount or 0)

    async def delete_commands_before(self, cutoff: datetime) -> int:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                delete(AgentTaskPlanCommandTable).where(
                    AgentTaskPlanCommandTable.status.in_(
                        ["succeeded", "failed", "rejected", "cancelled"]
                    ),
                    AgentTaskPlanCommandTable.completed_at < cutoff,
                )
            )
            return int(result.rowcount or 0)


__all__ = ["AgentTaskPlanRepository"]
