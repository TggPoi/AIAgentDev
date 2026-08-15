"""Agent TaskPlan 多 Worker 执行的领域对象与状态转换契约。

``TaskPlanLease`` 是"当前协程已从数据库取得的租约句柄"的内存镜像；真正的权威
事实始终在 ``agent_task_plans`` 行上（lease_owner / lease_until / lease_fence_token）。
这里的 ``ContextVar`` 只负责把句柄传播给当前执行链路，绝不代替数据库锁。

``ALLOWED_SOURCE_STATUSES_BY_TARGET`` 是 TaskPlan 生命周期的权威状态图。确认前
计算和确认后执行使用不同状态，真实副作用不能从 ``waiting_confirmation`` 直接
落终态。
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator, Literal

from fast_app.domain.agent_task_plan import AgentTaskPlanStatus
from fast_app.services.exceptions import AgentTaskPlanLeaseLostError


TaskPlanOperation = Literal["execute", "confirm", "retry", "cleanup"]
TaskPlanWorkloadType = Literal["research", "document"]


@dataclass(slots=True)
class TaskPlanLease:
    """一次数据库租约领取的内存句柄；所有条件写入都要携带其代际编号。"""

    task_plan_id: str
    operation: TaskPlanOperation
    owner: str
    fence_token: int
    record_version: int
    command_id: str
    idempotency_key: str
    workload_type: TaskPlanWorkloadType
    capacity_slot_no: int
    capacity_fence_token: int
    lost: asyncio.Event = field(default_factory=asyncio.Event)
    closing: asyncio.Event = field(default_factory=asyncio.Event)

    def assert_active(self) -> None:
        if self.lost.is_set():
            raise AgentTaskPlanLeaseLostError(
                "Agent TaskPlan 租约已经丢失，旧执行者必须停止"
            )


@dataclass(frozen=True, slots=True)
class TaskPlanCommandReplay:
    """同键命令已成功，返回给调用方的重放结果。"""

    task_plan_id: str
    operation: str
    idempotency_key: str
    response_json: dict[str, object]


_CURRENT_TASK_PLAN_LEASE: ContextVar[TaskPlanLease | None] = ContextVar(
    "current_agent_task_plan_lease",
    default=None,
)


@contextmanager
def bind_task_plan_lease(lease: TaskPlanLease) -> Iterator[None]:
    token = _CURRENT_TASK_PLAN_LEASE.set(lease)
    try:
        yield
    finally:
        _CURRENT_TASK_PLAN_LEASE.reset(token)


def require_task_plan_lease(task_plan_id: str) -> TaskPlanLease:
    lease = _CURRENT_TASK_PLAN_LEASE.get()
    if lease is None or lease.task_plan_id != task_plan_id:
        raise AgentTaskPlanLeaseLostError(
            "当前执行路径没有有效的 TaskPlan 数据库租约"
        )
    lease.assert_active()
    return lease


ALLOWED_SOURCE_STATUSES_BY_TARGET: dict[AgentTaskPlanStatus, set[AgentTaskPlanStatus]] = {
    AgentTaskPlanStatus.CREATED: set(),
    AgentTaskPlanStatus.PREPARING_CONFIRMATION: {
        AgentTaskPlanStatus.CREATED,
        AgentTaskPlanStatus.PREPARING_CONFIRMATION,
        AgentTaskPlanStatus.FAILED,
    },
    AgentTaskPlanStatus.WAITING_CONFIRMATION: {
        AgentTaskPlanStatus.PREPARING_CONFIRMATION,
    },
    AgentTaskPlanStatus.EXECUTING_CONFIRMED: {
        AgentTaskPlanStatus.WAITING_CONFIRMATION,
        AgentTaskPlanStatus.EXECUTING_CONFIRMED,
        AgentTaskPlanStatus.FAILED,
        AgentTaskPlanStatus.COMPLETED_WITH_WARNINGS,
    },
    AgentTaskPlanStatus.COMPLETED: {
        AgentTaskPlanStatus.EXECUTING_CONFIRMED,
    },
    AgentTaskPlanStatus.COMPLETED_WITH_WARNINGS: {
        AgentTaskPlanStatus.EXECUTING_CONFIRMED,
    },
    AgentTaskPlanStatus.FAILED: {
        AgentTaskPlanStatus.CREATED,
        AgentTaskPlanStatus.PREPARING_CONFIRMATION,
        AgentTaskPlanStatus.EXECUTING_CONFIRMED,
    },
    AgentTaskPlanStatus.CANCELLED: {
        AgentTaskPlanStatus.CREATED,
        AgentTaskPlanStatus.PREPARING_CONFIRMATION,
        AgentTaskPlanStatus.WAITING_CONFIRMATION,
        AgentTaskPlanStatus.EXECUTING_CONFIRMED,
        AgentTaskPlanStatus.FAILED,
    },
}


def allowed_source_status_values(target: AgentTaskPlanStatus) -> list[str]:
    return [item.value for item in ALLOWED_SOURCE_STATUSES_BY_TARGET[target]]


__all__ = [
    "ALLOWED_SOURCE_STATUSES_BY_TARGET",
    "TaskPlanCommandReplay",
    "TaskPlanLease",
    "TaskPlanOperation",
    "TaskPlanWorkloadType",
    "allowed_source_status_values",
    "bind_task_plan_lease",
    "require_task_plan_lease",
]
