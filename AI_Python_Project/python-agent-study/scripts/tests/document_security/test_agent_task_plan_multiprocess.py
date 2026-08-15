from __future__ import annotations

"""Windows 独立进程争抢同一 TaskPlan 的跨进程互斥回归。

两个独立 Python 进程针对同一个 task_plan_id 调用真实
``AgentTaskPlanRepository.begin_operation()``，必须一个 acquired、
一个 AGENT_TASK_PLAN_BUSY。GREEN 标准只能是 acquired=1 + busy=1。

运行前提：DATABASE_URL 指向已执行 `alembic upgrade head` 的 PostgreSQL。
"""

import asyncio
import multiprocessing as mp
import sys
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty
from uuid import uuid4

from sqlalchemy import delete

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fast_app.core.config import get_settings
from fast_app.db.agent_task_plan_tables import (
    AgentTaskPlanCommandTable,
    AgentTaskPlanTable,
)
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.domain.agent_task_execution import TaskPlanLease
from fast_app.domain.agent_task_plan import AgentTaskPlan, AgentTaskPlanStatus
from fast_app.services.agent_tasks.agent_task_plan_repository import (
    AgentTaskPlanRepository,
)


def build_plan(task_plan_id: str) -> AgentTaskPlan:
    now = datetime.now(UTC)
    return AgentTaskPlan(
        task_plan_id=task_plan_id,
        task_kind="knowledge_document_management",
        user_id="multiprocess_test_user",
        original_query="multiprocess consistency",
        objective="only one process acquires",
        task_type="analysis",
        goal="only one process acquires",
        sub_questions=[],
        research_policy=None,
        final_synthesis_instruction="none",
        source_query="multiprocess consistency",
        target_path=None,
        report_title="multiprocess",
        status=AgentTaskPlanStatus.CREATED,
        steps=[],
        final_output={},
        created_at=now,
        updated_at=now,
        error=None,
    )


async def child_async(
    task_plan_id: str,
    worker_id: str,
    barrier,
    queue,
) -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    repository = AgentTaskPlanRepository(create_session_factory(engine))
    try:
        await asyncio.to_thread(barrier.wait)
        try:
            result = await repository.begin_operation(
                task_plan_id=task_plan_id,
                operation="execute",
                idempotency_key=f"{worker_id}-0000000000000000",
                request_hash=(worker_id * 64)[:64],
                worker_id=worker_id,
                allowed_statuses={AgentTaskPlanStatus.CREATED},
                workload_type="document",
                capacity_limit=4,
                lease_seconds=60,
            )
            if not isinstance(result, TaskPlanLease):
                queue.put((worker_id, "replay", None))
                return
            queue.put((worker_id, "acquired", result.fence_token))
            await asyncio.sleep(3)
            await repository.finish_failure(
                lease=result,
                error_code="TEST_RELEASE",
                error_message="release",
            )
        except Exception as exc:
            queue.put(
                (
                    worker_id,
                    getattr(exc, "error_code", type(exc).__name__),
                    None,
                )
            )
    finally:
        await engine.dispose()


def child(task_plan_id: str, worker_id: str, barrier, queue) -> None:
    asyncio.run(child_async(task_plan_id, worker_id, barrier, queue))


async def setup_task(task_plan_id: str):
    settings = get_settings()
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    repository = AgentTaskPlanRepository(factory)
    await repository.ensure_capacity_slots(workload_type="document", count=4)
    await repository.create_plan(build_plan(task_plan_id).model_dump(mode="json"))
    await engine.dispose()


async def cleanup_task(task_plan_id: str) -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    try:
        async with factory() as session, session.begin():
            await session.execute(
                delete(AgentTaskPlanCommandTable).where(
                    AgentTaskPlanCommandTable.task_plan_id == task_plan_id
                )
            )
            await session.execute(
                delete(AgentTaskPlanTable).where(
                    AgentTaskPlanTable.task_plan_id == task_plan_id
                )
            )
    finally:
        await engine.dispose()


def main() -> None:
    mp.freeze_support()
    context = mp.get_context("spawn")
    task_plan_id = f"task_plan_mp_{uuid4().hex}"
    asyncio.run(setup_task(task_plan_id))
    barrier = context.Barrier(2)
    queue = context.Queue()
    processes = [
        context.Process(
            target=child,
            args=(task_plan_id, f"worker-{index}", barrier, queue),
        )
        for index in range(2)
    ]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=30)
            if process.is_alive():
                process.terminate()
                raise RuntimeError("child process timeout")
            if process.exitcode != 0:
                raise RuntimeError(f"child process exit={process.exitcode}")

        results = []
        for _ in processes:
            try:
                results.append(queue.get(timeout=5))
            except Empty as exc:
                raise RuntimeError("child result missing") from exc
        acquired = [item for item in results if item[1] == "acquired"]
        busy = [item for item in results if item[1] == "AGENT_TASK_PLAN_BUSY"]
        assert len(acquired) == 1, results
        assert len(busy) == 1, results
        print(f"results={results}")
        print("multiprocess_single_owner=passed")
    finally:
        asyncio.run(cleanup_task(task_plan_id))


if __name__ == "__main__":
    main()
