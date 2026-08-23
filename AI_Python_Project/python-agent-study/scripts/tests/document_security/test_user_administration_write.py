"""验证四个用户管理写接口的事务、范围、凭证失效和 HTTP 契约。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.api.user_admin_routes import router
from fast_app.core.config import get_settings
from fast_app.core.exception_handlers import register_exception_handlers
from fast_app.core.request_context import reset_request_context, set_request_context
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.dependencies.user_admin_dependencies import (
    get_user_administration_service,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.auth_models import AccountType, UserStatus
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.user_admin_schema import (
    CreateManagedUserRequest,
    ManagedDepartmentAccessInput,
    ManagedUserDetail,
    ManagedUserPasswordResetResponse,
    ManagedUserStatusResponse,
    ReplaceManagedUserAccessRequest,
    ResetManagedUserPasswordRequest,
    UpdateManagedUserStatusRequest,
)
from fast_app.services.auth.auth_crypto import hash_password, verify_password
from fast_app.services.auth.permission_repository import PermissionRepository
from fast_app.services.auth.permission_service import PermissionService
from fast_app.services.auth.user_administration_repository import (
    UserAdministrationRepository,
)
from fast_app.services.auth.user_administration_service import (
    UserAdministrationService,
)
from fast_app.services.exceptions import (
    AccessManagementPermissionDeniedError,
    LastSystemAdminProtectedError,
    ManagedUserConflictError,
    ManagedUserSelfOperationError,
)


ADMIN_ID = "user_admin_write_actor"
MANAGER_ID = "user_admin_write_manager"
EMPLOYEE_ID_PREFIX = "user_"
TEST_USERNAMES = (
    "admin_write_actor",
    "admin_write_manager",
    "admin_write_employee",
    "admin_write_department_manager",
    "admin_write_second_admin",
    "admin_write_rollback",
)
INITIAL_PASSWORD = "InitialPassword123!"
RESET_PASSWORD = "ResetPassword456!"


def main() -> None:
    asyncio.run(assert_database_flow())
    assert_http_contract()
    print("user_administration_write=passed")


async def assert_database_flow() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await _cleanup(session)
            await _seed_actors(session)
            repository = UserAdministrationRepository(session)
            service = UserAdministrationService(
                repository=repository,
                permission_service=PermissionService(PermissionRepository(session)),
            )
            admin = _actor(ADMIN_ID, AccountType.ADMIN, "development")
            manager = _actor(
                MANAGER_ID,
                AccountType.DEPARTMENT_MANAGER,
                "development",
            )

            context_tokens = set_request_context("request-user-admin-write")
            try:
                created = await service.create_user(
                    manager,
                    _create_request(
                        username="admin_write_employee",
                        department="development",
                        direct_permissions=["agent:tool:web_search"],
                    ),
                )
            finally:
                reset_request_context(*context_tokens)
            assert created.account_type == AccountType.EMPLOYEE
            assert next(
                item.department_code
                for item in created.department_access
                if item.is_primary
            ) == "development"
            assert created.direct_permission_codes == ["agent:tool:web_search"]
            employee_id = created.user_id
            assert employee_id.startswith(EMPLOYEE_ID_PREFIX)

            created_manager = await service.create_user(
                admin,
                _create_request(
                    username="admin_write_department_manager",
                    department="art",
                    account_type=AccountType.DEPARTMENT_MANAGER,
                    role_codes=[],
                ),
            )
            assert created_manager.account_type == AccountType.DEPARTMENT_MANAGER
            assert created_manager.department_access[0].role_codes == [
                "department_manager"
            ]
            created_admin = await service.create_user(
                admin,
                _create_request(
                    username="admin_write_second_admin",
                    department="development",
                    account_type=AccountType.ADMIN,
                    role_codes=[],
                ),
            )
            assert created_admin.account_type == AccountType.ADMIN
            try:
                await service.reset_user_password(
                    manager,
                    created_manager.user_id,
                    ResetManagedUserPasswordRequest(
                        new_password=RESET_PASSWORD
                    ),
                )
            except AccessManagementPermissionDeniedError:
                pass
            else:
                raise AssertionError("部门主管不应重置其他主管密码")

            try:
                await service.create_user(
                    manager,
                    _create_request(
                        username="admin_write_manager_escalation",
                        department="development",
                        account_type=AccountType.ADMIN,
                        role_codes=[],
                    ),
                )
            except AccessManagementPermissionDeniedError:
                pass
            else:
                raise AssertionError("部门主管不应创建管理员")

            try:
                await service.create_user(
                    manager,
                    _create_request(
                        username="admin_write_other_department",
                        department="art",
                    ),
                )
            except AccessManagementPermissionDeniedError:
                pass
            else:
                raise AssertionError("部门主管不应创建其他部门账号")

            try:
                await service.create_user(
                    admin,
                    _create_request(
                        username="admin_write_employee",
                        department="development",
                        email="rollback@example.com",
                    ),
                )
            except ManagedUserConflictError as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("重复用户名必须返回稳定冲突")
            assert int(
                await session.scalar(
                    text("select count(*) from users where email = 'rollback@example.com'")
                )
                or 0
            ) == 0

            original_replace = repository.replace_department_access
            repository.replace_department_access = AsyncMock(  # type: ignore[method-assign]
                side_effect=RuntimeError("forced access failure")
            )
            try:
                await service.create_user(
                    admin,
                    _create_request(
                        username="admin_write_rollback",
                        department="development",
                    ),
                )
            except RuntimeError:
                pass
            else:
                raise AssertionError("后续授权失败必须向上抛出")
            finally:
                repository.replace_department_access = original_replace  # type: ignore[method-assign]
            assert int(
                await session.scalar(
                    text(
                        "select count(*) from users "
                        "where username = 'admin_write_rollback'"
                    )
                )
                or 0
            ) == 0

            replaced = await service.replace_user_access(
                admin,
                employee_id,
                ReplaceManagedUserAccessRequest(
                    account_type=AccountType.EMPLOYEE,
                    department_access=[
                        ManagedDepartmentAccessInput(
                            department_code="art",
                            is_primary=True,
                            role_codes=["department_editor"],
                        ),
                        ManagedDepartmentAccessInput(
                            department_code="development",
                            is_primary=False,
                            role_codes=["department_reader"],
                        ),
                    ],
                    direct_permission_codes=["agent:tool:mcp"],
                ),
            )
            assert next(
                item.department_code
                for item in replaced.department_access
                if item.is_primary
            ) == "art"
            assert {item.department_code for item in replaced.department_access} == {
                "art",
                "development",
            }
            assert replaced.direct_permission_codes == ["agent:tool:mcp"]

            await _seed_credentials(session, employee_id, suffix="status")
            disabled = await service.update_user_status(
                admin,
                employee_id,
                UpdateManagedUserStatusRequest(status=UserStatus.DISABLED),
            )
            assert disabled.user.status == UserStatus.DISABLED
            assert disabled.revoked_refresh_token_count == 1
            assert disabled.revoked_api_key_count == 1
            enabled = await service.update_user_status(
                admin,
                employee_id,
                UpdateManagedUserStatusRequest(status=UserStatus.ACTIVE),
            )
            assert enabled.user.status == UserStatus.ACTIVE
            assert enabled.revoked_refresh_token_count == 0
            assert enabled.revoked_api_key_count == 0
            assert await _credential_statuses(session, employee_id, "status") == {
                "api": "revoked",
                "refresh": "revoked",
            }

            await _seed_credentials(session, employee_id, suffix="password")
            reset = await service.reset_user_password(
                admin,
                employee_id,
                ResetManagedUserPasswordRequest(new_password=RESET_PASSWORD),
            )
            assert reset.password_reset is True
            assert reset.revoked_refresh_token_count == 1
            assert reset.revoked_api_key_count == 1
            password_hash = await session.scalar(
                text("select password_hash from users where id = :user_id"),
                {"user_id": employee_id},
            )
            assert isinstance(password_hash, str)
            assert verify_password(RESET_PASSWORD, password_hash)
            assert not verify_password(INITIAL_PASSWORD, password_hash)

            audits = (
                await session.execute(
                    text(
                        "select action, request_id, details_json::text "
                        "from user_administration_audits "
                        "where target_user_id = :user_id order by created_at, id"
                    ),
                    {"user_id": employee_id},
                )
            ).all()
            assert {row.action for row in audits} == {
                "create_user",
                "replace_access",
                "update_status",
                "reset_password",
            }
            create_audit = next(row for row in audits if row.action == "create_user")
            assert create_audit.request_id == "request-user-admin-write"
            assert all(INITIAL_PASSWORD not in row[2] for row in audits)
            assert all(RESET_PASSWORD not in row[2] for row in audits)
            await _assert_self_protection(service, admin)
            await _assert_last_admin_protection()
    finally:
        async with session_factory() as cleanup_session:
            await _cleanup(cleanup_session)
        await engine.dispose()


async def _seed_actors(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into users (id, username, password_hash, status)
            values
                (:admin_id, 'admin_write_actor', :password_hash, 'active'),
                (:manager_id, 'admin_write_manager', :password_hash, 'active')
            """
        ),
        {
            "admin_id": ADMIN_ID,
            "manager_id": MANAGER_ID,
            "password_hash": hash_password(INITIAL_PASSWORD),
        },
    )
    await session.execute(
        text(
            """
            insert into user_roles (id, user_id, role_id)
            select 'user_role_admin_write_actor', :admin_id, id
            from roles where code = 'system_admin'
            """
        ),
        {"admin_id": ADMIN_ID},
    )
    await session.execute(
        text(
            """
            insert into user_departments (id, user_id, department_code, is_primary)
            values ('user_dept_admin_write_manager', :manager_id, 'development', true)
            """
        ),
        {"manager_id": MANAGER_ID},
    )
    await session.execute(
        text(
            """
            insert into user_department_roles (id, user_id, department_code, role_id)
            select
                'user_dept_role_admin_write_manager',
                :manager_id,
                'development',
                id
            from roles where code = 'department_manager'
            """
        ),
        {"manager_id": MANAGER_ID},
    )
    await session.commit()


async def _seed_credentials(
    session: AsyncSession,
    user_id: str,
    *,
    suffix: str,
) -> None:
    await session.execute(
        text(
            """
            insert into refresh_tokens
                (id, user_id, token_hash, status, expires_at, metadata_json)
            values
                (:refresh_id, :user_id, :token_hash, 'active', now() + interval '1 day', '{}'::jsonb)
            """
        ),
        {
            "refresh_id": f"refresh_admin_write_{suffix}",
            "user_id": user_id,
            "token_hash": f"refresh_hash_admin_write_{suffix}",
        },
    )
    await session.execute(
        text(
            """
            insert into api_keys
                (id, user_id, name, key_prefix, key_fingerprint, key_hash, status)
            values
                (:api_id, :user_id, :name, :prefix, :fingerprint, :key_hash, 'active')
            """
        ),
        {
            "api_id": f"api_admin_write_{suffix}",
            "user_id": user_id,
            "name": suffix,
            "prefix": f"prefix_{suffix}",
            "fingerprint": f"fingerprint_admin_write_{suffix}",
            "key_hash": f"key_hash_admin_write_{suffix}",
        },
    )
    await session.commit()


async def _credential_statuses(
    session: AsyncSession,
    user_id: str,
    suffix: str,
) -> dict[str, str]:
    refresh_status = await session.scalar(
        text(
            "select status from refresh_tokens "
            "where user_id = :user_id and id = :credential_id"
        ),
        {"user_id": user_id, "credential_id": f"refresh_admin_write_{suffix}"},
    )
    api_status = await session.scalar(
        text(
            "select status from api_keys "
            "where user_id = :user_id and id = :credential_id"
        ),
        {"user_id": user_id, "credential_id": f"api_admin_write_{suffix}"},
    )
    return {"refresh": str(refresh_status), "api": str(api_status)}


async def _cleanup(session: AsyncSession) -> None:
    user_ids = (
        await session.execute(
            text(
                "select id from users where id = any(:actor_ids) "
                "or username = any(:usernames) "
                "or username like 'admin_write_%'"
            ),
            {
                "actor_ids": [ADMIN_ID, MANAGER_ID],
                "usernames": list(TEST_USERNAMES),
            },
        )
    ).scalars().all()
    if user_ids:
        await session.execute(
            text(
                "delete from user_administration_audits "
                "where actor_user_id = any(:user_ids) or target_user_id = any(:user_ids)"
            ),
            {"user_ids": list(user_ids)},
        )
        await session.execute(
            text(
                "delete from user_permission_grants "
                "where user_id = any(:user_ids) "
                "or granted_by_user_id = any(:user_ids) "
                "or revoked_by_user_id = any(:user_ids)"
            ),
            {"user_ids": list(user_ids)},
        )
        await session.execute(
            text(
                "delete from document_access_grants "
                "where grantee_user_id = any(:user_ids) "
                "or granted_by_user_id = any(:user_ids) "
                "or revoked_by_user_id = any(:user_ids)"
            ),
            {"user_ids": list(user_ids)},
        )
        await session.execute(
            text("delete from users where id = any(:user_ids)"),
            {"user_ids": list(user_ids)},
        )
    await session.commit()


async def _assert_self_protection(
    service: UserAdministrationService,
    admin: CurrentUserContext,
) -> None:
    operations = (
        service.replace_user_access(
            admin,
            admin.user_id,
            ReplaceManagedUserAccessRequest(
                account_type=AccountType.ADMIN,
                department_access=[
                    ManagedDepartmentAccessInput(
                        department_code="development",
                        is_primary=True,
                    )
                ],
            ),
        ),
        service.update_user_status(
            admin,
            admin.user_id,
            UpdateManagedUserStatusRequest(status=UserStatus.DISABLED),
        ),
        service.reset_user_password(
            admin,
            admin.user_id,
            ResetManagedUserPasswordRequest(new_password=RESET_PASSWORD),
        ),
    )
    for operation in operations:
        try:
            await operation
        except ManagedUserSelfOperationError:
            pass
        else:
            raise AssertionError("高风险用户管理写操作不应以当前 actor 自身为目标")


async def _assert_last_admin_protection() -> None:
    now = datetime.now(UTC)
    detail = ManagedUserDetail.model_validate(
        {
            "user_id": "last-admin",
            "username": "last-admin",
            "email": None,
            "display_name": None,
            "status": "active",
            "account_type": "admin",
            "global_role_codes": ["system_admin"],
            "direct_permission_codes": [],
            "effective_global_permission_codes": [],
            "department_access": [
                {
                    "department_code": "development",
                    "is_primary": True,
                    "role_codes": [],
                    "permission_codes": [],
                }
            ],
            "created_at": now,
            "updated_at": now,
            "last_login_at": None,
        }
    )
    repository = AsyncMock()
    repository.get_user_for_update.return_value = SimpleNamespace(id="last-admin")
    repository.lock_system_admin_role.return_value = SimpleNamespace(
        id="role_system_admin"
    )
    repository.count_active_system_admins.return_value = 1
    repository.get_departments_by_codes.return_value = {
        "development": SimpleNamespace(code="development")
    }
    repository.get_roles_by_codes.return_value = {
        "department_reader": SimpleNamespace(
            id="role_department_reader",
            code="department_reader",
        )
    }
    repository.get_permissions_by_codes.return_value = {}
    service = UserAdministrationService(
        repository=repository,
        permission_service=AsyncMock(),
    )
    service.get_user = AsyncMock(return_value=detail)  # type: ignore[method-assign]
    actor = _actor("other-admin", AccountType.ADMIN, "development")

    try:
        await service.update_user_status(
            actor,
            "last-admin",
            UpdateManagedUserStatusRequest(status=UserStatus.DISABLED),
        )
    except LastSystemAdminProtectedError:
        pass
    else:
        raise AssertionError("最后一个 active 管理员不应被禁用")

    try:
        await service.replace_user_access(
            actor,
            "last-admin",
            ReplaceManagedUserAccessRequest(
                account_type=AccountType.EMPLOYEE,
                department_access=[
                    ManagedDepartmentAccessInput(
                        department_code="development",
                        is_primary=True,
                        role_codes=["department_reader"],
                    )
                ],
            ),
        )
    except LastSystemAdminProtectedError:
        pass
    else:
        raise AssertionError("最后一个 active 管理员不应被降级")


def _create_request(
    *,
    username: str,
    department: str,
    email: str | None = None,
    direct_permissions: list[str] | None = None,
    account_type: AccountType = AccountType.EMPLOYEE,
    role_codes: list[str] | None = None,
) -> CreateManagedUserRequest:
    return CreateManagedUserRequest(
        username=username,
        password=INITIAL_PASSWORD,
        email=email,
        display_name="Write Test",
        account_type=account_type,
        department_access=[
            ManagedDepartmentAccessInput(
                department_code=department,
                is_primary=True,
                role_codes=(
                    ["department_reader"]
                    if role_codes is None
                    else role_codes
                ),
            )
        ],
        direct_permission_codes=direct_permissions or [],
    )


def _actor(
    user_id: str,
    account_type: AccountType,
    department: str | None,
) -> CurrentUserContext:
    return CurrentUserContext(
        user_id=user_id,
        username=user_id,
        account_type=account_type,
        is_authenticated=True,
        auth_source="jwt",
        primary_department_code=department,
        department_codes=[department] if department else [],
    )


def assert_http_contract() -> None:
    actor = _actor(ADMIN_ID, AccountType.ADMIN, "development")
    detail = ManagedUserDetail.model_validate(
        {
            "user_id": "http-target",
            "username": "http-target",
            "email": None,
            "display_name": None,
            "status": "active",
            "account_type": "employee",
            "global_role_codes": [],
            "direct_permission_codes": [],
            "effective_global_permission_codes": [],
            "department_access": [],
            "created_at": "2026-08-24T00:00:00Z",
            "updated_at": "2026-08-24T00:00:00Z",
            "last_login_at": None,
        }
    )
    fake_service = AsyncMock()
    fake_service.create_user.return_value = detail
    fake_service.replace_user_access.return_value = detail
    fake_service.update_user_status.return_value = ManagedUserStatusResponse(
        user=detail,
        revoked_refresh_token_count=1,
        revoked_api_key_count=1,
    )
    fake_service.reset_user_password.return_value = ManagedUserPasswordResetResponse(
        password_reset=True,
        revoked_refresh_token_count=1,
        revoked_api_key_count=1,
    )

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: actor
    app.dependency_overrides[get_user_administration_service] = lambda: fake_service
    client = TestClient(app, raise_server_exceptions=False)

    create_response = client.post(
        "/admin/users",
        json=_create_request(
            username="http-target",
            department="development",
        ).model_dump(mode="json"),
    )
    assert create_response.status_code == 201, create_response.text
    access_response = client.put(
        "/admin/users/http-target/access",
        json={
            "account_type": "employee",
            "department_access": [
                {
                    "department_code": "development",
                    "is_primary": True,
                    "role_codes": ["department_reader"],
                }
            ],
            "direct_permission_codes": [],
        },
    )
    assert access_response.status_code == 200, access_response.text
    status_response = client.patch(
        "/admin/users/http-target/status",
        json={"status": "disabled"},
    )
    assert status_response.status_code == 200, status_response.text
    reset_response = client.post(
        "/admin/users/http-target/reset-password",
        json={"new_password": RESET_PASSWORD},
    )
    assert reset_response.status_code == 200, reset_response.text

    invalid_extra = client.patch(
        "/admin/users/http-target/status",
        json={"status": "active", "is_admin": True},
    )
    assert invalid_extra.status_code == 422, invalid_extra.text
    paths = app.openapi()["paths"]
    assert "/admin/users" in paths
    assert "/admin/users/{user_id}/access" in paths
    assert "/admin/users/{user_id}/status" in paths
    assert "/admin/users/{user_id}/reset-password" in paths


if __name__ == "__main__":
    main()
