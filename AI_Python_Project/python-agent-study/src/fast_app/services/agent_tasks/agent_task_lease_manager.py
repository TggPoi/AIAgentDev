"""Agent TaskPlan 租约上下文管理器与心跳续租。

``hold()`` 一次性完成：幂等命令插入、数据库租约领取、容量槽领取、ContextVar
绑定与心跳任务启动。心跳失败会置 ``lease.lost``，主执行协程在每个模型调用、
工具调用和真实副作用前通过 ``require_task_plan_lease().assert_active()`` 停止。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
from contextlib import asynccontextmanager
from typing import AsyncIterator, Any
from uuid import uuid4

from fast_app.core.config import Settings
from fast_app.domain.agent_task_execution import (
    TaskPlanCommandReplay,
    TaskPlanLease,
    TaskPlanOperation,
    TaskPlanWorkloadType,
    bind_task_plan_lease,
)
from fast_app.domain.agent_task_plan import AgentTaskPlanStatus
from fast_app.services.agent_tasks.agent_task_plan_store import AgentTaskPlanStore


def build_request_hash(
    *, task_plan_id: str, operation: str, payload: dict[str, Any]
) -> str:
    canonical = json.dumps(
        {
            "task_plan_id": task_plan_id,
            "operation": operation,
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AgentTaskLeaseManager:
    def __init__(self, *, settings: Settings, store: AgentTaskPlanStore) -> None:
        self._settings = settings
        self._store = store
        self.worker_id = (
            f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:12]}"
        )

    @asynccontextmanager
    async def hold(
        self,
        *,
        task_plan_id: str,
        operation: TaskPlanOperation,
        idempotency_key: str,
        request_payload: dict[str, Any],
        allowed_statuses: set[AgentTaskPlanStatus],
        workload_type: TaskPlanWorkloadType,
    ) -> AsyncIterator[TaskPlanLease | TaskPlanCommandReplay]:
        capacity_limit = (
            self._settings.agent_research_global_concurrency
            if workload_type == "research"
            else self._settings.agent_document_global_concurrency
        )
        acquired = await self._store.begin_operation(
            task_plan_id=task_plan_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=build_request_hash(
                task_plan_id=task_plan_id,
                operation=operation,
                payload=request_payload,
            ),
            worker_id=self.worker_id,
            allowed_statuses=allowed_statuses,
            workload_type=workload_type,
            capacity_limit=capacity_limit,
            lease_seconds=self._settings.agent_task_lease_seconds,
        )
        if isinstance(acquired, TaskPlanCommandReplay):
            yield acquired
            return

        stop = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(acquired, stop))
        with bind_task_plan_lease(acquired):
            try:
                yield acquired
                # closing 表示执行器已经停止心跳并进入带 fencing 条件的终态提交。
                # 终态提交自身会验证数据库租约；cancel 胜出时 fence 失效是预期结果，
                # 不能在上下文退出阶段再次用内存 lost 标记覆盖权威 cancelled 快照。
                if not acquired.closing.is_set():
                    acquired.assert_active()
            finally:
                stop.set()
                heartbeat.cancel()
                try:
                    await heartbeat
                except asyncio.CancelledError:
                    pass
                except BaseException:
                    # 心跳异常已经通过 lease.lost 传给主执行路径；清理阶段不再
                    # 用它覆盖主异常或成功返回前的 acquired.assert_active()。
                    pass

    async def _heartbeat(self, lease: TaskPlanLease, stop: asyncio.Event) -> None:
        try:
            while True:
                stop_task = asyncio.create_task(stop.wait())
                closing_task = asyncio.create_task(lease.closing.wait())
                done, pending = await asyncio.wait(
                    {stop_task, closing_task},
                    timeout=self._settings.agent_task_heartbeat_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                if done:
                    return
                await self._store.repository.renew_lease(
                    lease,
                    lease_seconds=self._settings.agent_task_lease_seconds,
                )
        except asyncio.CancelledError:
            raise
        except BaseException:
            if lease.closing.is_set():
                return
            lease.lost.set()
            raise


__all__ = ["AgentTaskLeaseManager", "build_request_hash"]
