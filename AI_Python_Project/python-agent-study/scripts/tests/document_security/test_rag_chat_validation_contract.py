"""验证 structured Chat 422 runtime 与 OpenAPI 使用同一安全字段错误契约。"""

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fast_app.api.rag_chat_routes import router
from fast_app.core.exception_handlers import register_exception_handlers
from fast_app.dependencies.conversation_dependencies import (
    get_structured_conversation_turn_recorder,
)
from fast_app.dependencies.document_access_dependencies import (
    get_document_access_policy,
)
from fast_app.dependencies.nl2sql_dependencies import get_nl2sql_service
from fast_app.dependencies.rag_dependencies import get_db_session, get_rag_pipeline
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.auth_models import AccountType
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.error_schema import RequestValidationErrorResponse


def main() -> None:
    assert_rag_chat_validation_runtime_contract()
    assert_rag_chat_validation_openapi_contract()
    print("rag_chat_validation_contract=passed")


def assert_rag_chat_validation_runtime_contract() -> None:
    client = TestClient(_build_test_app(), raise_server_exceptions=False)

    blank_query = client.post(
        "/rag/chat/stream/events",
        json={"query": "   "},
    )
    assert blank_query.status_code == 422, blank_query.text
    assert blank_query.json().get("field_errors") == [
        {
            "field": "query",
            "code": "invalid",
            "message": "输入值不合法",
        }
    ], blank_query.text
    RequestValidationErrorResponse.model_validate(blank_query.json())

    sensitive_marker = "must-not-appear-in-public-response"
    invalid_type = client.post(
        "/rag/chat/stream/events",
        json={"query": [sensitive_marker]},
    )
    assert invalid_type.status_code == 422, invalid_type.text
    assert sensitive_marker not in invalid_type.text
    invalid_type_body = RequestValidationErrorResponse.model_validate(
        invalid_type.json()
    )
    assert [item.model_dump() for item in invalid_type_body.field_errors] == [
        {
            "field": "query",
            "code": "invalid_type",
            "message": "请输入文本",
        }
    ]

    malformed = client.post(
        "/rag/chat/stream/events",
        content="{",
        headers={"Content-Type": "application/json"},
    )
    assert malformed.status_code == 422, malformed.text
    malformed_body = RequestValidationErrorResponse.model_validate(malformed.json())
    assert malformed_body.field_errors == []

    for payload in (
        {"query": "valid", "session_id": "   "},
        {
            "query": "valid",
            "filters": {"section_path": [{"private": sensitive_marker}]},
        },
        {"query": "valid", "dataset_id": "dataset-contract"},
        {"query": "valid", "private_acl_marker": sensitive_marker},
    ):
        response = client.post("/rag/chat/stream/events", json=payload)
        assert response.status_code == 422, response.text
        assert sensitive_marker not in response.text
        body = RequestValidationErrorResponse.model_validate(response.json())
        assert body.field_errors == []

    for path in ("/rag/chat", "/rag/chat/stream"):
        unrelated = client.post(path, json={"query": "   "})
        assert unrelated.status_code == 422, unrelated.text
        assert set(unrelated.json()) == {
            "code",
            "message",
            "error_category",
            "request_id",
            "trace_id",
        }


def assert_rag_chat_validation_openapi_contract() -> None:
    openapi = _build_test_app().openapi()
    response_schema = openapi["paths"]["/rag/chat/stream/events"]["post"][
        "responses"
    ]["422"]["content"]["application/json"]["schema"]
    assert response_schema == {
        "$ref": "#/components/schemas/RequestValidationErrorResponse"
    }

    for path in ("/rag/chat", "/rag/chat/stream"):
        legacy_schema = openapi["paths"][path]["post"]["responses"]["422"][
            "content"
        ]["application/json"]["schema"]
        assert legacy_schema == {"$ref": "#/components/schemas/HTTPValidationError"}

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
        "department_code",
        "document_type",
        "status",
        "session_id",
        "limit",
    ]


def _build_test_app() -> FastAPI:
    current_user = CurrentUserContext(
        user_id="rag-chat-contract-user",
        username="rag-chat-contract-user",
        account_type=AccountType.EMPLOYEE,
        is_authenticated=True,
        auth_source="jwt",
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: current_user
    for dependency in (
        get_rag_pipeline,
        get_db_session,
        get_nl2sql_service,
        get_document_access_policy,
        get_structured_conversation_turn_recorder,
    ):
        app.dependency_overrides[dependency] = lambda: AsyncMock()
    return app


if __name__ == "__main__":
    main()
