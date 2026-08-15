from __future__ import annotations

"""Agent TaskPlan 多 Worker 一致性的 PostgreSQL 原子回归。

使用真实 PostgreSQL 验证四类数据库原语，不允许用内存 Store 伪装 CAS：

1. 同一任务只能有一个数据库租约；完成后的同键命令可重放。
2. 旧 record_version 的 TaskPlan 快照保存必须 CAS 失败（不能最后写入覆盖）。
3. cancel 必须使旧 fencing token 失效，旧 runner 不能把 cancelled 覆盖回 completed。
4. RuntimeRecord 的两个旧 writer 只能成功一个（原子 CAS）。
5. 【修订】failed 命令允许同键复活重试，而不是永久 IdempotencyConflict。
6. 【修订】busy 被拒的命令允许同键复活重试。
7. waiting_confirmation 不能直接完成；必须经过 executing_confirmed 才能落终态。
8. 容量槽不足返回 AGENT_CAPACITY_EXCEEDED，同键复活后槽位恢复可领取。
9. failed 命令被多个 Worker 同键并发复活时，只能有一个可完成的执行者。
10. 清理任务不能把仍有匹配有效租约的旧 running 命令误判为孤儿。
11. 租约已经过期的旧 running 命令必须收敛为 failed。

运行前提：DATABASE_URL 指向已执行 `alembic upgrade head` 的 PostgreSQL。
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, update

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fast_app.core.config import get_settings
from fast_app.db.agent_task_plan_tables import (
    AgentTaskCapacitySlotTable,
    AgentTaskPlanCommandTable,
    AgentTaskPlanRuntimeRecordTable,
    AgentTaskPlanTable,
)
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.domain.agent_task_execution import TaskPlanCommandReplay, TaskPlanLease
from fast_app.domain.agent_task_plan import AgentTaskPlan, AgentTaskPlanStatus
from fast_app.services.agent_tasks.agent_task_plan_repository import (
    AgentTaskPlanRepository,
)
from fast_app.services.exceptions import (
    AgentTaskCapacityExceededError,
    AgentTaskPlanBusyError,
    AgentTaskPlanVersionConflictError,
    DocumentAgentCheckpointConflictError,
)


def build_plan(task_plan_id: str, *, status: AgentTaskPlanStatus) -> AgentTaskPlan:
    now = datetime.now(UTC)
    return AgentTaskPlan(
        task_plan_id=task_plan_id,
        task_kind="knowledge_document_management",
        user_id="agent_consistency_test_user",
        original_query="一致性测试",
        objective="验证数据库租约和 CAS",
        task_type="analysis",
        goal="验证数据库租约和 CAS",
        sub_questions=[],
        research_policy=None,
        final_synthesis_instruction="不调用真实模型",
        source_query="一致性测试",
        target_path=None,
        report_title="一致性测试",
        status=status,
        steps=[],
        final_output={},
        created_at=now,
        updated_at=now,
        error=None,
    )


async def acquire(
    repository: AgentTaskPlanRepository,
    task_plan_id: str,
    *,
    worker: str,
    key: str,
    allowed: set[AgentTaskPlanStatus],
) -> TaskPlanLease:
    result = await repository.begin_operation(
        task_plan_id=task_plan_id,
        operation="execute",
        idempotency_key=key,
        request_hash=key.ljust(64, "0")[:64],
        worker_id=worker,
        allowed_statuses=allowed,
        workload_type="document",
        capacity_limit=8,
        lease_seconds=60,
    )
    assert isinstance(result, TaskPlanLease)
    return result


async def cleanup(factory, task_ids: list[str]) -> None:
    async with factory() as session, session.begin():
        await session.execute(
            delete(AgentTaskPlanCommandTable).where(
                AgentTaskPlanCommandTable.task_plan_id.in_(task_ids)
            )
        )
        await session.execute(
            delete(AgentTaskPlanRuntimeRecordTable).where(
                AgentTaskPlanRuntimeRecordTable.task_plan_id.in_(task_ids)
            )
        )
        await session.execute(
            delete(AgentTaskPlanTable).where(
                AgentTaskPlanTable.task_plan_id.in_(task_ids)
            )
        )
        await session.execute(
            delete(AgentTaskCapacitySlotTable).where(
                AgentTaskCapacitySlotTable.task_plan_id.in_(task_ids)
            )
        )


async def main() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    repository = AgentTaskPlanRepository(factory)
    await repository.ensure_capacity_slots(workload_type="document", count=8)
    ids = [f"task_plan_pg_{uuid4().hex}" for _ in range(22)]
    try:
        # 1. 同一任务只能有一个数据库租约。
        plan = build_plan(ids[0], status=AgentTaskPlanStatus.CREATED)
        await repository.create_plan(plan.model_dump(mode="json"))
        first = await acquire(
            repository,
            ids[0],
            worker="worker-a",
            key="lease-a-0000000000000001",
            allowed={AgentTaskPlanStatus.CREATED},
        )
        try:
            await acquire(
                repository,
                ids[0],
                worker="worker-b",
                key="lease-b-0000000000000002",
                allowed={AgentTaskPlanStatus.CREATED},
            )
            raise AssertionError("第二个 Worker 不应取得同一任务")
        except AgentTaskPlanBusyError:
            pass
        await repository.finish_success(
            lease=first,
            response_json=plan.model_dump(mode="json"),
        )
        replay = await repository.begin_operation(
            task_plan_id=ids[0],
            operation="execute",
            idempotency_key="lease-a-0000000000000001",
            request_hash="lease-a-0000000000000001".ljust(64, "0")[:64],
            worker_id="worker-replay",
            allowed_statuses={AgentTaskPlanStatus.CREATED},
            workload_type="document",
            capacity_limit=8,
            lease_seconds=60,
        )
        assert isinstance(replay, TaskPlanCommandReplay)

        # 2. stale TaskPlan record_version 必须 CAS 失败。
        plan = build_plan(ids[1], status=AgentTaskPlanStatus.CREATED)
        await repository.create_plan(plan.model_dump(mode="json"))
        lease = await acquire(
            repository,
            ids[1],
            worker="worker-c",
            key="cas-c-000000000000000003",
            allowed={AgentTaskPlanStatus.CREATED},
        )
        stale_version = lease.record_version
        plan.status = AgentTaskPlanStatus.PREPARING_CONFIRMATION
        await repository.save_snapshot(
            snapshot=plan.model_dump(mode="json"), lease=lease
        )
        stale = TaskPlanLease(
            task_plan_id=lease.task_plan_id,
            operation=lease.operation,
            owner=lease.owner,
            fence_token=lease.fence_token,
            record_version=stale_version,
            command_id=lease.command_id,
            idempotency_key=lease.idempotency_key,
            workload_type=lease.workload_type,
            capacity_slot_no=lease.capacity_slot_no,
            capacity_fence_token=lease.capacity_fence_token,
        )
        try:
            await repository.save_snapshot(
                snapshot=plan.model_dump(mode="json"), lease=stale
            )
            raise AssertionError("旧 record_version 不应写入成功")
        except AgentTaskPlanVersionConflictError:
            pass
        await repository.finish_failure(
            lease=lease,
            error_code="TEST_RELEASE",
            error_message="release",
        )

        # 3. cancel 必须使旧 token 失效，旧 runner 不能覆盖 cancelled。
        plan = build_plan(ids[2], status=AgentTaskPlanStatus.CREATED)
        await repository.create_plan(plan.model_dump(mode="json"))
        lease = await acquire(
            repository,
            ids[2],
            worker="worker-d",
            key="cancel-d-0000000000000004",
            allowed={AgentTaskPlanStatus.CREATED},
        )
        cancelled = await repository.cancel_atomic(
            task_plan_id=ids[2],
            actor_user_id=plan.user_id or "",
            can_manage_all=False,
            idempotency_key="cancel-api-00000000000005",
            request_hash="c" * 64,
            mutate_snapshot=lambda payload: {
                **payload,
                "status": "cancelled",
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
        assert cancelled["status"] == "cancelled"
        plan.status = AgentTaskPlanStatus.COMPLETED
        try:
            await repository.save_snapshot(
                snapshot=plan.model_dump(mode="json"), lease=lease
            )
            raise AssertionError("旧 runner 不应覆盖 cancelled")
        except AgentTaskPlanVersionConflictError:
            pass
        final, _version = await repository.load_snapshot(ids[2])
        assert final["status"] == "cancelled"

        # 4. RuntimeRecord 两个旧 writer 只能成功一个。
        plan = build_plan(ids[3], status=AgentTaskPlanStatus.CREATED)
        await repository.create_plan(plan.model_dump(mode="json"))
        lease = await acquire(
            repository,
            ids[3],
            worker="worker-e",
            key="runtime-e-000000000000006",
            allowed={AgentTaskPlanStatus.CREATED},
        )
        now = datetime.now(UTC)
        runtime = {
            "schema_version": 1,
            "record_version": 1,
            "task_plan_id": ids[3],
            "thread_id": f"document:{ids[3]}",
            "acl_fingerprint": "test",
            "candidates": {},
            "read_snapshots": {},
            "used_tools": [],
            "resume_count": 0,
            "status": "running",
            "expires_at": (now + timedelta(days=1)).isoformat(),
            "updated_at": now.isoformat(),
        }
        await repository.create_runtime_record(snapshot=runtime, lease=lease)
        runtime["record_version"] = 2
        first_version = await repository.update_runtime_record(
            task_plan_id=ids[3],
            expected_version=1,
            snapshot=runtime,
            lease=lease,
        )
        assert first_version == 2
        try:
            await repository.update_runtime_record(
                task_plan_id=ids[3],
                expected_version=1,
                snapshot=runtime,
                lease=lease,
            )
            raise AssertionError("第二个 stale Runtime writer 不应成功")
        except DocumentAgentCheckpointConflictError:
            pass
        await repository.finish_failure(
            lease=lease,
            error_code="TEST_RELEASE",
            error_message="release",
        )

        # 5.【修订】failed 命令允许同键复活重试，而不是永久 IdempotencyConflict。
        plan = build_plan(ids[4], status=AgentTaskPlanStatus.CREATED)
        await repository.create_plan(plan.model_dump(mode="json"))
        first = await acquire(
            repository,
            ids[4],
            worker="worker-f",
            key="retry-f-0000000000000007",
            allowed={AgentTaskPlanStatus.CREATED},
        )
        await repository.finish_failure(
            lease=first,
            error_code="SIMULATED_FAILURE",
            error_message="boom",
        )
        revived = await acquire(
            repository,
            ids[4],
            worker="worker-f2",
            key="retry-f-0000000000000007",
            allowed={AgentTaskPlanStatus.CREATED},
        )
        assert revived.fence_token == first.fence_token + 1
        await repository.finish_failure(
            lease=revived,
            error_code="TEST_RELEASE",
            error_message="release",
        )

        # 6.【修订】busy 被拒的命令允许同键复活重试。
        plan = build_plan(ids[5], status=AgentTaskPlanStatus.CREATED)
        await repository.create_plan(plan.model_dump(mode="json"))
        holder = await acquire(
            repository,
            ids[5],
            worker="worker-g",
            key="busy-g-0000000000000008",
            allowed={AgentTaskPlanStatus.CREATED},
        )
        try:
            await acquire(
                repository,
                ids[5],
                worker="worker-g2",
                key="busy-g2-0000000000000009",
                allowed={AgentTaskPlanStatus.CREATED},
            )
            raise AssertionError("租约占用时第二个 worker 不应成功")
        except AgentTaskPlanBusyError:
            pass
        await repository.finish_failure(
            lease=holder,
            error_code="TEST_RELEASE",
            error_message="release",
        )
        revived_busy = await acquire(
            repository,
            ids[5],
            worker="worker-g2",
            key="busy-g2-0000000000000009",
            allowed={AgentTaskPlanStatus.CREATED},
        )
        assert isinstance(revived_busy, TaskPlanLease)
        await repository.finish_failure(
            lease=revived_busy,
            error_code="TEST_RELEASE",
            error_message="release",
        )

        # 7. 人工确认是数据库权威安全边界：waiting_confirmation 不能直接完成。
        plan = build_plan(ids[6], status=AgentTaskPlanStatus.WAITING_CONFIRMATION)
        await repository.create_plan(plan.model_dump(mode="json"))
        lease = await acquire(
            repository,
            ids[6],
            worker="worker-h",
            key="confirm-h-000000000000010",
            allowed={AgentTaskPlanStatus.WAITING_CONFIRMATION},
        )
        plan.status = AgentTaskPlanStatus.COMPLETED
        try:
            await repository.save_snapshot(
                snapshot=plan.model_dump(mode="json"), lease=lease
            )
            raise AssertionError("waiting_confirmation 不应绕过确认执行状态直接完成")
        except AgentTaskPlanVersionConflictError:
            pass
        plan.status = AgentTaskPlanStatus.EXECUTING_CONFIRMED
        await repository.save_snapshot(snapshot=plan.model_dump(mode="json"), lease=lease)
        plan.status = AgentTaskPlanStatus.COMPLETED
        await repository.save_snapshot(snapshot=plan.model_dump(mode="json"), lease=lease)
        final, version = await repository.load_snapshot(ids[6])
        assert final["status"] == "completed" and version == 3
        await repository.finish_success(
            lease=lease,
            response_json=plan.model_dump(mode="json"),
        )

        # 8. 容量槽不足返回 AGENT_CAPACITY_EXCEEDED；同键复活后槽位恢复可领取。
        plan = build_plan(ids[7], status=AgentTaskPlanStatus.CREATED)
        await repository.create_plan(plan.model_dump(mode="json"))
        try:
            await repository.begin_operation(
                task_plan_id=ids[7],
                operation="execute",
                idempotency_key="capacity-000000000000011",
                request_hash="c" * 64,
                worker_id="worker-i",
                allowed_statuses={AgentTaskPlanStatus.CREATED},
                workload_type="document",
                capacity_limit=0,
                lease_seconds=60,
            )
            raise AssertionError("容量不足时不应领取成功")
        except AgentTaskCapacityExceededError:
            pass
        revived_cap = await repository.begin_operation(
            task_plan_id=ids[7],
            operation="execute",
            idempotency_key="capacity-000000000000011",
            request_hash="c" * 64,
            worker_id="worker-i",
            allowed_statuses={AgentTaskPlanStatus.CREATED},
            workload_type="document",
            capacity_limit=8,
            lease_seconds=60,
        )
        assert isinstance(revived_cap, TaskPlanLease)
        await repository.finish_failure(
            lease=revived_cap,
            error_code="TEST_RELEASE",
            error_message="release",
        )

        # 9. failed 命令并发复活必须串行化，busy 调用者不能覆盖赢家的 command。
        # 两调用者是生产中最常见的“客户端重试 + 原请求仍在执行”形态，多轮运行
        # 用于提高旧实现丢失 command 状态更新的复现率。
        for round_no, task_plan_id in enumerate(ids[8:20], start=1):
            plan = build_plan(task_plan_id, status=AgentTaskPlanStatus.CREATED)
            await repository.create_plan(plan.model_dump(mode="json"))
            key = f"retry-j-{round_no:020d}"
            failed = await acquire(
                repository,
                task_plan_id,
                worker=f"worker-j-initial-{round_no}",
                key=key,
                allowed={AgentTaskPlanStatus.CREATED},
            )
            await repository.finish_failure(
                lease=failed,
                error_code="SIMULATED_FAILURE",
                error_message="boom",
            )

            async def revive(
                worker_no: int,
            ) -> TaskPlanLease | AgentTaskPlanBusyError:
                try:
                    return await acquire(
                        repository,
                        task_plan_id,
                        worker=f"worker-j-{round_no}-{worker_no}",
                        key=key,
                        allowed={AgentTaskPlanStatus.CREATED},
                    )
                except AgentTaskPlanBusyError as exc:
                    return exc

            revival_results = await asyncio.gather(revive(1), revive(2))
            revival_winners = [
                item for item in revival_results if isinstance(item, TaskPlanLease)
            ]
            revival_busy = [
                item
                for item in revival_results
                if isinstance(item, AgentTaskPlanBusyError)
            ]
            assert len(revival_winners) == 1, revival_results
            assert len(revival_busy) == 1, revival_results
            await repository.finish_success(
                lease=revival_winners[0],
                response_json=plan.model_dump(mode="json"),
            )

        # 10. 保留期只决定候选范围；匹配有效租约的 running 命令仍是活跃执行者。
        plan = build_plan(ids[20], status=AgentTaskPlanStatus.CREATED)
        await repository.create_plan(plan.model_dump(mode="json"))
        active = await acquire(
            repository,
            ids[20],
            worker="worker-k-active",
            key="cleanup-k-000000000000013",
            allowed={AgentTaskPlanStatus.CREATED},
        )
        cutoff = datetime.now(UTC) - timedelta(days=7)
        async with factory() as session, session.begin():
            await session.execute(
                update(AgentTaskPlanCommandTable)
                .where(AgentTaskPlanCommandTable.command_id == active.command_id)
                .values(created_at=cutoff - timedelta(days=1))
            )
        expired = await repository.expire_stale_running_commands(cutoff)
        assert expired == 0
        await repository.finish_success(
            lease=active,
            response_json=plan.model_dump(mode="json"),
        )

        # 11. 相同年龄但父 TaskPlan 租约已过期时，命令才属于可回收孤儿。
        plan = build_plan(ids[21], status=AgentTaskPlanStatus.CREATED)
        await repository.create_plan(plan.model_dump(mode="json"))
        orphan = await acquire(
            repository,
            ids[21],
            worker="worker-l-orphan",
            key="cleanup-l-000000000000014",
            allowed={AgentTaskPlanStatus.CREATED},
        )
        async with factory() as session, session.begin():
            await session.execute(
                update(AgentTaskPlanCommandTable)
                .where(AgentTaskPlanCommandTable.command_id == orphan.command_id)
                .values(created_at=cutoff - timedelta(days=1))
            )
            await session.execute(
                update(AgentTaskPlanTable)
                .where(AgentTaskPlanTable.task_plan_id == ids[21])
                .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
            )
        expired = await repository.expire_stale_running_commands(cutoff)
        assert expired == 1

        print("task_plan_postgres_consistency=passed")
    finally:
        await cleanup(factory, ids)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
