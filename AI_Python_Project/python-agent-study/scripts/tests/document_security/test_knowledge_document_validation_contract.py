"""验证 Initial React Knowledge Documents Route 的安全 422 契约。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from fast_app.api.knowledge_document_routes import router
from fast_app.core.exception_handlers import register_exception_handlers
from fast_app.dependencies.knowledge_document_dependencies import (
    get_knowledge_document_read_service,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.error_schema import RequestValidationErrorResponse


DOCUMENT_VALIDATION_OPERATIONS = (
    ("/knowledge/documents", "get"),
    ("/knowledge/documents/{doc_id}", "get"),
    ("/knowledge/documents/{doc_id}/content", "get"),
    ("/knowledge/documents/{doc_id}/download", "get"),
)


class ProbeRequest(BaseModel):
    value: str


def main() -> None:
    assert_list_query_fields_are_safely_projected()
    assert_path_and_unrelated_errors_remain_form_level()
    assert_openapi_uses_safe_validation_model()
    print("knowledge_document_validation_contract=passed")


def assert_list_query_fields_are_safely_projected() -> None:
    marker = "must-not-appear-in-knowledge-document-validation"
    cases = (
        (
            {"query": marker * 8},
            {"field": "query", "code": "too_long", "message": "输入长度过长"},
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
            {"document_type": marker},
            {
                "field": "document_type",
                "code": "invalid",
                "message": "输入值不合法",
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
        for params, expected in cases:
            response = client.get("/knowledge/documents", params=params)
            assert response.status_code == 422, response.text
            body = RequestValidationErrorResponse.model_validate(response.json())
            assert [item.model_dump() for item in body.field_errors] == [expected]
            assert marker not in response.text


def assert_path_and_unrelated_errors_remain_form_level() -> None:
    marker = "must-not-appear-in-knowledge-document-form-validation"
    invalid_doc_id = marker * 2

    with _client() as client:
        responses = (
            client.get(f"/knowledge/documents/{invalid_doc_id}"),
            client.get(f"/knowledge/documents/{invalid_doc_id}/content"),
            client.get(f"/knowledge/documents/{invalid_doc_id}/download"),
        )
        unrelated = client.post("/contract-probe", json={})

    for response in responses:
        assert response.status_code == 422, response.text
        body = RequestValidationErrorResponse.model_validate(response.json())
        assert body.field_errors == []
        assert marker not in response.text

    assert unrelated.status_code == 422, unrelated.text
    assert set(unrelated.json()) == {
        "code",
        "message",
        "error_category",
        "request_id",
        "trace_id",
    }


def assert_openapi_uses_safe_validation_model() -> None:
    openapi = _app().openapi()
    for path, method in DOCUMENT_VALIDATION_OPERATIONS:
        response_schema = openapi["paths"][path][method]["responses"]["422"][
            "content"
        ]["application/json"]["schema"]
        assert response_schema == {
            "$ref": "#/components/schemas/RequestValidationErrorResponse"
        }

    fields = openapi["components"]["schemas"]["RequestValidationFieldError"][
        "properties"
    ]["field"]["enum"]
    assert {"query", "department_code", "document_type", "limit"}.issubset(fields)


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
        user_id="knowledge-document-contract-user",
        username="knowledge-document-contract-user",
        is_authenticated=True,
        auth_source="jwt",
    )
    app.dependency_overrides[get_knowledge_document_read_service] = lambda: object()
    return app


if __name__ == "__main__":
    main()
