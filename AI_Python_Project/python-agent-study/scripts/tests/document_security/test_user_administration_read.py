"""通过用户管理模块 interface 验证目录裁剪、查询隔离和详情授权。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fast_app.core.config import get_settings
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.domain.agent_tool_permissions import (
    DepartmentPermissionScope,
    EffectivePermissionSet,
    PermissionCode,
    RoleCode,
)
from fast_app.domain.auth_models import AccountType
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.auth.user_administration_service import (
    UserAdministrationService,
)
from fast_app.services.auth.user_administration_repository import (
    UserAdministrationRepository,
)
from fast_app.services.exceptions import (
    AccessManagementPermissionDeniedError,
    UserListCursorInvalidError,
)


async def main() -> None:
    await assert_database_adapter()
    repository = _repository()
    permission_service = AsyncMock()
    permission_service.get_effective_permissions.side_effect = _effective_permissions
    service = UserAdministrationService(
        repository=repository,
        permission_service=permission_service,
    )

    manager = _actor(AccountType.DEPARTMENT_MANAGER, "development")
    manager_catalog = await service.get_access_catalog(manager)
    assert [item.code for item in manager_catalog.departments] == ["development"]
    assert [item.code for item in manager_catalog.account_types] == ["employee"]
    assert "agent:tool:mcp" not in {
        item.code for item in manager_catalog.direct_permissions
    }

    admin_catalog = await service.get_access_catalog(_actor(AccountType.ADMIN, None))
    assert {item.code for item in admin_catalog.account_types} == {
        "admin",
        "department_manager",
        "employee",
    }
    assert "agent:tool:mcp" in {
        item.code for item in admin_catalog.direct_permissions
    }

    page = await service.list_users(
        manager,
        cursor=None,
        limit=20,
        query=None,
        status=None,
        department_code=None,
    )
    assert [item.user_id for item in page.items] == ["employee-dev"]
    assert repository.list_users.await_args.kwargs["department_code"] == "development"
    assert repository.list_users.await_args.kwargs["employee_only"] is True

    try:
        await service.list_users(
            manager,
            cursor=None,
            limit=20,
            query=None,
            status=None,
            department_code="art",
        )
    except AccessManagementPermissionDeniedError:
        pass
    else:
        raise AssertionError("主管不应扩大部门查询范围")

    try:
        await service.list_users(
            manager,
            cursor="invalid",
            limit=20,
            query=None,
            status=None,
            department_code=None,
        )
    except UserListCursorInvalidError:
        pass
    else:
        raise AssertionError("非法 cursor 不应通过")

    detail = await service.get_user(manager, "employee-dev")
    assert detail.account_type == AccountType.EMPLOYEE
    assert detail.direct_permission_codes == ["agent:tool:web_search"]
    assert detail.department_access[0].department_code == "development"

    repository.get_user.return_value = _user("employee-art")
    repository.list_user_departments.return_value = [
        _department("employee-art", "art")
    ]
    try:
        await service.get_user(manager, "employee-art")
    except AccessManagementPermissionDeniedError:
        pass
    else:
        raise AssertionError("主管不应查看外部门员工")

    print("user_administration_read=passed")


async def assert_database_adapter() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            repository = UserAdministrationRepository(session)
            rows, _has_more = await repository.list_users(
                limit=2,
                query=None,
                status=None,
                department_code=None,
                cursor_updated_at=None,
                cursor_user_id=None,
                employee_only=False,
            )
            await repository.list_departments()
            if rows:
                await repository.list_user_departments(rows[0].id)
                await repository.list_department_role_codes(rows[0].id)
                await repository.list_direct_permission_codes(rows[0].id)
    finally:
        await engine.dispose()


def _repository() -> AsyncMock:
    repository = AsyncMock()
    repository.list_departments.side_effect = lambda codes=None: [
        SimpleNamespace(code=code, name=code, description=None)
        for code in (["art", "development"] if codes is None else sorted(codes))
    ]
    permission_rows = {
        code: SimpleNamespace(
            code=code,
            name=code,
            description=None,
            risk_level="medium",
        )
        for code in (
            "agent:tool:calculator",
            "agent:tool:web_search",
            "agent:tool:mcp",
            "data:query:execute",
        )
    }
    repository.list_permissions.side_effect = lambda codes: [
        permission_rows[code] for code in sorted(codes)
    ]
    repository.list_roles.return_value = [
        SimpleNamespace(code="department_reader", name="reader", description=None)
    ]
    repository.list_users.return_value = ([_user("employee-dev")], False)
    repository.get_user.return_value = _user("employee-dev")
    repository.list_user_departments.return_value = [
        _department("employee-dev", "development")
    ]
    repository.list_department_role_codes.return_value = {
        "development": ["department_reader"]
    }
    repository.list_direct_permission_codes.return_value = [
        "agent:tool:web_search"
    ]
    return repository


def _effective_permissions(user_id: str) -> EffectivePermissionSet:
    department = "art" if user_id.endswith("art") else "development"
    return EffectivePermissionSet(
        user_id=user_id,
        department_scopes=[
            DepartmentPermissionScope(
                department_code=department,
                role_codes=[RoleCode.DEPARTMENT_READER.value],
                permission_codes={PermissionCode.KNOWLEDGE_DOCUMENT_READ},
            )
        ],
    )


def _actor(account_type: AccountType, department: str | None) -> CurrentUserContext:
    return CurrentUserContext(
        user_id=f"actor-{account_type.value}",
        username=f"actor-{account_type.value}",
        account_type=account_type,
        is_authenticated=True,
        auth_source="jwt",
        primary_department_code=department,
        department_codes=[department] if department else [],
    )


def _user(user_id: str) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=user_id,
        username=user_id,
        email=f"{user_id}@example.com",
        display_name=user_id,
        status="active",
        created_at=now,
        updated_at=now,
        last_login_at=None,
    )


def _department(user_id: str, code: str) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        department_code=code,
        is_primary=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
