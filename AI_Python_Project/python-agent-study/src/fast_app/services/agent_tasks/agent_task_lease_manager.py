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
        # 重放短路：同一幂等键上次已成功执行过，直接重放上次的响应。
        # 没有真实执行，就不需要心跳续租，直接返回。
        if isinstance(acquired, TaskPlanCommandReplay):
            yield acquired
            return

        # ---------- 心跳启动 ----------
        # stop 是"请心跳下班"的开关信号（asyncio.Event）：
        # 心跳协程每轮都在等它，一旦被 set，心跳当轮立即退出。
        # 它在下方 finally 清理阶段被置位，是兜底停止手段。
        stop = asyncio.Event()
        # create_task 是心跳"启动"的本质：把 _heartbeat 协程交给事件循环，
        # 从这一刻起心跳与主协程并发运行——主协程去跑业务（yield acquired），
        # 心跳在后台独立循环续租，两者互不阻塞（asyncio 单线程并发）。
        heartbeat = asyncio.create_task(self._heartbeat(acquired, stop))
        # 把租约句柄绑进 ContextVar：业务代码任何深度调用
        # require_task_plan_lease() 都能拿到句柄，做 assert_active() 失租检查。
        with bind_task_plan_lease(acquired):
            try:
                # 控制权交回 async with 块内的业务代码；心跳同时在后台循环。
                yield acquired
                # closing 表示执行器已经停止心跳并进入带 fencing 条件的终态提交。
                # 终态提交自身会验证数据库租约；cancel 胜出时 fence 失效是预期结果，
                # 不能在上下文退出阶段再次用内存 lost 标记覆盖权威 cancelled 快照。
                if not acquired.closing.is_set():
                    acquired.assert_active()
            finally:
                # ---------- 心跳停止（兜底路径） ----------
                # 无论业务成功返回还是中途抛异常，这里必定执行，
                # 保证绝不留一个无人负责的心跳继续给已结束的租约续命。
                stop.set()          # 发信号：请下班（心跳当轮 wait 立即返回）
                heartbeat.cancel()  # 强制取消：即使心跳正卡在续租 IO 上也能打断
                try:
                    # cancel() 只是"提出请求"，await 才是等心跳真正结束。
                    await heartbeat
                except asyncio.CancelledError:
                    pass  # 被我们 cancel 是预期结果，吞掉即可
                except BaseException:
                    # 心跳异常已经通过 lease.lost 传给主执行路径；清理阶段不再
                    # 用它覆盖主异常或成功返回前的 acquired.assert_active()。
                    pass

    async def _heartbeat(self, lease: TaskPlanLease, stop: asyncio.Event) -> None:
        """心跳循环：每轮"等两个停止信号，最多等 heartbeat_seconds"。

        每轮只有三种结局：
        1. 信号到达（stop/closing 被 set）→ return 优雅下班，不再续租；
        2. 等满超时且无信号 → renew_lease 续租一次，进入下一轮；
        3. 续租抛异常（数据库条件落空 = 失租）→ 走下方异常处理。

        刻意不用 asyncio.sleep：sleep 无法被信号提前唤醒，会在执行器已进入
        终态提交后多余地续一次租、与释放动作打架。asyncio.wait 监听 Event，
        信号一置位当轮立刻返回，停止响应延迟接近零。
        """
        try:
            while True:
                # 每轮重建两个一次性等待任务：分别盯 stop（上下文退出信号）
                # 和 closing（执行器进入终态提交的信号）。被 cancel 过的等待
                # 任务不能复用，所以必须在每轮开头新建。
                stop_task = asyncio.create_task(stop.wait())
                closing_task = asyncio.create_task(lease.closing.wait())
                # "同时等这两个信号，最多等 heartbeat_seconds"：
                # 信号先到 → done 非空；等满超时 → done 为空。await 让出执行权，等待 agent_task_heartbeat_seconds 秒，如果没有信号到达，则 done 为空，继续往下执行续租
                done, pending = await asyncio.wait(
                    {stop_task, closing_task},
                    timeout=self._settings.agent_task_heartbeat_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # ---------- 清理未完成的等待任务 ----------
                # cancel() 只是提出取消请求，任务要等下一轮调度才真正结束。
                for task in pending:
                    task.cancel()
                if pending:
                    # await gather 等这些任务真正退出；return_exceptions=True
                    # 把 CancelledError 当返回值收集，避免清理代码自身抛异常。
                    # 这里只"销毁"旧等待任务，新任务在下一轮开头创建。
                    await asyncio.gather(*pending, return_exceptions=True)
                if done:
                    # 任一停止信号到达 → 心跳下班，不再续租。
                    # （closing 先到是正常终态路径；stop 先到是上下文退出。）
                    return
                # 平安等满一个心跳间隔 → 续租：带 owner/fence/未过期条件，
                # 同时延长任务行与容量槽行的 lease_until。任一条件落空即抛异常。
                await self._store.repository.renew_lease(
                    lease,
                    lease_seconds=self._settings.agent_task_lease_seconds,
                )
        except asyncio.CancelledError:
            raise  # 被 hold() 的 finally 强制取消：如实传播，不做 lost 标记
        except BaseException:
            if lease.closing.is_set():
                # 终态提交阶段的续租失败是预期结果（执行器刚释放租约或 cancel
                # 抢跑使 fence 失效）：静默下班，不点 lost 灯，避免假失租。
                return
            # 真正失租：置位 lost 通知主协程（主协程在下一个 assert_active
            # 检查点停止），然后心跳自杀。此后无人续租，lease_until 自然到期，
            # 其他 Worker 可合法接管。
            lease.lost.set()
            raise


__all__ = ["AgentTaskLeaseManager", "build_request_hash"]
