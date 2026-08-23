"""验证当前用户 TaskPlan 列表、筛选、分页和公开字段边界。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete

from fast_app.api.agent_task_plan_routes import router
from fast_app.core.config import get_settings
from fast_app.core.exception_handlers import register_exception_handlers
from fast_app.db.agent_task_plan_tables import AgentTaskPlanTable
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.dependencies.rag_dependencies import get_agent_task_plan_store
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.agent_task_plan import AgentTaskPlanStatus
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_tasks.agent_task_plan_catalog_service import (
    AgentTaskPlanCatalogService,
)
from fast_app.services.agent_tasks.agent_task_plan_repository import (
    AgentTaskPlanRepository,
    TaskPlanCatalogRecord,
)
from fast_app.services.agent_tasks.agent_task_plan_store import (
    AgentTaskPlanExportStore,
    AgentTaskPlanStore,
)
from fast_app.services.exceptions import AgentTaskPlanCursorInvalidError


PREFIX = "task_plan_catalog_"
USER_A = "task_plan_catalog_user_a"
USER_B = "task_plan_catalog_user_b"


def main() -> None:
    asyncio.run(assert_database_contract())
    assert_http_contract()
    print("agent_task_plan_list=passed")


async def assert_database_contract() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    repository = AgentTaskPlanRepository(session_factory)
    store = AgentTaskPlanStore(
        repository=repository,
        export_store=AgentTaskPlanExportStore(settings),
    )
    service = AgentTaskPlanCatalogService(store)
    now = datetime.now(UTC)
    try:
        async with session_factory() as session:
            await _cleanup(session)
            session.add_all(
                [
                    _row(
                        f"{PREFIX}a3",
                        USER_A,
                        "waiting_confirmation",
                        "session-alpha",
                        now,
                        "  Compare   permissions and retrieval  ",
                    ),
                    _row(
                        f"{PREFIX}a2",
                        USER_A,
                        "failed",
                        "session-alpha",
                        now,
                        "F" * 260,
                        error_code="AGENT_TEST_FAILURE",
                    ),
                    _row(
                        f"{PREFIX}a1",
                        USER_A,
                        "completed",
                        "session-beta",
                        now - timedelta(minutes=1),
                        "Completed research",
                    ),
                    _row(
                        f"{PREFIX}b1",
                        USER_B,
                        "waiting_confirmation",
                        "session-alpha",
                        now + timedelta(minutes=1),
                        "Other user secret objective",
                    ),
                ]
            )
            await session.commit()

        user_a = _user(USER_A)
        first = await service.list_plans(
            user_a,
            cursor=None,
            limit=2,
            status=None,
            session_id=None,
        )
        assert [item.task_plan_id for item in first.items] == [
            f"{PREFIX}a3",
            f"{PREFIX}a2",
        ]
        assert first.next_cursor is not None
        assert first.items[0].requires_confirmation is True
        assert first.items[0].summary == "Compare permissions and retrieval"
        assert len(first.items[1].summary) == 200
        assert first.items[1].error_code == "AGENT_TEST_FAILURE"

        second = await service.list_plans(
            user_a,
            cursor=first.next_cursor,
            limit=2,
            status=None,
            session_id=None,
        )
        assert [item.task_plan_id for item in second.items] == [f"{PREFIX}a1"]
        assert second.next_cursor is None
        assert all(USER_B not in item.task_plan_id for item in [*first.items, *second.items])

        failed = await service.list_plans(
            user_a,
            cursor=None,
            limit=20,
            status=AgentTaskPlanStatus.FAILED,
            session_id=None,
        )
        assert [item.task_plan_id for item in failed.items] == [f"{PREFIX}a2"]
        alpha = await service.list_plans(
            user_a,
            cursor=None,
            limit=20,
            status=None,
            session_id="session-alpha",
        )
        assert {item.task_plan_id for item in alpha.items} == {
            f"{PREFIX}a2",
            f"{PREFIX}a3",
        }
        public_keys = set(first.items[0].model_dump(mode="json"))
        assert "snapshot_json" not in public_keys
        assert "lease_owner" not in public_keys
        assert "worker_checkpoints" not in public_keys
        try:
            await service.list_plans(
                user_a,
                cursor="not-a-cursor",
                limit=20,
                status=None,
                session_id=None,
            )
        except AgentTaskPlanCursorInvalidError:
            pass
        else:
            raise AssertionError("非法 TaskPlan cursor 未被拒绝")
    finally:
        async with session_factory() as session:
            await _cleanup(session)
        await engine.dispose()


def _row(
    task_plan_id: str,
    owner_user_id: str,
    status: str,
    session_id: str,
    updated_at: datetime,
    objective: str,
    *,
    error_code: str | None = None,
) -> AgentTaskPlanTable:
    return AgentTaskPlanTable(
        task_plan_id=task_plan_id,
        schema_version=2,
        task_kind="question_decomposition",
        status=status,
        owner_user_id=owner_user_id,
        session_id=session_id,
        snapshot_json={
            "objective": objective,
            "error_code": error_code,
            "internal_tool_input": {"secret": "must-not-leak"},
            "worker_checkpoints": {"private": True},
        },
        created_at=updated_at - timedelta(minutes=1),
        updated_at=updated_at,
    )


async def _cleanup(session) -> None:
    await session.execute(
        delete(AgentTaskPlanTable).where(
            AgentTaskPlanTable.task_plan_id.startswith(PREFIX)
        )
    )
    await session.commit()


def _user(user_id: str) -> CurrentUserContext:
    return CurrentUserContext(
        user_id=user_id,
        username=user_id,
        is_authenticated=True,
        auth_source="jwt",
    )


class _HttpStore:
    async def list_owned(self, **_kwargs):
        now = datetime.now(UTC)
        return [
            TaskPlanCatalogRecord(
                task_plan_id=f"{PREFIX}http",
                task_kind="question_decomposition",
                status="waiting_confirmation",
                session_id="session-http",
                summary="HTTP summary",
                error_code=None,
                created_at=now,
                updated_at=now,
            )
        ], False


def assert_http_contract() -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: _user(USER_A)
    app.dependency_overrides[get_agent_task_plan_store] = lambda: _HttpStore()
    with TestClient(app) as client:
        response = client.get(
            "/agent/task-plans",
            params={"status": "waiting_confirmation", "session_id": "session-http"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["task_plan_id"] == f"{PREFIX}http"
        assert "snapshot_json" not in payload["items"][0]
        assert client.get("/agent/task-plans", params={"cursor": "bad"}).status_code == 400
        assert client.get("/agent/task-plans", params={"status": "unknown"}).status_code == 422
        assert client.get("/agent/task-plans", params={"limit": 101}).status_code == 422
    operation = app.openapi()["paths"]["/agent/task-plans"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]


if __name__ == "__main__":
    main()
