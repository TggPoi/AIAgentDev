"""验证 Initial React TaskPlan Route 的安全 422 契约。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from fast_app.api.agent_task_plan_routes import router
from fast_app.core.config import Settings, get_settings
from fast_app.core.exception_handlers import register_exception_handlers
from fast_app.dependencies.rag_dependencies import (
    get_agent_task_executor,
    get_agent_task_plan_store,
    get_prompt_guard_service,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.error_schema import RequestValidationErrorResponse


TASK_PLAN_VALIDATION_OPERATIONS = (
    ("/agent/task-plans", "get"),
    ("/agent/task-plans/{task_plan_id}", "get"),
    ("/agent/task-plans/{task_plan_id}/markdown", "get"),
    ("/agent/task-plans/{task_plan_id}/confirm/stream", "post"),
    ("/agent/task-plans/{task_plan_id}/cancel", "post"),
    ("/agent/task-plans/{task_plan_id}/retry", "post"),
)


class ProbeRequest(BaseModel):
    value: str


def main() -> None:
    assert_list_query_fields_are_safely_projected()
    assert_fixed_body_and_headers_remain_form_level()
    assert_openapi_uses_safe_validation_model()
    assert_non_allowlisted_routes_are_unchanged()
    print("agent_task_plan_validation_contract=passed")


def assert_list_query_fields_are_safely_projected() -> None:
    marker = "must-not-appear-in-task-plan-list-validation"
    cases = (
        (
            f"/agent/task-plans?status={marker}",
            {"field": "status", "code": "invalid", "message": "输入值不合法"},
        ),
        (
            "/agent/task-plans?session_id=",
            {
                "field": "session_id",
                "code": "too_short",
                "message": "输入长度过短",
            },
        ),
        (
            f"/agent/task-plans?limit={marker}",
            {
                "field": "limit",
                "code": "invalid_type",
                "message": "请输入有效数字",
            },
        ),
        (
            "/agent/task-plans?limit=0",
            {"field": "limit", "code": "invalid", "message": "输入值不合法"},
        ),
    )

    with _client() as client:
        for path, expected in cases:
            response = client.get(path)
            assert response.status_code == 422, response.text
            body = RequestValidationErrorResponse.model_validate(response.json())
            assert [item.model_dump() for item in body.field_errors] == [expected]
            assert marker not in response.text


def assert_fixed_body_and_headers_remain_form_level() -> None:
    marker = "must-not-appear-in-task-plan-form-validation"
    valid_key = "task-plan-contract-key-0001"

    with _client() as client:
        responses = (
            client.post(
                "/agent/task-plans/task_plan_contract/confirm/stream",
                json={"confirmed": [marker]},
                headers={"Idempotency-Key": valid_key},
            ),
            client.post("/agent/task-plans/task_plan_contract/cancel"),
            client.post(
                "/agent/task-plans/task_plan_contract/retry",
                headers={"Idempotency-Key": marker * 4},
            ),
        )

    for response in responses:
        assert response.status_code == 422, response.text
        body = RequestValidationErrorResponse.model_validate(response.json())
        assert body.field_errors == []
        assert marker not in response.text


def assert_openapi_uses_safe_validation_model() -> None:
    openapi = _app().openapi()
    for path, method in TASK_PLAN_VALIDATION_OPERATIONS:
        response_schema = openapi["paths"][path][method]["responses"]["422"][
            "content"
        ]["application/json"]["schema"]
        assert response_schema == {
            "$ref": "#/components/schemas/RequestValidationErrorResponse"
        }

    fields = openapi["components"]["schemas"]["RequestValidationFieldError"][
        "properties"
    ]["field"]["enum"]
    assert {"status", "session_id", "limit"}.issubset(fields)


def assert_non_allowlisted_routes_are_unchanged() -> None:
    with _client() as client:
        non_stream_confirm = client.post(
            "/agent/task-plans/task_plan_contract/confirm",
            json={},
        )
        unrelated = client.post("/contract-probe", json={})

    for response in (non_stream_confirm, unrelated):
        assert response.status_code == 422, response.text
        assert set(response.json()) == {
            "code",
            "message",
            "error_category",
            "request_id",
            "trace_id",
        }

    openapi = _app().openapi()
    legacy_schema = openapi["paths"][
        "/agent/task-plans/{task_plan_id}/confirm"
    ]["post"]["responses"]["422"]["content"]["application/json"]["schema"]
    assert legacy_schema == {"$ref": "#/components/schemas/HTTPValidationError"}


def _client() -> TestClient:
    return TestClient(_app(), raise_server_exceptions=False)


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/contract-probe")
    async def contract_probe(_req: ProbeRequest) -> None:
        return None

    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(
        user_id="owner",
        username="owner",
        is_authenticated=True,
        auth_source="jwt",
    )
    app.dependency_overrides[get_agent_task_plan_store] = lambda: object()
    app.dependency_overrides[get_agent_task_executor] = lambda: object()
    app.dependency_overrides[get_prompt_guard_service] = lambda: object()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        OPENAI_API_KEY="",
        LANGSMITH_TRACING=False,
    )
    return app


if __name__ == "__main__":
    main()
