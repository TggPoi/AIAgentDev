"""验证 Initial React User Administration Route 的安全 422 公共契约。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from fast_app.api.user_admin_routes import router
from fast_app.core.exception_handlers import register_exception_handlers
from fast_app.dependencies.user_admin_dependencies import (
    get_user_administration_service,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.auth_models import AccountType
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.error_schema import RequestValidationErrorResponse
from fast_app.schemas.user_admin_schema import (
    CreateManagedUserRequest,
    ManagedDepartmentAccessInput,
)
from fast_app.services.auth.user_administration_service import (
    UserAdministrationService,
)
from fast_app.services.exceptions import ManagedUserAccessInvalidError


REQUEST_VALIDATION_OPERATIONS = (
    ("/admin/access/catalog", "get"),
    ("/admin/users", "get"),
    ("/admin/users/{user_id}", "get"),
    ("/admin/users/{user_id}/status", "patch"),
    ("/admin/users/{user_id}/reset-password", "post"),
)
BUSINESS_VALIDATION_OPERATIONS = (
    ("/admin/users", "post"),
    ("/admin/users/{user_id}/access", "put"),
)


class ProbeRequest(BaseModel):
    value: str


class InvalidAccessService:
    """只在公共 Route seam 触发已分类业务错误，不模拟持久化。"""

    async def create_user(self, actor, request):
        raise ManagedUserAccessInvalidError(
            "must-not-appear-from-create-service",
            field="department_access",
            field_code="invalid",
        )

    async def replace_user_access(self, actor, user_id, request):
        raise ManagedUserAccessInvalidError(
            "must-not-appear-from-access-service",
            field="direct_permission_codes",
            field_code="invalid",
        )


def main() -> None:
    assert_request_validation_fields_are_safely_projected()
    assert_nested_and_form_level_projection_is_safe()
    assert_business_validation_is_discriminated_and_safe()
    asyncio.run(assert_service_branches_supply_stable_field_codes())
    assert_openapi_matches_both_runtime_422_shapes()
    print("user_administration_validation_contract=passed")


def assert_request_validation_fields_are_safely_projected() -> None:
    marker = "must-not-appear-in-user-admin-request-validation"
    list_cases = (
        (
            {"query": marker * 4},
            {"field": "query", "code": "too_long", "message": "输入长度过长"},
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
        for params, expected in list_cases:
            response = client.get("/admin/users", params=params)
            assert response.status_code == 422, response.text
            body = RequestValidationErrorResponse.model_validate(response.json())
            assert [item.model_dump() for item in body.field_errors] == [expected]
            assert marker not in response.text

        create = client.post("/admin/users", json={})
        invalid_optional_create = client.post(
            "/admin/users",
            json={
                **_valid_create_payload(),
                "email": marker * 6,
                "display_name": marker * 3,
                "direct_permission_codes": marker,
            },
        )
        access = client.put("/admin/users/target/access", json={})
        invalid_access_permissions = client.put(
            "/admin/users/target/access",
            json={
                "account_type": "employee",
                "department_access": _valid_create_payload()[
                    "department_access"
                ],
                "direct_permission_codes": marker,
            },
        )
        status = client.patch("/admin/users/target/status", json={})
        reset = client.post("/admin/users/target/reset-password", json={})

    assert _field_names(create) == {
        "username",
        "password",
        "account_type",
        "department_access",
    }
    assert _field_names(invalid_optional_create) == {
        "email",
        "display_name",
        "direct_permission_codes",
    }
    assert marker not in invalid_optional_create.text
    assert _field_names(access) == {"account_type", "department_access"}
    assert _field_names(invalid_access_permissions) == {
        "direct_permission_codes"
    }
    assert marker not in invalid_access_permissions.text
    assert _field_names(status) == {"status"}
    assert _field_names(reset) == {"new_password"}


def assert_nested_and_form_level_projection_is_safe() -> None:
    marker = "must-not-appear-in-user-admin-nested-validation"
    nested_payload = {
        "username": "contract-user",
        "password": "InitialPassword123!",
        "account_type": "employee",
        "department_access": [
            {
                "department_code": marker * 2,
                "is_primary": True,
                "role_codes": [],
            }
        ],
        "direct_permission_codes": [],
    }

    with _client() as client:
        nested = client.post("/admin/users", json=nested_payload)
        invalid_path = client.get("/admin/users/" + (marker * 2))
        malformed = client.post(
            "/admin/users",
            content="{",
            headers={"Content-Type": "application/json"},
        )
        unknown_status_field = client.patch(
            "/admin/users/target/status",
            json={"status": "active", "private_marker": marker},
        )
        unrelated = client.post("/contract-probe", json={})

    nested_body = RequestValidationErrorResponse.model_validate(nested.json())
    assert [item.model_dump() for item in nested_body.field_errors] == [
        {
            "field": "department_access",
            "code": "too_long",
            "message": "输入长度过长",
        }
    ]
    assert marker not in nested.text
    assert "department_code" not in nested.text

    for response in (invalid_path, malformed, unknown_status_field):
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


def assert_business_validation_is_discriminated_and_safe() -> None:
    create_payload = _valid_create_payload()
    access_payload = {
        "account_type": "employee",
        "department_access": create_payload["department_access"],
        "direct_permission_codes": [],
    }

    with _client() as client:
        create = client.post("/admin/users", json=create_payload)
        access = client.put("/admin/users/target/access", json=access_payload)

    expected_common = {
        "code": "MANAGED_USER_ACCESS_INVALID",
        "message": "账号访问设置不合法",
        "error_category": "user_error",
        "request_id": None,
        "trace_id": None,
    }
    assert create.status_code == 422, create.text
    assert create.json() == {
        **expected_common,
        "field_errors": [
            {
                "field": "department_access",
                "code": "invalid",
                "message": "输入值不合法",
            }
        ],
    }
    assert "must-not-appear-from-create-service" not in create.text

    assert access.status_code == 422, access.text
    assert access.json() == {
        **expected_common,
        "field_errors": [
            {
                "field": "direct_permission_codes",
                "code": "invalid",
                "message": "输入值不合法",
            }
        ],
    }
    assert "must-not-appear-from-access-service" not in access.text


async def assert_service_branches_supply_stable_field_codes() -> None:
    repository = AsyncMock()
    repository.get_departments_by_codes.side_effect = lambda codes: {
        code: object() for code in codes
    }
    repository.get_roles_by_codes.side_effect = lambda codes: {
        code: object() for code in codes
    }
    repository.get_permissions_by_codes.side_effect = lambda codes: {
        code: object() for code in codes
    }
    service = UserAdministrationService(
        repository=repository,
        permission_service=AsyncMock(),
    )
    actor = _actor()

    cases = (
        (
            CreateManagedUserRequest.model_validate(
                {**_valid_create_payload(), "username": "   "}
            ),
            "username",
        ),
        (
            CreateManagedUserRequest.model_validate(
                {
                    **_valid_create_payload(),
                    "department_access": [
                        *_valid_create_payload()["department_access"],
                        *_valid_create_payload()["department_access"],
                    ],
                }
            ),
            "department_access",
        ),
        (
            CreateManagedUserRequest(
                username="manager-contract-user",
                password="InitialPassword123!",
                account_type=AccountType.DEPARTMENT_MANAGER,
                department_access=[
                    ManagedDepartmentAccessInput(
                        department_code="development",
                        is_primary=True,
                    ),
                    ManagedDepartmentAccessInput(
                        department_code="art",
                        is_primary=False,
                    ),
                ],
            ),
            "account_type",
        ),
        (
            CreateManagedUserRequest.model_validate(
                {
                    **_valid_create_payload(),
                    "direct_permission_codes": [
                        "agent:tool:web_search",
                        "agent:tool:web_search",
                    ],
                }
            ),
            "direct_permission_codes",
        ),
    )

    for request, expected_field in cases:
        try:
            await service.create_user(actor, request)
        except ManagedUserAccessInvalidError as exc:
            assert exc.field == expected_field
            assert exc.field_code == "invalid"
        else:
            raise AssertionError(f"expected ManagedUserAccessInvalidError: {expected_field}")


def assert_openapi_matches_both_runtime_422_shapes() -> None:
    openapi = _app().openapi()
    for path, method in REQUEST_VALIDATION_OPERATIONS:
        schema = openapi["paths"][path][method]["responses"]["422"]["content"][
            "application/json"
        ]["schema"]
        assert schema == {
            "$ref": "#/components/schemas/RequestValidationErrorResponse"
        }

    expected_mapping = {
        "REQUEST_VALIDATION_ERROR": (
            "#/components/schemas/RequestValidationErrorResponse"
        ),
        "MANAGED_USER_ACCESS_INVALID": (
            "#/components/schemas/ManagedUserAccessInvalidErrorResponse"
        ),
    }
    for path, method in BUSINESS_VALIDATION_OPERATIONS:
        schema = openapi["paths"][path][method]["responses"]["422"]["content"][
            "application/json"
        ]["schema"]
        assert schema["discriminator"] == {
            "propertyName": "code",
            "mapping": expected_mapping,
        }
        assert schema["oneOf"] == [
            {"$ref": "#/components/schemas/RequestValidationErrorResponse"},
            {
                "$ref": (
                    "#/components/schemas/ManagedUserAccessInvalidErrorResponse"
                )
            },
        ]

    request_fields = set(
        openapi["components"]["schemas"]["RequestValidationFieldError"][
            "properties"
        ]["field"]["enum"]
    )
    assert {
        "username",
        "password",
        "email",
        "display_name",
        "account_type",
        "department_access",
        "direct_permission_codes",
    } <= request_fields
    business_fields = openapi["components"]["schemas"][
        "ManagedUserAccessFieldError"
    ]["properties"]["field"]["enum"]
    assert business_fields == [
        "username",
        "account_type",
        "department_access",
        "direct_permission_codes",
    ]

    unrelated_schema = openapi["paths"]["/contract-probe"]["post"]["responses"][
        "422"
    ]["content"]["application/json"]["schema"]
    assert unrelated_schema == {"$ref": "#/components/schemas/HTTPValidationError"}


def _field_names(response) -> set[str]:
    assert response.status_code == 422, response.text
    body = RequestValidationErrorResponse.model_validate(response.json())
    return {item.field for item in body.field_errors}


def _valid_create_payload() -> dict[str, object]:
    return {
        "username": "contract-user",
        "password": "InitialPassword123!",
        "account_type": "employee",
        "department_access": [
            {
                "department_code": "development",
                "is_primary": True,
                "role_codes": [],
            }
        ],
        "direct_permission_codes": [],
    }


def _actor() -> CurrentUserContext:
    return CurrentUserContext(
        user_id="user-admin-contract-actor",
        username="user-admin-contract-actor",
        account_type=AccountType.ADMIN,
        is_authenticated=True,
        auth_source="jwt",
        primary_department_code="development",
        department_codes=["development"],
    )


def _client() -> TestClient:
    return TestClient(_app(), raise_server_exceptions=False)


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/contract-probe")
    async def contract_probe(_request: ProbeRequest) -> None:
        return None

    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = _actor
    app.dependency_overrides[get_user_administration_service] = InvalidAccessService
    return app


if __name__ == "__main__":
    main()
