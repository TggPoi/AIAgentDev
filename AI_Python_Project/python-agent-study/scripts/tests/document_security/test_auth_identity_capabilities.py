"""验证三类账号身份推导、/auth/me 与 /auth/capabilities 契约。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fast_app.api.auth_routes import router
from fast_app.core.exception_handlers import register_exception_handlers
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.agent_tool_permissions import (
    DepartmentPermissionScope,
    EffectivePermissionSet,
    PermissionCode,
    RoleCode,
)
from fast_app.domain.auth_models import AccountType
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.auth_schema import CurrentUserResponse, UserCapabilitiesResponse
from fast_app.services.auth.capability_service import (
    resolve_account_type,
    resolve_auth_capabilities,
)


def main() -> None:
    assert_account_type_policy()
    assert_capability_policy()
    assert_http_contract()
    assert_schema_descriptions()
    print("auth_identity_capabilities=passed")


def assert_account_type_policy() -> None:
    admin = EffectivePermissionSet(
        user_id="admin",
        global_role_codes=[RoleCode.SYSTEM_ADMIN.value],
    )
    assert resolve_account_type(
        admin,
        primary_department_code=None,
    ) == AccountType.ADMIN

    manager = EffectivePermissionSet(
        user_id="manager",
        department_scopes=[
            DepartmentPermissionScope(
                department_code="development",
                role_codes=[RoleCode.DEPARTMENT_MANAGER.value],
                permission_codes={PermissionCode.KNOWLEDGE_DOCUMENT_READ},
            )
        ],
    )
    assert resolve_account_type(
        manager,
        primary_department_code="development",
    ) == AccountType.DEPARTMENT_MANAGER
    assert resolve_account_type(
        manager,
        primary_department_code="art",
    ) == AccountType.EMPLOYEE


def assert_capability_policy() -> None:
    manager = _manager_context()
    snapshot = resolve_auth_capabilities(manager)
    assert snapshot.can_manage_users is True
    assert snapshot.user_management_scope.value == "own_department"
    assert snapshot.can_manage_document_grants is True
    assert snapshot.can_use_web_search is True
    assert snapshot.can_use_nl2sql is False
    assert snapshot.can_read_documents is True
    assert snapshot.can_manage_documents is True

    employee = CurrentUserContext(
        user_id="employee",
        username="employee",
        account_type=AccountType.EMPLOYEE,
        is_authenticated=True,
        auth_source="jwt",
        department_codes=["development"],
        primary_department_code="development",
        department_permission_codes={
            "development": [PermissionCode.KNOWLEDGE_DOCUMENT_READ.value]
        },
    )
    employee_snapshot = resolve_auth_capabilities(employee)
    assert employee_snapshot.can_manage_users is False
    assert employee_snapshot.user_management_scope.value == "none"
    assert employee_snapshot.can_manage_document_grants is False
    assert employee_snapshot.can_read_documents is True
    assert employee_snapshot.can_manage_documents is False


def assert_http_contract() -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = _manager_context
    client = TestClient(app, raise_server_exceptions=False)

    me_response = client.get("/auth/me")
    assert me_response.status_code == 200, me_response.text
    me = me_response.json()
    assert me["username"] == "manager"
    assert me["account_type"] == "department_manager"
    assert me["department_permission_codes"]["development"] == [
        PermissionCode.KNOWLEDGE_DOCUMENT_CREATE.value,
        PermissionCode.KNOWLEDGE_DOCUMENT_READ.value,
    ]

    capability_response = client.get("/auth/capabilities")
    assert capability_response.status_code == 200, capability_response.text
    capabilities = capability_response.json()
    assert capabilities["can_manage_users"] is True
    assert capabilities["user_management_scope"] == "own_department"
    assert capabilities["can_manage_document_grants"] is True

    app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(
        user_id="anonymous",
        auth_source="anonymous",
    )
    denied_response = client.get("/auth/me")
    assert denied_response.status_code == 401, denied_response.text
    assert denied_response.json()["code"] == "AUTHENTICATION_FAILED"


def assert_schema_descriptions() -> None:
    for model in (CurrentUserResponse, UserCapabilitiesResponse):
        properties = model.model_json_schema()["properties"]
        missing = [
            field_name
            for field_name, field_schema in properties.items()
            if not field_schema.get("description")
        ]
        assert not missing, f"{model.__name__} 缺少字段说明: {missing}"


def _manager_context() -> CurrentUserContext:
    return CurrentUserContext(
        user_id="manager",
        username="manager",
        account_type=AccountType.DEPARTMENT_MANAGER,
        is_authenticated=True,
        auth_source="jwt",
        global_permission_codes=[PermissionCode.AGENT_TOOL_WEB_SEARCH.value],
        department_permission_codes={
            "development": [
                PermissionCode.KNOWLEDGE_DOCUMENT_CREATE.value,
                PermissionCode.KNOWLEDGE_DOCUMENT_READ.value,
            ]
        },
        department_codes=["development"],
        primary_department_code="development",
    )


if __name__ == "__main__":
    main()
