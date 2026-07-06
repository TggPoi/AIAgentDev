from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.core.config import get_settings
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.domain.agent_tool_permissions import (
    AgentToolCallContext,
    AgentToolPermissionAction,
)
from fast_app.domain.knowledge_document_actions import (
    KnowledgeDocumentOperation,
    KnowledgeDocumentRiskLevel,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_tool_permission_service import (
    AgentToolPermissionService,
    tool_name_for_document_operation,
)
from fast_app.services.permission_repository import PermissionRepository
from fast_app.services.permission_service import PermissionService


TEST_USERS = {
    "reader": "user_15_7_reader",
    "editor": "user_15_7_editor",
    "manager": "user_15_7_manager",
    "admin": "user_15_7_admin",
    "unscoped": "user_15_7_unscoped",
}


async def main() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        await seed_test_users(session)
        repository = PermissionRepository(session=session)
        permission_service = PermissionService(repository=repository)
        tool_permission_service = AgentToolPermissionService(
            permission_service=permission_service
        )

        await assert_decision(
            tool_permission_service,
            user_id=TEST_USERS["unscoped"],
            operation=KnowledgeDocumentOperation.UPDATE,
            department="development",
            expected=AgentToolPermissionAction.DENY,
            label="unscoped_update_denied",
            expected_requires_confirmation=False,
        )
        await assert_decision(
            tool_permission_service,
            user_id=TEST_USERS["reader"],
            operation=KnowledgeDocumentOperation.UPDATE,
            department="development",
            expected=AgentToolPermissionAction.DENY,
            label="reader_update_denied",
            expected_requires_confirmation=False,
        )
        await assert_decision(
            tool_permission_service,
            user_id=TEST_USERS["editor"],
            operation=KnowledgeDocumentOperation.UPDATE,
            department="development",
            expected=AgentToolPermissionAction.CONFIRMATION_REQUIRED,
            label="editor_update_confirmation_required",
            expected_requires_confirmation=True,
        )
        await assert_decision(
            tool_permission_service,
            user_id=TEST_USERS["editor"],
            operation=KnowledgeDocumentOperation.CREATE,
            department="development",
            expected=AgentToolPermissionAction.DENY,
            label="editor_create_denied",
            expected_requires_confirmation=False,
        )
        await assert_decision(
            tool_permission_service,
            user_id=TEST_USERS["manager"],
            operation=KnowledgeDocumentOperation.DELETE,
            department="development",
            expected=AgentToolPermissionAction.CONFIRMATION_REQUIRED,
            label="manager_delete_confirmation_required",
            expected_requires_confirmation=True,
        )
        await assert_decision(
            tool_permission_service,
            user_id=TEST_USERS["manager"],
            operation=KnowledgeDocumentOperation.UPDATE,
            department="art",
            expected=AgentToolPermissionAction.DENY,
            label="manager_cross_department_denied",
            expected_requires_confirmation=False,
        )
        await assert_decision(
            tool_permission_service,
            user_id=TEST_USERS["manager"],
            operation=KnowledgeDocumentOperation.DELETE,
            department="development",
            expected=AgentToolPermissionAction.EXECUTE_ALLOWED,
            label="manager_delete_execute_allowed",
            confirmation_text="CONFIRM EXECUTE TOOL APPROVAL demo",
            expected_requires_confirmation=False,
        )
        await assert_decision(
            tool_permission_service,
            user_id=TEST_USERS["admin"],
            operation=KnowledgeDocumentOperation.UPDATE,
            department="art",
            expected=AgentToolPermissionAction.CONFIRMATION_REQUIRED,
            label="admin_cross_department_confirmation_required",
            role="admin",
            expected_requires_confirmation=True,
        )

    await engine.dispose()
    print("agent_tool_permission_policy=passed")


async def seed_test_users(session) -> None:
    for key, user_id in TEST_USERS.items():
        role = "admin" if key == "admin" else "user"
        await session.execute(
            text(
                """
                insert into users
                    (id, username, email, display_name, password_hash, role, status)
                values
                    (:id, :username, :email, :display_name, 'test-hash', :role, 'active')
                on conflict (id) do nothing
                """
            ),
            {
                "id": user_id,
                "username": user_id,
                "email": f"{user_id}@example.com",
                "display_name": user_id,
                "role": role,
            },
        )

    await grant_department_role(
        session,
        TEST_USERS["reader"],
        "development",
        "department_reader",
    )
    await grant_department_role(
        session,
        TEST_USERS["editor"],
        "development",
        "department_editor",
    )
    await grant_department_role(
        session,
        TEST_USERS["manager"],
        "development",
        "department_document_manager",
    )
    await grant_global_role(session, TEST_USERS["admin"], "system_admin")
    await session.commit()


async def grant_department_role(
    session,
    user_id: str,
    department_code: str,
    role_code: str,
) -> None:
    await session.execute(
        text(
            """
            insert into user_departments (id, user_id, department_code, is_primary)
            values (:id, :user_id, :department_code, true)
            on conflict (user_id, department_code) do nothing
            """
        ),
        {
            "id": f"user_dept_{user_id}_{department_code}",
            "user_id": user_id,
            "department_code": department_code,
        },
    )
    await session.execute(
        text(
            """
            insert into user_department_roles (id, user_id, department_code, role_id)
            select :id, :user_id, :department_code, roles.id
            from roles
            where roles.code = :role_code
            on conflict (user_id, department_code, role_id) do nothing
            """
        ),
        {
            "id": build_short_id("udr", user_id, department_code, role_code),
            "user_id": user_id,
            "department_code": department_code,
            "role_code": role_code,
        },
    )


async def grant_global_role(session, user_id: str, role_code: str) -> None:
    await session.execute(
        text(
            """
            insert into user_roles (id, user_id, role_id)
            select :id, :user_id, roles.id
            from roles
            where roles.code = :role_code
            on conflict (user_id, role_id) do nothing
            """
        ),
        {
            "id": build_short_id("ur", user_id, role_code),
            "user_id": user_id,
            "role_code": role_code,
        },
    )


async def assert_decision(
    service: AgentToolPermissionService,
    user_id: str,
    operation: KnowledgeDocumentOperation,
    department: str,
    expected: AgentToolPermissionAction,
    label: str,
    role: str = "user",
    confirmation_text: str | None = None,
    expected_requires_confirmation: bool | None = None,
) -> None:
    tool_name = tool_name_for_document_operation(operation)
    decision = await service.authorize(
        user=CurrentUserContext(
            user_id=user_id,
            is_authenticated=True,
            auth_source="jwt",
            role=role,
            department_codes=[department],
        ),
        context=AgentToolCallContext(
            tool_name=tool_name,
            operation=operation,
            risk_level=KnowledgeDocumentRiskLevel.CRITICAL
            if operation == KnowledgeDocumentOperation.DELETE
            else KnowledgeDocumentRiskLevel.HIGH
            if operation == KnowledgeDocumentOperation.UPDATE
            else KnowledgeDocumentRiskLevel.MEDIUM,
            target_path=f"{department}/test.md",
            target_department_codes=[department],
            requires_confirmation=True,
            confirmation_text=confirmation_text,
        ),
    )
    if decision.action != expected:
        raise AssertionError(
            f"{label}: expected={expected.value} actual={decision.action.value} reason={decision.reason}"
        )
    if (
        expected_requires_confirmation is not None
        and decision.requires_confirmation != expected_requires_confirmation
    ):
        raise AssertionError(
            f"{label}: expected_requires_confirmation={expected_requires_confirmation} "
            f"actual={decision.requires_confirmation}"
        )
    print(f"{label}=passed action={decision.action.value}")


def build_short_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


if __name__ == "__main__":
    asyncio.run(main())
