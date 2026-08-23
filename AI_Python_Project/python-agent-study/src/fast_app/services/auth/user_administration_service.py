from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime

from fast_app.db.auth_tables import UserTable
from fast_app.domain.agent_tool_permissions import PermissionCode, RoleCode
from fast_app.domain.auth_models import AccountType, UserStatus
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.user_admin_schema import (
    AccessCatalogItem,
    AccessCatalogResponse,
    ManagedDepartmentAccess,
    ManagedUserDetail,
    ManagedUserListResponse,
    ManagedUserSummary,
)
from fast_app.services.auth.capability_service import resolve_account_type
from fast_app.services.auth.permission_service import PermissionService
from fast_app.services.auth.user_administration_repository import (
    UserAdministrationRepository,
)
from fast_app.services.exceptions import (
    AccessManagementPermissionDeniedError,
    ManagedUserNotFoundError,
    UserListCursorInvalidError,
)


DIRECT_PERMISSION_CODES_ADMIN = {
    PermissionCode.AGENT_TOOL_CALCULATOR.value,
    PermissionCode.AGENT_TOOL_WEB_SEARCH.value,
    PermissionCode.AGENT_TOOL_MCP.value,
    PermissionCode.DATA_QUERY_EXECUTE.value,
}
DIRECT_PERMISSION_CODES_MANAGER = DIRECT_PERMISSION_CODES_ADMIN - {
    PermissionCode.AGENT_TOOL_MCP.value
}
EMPLOYEE_DEPARTMENT_ROLE_CODES = {
    RoleCode.DEPARTMENT_READER.value,
    RoleCode.DEPARTMENT_EDITOR.value,
    RoleCode.DEPARTMENT_DOCUMENT_MANAGER.value,
}


class UserAdministrationService:
    """集中执行 actor 范围、目录裁剪、用户读取和账号类型推导。"""

    def __init__(
        self,
        *,
        repository: UserAdministrationRepository,
        permission_service: PermissionService,
    ) -> None:
        self._repository = repository
        self._permission_service = permission_service

    async def get_access_catalog(
        self,
        actor: CurrentUserContext,
    ) -> AccessCatalogResponse:
        is_admin, manager_department = self._management_scope(actor)
        department_filter = None if is_admin else {manager_department}
        direct_codes = (
            DIRECT_PERMISSION_CODES_ADMIN
            if is_admin
            else DIRECT_PERMISSION_CODES_MANAGER
        )
        departments = await self._repository.list_departments(department_filter)
        permissions = await self._repository.list_permissions(direct_codes)
        roles = await self._repository.list_roles(EMPLOYEE_DEPARTMENT_ROLE_CODES)
        account_types = (
            [AccountType.ADMIN, AccountType.DEPARTMENT_MANAGER, AccountType.EMPLOYEE]
            if is_admin
            else [AccountType.EMPLOYEE]
        )
        account_names = {
            AccountType.ADMIN: "管理员",
            AccountType.DEPARTMENT_MANAGER: "部门主管",
            AccountType.EMPLOYEE: "普通员工",
        }
        return AccessCatalogResponse(
            departments=[
                AccessCatalogItem(
                    code=row.code,
                    name=row.name,
                    description=row.description,
                )
                for row in departments
            ],
            account_types=[
                AccessCatalogItem(code=item.value, name=account_names[item])
                for item in account_types
            ],
            direct_permissions=[
                AccessCatalogItem(
                    code=row.code,
                    name=row.name,
                    description=row.description,
                    risk_level=row.risk_level,
                )
                for row in permissions
            ],
            department_roles=[
                AccessCatalogItem(
                    code=row.code,
                    name=row.name,
                    description=row.description,
                )
                for row in roles
            ],
        )

    async def list_users(
        self,
        actor: CurrentUserContext,
        *,
        cursor: str | None,
        limit: int,
        query: str | None,
        status: UserStatus | None,
        department_code: str | None,
    ) -> ManagedUserListResponse:
        is_admin, manager_department = self._management_scope(actor)
        if not is_admin:
            if department_code is not None and department_code != manager_department:
                raise AccessManagementPermissionDeniedError(
                    "部门主管不能扩大用户查询部门范围"
                )
            department_code = manager_department
        cursor_updated_at, cursor_user_id = _decode_cursor(cursor)
        rows, has_more = await self._repository.list_users(
            limit=limit,
            query=query.strip() if query and query.strip() else None,
            status=status.value if status is not None else None,
            department_code=department_code,
            cursor_updated_at=cursor_updated_at,
            cursor_user_id=cursor_user_id,
            employee_only=not is_admin,
        )
        items = [await self._build_summary(row) for row in rows]
        next_cursor = (
            _encode_cursor(rows[-1].updated_at, rows[-1].id)
            if has_more and rows
            else None
        )
        return ManagedUserListResponse(items=items, next_cursor=next_cursor)

    async def get_user(
        self,
        actor: CurrentUserContext,
        user_id: str,
    ) -> ManagedUserDetail:
        is_admin, manager_department = self._management_scope(actor)
        row = await self._repository.get_user(user_id)
        if row is None:
            raise ManagedUserNotFoundError("管理范围内不存在目标用户")

        departments = await self._repository.list_user_departments(user_id)
        primary_department = next(
            (item.department_code for item in departments if item.is_primary),
            departments[0].department_code if departments else None,
        )
        effective = await self._permission_service.get_effective_permissions(user_id)
        account_type = resolve_account_type(
            effective,
            primary_department_code=primary_department,
        )
        if not is_admin and (
            account_type != AccountType.EMPLOYEE
            or primary_department != manager_department
        ):
            raise AccessManagementPermissionDeniedError(
                "部门主管只能查看自己主部门的普通员工"
            )

        department_roles = await self._repository.list_department_role_codes(user_id)
        scopes = {scope.department_code: scope for scope in effective.department_scopes}
        return ManagedUserDetail(
            user_id=row.id,
            username=row.username,
            email=row.email,
            display_name=row.display_name,
            status=UserStatus(row.status),
            account_type=account_type,
            global_role_codes=list(effective.global_role_codes),
            direct_permission_codes=(
                await self._repository.list_direct_permission_codes(user_id)
            ),
            effective_global_permission_codes=sorted(
                permission.value for permission in effective.global_permission_codes
            ),
            department_access=[
                ManagedDepartmentAccess(
                    department_code=department.department_code,
                    is_primary=department.is_primary,
                    role_codes=department_roles.get(department.department_code, []),
                    permission_codes=sorted(
                        permission.value
                        for permission in (
                            scopes[department.department_code].permission_codes
                            if department.department_code in scopes
                            else set()
                        )
                    ),
                )
                for department in departments
            ],
            created_at=row.created_at,
            updated_at=row.updated_at,
            last_login_at=row.last_login_at,
        )

    async def _build_summary(self, row: UserTable) -> ManagedUserSummary:
        user_id = row.id
        departments = await self._repository.list_user_departments(user_id)
        primary_department = next(
            (item.department_code for item in departments if item.is_primary),
            departments[0].department_code if departments else None,
        )
        effective = await self._permission_service.get_effective_permissions(user_id)
        return ManagedUserSummary(
            user_id=user_id,
            username=row.username,
            email=row.email,
            display_name=row.display_name,
            status=UserStatus(row.status),
            account_type=resolve_account_type(
                effective,
                primary_department_code=primary_department,
            ),
            department_codes=[item.department_code for item in departments],
            primary_department_code=primary_department,
            updated_at=row.updated_at,
        )

    def _management_scope(
        self,
        actor: CurrentUserContext,
    ) -> tuple[bool, str]:
        if not actor.is_authenticated:
            raise AccessManagementPermissionDeniedError("用户管理只允许已认证管理员或部门主管")
        if actor.account_type == AccountType.ADMIN:
            return True, ""
        if (
            actor.account_type == AccountType.DEPARTMENT_MANAGER
            and actor.primary_department_code
        ):
            return False, actor.primary_department_code
        raise AccessManagementPermissionDeniedError("当前用户没有账号管理权限")


def _encode_cursor(updated_at: datetime, user_id: str) -> str:
    payload = json.dumps(
        {"updated_at": updated_at.isoformat(), "user_id": user_id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        updated_at = datetime.fromisoformat(payload["updated_at"])
        user_id = payload["user_id"]
        if updated_at.tzinfo is None or not isinstance(user_id, str) or not user_id:
            raise ValueError
        return updated_at, user_id
    except (
        binascii.Error,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise UserListCursorInvalidError("用户列表 cursor 无效") from exc


__all__ = [
    "DIRECT_PERMISSION_CODES_ADMIN",
    "DIRECT_PERMISSION_CODES_MANAGER",
    "EMPLOYEE_DEPARTMENT_ROLE_CODES",
    "UserAdministrationService",
]
