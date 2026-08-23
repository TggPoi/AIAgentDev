"""验证服务端注销和修改密码的凭证失效边界。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.api.auth_routes import router
from fast_app.core.config import get_settings
from fast_app.core.exception_handlers import register_exception_handlers
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.dependencies.rag_dependencies import get_auth_service
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.auth_models import AccountType
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.auth.auth_crypto import hash_password
from fast_app.services.auth.auth_service import AuthService
from fast_app.services.auth.permission_repository import PermissionRepository
from fast_app.services.auth.permission_service import PermissionService
from fast_app.services.auth.user_repository import UserRepository
from fast_app.services.exceptions import (
    AuthenticationError,
    CurrentPasswordInvalidError,
    PasswordPolicyError,
)


TEST_USER_ID = "user_auth_session_security"
TEST_OTHER_USER_ID = "user_auth_session_security_other"
OLD_PASSWORD = "OldPassword123!"
NEW_PASSWORD = "NewPassword456!"


def main() -> None:
    asyncio.run(assert_database_flow())
    assert_http_contract()
    print("auth_session_security=passed")


async def assert_database_flow() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await _cleanup_users(session)
            await session.execute(
                text(
                    """
                    insert into users (id, username, password_hash, status)
                    values
                        (:user_id, 'auth_session_security', :password_hash, 'active'),
                        (:other_user_id, 'auth_session_security_other', :password_hash, 'active')
                    """
                ),
                {
                    "user_id": TEST_USER_ID,
                    "other_user_id": TEST_OTHER_USER_ID,
                    "password_hash": hash_password(OLD_PASSWORD),
                },
            )
            await session.commit()

            repository = UserRepository(session)
            auth_service = AuthService(
                settings=settings,
                repository=repository,
                permission_service=PermissionService(PermissionRepository(session)),
            )

            first_pair = await auth_service.login(
                "auth_session_security",
                OLD_PASSWORD,
            )
            current_user = await auth_service.authenticate_jwt(first_pair.access_token)
            assert current_user is not None
            assert await auth_service.logout(
                current_user=current_user,
                refresh_token=first_pair.refresh_token,
            )
            assert await auth_service.logout(
                current_user=current_user,
                refresh_token=first_pair.refresh_token,
            )
            await _assert_authentication_error(
                auth_service.refresh(first_pair.refresh_token)
            )

            other_pair = await auth_service.login(
                "auth_session_security_other",
                OLD_PASSWORD,
            )
            await _assert_authentication_error(
                auth_service.logout(
                    current_user=current_user,
                    refresh_token=other_pair.refresh_token,
                )
            )

            second_pair = await auth_service.login(
                "auth_session_security",
                OLD_PASSWORD,
            )
            third_pair = await auth_service.login(
                "auth_session_security",
                OLD_PASSWORD,
            )
            current_user = await auth_service.authenticate_jwt(second_pair.access_token)
            assert current_user is not None

            try:
                await auth_service.change_password(
                    current_user=current_user,
                    current_password="WrongPassword123!",
                    new_password=NEW_PASSWORD,
                )
            except CurrentPasswordInvalidError as exc:
                assert exc.error_code == "AUTH_CURRENT_PASSWORD_INVALID"
            else:
                raise AssertionError("错误当前密码不应通过")

            for invalid_password in (OLD_PASSWORD, "weak-password"):
                try:
                    await auth_service.change_password(
                        current_user=current_user,
                        current_password=OLD_PASSWORD,
                        new_password=invalid_password,
                    )
                except PasswordPolicyError as exc:
                    assert exc.error_code == "AUTH_PASSWORD_POLICY_FAILED"
                else:
                    raise AssertionError("相同或弱密码不应通过")

            revoked_count = await auth_service.change_password(
                current_user=current_user,
                current_password=OLD_PASSWORD,
                new_password=NEW_PASSWORD,
            )
            assert revoked_count == 2
            await _assert_authentication_error(
                auth_service.refresh(second_pair.refresh_token)
            )
            await _assert_authentication_error(
                auth_service.refresh(third_pair.refresh_token)
            )
            await _assert_authentication_error(
                auth_service.login("auth_session_security", OLD_PASSWORD)
            )
            new_pair = await auth_service.login(
                "auth_session_security",
                NEW_PASSWORD,
            )
            assert new_pair.access_token
    finally:
        async with session_factory() as cleanup_session:
            await _cleanup_users(cleanup_session)
        await engine.dispose()


async def _assert_authentication_error(awaitable: Awaitable[object]) -> None:
    try:
        await awaitable
    except AuthenticationError:
        return
    raise AssertionError("预期 AuthenticationError")


async def _cleanup_users(session: AsyncSession) -> None:
    await session.execute(
        text("delete from users where id = any(:user_ids)"),
        {"user_ids": [TEST_USER_ID, TEST_OTHER_USER_ID]},
    )
    await session.commit()


def assert_http_contract() -> None:
    current_user = CurrentUserContext(
        user_id="http-user",
        username="http-user",
        account_type=AccountType.EMPLOYEE,
        is_authenticated=True,
        auth_source="jwt",
    )
    fake_auth_service = AsyncMock()
    fake_auth_service.logout.return_value = True
    fake_auth_service.change_password.return_value = 3

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: current_user
    app.dependency_overrides[get_auth_service] = lambda: fake_auth_service
    client = TestClient(app, raise_server_exceptions=False)

    logout_response = client.post(
        "/auth/logout",
        json={"refresh_token": "refresh-token"},
    )
    assert logout_response.status_code == 200, logout_response.text
    assert logout_response.json() == {"logged_out": True}

    password_response = client.post(
        "/auth/change-password",
        json={
            "current_password": OLD_PASSWORD,
            "new_password": NEW_PASSWORD,
        },
    )
    assert password_response.status_code == 200, password_response.text
    assert password_response.json() == {
        "password_changed": True,
        "revoked_refresh_token_count": 3,
    }

    openapi = app.openapi()
    assert "/auth/logout" in openapi["paths"]
    assert "/auth/change-password" in openapi["paths"]

    app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(
        user_id="anonymous",
        auth_source="anonymous",
    )
    denied = client.post(
        "/auth/change-password",
        json={
            "current_password": OLD_PASSWORD,
            "new_password": NEW_PASSWORD,
        },
    )
    assert denied.status_code == 401, denied.text
    assert denied.json()["code"] == "AUTHENTICATION_FAILED"


if __name__ == "__main__":
    main()
