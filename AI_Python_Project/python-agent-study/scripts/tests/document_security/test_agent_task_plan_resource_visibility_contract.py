"""验证 Initial React TaskPlan Route 使用不可枚举的 owned-resource 404。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fast_app.api.agent_task_plan_routes import router
from fast_app.core.config import Settings, get_settings
from fast_app.core.exception_handlers import register_exception_handlers
from fast_app.dependencies.rag_dependencies import (
    get_agent_task_executor,
    get_agent_task_plan_store,
    get_prompt_guard_service,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.agent_task_plan import AgentTaskPlan
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.exceptions import AppServiceError


PUBLIC_NOT_FOUND_CODE = "AGENT_TASK_PLAN_NOT_FOUND"
PUBLIC_NOT_FOUND_MESSAGE = "TaskPlan 不存在或当前不可访问"


def main() -> None:
    assert_detail_inaccessible_resources_are_indistinguishable()
    assert_detail_remains_available_to_owner()
    assert_markdown_inaccessible_resources_are_indistinguishable()
    assert_markdown_remains_available_to_owner()
    assert_confirm_stream_inaccessible_resources_are_pre_stream_404()
    assert_confirm_stream_remains_available_to_owner()
    assert_cancel_inaccessible_resources_are_404()
    assert_cancel_remains_available_to_owner()
    assert_retry_inaccessible_resources_are_404()
    assert_retry_remains_available_to_owner()
    assert_non_stream_confirm_admin_behavior_is_unchanged()
    print("agent_task_plan_resource_visibility_contract=passed")


def assert_detail_inaccessible_resources_are_indistinguishable() -> None:
    marker = "must-not-appear-in-task-plan-404"
    other_plan = _document_plan(owner_user_id=f"other-owner-{marker}")

    responses = (
        _client(
            user=_user("viewer"),
            store=_Store(error=AppServiceError(f"missing {marker}")),
        ).get("/agent/task-plans/task_plan_missing"),
        _client(user=_user("viewer"), store=_Store(plan=other_plan)).get(
            f"/agent/task-plans/{other_plan.task_plan_id}"
        ),
        _client(
            user=_user("admin", global_role_codes=["system_admin"]),
            store=_Store(plan=other_plan),
        ).get(f"/agent/task-plans/{other_plan.task_plan_id}"),
    )

    for response in responses:
        assert response.status_code == 404, response.text
        assert response.json().get("code") == PUBLIC_NOT_FOUND_CODE, response.text
        assert response.json().get("message") == PUBLIC_NOT_FOUND_MESSAGE, response.text
        assert marker not in response.text


def assert_detail_remains_available_to_owner() -> None:
    plan = _document_plan(owner_user_id="owner")
    response = _client(user=_user("owner"), store=_Store(plan=plan)).get(
        f"/agent/task-plans/{plan.task_plan_id}"
    )
    assert response.status_code == 200, response.text
    assert response.json().get("task_plan_id") == plan.task_plan_id


def assert_markdown_inaccessible_resources_are_indistinguishable() -> None:
    marker = "must-not-appear-in-task-plan-markdown-404"
    other_plan = _document_plan(owner_user_id=f"other-owner-{marker}")

    responses = (
        _client(
            user=_user("viewer"),
            store=_Store(error=AppServiceError(f"missing {marker}")),
        ).get("/agent/task-plans/task_plan_missing/markdown"),
        _client(user=_user("viewer"), store=_Store(plan=other_plan)).get(
            f"/agent/task-plans/{other_plan.task_plan_id}/markdown"
        ),
        _client(
            user=_user("admin", global_role_codes=["system_admin"]),
            store=_Store(plan=other_plan),
        ).get(f"/agent/task-plans/{other_plan.task_plan_id}/markdown"),
    )

    for response in responses:
        assert response.status_code == 404, response.text
        assert response.json().get("code") == PUBLIC_NOT_FOUND_CODE, response.text
        assert response.json().get("message") == PUBLIC_NOT_FOUND_MESSAGE, response.text
        assert marker not in response.text


def assert_markdown_remains_available_to_owner() -> None:
    plan = _document_plan(owner_user_id="owner")
    response = _client(user=_user("owner"), store=_Store(plan=plan)).get(
        f"/agent/task-plans/{plan.task_plan_id}/markdown"
    )
    assert response.status_code == 200, response.text
    assert response.text == "# Safe TaskPlan review"


def assert_confirm_stream_inaccessible_resources_are_pre_stream_404() -> None:
    marker = "must-not-appear-in-task-plan-confirm-stream-404"
    other_plan = _document_plan(owner_user_id=f"other-owner-{marker}")

    responses = (
        _post_confirm_stream(
            _client(
                user=_user("viewer"),
                store=_Store(
                    plan=other_plan,
                    error=AppServiceError(f"missing {marker}"),
                ),
            ),
            "task_plan_missing",
        ),
        _post_confirm_stream(
            _client(user=_user("viewer"), store=_Store(plan=other_plan)),
            other_plan.task_plan_id,
        ),
        _post_confirm_stream(
            _client(
                user=_user("admin", global_role_codes=["system_admin"]),
                store=_Store(plan=other_plan),
            ),
            other_plan.task_plan_id,
        ),
    )

    for response in responses:
        assert response.status_code == 404, response.text
        assert response.json().get("code") == PUBLIC_NOT_FOUND_CODE, response.text
        assert response.json().get("message") == PUBLIC_NOT_FOUND_MESSAGE, response.text
        assert marker not in response.text


def assert_confirm_stream_remains_available_to_owner() -> None:
    plan = _document_plan(owner_user_id="owner")
    response = _post_confirm_stream(
        _client(user=_user("owner"), store=_Store(plan=plan)),
        plan.task_plan_id,
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")


def assert_cancel_inaccessible_resources_are_404() -> None:
    marker = "must-not-appear-in-task-plan-cancel-404"
    other_plan = _document_plan(owner_user_id=f"other-owner-{marker}")

    responses = (
        _post_control(
            _client(
                user=_user("viewer"),
                store=_Store(
                    plan=other_plan,
                    error=AppServiceError(f"missing {marker}"),
                ),
            ),
            "task_plan_missing",
            "cancel",
        ),
        _post_control(
            _client(user=_user("viewer"), store=_Store(plan=other_plan)),
            other_plan.task_plan_id,
            "cancel",
        ),
        _post_control(
            _client(
                user=_user("admin", global_role_codes=["system_admin"]),
                store=_Store(plan=other_plan),
            ),
            other_plan.task_plan_id,
            "cancel",
        ),
    )

    for response in responses:
        assert response.status_code == 404, response.text
        assert response.json().get("code") == PUBLIC_NOT_FOUND_CODE, response.text
        assert response.json().get("message") == PUBLIC_NOT_FOUND_MESSAGE, response.text
        assert marker not in response.text


def assert_cancel_remains_available_to_owner() -> None:
    plan = _document_plan(owner_user_id="owner")
    response = _post_control(
        _client(user=_user("owner"), store=_Store(plan=plan)),
        plan.task_plan_id,
        "cancel",
    )
    assert response.status_code == 200, response.text
    assert response.json()["task_plan_id"] == plan.task_plan_id


def assert_retry_inaccessible_resources_are_404() -> None:
    marker = "must-not-appear-in-task-plan-retry-404"
    other_plan = _document_plan(owner_user_id=f"other-owner-{marker}")

    responses = (
        _post_control(
            _client(
                user=_user("viewer"),
                store=_Store(
                    plan=other_plan,
                    error=AppServiceError(f"missing {marker}"),
                ),
            ),
            "task_plan_missing",
            "retry",
        ),
        _post_control(
            _client(user=_user("viewer"), store=_Store(plan=other_plan)),
            other_plan.task_plan_id,
            "retry",
        ),
        _post_control(
            _client(
                user=_user("admin", global_role_codes=["system_admin"]),
                store=_Store(plan=other_plan),
            ),
            other_plan.task_plan_id,
            "retry",
        ),
    )

    for response in responses:
        assert response.status_code == 404, response.text
        assert response.json().get("code") == PUBLIC_NOT_FOUND_CODE, response.text
        assert response.json().get("message") == PUBLIC_NOT_FOUND_MESSAGE, response.text
        assert marker not in response.text


def assert_retry_remains_available_to_owner() -> None:
    plan = _document_plan(owner_user_id="owner")
    response = _post_control(
        _client(user=_user("owner"), store=_Store(plan=plan)),
        plan.task_plan_id,
        "retry",
    )
    assert response.status_code == 200, response.text
    assert response.json()["task_plan_id"] == plan.task_plan_id


def assert_non_stream_confirm_admin_behavior_is_unchanged() -> None:
    plan = _document_plan(owner_user_id="other-owner")
    client = _client(
        user=_user("admin", global_role_codes=["system_admin"]),
        store=_Store(plan=plan),
    )
    response = client.post(
        f"/agent/task-plans/{plan.task_plan_id}/confirm",
        json={"confirmed": True},
        headers={"Idempotency-Key": "visibility-contract-key"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["task_plan_id"] == plan.task_plan_id


def _post_confirm_stream(client: TestClient, task_plan_id: str):
    return client.post(
        f"/agent/task-plans/{task_plan_id}/confirm/stream",
        json={"confirmed": True},
        headers={"Idempotency-Key": "visibility-contract-key"},
    )


def _post_control(client: TestClient, task_plan_id: str, operation: str):
    return client.post(
        f"/agent/task-plans/{task_plan_id}/{operation}",
        headers={"Idempotency-Key": "visibility-contract-key"},
    )


class _Store:
    def __init__(
        self,
        *,
        plan: AgentTaskPlan | None = None,
        error: Exception | None = None,
    ) -> None:
        self._plan = plan
        self._error = error

    async def load(self, _task_plan_id: str) -> AgentTaskPlan:
        if self._error is not None:
            raise self._error
        assert self._plan is not None
        return self._plan

    async def load_markdown(self, _task_plan_id: str) -> str:
        return "# Safe TaskPlan review"


class _Executor:
    def __init__(self, plan: AgentTaskPlan | None) -> None:
        self._plan = plan

    async def confirm(self, **_kwargs) -> AgentTaskPlan:
        assert self._plan is not None
        return self._plan

    async def cancel(self, *_args, **_kwargs) -> AgentTaskPlan:
        assert self._plan is not None
        return self._plan

    async def resume(self, *_args, **_kwargs) -> AgentTaskPlan:
        assert self._plan is not None
        return self._plan


def _client(*, user: CurrentUserContext, store: _Store) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: user
    app.dependency_overrides[get_agent_task_plan_store] = lambda: store
    app.dependency_overrides[get_agent_task_executor] = lambda: _Executor(store._plan)
    app.dependency_overrides[get_prompt_guard_service] = lambda: object()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        OPENAI_API_KEY="",
        LANGSMITH_TRACING=False,
    )
    return TestClient(app, raise_server_exceptions=False)


def _user(
    user_id: str,
    *,
    global_role_codes: list[str] | None = None,
) -> CurrentUserContext:
    return CurrentUserContext(
        user_id=user_id,
        username=user_id,
        is_authenticated=True,
        auth_source="jwt",
        global_role_codes=global_role_codes or [],
    )


def _document_plan(*, owner_user_id: str) -> AgentTaskPlan:
    now = datetime.now(UTC)
    return AgentTaskPlan(
        task_plan_id="task_plan_visibility_contract",
        task_kind="knowledge_document_management",
        user_id=owner_user_id,
        original_query="公开契约测试",
        objective="公开契约测试",
        task_type="analysis",
        goal="公开契约测试",
        sub_questions=[],
        research_policy=None,
        final_synthesis_instruction="不调用外部服务",
        source_query="公开契约测试",
        target_path=None,
        report_title="公开契约测试",
        steps=[],
        final_output={},
        created_at=now,
        updated_at=now,
    )


if __name__ == "__main__":
    main()
