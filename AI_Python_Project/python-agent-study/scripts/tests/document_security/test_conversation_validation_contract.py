"""验证 Conversation 422 runtime 与 OpenAPI 使用同一安全字段错误契约。"""

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from fast_app.api.conversation_routes import router
from fast_app.core.exception_handlers import register_exception_handlers
from fast_app.dependencies.conversation_dependencies import (
    get_conversation_catalog_service,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.auth_models import AccountType
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.error_schema import RequestValidationErrorResponse


class ProbeRequest(BaseModel):
    value: str


def main() -> None:
    assert_conversation_validation_runtime_contract()
    assert_conversation_validation_openapi_contract()
    print("conversation_validation_contract=passed")


def assert_conversation_validation_runtime_contract() -> None:
    app = _build_test_app()
    client = TestClient(app, raise_server_exceptions=False)

    for method, path in (
        ("post", "/conversations"),
        ("patch", "/conversations/contract-session"),
    ):
        response = getattr(client, method)(path, json={"title": "   "})
        assert response.status_code == 422, response.text
        body = RequestValidationErrorResponse.model_validate(response.json())
        assert [item.model_dump() for item in body.field_errors] == [
            {
                "field": "title",
                "code": "invalid",
                "message": "输入值不合法",
            }
        ]

    sensitive_marker = "must-not-appear-in-public-response"
    invalid_type = client.post(
        "/conversations",
        json={"title": [sensitive_marker]},
    )
    assert invalid_type.status_code == 422, invalid_type.text
    assert sensitive_marker not in invalid_type.text
    invalid_type_body = RequestValidationErrorResponse.model_validate(
        invalid_type.json()
    )
    assert [item.model_dump() for item in invalid_type_body.field_errors] == [
        {
            "field": "title",
            "code": "invalid_type",
            "message": "请输入文本",
        }
    ]

    malformed = client.post(
        "/conversations",
        content="{",
        headers={"Content-Type": "application/json"},
    )
    assert malformed.status_code == 422, malformed.text
    malformed_body = RequestValidationErrorResponse.model_validate(malformed.json())
    assert malformed_body.field_errors == []

    invalid_path = client.patch(
        f"/conversations/{'s' * 129}",
        json={"title": "Valid title"},
    )
    assert invalid_path.status_code == 422, invalid_path.text
    invalid_path_body = RequestValidationErrorResponse.model_validate(
        invalid_path.json()
    )
    assert invalid_path_body.field_errors == []

    unrelated = client.post("/contract-probe", json={})
    assert unrelated.status_code == 422, unrelated.text
    assert set(unrelated.json()) == {
        "code",
        "message",
        "error_category",
        "request_id",
        "trace_id",
    }


def assert_conversation_validation_openapi_contract() -> None:
    openapi = _build_test_app().openapi()
    for path, method in (
        ("/conversations", "post"),
        ("/conversations/{session_id}", "patch"),
    ):
        response_schema = openapi["paths"][path][method]["responses"]["422"][
            "content"
        ]["application/json"]["schema"]
        assert response_schema == {
            "$ref": "#/components/schemas/RequestValidationErrorResponse"
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
    ]


def _build_test_app() -> FastAPI:
    current_user = CurrentUserContext(
        user_id="conversation-contract-user",
        username="conversation-contract-user",
        account_type=AccountType.EMPLOYEE,
        is_authenticated=True,
        auth_source="jwt",
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_conversation_catalog_service] = lambda: AsyncMock()
    app.dependency_overrides[get_current_user_context] = lambda: current_user

    @app.post("/contract-probe")
    async def contract_probe(req: ProbeRequest) -> dict[str, str]:
        return {"value": req.value}

    return app


if __name__ == "__main__":
    main()
