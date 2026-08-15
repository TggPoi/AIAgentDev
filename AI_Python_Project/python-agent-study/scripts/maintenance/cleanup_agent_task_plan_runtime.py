from __future__ import annotations

"""过期 Runtime 与 checkpoint 的完整清理维护命令（修订版）。

由单独的定时任务调用；即使误启动两个维护进程，数据库 TaskPlan 租约也只能让
一个进程删除同一 thread。每轮顺序：

1. 为过期 RuntimeRecord 领取 cleanup 租约，领取成功才删 checkpoint 与业务行；
2. 把超过保留期仍未结束的 running 命令按崩溃孤儿收敛为 failed；
3. 删除超过保留期的终态命令。
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fast_app.core.config import get_settings
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.domain.agent_task_execution import TaskPlanCommandReplay, TaskPlanLease
from fast_app.domain.agent_task_plan import AgentTaskPlanStatus
from fast_app.services.agent_tasks.agent_task_lease_manager import (
    AgentTaskLeaseManager,
)
from fast_app.services.agent_tasks.agent_task_plan_repository import (
    AgentTaskPlanRepository,
)
from fast_app.services.agent_tasks.agent_task_plan_store import (
    AgentTaskPlanExportStore,
    AgentTaskPlanStore,
)
from fast_app.services.agent_tasks.deep_document_runtime import DeepDocumentRuntime
from fast_app.services.exceptions import (
    AgentTaskCapacityExceededError,
    AgentTaskPlanBusyError,
    AgentTaskPlanIdempotencyConflictError,
)


ALL_STATUSES = set(AgentTaskPlanStatus)


async def run(limit: int) -> tuple[int, int, int, int]:
    settings = get_settings()
    engine = create_database_engine(settings)
    repository = AgentTaskPlanRepository(create_session_factory(engine))
    store = AgentTaskPlanStore(
        repository=repository,
        export_store=AgentTaskPlanExportStore(settings),
    )
    lease_manager = AgentTaskLeaseManager(settings=settings, store=store)
    runtime = await DeepDocumentRuntime.start(settings, repository)
    cleaned = 0
    skipped = 0
    try:
        task_ids = await repository.list_expired_runtime_task_ids(limit=limit)
        for task_plan_id in task_ids:
            record = await repository.load_runtime_record(task_plan_id)
            if record is None:
                continue
            # 修订：幂等键不再包含 record_version：清理失败后必须能用同一键重试，
            # 否则失败一次的命令记录会让该任务永远无法被清理。
            idempotency_key = f"cleanup:{task_plan_id}"
            try:
                async with lease_manager.hold(
                    task_plan_id=task_plan_id,
                    operation="cleanup",
                    idempotency_key=idempotency_key,
                    request_payload={
                        "runtime_record_version": record["record_version"]
                    },
                    allowed_statuses=ALL_STATUSES,
                    workload_type="document",
                ) as acquired:
                    if isinstance(acquired, TaskPlanCommandReplay):
                        continue
                    assert isinstance(acquired, TaskPlanLease)
                    await runtime.release(task_plan_id)
                    acquired.closing.set()
                    await repository.finish_success(
                        lease=acquired,
                        response_json={
                            "task_plan_id": task_plan_id,
                            "cleaned": True,
                        },
                    )
                    cleaned += 1
            except (
                AgentTaskPlanBusyError,
                AgentTaskCapacityExceededError,
                # 修订：记录版本变化导致 request_hash 不一致时跳过，下一轮重试；
                # 不能让它中断整个维护脚本。
                AgentTaskPlanIdempotencyConflictError,
            ):
                skipped += 1
        # 修订：先把超期仍处于 running 的崩溃孤儿命令收敛为 failed，
        # 再按保留期删除终态命令，防止孤儿命令永久阻塞同键重试。
        orphaned = await repository.expire_stale_running_commands(
            datetime.now(UTC)
            - timedelta(days=settings.agent_task_idempotency_retention_days)
        )
        commands_deleted = await repository.delete_commands_before(
            datetime.now(UTC)
            - timedelta(days=settings.agent_task_idempotency_retention_days)
        )
        return cleaned, skipped, orphaned, commands_deleted
    finally:
        await runtime.close()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    cleaned, skipped, orphaned, commands_deleted = asyncio.run(run(args.limit))
    print(
        f"cleaned={cleaned} skipped={skipped} "
        f"orphaned_commands={orphaned} commands_deleted={commands_deleted}"
    )


if __name__ == "__main__":
    main()
