"""验证 Auth 422 runtime 与 OpenAPI 使用同一安全字段错误契约。"""

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from fast_app.api.auth_routes import router
from fast_app.core.exception_handlers import register_exception_handlers
from fast_app.dependencies.rag_dependencies import get_auth_service
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.auth_models import AccountType
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.error_schema import RequestValidationErrorResponse


AUTH_VALIDATION_PATHS = (
    "/auth/login",
    "/auth/refresh",
    "/auth/change-password",
)


class ProbeRequest(BaseModel):
    value: str


def main() -> None:
    assert_auth_validation_runtime_contract()
    assert_auth_validation_openapi_contract()
    print("auth_validation_contract=passed")


def assert_auth_validation_runtime_contract() -> None:
    app = _build_test_app()
    client = TestClient(app, raise_server_exceptions=False)

    missing = client.post("/auth/login", json={})
    assert missing.status_code == 422, missing.text
    missing_body = RequestValidationErrorResponse.model_validate(missing.json())
    assert missing_body.code == "REQUEST_VALIDATION_ERROR"
    assert {
        item.field: (item.code, item.message) for item in missing_body.field_errors
    } == {
        "username_or_email": ("required", "该字段为必填项"),
        "password": ("required", "该字段为必填项"),
    }

    for path, expected_fields in (
        ("/auth/refresh", {"refresh_token"}),
        ("/auth/change-password", {"current_password", "new_password"}),
    ):
        response = client.post(path, json={})
        assert response.status_code == 422, response.text
        body = RequestValidationErrorResponse.model_validate(response.json())
        assert {item.field for item in body.field_errors} == expected_fields
        assert {item.code for item in body.field_errors} == {"required"}

    sensitive_marker = "must-not-appear-in-public-response"
    invalid_type = client.post(
        "/auth/login",
        json={
            "username_or_email": "reader@example.com",
            "password": [sensitive_marker],
        },
    )
    assert invalid_type.status_code == 422, invalid_type.text
    assert sensitive_marker not in invalid_type.text
    invalid_type_body = RequestValidationErrorResponse.model_validate(
        invalid_type.json()
    )
    assert [item.model_dump() for item in invalid_type_body.field_errors] == [
        {
            "field": "password",
            "code": "invalid_type",
            "message": "请输入文本",
        }
    ]

    malformed = client.post(
        "/auth/login",
        content="{",
        headers={"Content-Type": "application/json"},
    )
    assert malformed.status_code == 422, malformed.text
    malformed_body = RequestValidationErrorResponse.model_validate(malformed.json())
    assert malformed_body.field_errors == []

    unrelated = client.post("/contract-probe", json={})
    assert unrelated.status_code == 422, unrelated.text
    assert set(unrelated.json()) == {
        "code",
        "message",
        "error_category",
        "request_id",
        "trace_id",
    }


def assert_auth_validation_openapi_contract() -> None:
    openapi = _build_test_app().openapi()
    for path in AUTH_VALIDATION_PATHS:
        response_schema = openapi["paths"][path]["post"]["responses"]["422"][
            "content"
        ]["application/json"]["schema"]
        assert response_schema == {
            "$ref": "#/components/schemas/RequestValidationErrorResponse"
        }

    response_schema = openapi["components"]["schemas"][
        "RequestValidationErrorResponse"
    ]
    assert set(response_schema["properties"]) == {
        "code",
        "message",
        "error_category",
        "request_id",
        "trace_id",
        "field_errors",
    }
    field_error_schema = openapi["components"]["schemas"][
        "RequestValidationFieldError"
    ]
    assert field_error_schema["properties"]["field"]["enum"] == [
        "username_or_email",
        "password",
        "refresh_token",
        "current_password",
        "new_password",
        "title",
        "query",
        "status",
        "session_id",
        "limit",
    ]
    assert field_error_schema["properties"]["code"]["enum"] == [
        "required",
        "invalid_type",
        "too_short",
        "too_long",
        "invalid",
    ]


def _build_test_app() -> FastAPI:
    current_user = CurrentUserContext(
        user_id="contract-user",
        username="contract-user",
        account_type=AccountType.EMPLOYEE,
        is_authenticated=True,
        auth_source="jwt",
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_auth_service] = lambda: AsyncMock()
    app.dependency_overrides[get_current_user_context] = lambda: current_user

    @app.post("/contract-probe")
    async def contract_probe(req: ProbeRequest) -> dict[str, str]:
        return {"value": req.value}

    return app


if __name__ == "__main__":
    main()
