"""创建并保留五个 RBAC 测试账号，同时验证真实登录和权限裁决。"""

from __future__ import annotations

import asyncio
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.core.config import get_settings
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.domain.agent_tool_permissions import (
    AgentToolCallContext,
    AgentToolPermissionAction,
    PermissionCode,
    RoleCode,
)
from fast_app.domain.auth_models import DepartmentCode
from fast_app.domain.knowledge_document_actions import KnowledgeDocumentOperation
from fast_app.services.agent_tasks.agent_tool_permission_service import (
    AgentToolPermissionService,
    risk_level_for_document_operation,
    tool_name_for_document_operation,
)
from fast_app.services.auth.auth_service import AuthService
from fast_app.services.auth.permission_repository import PermissionRepository
from fast_app.services.auth.permission_service import PermissionService
from fast_app.services.auth.user_repository import UserRepository
from fast_app.services.knowledge.knowledge_permission_policy import (
    KnowledgePermissionPolicy,
)


@dataclass(frozen=True)
class AccountSpec:
    username: str
    display_name: str
    department: DepartmentCode | None = None
    department_role: RoleCode | None = None
    global_roles: tuple[RoleCode, ...] = ()


ACCOUNTS = (
    AccountSpec(
        "rbac_reader",
        "RBAC 只读员工",
        DepartmentCode.DEVELOPMENT,
        RoleCode.DEPARTMENT_READER,
    ),
    AccountSpec(
        "rbac_editor",
        "RBAC 编辑员工",
        DepartmentCode.DEVELOPMENT,
        RoleCode.DEPARTMENT_EDITOR,
    ),
    AccountSpec(
        "rbac_manager",
        "RBAC 文档管理员工",
        DepartmentCode.DEVELOPMENT,
        RoleCode.DEPARTMENT_DOCUMENT_MANAGER,
    ),
    AccountSpec(
        "rbac_operator",
        "RBAC 全局工具员工",
        DepartmentCode.ART,
        RoleCode.DEPARTMENT_READER,
        (
            RoleCode.KNOWLEDGE_GLOBAL_READER,
            RoleCode.AGENT_TOOL_OPERATOR,
            RoleCode.GITLAB_MANAGER,
        ),
    ),
    AccountSpec(
        "rbac_admin",
        "RBAC 系统管理员",
        global_roles=(RoleCode.SYSTEM_ADMIN,),
    ),
)


def tool_context(
    operation: KnowledgeDocumentOperation,
    department: DepartmentCode,
    *,
    confirmation_text: str | None = None,
) -> AgentToolCallContext:
    return AgentToolCallContext(
        tool_name=tool_name_for_document_operation(operation),
        operation=operation,
        risk_level=risk_level_for_document_operation(operation),
        target_path=f"{department.value}/rbac-test.md",
        target_department_codes=[department.value],
        requires_confirmation=True,
        confirmation_text=confirmation_text,
    )


async def main() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    passwords = {
        spec.username: f"{secrets.token_urlsafe(16)}!"
        for spec in ACCOUNTS
    }

    try:
        async with session_factory() as session:
            await session.execute(
                text(
                    "delete from users where username in "
                    "('rbac_reader', 'rbac_editor', 'rbac_manager', "
                    "'rbac_operator', 'rbac_admin')"
                )
            )
            await session.commit()

            users = UserRepository(session)
            permission_repository = PermissionRepository(session)
            permissions = PermissionService(permission_repository)
            auth = AuthService(settings, users, permissions)
            tool_permissions = AgentToolPermissionService(permissions)
            tokens: dict[str, str] = {}
            user_ids: dict[str, str] = {}

            for spec in ACCOUNTS:
                user = await auth.create_user(
                    username=spec.username,
                    password=passwords[spec.username],
                    email=f"{spec.username}@example.com",
                    display_name=spec.display_name,
                )
                user_ids[spec.username] = user.id
                tokens[spec.username] = (
                    await auth.login(spec.username, passwords[spec.username])
                ).access_token

                if spec.department is not None:
                    await users.add_user_department(
                        user.id,
                        spec.department,
                        is_primary=True,
                    )
                    assert spec.department_role is not None
                    await permission_repository.add_user_department_role(
                        user.id,
                        spec.department.value,
                        spec.department_role.value,
                    )
                for role in spec.global_roles:
                    await permission_repository.add_user_role(user.id, role.value)

            contexts = {
                username: await auth.authenticate_jwt(token)
                for username, token in tokens.items()
            }
            assert all(contexts.values())
            reader = contexts["rbac_reader"]
            editor = contexts["rbac_editor"]
            manager = contexts["rbac_manager"]
            operator = contexts["rbac_operator"]
            admin = contexts["rbac_admin"]
            assert reader and editor and manager and operator and admin

            reader_effective = await permissions.get_effective_permissions(
                reader.user_id
            )
            reader_scope = reader_effective.scope_for_department(
                DepartmentCode.DEVELOPMENT.value
            )
            assert reader_scope is not None
            assert reader_scope.permission_codes == {
                PermissionCode.KNOWLEDGE_DOCUMENT_READ
            }
            assert not KnowledgePermissionPolicy().build_scope(reader).can_read_all
            assert (
                await tool_permissions.authorize(
                    reader,
                    tool_context(
                        KnowledgeDocumentOperation.UPDATE,
                        DepartmentCode.DEVELOPMENT,
                    ),
                )
            ).action == AgentToolPermissionAction.DENY

            assert (
                await tool_permissions.authorize(
                    editor,
                    tool_context(
                        KnowledgeDocumentOperation.UPDATE,
                        DepartmentCode.DEVELOPMENT,
                    ),
                )
            ).action == AgentToolPermissionAction.CONFIRMATION_REQUIRED
            assert (
                await tool_permissions.authorize(
                    editor,
                    tool_context(
                        KnowledgeDocumentOperation.UPDATE,
                        DepartmentCode.DEVELOPMENT,
                        confirmation_text="RBAC TEST CONFIRMED",
                    ),
                )
            ).action == AgentToolPermissionAction.DENY
            assert (
                await tool_permissions.authorize(
                    editor,
                    tool_context(
                        KnowledgeDocumentOperation.CREATE,
                        DepartmentCode.DEVELOPMENT,
                    ),
                )
            ).action == AgentToolPermissionAction.DENY

            assert (
                await tool_permissions.authorize(
                    manager,
                    tool_context(
                        KnowledgeDocumentOperation.DELETE,
                        DepartmentCode.DEVELOPMENT,
                    ),
                )
            ).action == AgentToolPermissionAction.CONFIRMATION_REQUIRED
            assert (
                await tool_permissions.authorize(
                    manager,
                    tool_context(
                        KnowledgeDocumentOperation.DELETE,
                        DepartmentCode.DEVELOPMENT,
                        confirmation_text="RBAC TEST CONFIRMED",
                    ),
                )
            ).action == AgentToolPermissionAction.EXECUTE_ALLOWED

            operator_permissions = set(operator.global_permission_codes)
            assert {
                PermissionCode.KNOWLEDGE_READ_ALL.value,
                PermissionCode.AGENT_TOOL_CALCULATOR.value,
                PermissionCode.AGENT_TOOL_WEB_SEARCH.value,
                PermissionCode.AGENT_TOOL_MCP.value,
                PermissionCode.GITLAB_SOURCE_MANAGE.value,
                PermissionCode.GITLAB_CHANGE_READ_ALL.value,
            } <= operator_permissions
            assert KnowledgePermissionPolicy().build_scope(operator).can_read_all
            assert (
                await tool_permissions.authorize(
                    operator,
                    tool_context(
                        KnowledgeDocumentOperation.UPDATE,
                        DepartmentCode.ART,
                    ),
                )
            ).action == AgentToolPermissionAction.DENY

            assert admin.global_role_codes == [RoleCode.SYSTEM_ADMIN.value]
            assert {permission.value for permission in PermissionCode} <= set(
                admin.global_permission_codes
            )
            assert KnowledgePermissionPolicy().build_scope(admin).can_read_all
            assert (
                await tool_permissions.authorize(
                    admin,
                    tool_context(
                        KnowledgeDocumentOperation.UPDATE,
                        DepartmentCode.ART,
                    ),
                )
            ).action == AgentToolPermissionAction.CONFIRMATION_REQUIRED

            saved_count = int(
                await session.scalar(
                    text(
                        "select count(*) from users where username in "
                        "('rbac_reader', 'rbac_editor', 'rbac_manager', "
                        "'rbac_operator', 'rbac_admin')"
                    )
                )
                or 0
            )
            assert saved_count == len(ACCOUNTS)

            for spec in ACCOUNTS:
                context = contexts[spec.username]
                assert context is not None
                roles = ",".join(
                    (*context.global_role_codes,)
                    + ((spec.department_role.value,) if spec.department_role else ())
                )
                print(
                    f"ACCOUNT username={spec.username} "
                    f"password={passwords[spec.username]} "
                    f"user_id={user_ids[spec.username]} "
                    f"roles={roles or '-'} "
                    f"departments={','.join(context.department_codes) or '-'}"
                )
            print("rbac_account_matrix=passed")
            print(f"persisted_accounts={saved_count}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
