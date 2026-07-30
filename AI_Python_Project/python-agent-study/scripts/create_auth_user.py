from __future__ import annotations

import argparse
import asyncio

from fast_app.core.config import get_settings
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.domain.agent_tool_permissions import RoleCode
from fast_app.domain.auth_models import DepartmentCode
from fast_app.services.auth.auth_service import AuthService
from fast_app.services.auth.permission_repository import PermissionRepository
from fast_app.services.auth.permission_service import PermissionService
from fast_app.services.auth.user_repository import UserRepository


GLOBAL_ROLE_CODES = {
    RoleCode.SYSTEM_ADMIN,
    RoleCode.KNOWLEDGE_GLOBAL_READER,
    RoleCode.AGENT_TOOL_OPERATOR,
    RoleCode.GITLAB_MANAGER,
    RoleCode.DATA_ANALYST,
}
DEPARTMENT_ROLE_CODES = {
    RoleCode.DEPARTMENT_READER,
    RoleCode.DEPARTMENT_EDITOR,
    RoleCode.DEPARTMENT_DOCUMENT_MANAGER,
}


def parse_department_role(value: str) -> tuple[DepartmentCode, RoleCode]:
    """解析 ``department=role``，并拒绝把全局管理员绑定到部门作用域。"""

    try:
        department, role = value.split("=", 1)
        department_code = DepartmentCode(department)
        role_code = RoleCode(role)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError(
            "部门角色格式必须为 development=department_editor"
        ) from exc
    if role_code not in DEPARTMENT_ROLE_CODES:
        raise argparse.ArgumentTypeError(f"{role_code.value} 不是部门作用域角色")
    return department_code, role_code


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="创建本地认证用户")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--email", default=None)
    parser.add_argument("--display-name", default=None)
    parser.add_argument(
        "--global-role",
        action="append",
        choices=sorted(role.value for role in GLOBAL_ROLE_CODES),
        default=[],
        help="可重复传入，例如 --global-role system_admin",
    )
    parser.add_argument(
        "--department",
        action="append",
        choices=[department.value for department in DepartmentCode],
        default=[],
        help="可重复传入，例如 --department development",
    )
    parser.add_argument(
        "--department-role",
        action="append",
        type=parse_department_role,
        default=[],
        metavar="DEPARTMENT=ROLE",
        help="可重复传入，例如 --department-role development=department_editor",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            repository = UserRepository(session=session)
            permission_repository = PermissionRepository(session=session)
            auth_service = AuthService(
                settings=settings,
                repository=repository,
                permission_service=PermissionService(permission_repository),
            )
            user = await auth_service.create_user(
                username=args.username,
                password=args.password,
                email=args.email,
                display_name=args.display_name,
            )
            department_roles = dict(args.department_role)
            departments = list(
                dict.fromkeys(
                    [DepartmentCode(item) for item in args.department]
                    + list(department_roles)
                )
            )
            for index, department in enumerate(departments):
                await repository.add_user_department(
                    user_id=user.id,
                    department_code=department,
                    is_primary=index == 0,
                )
                role = department_roles.get(department)
                if role is not None:
                    await permission_repository.add_user_department_role(
                        user_id=user.id,
                        department_code=department.value,
                        role_code=role.value,
                    )
            for role in dict.fromkeys(args.global_role):
                await permission_repository.add_user_role(user.id, role)

            saved_user = await repository.get_user_by_id(user.id)
            effective = await permission_repository.list_global_roles_for_user(user.id)
            print(f"created_user_id={user.id}")
            print(f"username={user.username}")
            print(f"global_roles={','.join(effective)}")
            print(
                "departments="
                f"{','.join(code.value for code in (saved_user.department_codes if saved_user else []))}"
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
