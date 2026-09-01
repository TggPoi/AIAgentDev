"""验证 Initial React Document Grant Route 的安全 422 公共契约。"""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from fast_app.api.document_access_routes import router
from fast_app.core.exception_handlers import register_exception_handlers
from fast_app.dependencies.document_access_dependencies import (
    get_document_access_service,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.auth_models import AccountType
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.error_schema import RequestValidationErrorResponse
from fast_app.services.exceptions import DocumentAccessGrantInvalidError


BUSINESS_MARKER = "must-not-appear-from-document-grant-service"


class ProbeRequest(BaseModel):
    value: str


class InvalidGrantService:
    """只在公共 Route seam 触发已分类业务错误，不模拟持久化。"""

    async def create_grants(self, actor, request):
        raise DocumentAccessGrantInvalidError(
            BUSINESS_MARKER,
            field="document_ids",
            field_code="invalid",
        )


class InvalidCursorService:
    """通过公共列表 Route 触发不含字段位置的 cursor 业务错误。"""

    async def list_grants(self, actor, **filters):
        raise DocumentAccessGrantInvalidError(BUSINESS_MARKER)


def main() -> None:
    assert_create_request_validation_fields_are_safely_projected()
    assert_create_business_validation_is_discriminated_and_safe()
    assert_list_request_and_cursor_validation_are_safe()
    assert_revoke_path_is_form_level_and_unrelated_route_is_unchanged()
    assert_openapi_matches_runtime_422_shapes()
    assert_business_error_metadata_is_strictly_allowlisted()
    print("document_access_grant_validation_contract=passed")


def assert_create_request_validation_fields_are_safely_projected() -> None:
    marker = "must-not-appear-in-document-grant-validation"

    with _client() as client:
        missing = client.post("/admin/document-access/grants", json={})
        invalid_target = client.post(
            "/admin/document-access/grants",
            json={"target_account": marker * 6, "document_ids": ["doc-safe"]},
        )
        duplicate_documents = client.post(
            "/admin/document-access/grants",
            json={
                "target_account": "target-safe",
                "document_ids": [marker, marker],
            },
        )
        long_document = client.post(
            "/admin/document-access/grants",
            json={
                "target_account": "target-safe",
                "document_ids": [marker * 2],
            },
        )
        malformed = client.post(
            "/admin/document-access/grants",
            content="{",
            headers={"Content-Type": "application/json"},
        )
        unknown_field = client.post(
            "/admin/document-access/grants",
            json={
                "target_account": "target-safe",
                "document_ids": ["doc-safe"],
                "private_marker": marker,
            },
        )

    assert _field_names(missing) == {"target_account", "document_ids"}
    assert _field_errors(invalid_target) == [
        {
            "field": "target_account",
            "code": "too_long",
            "message": "输入长度过长",
        }
    ]
    assert marker not in invalid_target.text
    assert _field_errors(duplicate_documents) == [
        {
            "field": "document_ids",
            "code": "invalid",
            "message": "输入值不合法",
        }
    ]
    assert marker not in duplicate_documents.text
    assert _field_errors(long_document) == [
        {
            "field": "document_ids",
            "code": "invalid",
            "message": "输入值不合法",
        }
    ]
    assert marker not in long_document.text
    assert _field_errors(malformed) == []
    assert _field_errors(unknown_field) == []
    assert marker not in unknown_field.text


def assert_create_business_validation_is_discriminated_and_safe() -> None:
    with _client(InvalidGrantService()) as client:
        response = client.post(
            "/admin/document-access/grants",
            json={
                "target_account": "target-safe",
                "document_ids": ["doc-safe"],
            },
        )

    assert response.status_code == 422, response.text
    assert response.json() == {
        "code": "DOCUMENT_ACCESS_GRANT_INVALID",
        "message": "文档授权请求不合法",
        "error_category": "user_error",
        "request_id": None,
        "trace_id": None,
        "field_errors": [
            {
                "field": "document_ids",
                "code": "invalid",
                "message": "输入值不合法",
            }
        ],
    }
    assert BUSINESS_MARKER not in response.text


def assert_list_request_and_cursor_validation_are_safe() -> None:
    marker = "must-not-appear-in-document-grant-list-validation"
    cases = (
        (
            {"target_account": marker * 6},
            {
                "field": "target_account",
                "code": "too_long",
                "message": "输入长度过长",
            },
        ),
        (
            {"doc_id": marker * 2},
            {
                "field": "doc_id",
                "code": "too_long",
                "message": "输入长度过长",
            },
        ),
        (
            {"status": marker},
            {"field": "status", "code": "invalid", "message": "输入值不合法"},
        ),
        (
            {"department_code": marker * 2},
            {
                "field": "department_code",
                "code": "too_long",
                "message": "输入长度过长",
            },
        ),
        (
            {"limit": marker},
            {
                "field": "limit",
                "code": "invalid_type",
                "message": "请输入有效数字",
            },
        ),
    )

    with _client() as client:
        responses = [
            (client.get("/admin/document-access/grants", params=params), expected)
            for params, expected in cases
        ]
    for response, expected in responses:
        assert _field_errors(response) == [expected]
        assert marker not in response.text

    with _client(InvalidCursorService()) as client:
        invalid_cursor = client.get(
            "/admin/document-access/grants",
            params={"cursor": marker},
        )

    assert invalid_cursor.status_code == 422, invalid_cursor.text
    assert invalid_cursor.json() == {
        "code": "DOCUMENT_ACCESS_GRANT_INVALID",
        "message": "文档授权请求不合法",
        "error_category": "user_error",
        "request_id": None,
        "trace_id": None,
        "field_errors": [],
    }
    assert marker not in invalid_cursor.text
    assert BUSINESS_MARKER not in invalid_cursor.text


def assert_revoke_path_is_form_level_and_unrelated_route_is_unchanged() -> None:
    marker = "must-not-appear-in-document-grant-path-validation"

    with _client() as client:
        invalid_path = client.delete(
            "/admin/document-access/grants/" + marker * 2,
        )
        unrelated = client.post("/contract-probe", json={})

    assert _field_errors(invalid_path) == []
    assert marker not in invalid_path.text
    assert unrelated.status_code == 422, unrelated.text
    assert set(unrelated.json()) == {
        "code",
        "message",
        "error_category",
        "request_id",
        "trace_id",
    }


def assert_openapi_matches_runtime_422_shapes() -> None:
    openapi = _app().openapi()
    expected_mapping = {
        "REQUEST_VALIDATION_ERROR": (
            "#/components/schemas/RequestValidationErrorResponse"
        ),
        "DOCUMENT_ACCESS_GRANT_INVALID": (
            "#/components/schemas/DocumentAccessGrantInvalidErrorResponse"
        ),
    }
    for method in ("get", "post"):
        schema = openapi["paths"]["/admin/document-access/grants"][method][
            "responses"
        ]["422"]["content"]["application/json"]["schema"]
        assert schema["discriminator"] == {
            "propertyName": "code",
            "mapping": expected_mapping,
        }
        assert schema["oneOf"] == [
            {"$ref": "#/components/schemas/RequestValidationErrorResponse"},
            {
                "$ref": (
                    "#/components/schemas/DocumentAccessGrantInvalidErrorResponse"
                )
            },
        ]

    revoke_schema = openapi["paths"][
        "/admin/document-access/grants/{grant_id}"
    ]["delete"]["responses"]["422"]["content"]["application/json"]["schema"]
    assert revoke_schema == {
        "$ref": "#/components/schemas/RequestValidationErrorResponse"
    }

    request_fields = set(
        openapi["components"]["schemas"]["RequestValidationFieldError"][
            "properties"
        ]["field"]["enum"]
    )
    assert {"target_account", "doc_id", "document_ids"} <= request_fields
    business_field = openapi["components"]["schemas"][
        "DocumentAccessGrantFieldError"
    ]["properties"]["field"]
    assert business_field["const"] == "document_ids"

    unrelated_schema = openapi["paths"]["/contract-probe"]["post"]["responses"][
        "422"
    ]["content"]["application/json"]["schema"]
    assert unrelated_schema == {"$ref": "#/components/schemas/HTTPValidationError"}


def assert_business_error_metadata_is_strictly_allowlisted() -> None:
    invalid_metadata = (
        {"field": "target_account", "field_code": "invalid"},
        {"field": "document_ids", "field_code": "too_long"},
        {"field_code": "invalid"},
    )
    for metadata in invalid_metadata:
        try:
            DocumentAccessGrantInvalidError("private-message", **metadata)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe business field metadata accepted: {metadata}")


def _field_names(response) -> set[str]:
    return {item["field"] for item in _field_errors(response)}


def _field_errors(response) -> list[dict[str, str]]:
    assert response.status_code == 422, response.text
    body = RequestValidationErrorResponse.model_validate(response.json())
    return [item.model_dump() for item in body.field_errors]


def _actor() -> CurrentUserContext:
    return CurrentUserContext(
        user_id="document-grant-contract-actor",
        username="document-grant-contract-actor",
        account_type=AccountType.ADMIN,
        is_authenticated=True,
        auth_source="jwt",
        primary_department_code="development",
        department_codes=["development"],
    )


def _client(service=None) -> TestClient:
    return TestClient(_app(service), raise_server_exceptions=False)


def _app(service=None) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/contract-probe")
    async def contract_probe(_request: ProbeRequest) -> None:
        return None

    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = _actor
    app.dependency_overrides[get_document_access_service] = lambda: (
        service if service is not None else AsyncMock()
    )
    return app


if __name__ == "__main__":
    main()
