from __future__ import annotations

"""AgentTaskPlanStore + AgentTaskLeaseManager 的端到端冒烟回归。

验证修订后的事实库链路：数据库创建计划 → 领取租约（绑定 ContextVar）→
租约内 CAS 保存进度 → 重读快照与 Markdown → 正常释放租约。

运行前提：DATABASE_URL 指向已执行 `alembic upgrade head` 的 PostgreSQL。
"""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fast_app.core.config import get_settings
from fast_app.db.agent_task_plan_tables import (
    AgentTaskCapacitySlotTable,
    AgentTaskPlanCommandTable,
    AgentTaskPlanTable,
)
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.domain.agent_task_execution import TaskPlanLease
from fast_app.domain.agent_task_plan import AgentTaskPlan, AgentTaskPlanStatus
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


async def main() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    repository = AgentTaskPlanRepository(factory)
    await repository.ensure_capacity_slots(workload_type="document", count=1)
    store = AgentTaskPlanStore(
        repository=repository,
        export_store=AgentTaskPlanExportStore(settings),
    )
    lease_manager = AgentTaskLeaseManager(settings=settings, store=store)
    tid = f"task_plan_smoke_{uuid4().hex}"
    now = datetime.now(UTC)
    plan = AgentTaskPlan(
        task_plan_id=tid,
        task_kind="knowledge_document_management",
        user_id="smoke_user",
        original_query="smoke",
        objective="smoke",
        task_type="analysis",
        goal="smoke",
        sub_questions=[],
        research_policy=None,
        final_synthesis_instruction="smoke",
        source_query="smoke",
        target_path=None,
        report_title="smoke",
        status=AgentTaskPlanStatus.CREATED,
        steps=[],
        final_output={},
        created_at=now,
        updated_at=now,
        error=None,
    )
    try:
        await store.create(plan)
        async with lease_manager.hold(
            task_plan_id=tid,
            operation="execute",
            idempotency_key="smoke-key-000000000000001",
            request_payload={},
            allowed_statuses={AgentTaskPlanStatus.CREATED},
            workload_type="document",
        ) as acquired:
            assert isinstance(acquired, TaskPlanLease), type(acquired)
            current = await store.load(tid)
            current.status = AgentTaskPlanStatus.PREPARING_CONFIRMATION
            await store.save(current)
            got = await store.load(tid)
            assert got.status == AgentTaskPlanStatus.PREPARING_CONFIRMATION
            # 确认前工作流允许在同一权威状态下反复保存草稿和审查检查点。
            got.final_output["checkpoint"] = "reviewed"
            await store.save(got)
            got.status = AgentTaskPlanStatus.WAITING_CONFIRMATION
            await store.save(got)
            got.status = AgentTaskPlanStatus.EXECUTING_CONFIRMED
            await store.save(got)
            got.status = AgentTaskPlanStatus.COMPLETED
            await store.save(got)
            md = await store.load_markdown(tid)
            assert tid in md
            acquired.closing.set()
            await repository.finish_success(
                lease=acquired,
                response_json=got.model_dump(mode="json"),
            )
        print("store_lease_smoke=passed")
    finally:
        async with factory() as session, session.begin():
            await session.execute(
                delete(AgentTaskPlanCommandTable).where(
                    AgentTaskPlanCommandTable.task_plan_id == tid
                )
            )
            await session.execute(
                delete(AgentTaskPlanTable).where(
                    AgentTaskPlanTable.task_plan_id == tid
                )
            )
            await session.execute(
                delete(AgentTaskCapacitySlotTable).where(
                    AgentTaskCapacitySlotTable.task_plan_id == tid
                )
            )
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
