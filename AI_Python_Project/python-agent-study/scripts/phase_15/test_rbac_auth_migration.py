"""验证认证上下文只从 RBAC 读取角色和权限。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

from pydantic import ValidationError
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.core.config import get_settings
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.agent_tool_permissions import PermissionCode, RoleCode
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.auth.auth_crypto import hash_password
from fast_app.services.auth.auth_service import AuthService
from fast_app.services.auth.jwt_service import JwtService
from fast_app.services.auth.permission_repository import PermissionRepository
from fast_app.services.auth.permission_service import PermissionService
from fast_app.services.auth.user_repository import UserRepository
from fast_app.services.exceptions import AuthenticationError


TEST_USER_ID = "user_rbac_auth_migration"


async def main() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            columns = set(
                (
                    await session.execute(
                        text(
                            """
                            select column_name
                            from information_schema.columns
                            where table_name = 'users'
                            """
                        )
                    )
                ).scalars()
            )
            assert "role" not in columns
            assert "permissions_json" not in columns
            global_role_permissions = set(
                (
                    await session.execute(
                        text(
                            """
                            select roles.code, permissions.code
                            from role_permissions
                            join roles on roles.id = role_permissions.role_id
                            join permissions
                                on permissions.id = role_permissions.permission_id
                            where roles.code in (
                                'knowledge_global_reader',
                                'agent_tool_operator',
                                'gitlab_manager'
                            )
                            """
                        )
                    )
                ).tuples()
            )
            assert (
                "knowledge_global_reader",
                PermissionCode.KNOWLEDGE_READ_ALL.value,
            ) in global_role_permissions
            assert (
                "agent_tool_operator",
                PermissionCode.AGENT_TOOL_WEB_SEARCH.value,
            ) in global_role_permissions
            assert (
                "agent_tool_operator",
                PermissionCode.AGENT_TOOL_MCP.value,
            ) in global_role_permissions
            assert (
                "gitlab_manager",
                PermissionCode.GITLAB_SOURCE_MANAGE.value,
            ) in global_role_permissions

            initial_user_count = int(
                await session.scalar(text("select count(*) from users")) or 0
            )
            await session.execute(
                text(
                    "delete from users "
                    "where id = :user_id or username = 'rbac_auth_migration'"
                ),
                {"user_id": TEST_USER_ID},
            )
            await session.execute(
                text(
                    """
                    insert into users
                        (id, username, password_hash, status)
                    values
                        (:id, 'rbac_auth_migration', :password_hash, 'active')
                    """
                ),
                {
                    "id": TEST_USER_ID,
                    "password_hash": hash_password("RbacMigration123!"),
                },
            )
            await session.commit()

            user_repository = UserRepository(session)
            permission_repository = PermissionRepository(session)
            permission_service = PermissionService(permission_repository)
            auth_service = AuthService(
                settings=settings,
                repository=user_repository,
                permission_service=permission_service,
            )
            user = await user_repository.get_user_by_id(TEST_USER_ID)
            assert user is not None

            await permission_repository.add_user_role(
                TEST_USER_ID,
                RoleCode.SYSTEM_ADMIN.value,
            )
            access_token, _expires_in, _token_id = JwtService(
                settings
            ).create_access_token(user)
            context = await auth_service.authenticate_jwt(access_token)
            assert context is not None
            assert context.has_global_role(RoleCode.SYSTEM_ADMIN.value)
            assert context.has_global_permission(
                PermissionCode.KNOWLEDGE_READ_ALL.value
            )
            assert context.has_global_permission(
                PermissionCode.GITLAB_SOURCE_MANAGE.value
            )
            assert context.has_global_permission(
                PermissionCode.GITLAB_CHANGE_READ_ALL.value
            )
            created_api_key = await auth_service.create_api_key(
                current_user=context,
                name="RBAC migration test",
            )
            api_key_context = await auth_service.authenticate_api_key(
                created_api_key.api_key
            )
            assert api_key_context is not None
            assert api_key_context.auth_source == "api_key"
            assert api_key_context.has_global_role(RoleCode.SYSTEM_ADMIN.value)
            assert api_key_context.has_global_permission(
                PermissionCode.KNOWLEDGE_READ_ALL.value
            )

            try:
                CurrentUserContext(
                    user_id="legacy",
                    role="admin",  # type: ignore[call-arg]
                    permissions=["*"],  # type: ignore[call-arg]
                )
            except ValidationError:
                pass
            else:
                raise AssertionError("CurrentUserContext 不应再接受旧 role/permissions")

            assert not hasattr(settings, "auth_api_keys")
            assert not hasattr(settings, "auth_bearer_tokens")
            rejected_auth = AsyncMock()
            rejected_auth.authenticate_api_key.return_value = None
            rejected_auth.authenticate_jwt.side_effect = AuthenticationError(
                "无效 JWT"
            )
            strict_settings = settings.model_copy(update={"auth_enabled": True})
            for x_api_key, authorization in (
                ("old-static-api-key", None),
                (None, "Bearer old-static-bearer-token"),
            ):
                try:
                    await get_current_user_context(
                        settings=strict_settings,
                        auth_service=rejected_auth,
                        x_api_key=x_api_key,
                        authorization=authorization,
                        x_demo_user_id=None,
                    )
                except AuthenticationError:
                    pass
                else:
                    raise AssertionError("旧静态凭证不应再通过认证")

            print(f"initial_users={initial_user_count}")
            print("legacy_static_credentials_removed=passed")
            print("database_api_key_rbac=passed")
            print("rbac_auth_migration=passed")
    finally:
        async with session_factory() as cleanup_session:
            await cleanup_session.execute(
                text("delete from users where id = :user_id"),
                {"user_id": TEST_USER_ID},
            )
            await cleanup_session.commit()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
