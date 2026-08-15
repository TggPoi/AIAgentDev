from __future__ import annotations

"""Agent TaskPlan 业务测试使用的异步内存替身。

生产事实库只能是 PostgreSQL；这里仅让不测试数据库语义的 Research/Document
离线回归继续通过与生产一致的 async Store 和租约上下文接口运行。
"""

from contextlib import asynccontextmanager, contextmanager
from typing import Iterator
from copy import deepcopy
from uuid import uuid4

from fast_app.domain.agent_task_execution import TaskPlanLease, bind_task_plan_lease
from fast_app.services.agent_tasks.agent_task_plan_store import (
    StoredAgentTaskPlan,
    _cancelled_snapshot,
    _render_task_plan_markdown,
)
from fast_app.services.exceptions import (
    AgentTaskPlanVersionConflictError,
    AppServiceError,
)


class InMemoryAgentTaskPlanStore:
    """只用于业务行为测试，不模拟 PostgreSQL CAS、租约或幂等命令。"""

    def __init__(self) -> None:
        self._plans: dict[str, StoredAgentTaskPlan] = {}
        # Executor 完成骨架通过 Store.repository 提交命令终态；测试替身由自身承接。
        self.repository = self

    @staticmethod
    def from_snapshot(payload: dict) -> StoredAgentTaskPlan:
        from fast_app.services.agent_tasks.agent_task_plan_store import _deserialize_plan

        return _deserialize_plan(payload)

    async def create(self, plan: StoredAgentTaskPlan) -> StoredAgentTaskPlan:
        if plan.task_plan_id in self._plans:
            raise AgentTaskPlanVersionConflictError(
                "测试内存 Store 中相同 task_plan_id 已存在"
            )
        self._plans[plan.task_plan_id] = deepcopy(plan)
        return plan

    async def load(self, task_plan_id: str) -> StoredAgentTaskPlan:
        plan = self._plans.get(task_plan_id)
        if plan is None:
            raise AppServiceError("Agent task plan 不存在")
        return deepcopy(plan)

    async def save(self, plan: StoredAgentTaskPlan) -> StoredAgentTaskPlan:
        self._plans[plan.task_plan_id] = deepcopy(plan)
        return plan

    async def load_markdown(self, task_plan_id: str) -> str:
        return _render_task_plan_markdown(await self.load(task_plan_id))

    async def cancel(
        self,
        *,
        task_plan_id: str,
        user,
        idempotency_key: str,
        request_hash: str,
    ) -> StoredAgentTaskPlan:
        del idempotency_key, request_hash
        plan = await self.load(task_plan_id)
        if plan.user_id != user.user_id and not user.has_global_role("system_admin"):
            raise AppServiceError("只能取消自己创建的 Agent task plan")
        cancelled = self.from_snapshot(
            _cancelled_snapshot(plan.model_dump(mode="json"))
        )
        await self.save(cancelled)
        return cancelled

    async def finish_success(self, **_kwargs) -> None:
        return None

    async def finish_failure(self, **_kwargs) -> None:
        return None


class InMemoryAgentTaskLeaseManager:
    """为离线业务测试绑定 TaskPlanLease；不替代数据库并发测试。"""

    @asynccontextmanager
    async def hold(
        self,
        *,
        task_plan_id: str,
        operation: str,
        idempotency_key: str,
        workload_type: str,
        **_kwargs,
    ):
        lease = TaskPlanLease(
            task_plan_id=task_plan_id,
            operation=operation,
            owner="in-memory-test-worker",
            fence_token=1,
            record_version=1,
            command_id=f"test_cmd_{uuid4().hex}",
            idempotency_key=idempotency_key,
            workload_type=workload_type,
            capacity_slot_no=1,
            capacity_fence_token=1,
        )
        with bind_task_plan_lease(lease):
            yield lease


@contextmanager
def bind_test_task_plan_lease(task_plan_id: str) -> Iterator[TaskPlanLease]:
    """给直接测试内部业务组件的调用显式绑定一份活跃测试租约。"""

    lease = TaskPlanLease(
        task_plan_id=task_plan_id,
        operation="execute",
        owner="in-memory-test-worker",
        fence_token=1,
        record_version=1,
        command_id=f"test_cmd_{uuid4().hex}",
        idempotency_key=f"test:{task_plan_id}",
        workload_type="document",
        capacity_slot_no=1,
        capacity_fence_token=1,
    )
    with bind_task_plan_lease(lease):
        yield lease


__all__ = [
    "InMemoryAgentTaskLeaseManager",
    "InMemoryAgentTaskPlanStore",
    "bind_test_task_plan_lease",
]
