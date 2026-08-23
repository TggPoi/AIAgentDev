from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from fast_app.core.request_context import get_request_id
from fast_app.db.auth_tables import PermissionTable, RoleTable, UserTable
from fast_app.domain.agent_tool_permissions import PermissionCode, RoleCode
from fast_app.domain.auth_models import AccountType, UserStatus
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.user_admin_schema import (
    AccessCatalogItem,
    AccessCatalogResponse,
    CreateManagedUserRequest,
    ManagedDepartmentAccess,
    ManagedDepartmentAccessInput,
    ManagedUserDetail,
    ManagedUserListResponse,
    ManagedUserPasswordResetResponse,
    ManagedUserStatusResponse,
    ManagedUserSummary,
    ReplaceManagedUserAccessRequest,
    ResetManagedUserPasswordRequest,
    UpdateManagedUserStatusRequest,
)
from fast_app.services.auth.auth_crypto import (
    generate_user_id,
    hash_password,
    validate_password_strength,
)
from fast_app.services.auth.capability_service import resolve_account_type
from fast_app.services.auth.permission_service import PermissionService
from fast_app.services.auth.user_administration_repository import (
    UserAdministrationRepository,
)
from fast_app.services.exceptions import (
    AccessManagementPermissionDeniedError,
    LastSystemAdminProtectedError,
    ManagedUserAccessInvalidError,
    ManagedUserConflictError,
    ManagedUserNotFoundError,
    ManagedUserSelfOperationError,
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


@dataclass(frozen=True)
class _ValidatedAccessSnapshot:
    departments: list[tuple[str, bool, set[str]]]
    roles_by_code: dict[str, RoleTable]
    permission_codes: set[str]
    permissions_by_code: dict[str, PermissionTable]


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
            or len(departments) != 1
        ):
            raise AccessManagementPermissionDeniedError(
                "部门主管只能管理仅属于自己主部门的普通员工"
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

    async def create_user(
        self,
        actor: CurrentUserContext,
        request: CreateManagedUserRequest,
    ) -> ManagedUserDetail:
        """在一个事务内创建账号、完整访问快照和安全审计事实。"""

        is_admin, manager_department = self._management_scope(actor)
        validated = await self._validate_access_snapshot(
            actor_is_admin=is_admin,
            manager_department=manager_department,
            account_type=request.account_type,
            department_access=request.department_access,
            direct_permission_codes=request.direct_permission_codes,
        )
        username = request.username.strip().lower()
        email = request.email.strip().lower() if request.email and request.email.strip() else None
        display_name = (
            request.display_name.strip()
            if request.display_name and request.display_name.strip()
            else None
        )
        if not username:
            raise ManagedUserAccessInvalidError("用户名不能只包含空白字符")
        validate_password_strength(request.password)
        user_id = generate_user_id()
        try:
            await self._repository.create_user(
                user_id=user_id,
                username=username,
                email=email,
                display_name=display_name,
                password_hash=hash_password(request.password),
            )
            await self._apply_access_snapshot(
                actor_user_id=actor.user_id,
                target_user_id=user_id,
                account_type=request.account_type,
                validated=validated,
            )
            await self._repository.add_audit(
                action="create_user",
                actor_user_id=actor.user_id,
                target_user_id=user_id,
                request_id=get_request_id(),
                details={
                    "username": username,
                    "access": _safe_access_snapshot(request.account_type, validated),
                },
            )
            await self._repository.commit()
        except IntegrityError as exc:
            await self._repository.rollback()
            raise ManagedUserConflictError("用户名或邮箱已经存在") from exc
        except Exception:
            await self._repository.rollback()
            raise
        return await self.get_user(actor, user_id)

    async def replace_user_access(
        self,
        actor: CurrentUserContext,
        user_id: str,
        request: ReplaceManagedUserAccessRequest,
    ) -> ManagedUserDetail:
        """原子替换账号类型、完整部门作用域和 active 直接权限。"""

        if actor.user_id == user_id:
            raise ManagedUserSelfOperationError("不能通过用户管理接口修改自己的访问权限")
        is_admin, manager_department = self._management_scope(actor)
        validated = await self._validate_access_snapshot(
            actor_is_admin=is_admin,
            manager_department=manager_department,
            account_type=request.account_type,
            department_access=request.department_access,
            direct_permission_codes=request.direct_permission_codes,
        )
        try:
            row = await self._repository.get_user_for_update(user_id)
            if row is None:
                raise ManagedUserNotFoundError("管理范围内不存在目标用户")
            current = await self.get_user(actor, user_id)
            system_admin_role = await self._repository.lock_system_admin_role()
            if (
                current.account_type == AccountType.ADMIN
                and current.status == UserStatus.ACTIVE
                and request.account_type != AccountType.ADMIN
                and await self._repository.count_active_system_admins(
                    system_admin_role.id
                )
                <= 1
            ):
                raise LastSystemAdminProtectedError("不能移除最后一个 active 系统管理员")
            await self._apply_access_snapshot(
                actor_user_id=actor.user_id,
                target_user_id=user_id,
                account_type=request.account_type,
                validated=validated,
                system_admin_role=system_admin_role,
            )
            await self._repository.touch_user(row)
            await self._repository.add_audit(
                action="replace_access",
                actor_user_id=actor.user_id,
                target_user_id=user_id,
                request_id=get_request_id(),
                details={
                    "before": _safe_detail_access(current),
                    "after": _safe_access_snapshot(request.account_type, validated),
                },
            )
            await self._repository.commit()
        except IntegrityError as exc:
            await self._repository.rollback()
            raise ManagedUserConflictError("访问权限替换与当前数据库状态冲突") from exc
        except Exception:
            await self._repository.rollback()
            raise
        return await self.get_user(actor, user_id)

    async def update_user_status(
        self,
        actor: CurrentUserContext,
        user_id: str,
        request: UpdateManagedUserStatusRequest,
    ) -> ManagedUserStatusResponse:
        """切换账号状态；禁用时不可逆地撤销当前 refresh token 和 API Key。"""

        if actor.user_id == user_id and request.status == UserStatus.DISABLED:
            raise ManagedUserSelfOperationError("不能禁用当前登录账号")
        revoked_refresh = 0
        revoked_api_keys = 0
        try:
            row = await self._repository.get_user_for_update(user_id)
            if row is None:
                raise ManagedUserNotFoundError("管理范围内不存在目标用户")
            current = await self.get_user(actor, user_id)
            if current.status != request.status:
                if (
                    current.account_type == AccountType.ADMIN
                    and current.status == UserStatus.ACTIVE
                    and request.status == UserStatus.DISABLED
                ):
                    system_admin_role = await self._repository.lock_system_admin_role()
                    if (
                        await self._repository.count_active_system_admins(
                            system_admin_role.id
                        )
                        <= 1
                    ):
                        raise LastSystemAdminProtectedError(
                            "不能禁用最后一个 active 系统管理员"
                        )
                await self._repository.update_user_status(row, request.status.value)
                if request.status == UserStatus.DISABLED:
                    revoked_refresh, revoked_api_keys = (
                        await self._repository.revoke_active_credentials(user_id)
                    )
            await self._repository.add_audit(
                action="update_status",
                actor_user_id=actor.user_id,
                target_user_id=user_id,
                request_id=get_request_id(),
                details={
                    "before": current.status.value,
                    "after": request.status.value,
                    "revoked_refresh_token_count": revoked_refresh,
                    "revoked_api_key_count": revoked_api_keys,
                },
            )
            await self._repository.commit()
        except Exception:
            await self._repository.rollback()
            raise
        return ManagedUserStatusResponse(
            user=await self.get_user(actor, user_id),
            revoked_refresh_token_count=revoked_refresh,
            revoked_api_key_count=revoked_api_keys,
        )

    async def reset_user_password(
        self,
        actor: CurrentUserContext,
        user_id: str,
        request: ResetManagedUserPasswordRequest,
    ) -> ManagedUserPasswordResetResponse:
        """重置管理范围内账号密码，并在同一事务撤销现有凭证。"""

        if actor.user_id == user_id:
            raise ManagedUserSelfOperationError("请使用修改当前密码接口处理自己的账号")
        validate_password_strength(request.new_password)
        try:
            row = await self._repository.get_user_for_update(user_id)
            if row is None:
                raise ManagedUserNotFoundError("管理范围内不存在目标用户")
            await self.get_user(actor, user_id)
            await self._repository.update_password_hash(
                row,
                hash_password(request.new_password),
            )
            revoked_refresh, revoked_api_keys = (
                await self._repository.revoke_active_credentials(user_id)
            )
            await self._repository.add_audit(
                action="reset_password",
                actor_user_id=actor.user_id,
                target_user_id=user_id,
                request_id=get_request_id(),
                details={
                    "revoked_refresh_token_count": revoked_refresh,
                    "revoked_api_key_count": revoked_api_keys,
                },
            )
            await self._repository.commit()
        except Exception:
            await self._repository.rollback()
            raise
        return ManagedUserPasswordResetResponse(
            password_reset=True,
            revoked_refresh_token_count=revoked_refresh,
            revoked_api_key_count=revoked_api_keys,
        )

    async def _validate_access_snapshot(
        self,
        *,
        actor_is_admin: bool,
        manager_department: str,
        account_type: AccountType,
        department_access: list[ManagedDepartmentAccessInput],
        direct_permission_codes: list[str],
    ) -> _ValidatedAccessSnapshot:
        if not actor_is_admin and account_type != AccountType.EMPLOYEE:
            raise AccessManagementPermissionDeniedError(
                "部门主管只能创建或管理普通员工"
            )
        department_items = list(department_access)
        department_codes = [item.department_code for item in department_items]
        if len(set(department_codes)) != len(department_codes):
            raise ManagedUserAccessInvalidError("部门作用域不能包含重复 department_code")
        primary_items = [item for item in department_items if item.is_primary]
        if len(primary_items) != 1:
            raise ManagedUserAccessInvalidError("部门作用域必须且只能包含一个主部门")
        if any(
            len(set(item.role_codes)) != len(item.role_codes)
            for item in department_items
        ):
            raise ManagedUserAccessInvalidError("同一部门的角色不能包含重复 code")
        if not actor_is_admin and set(department_codes) != {manager_department}:
            raise AccessManagementPermissionDeniedError(
                "部门主管只能管理自己主部门的普通员工"
            )
        departments_by_code = await self._repository.get_departments_by_codes(
            set(department_codes)
        )
        if set(departments_by_code) != set(department_codes):
            raise ManagedUserAccessInvalidError("部门作用域包含未知 department_code")

        submitted_role_codes = {
            role_code
            for item in department_items
            for role_code in item.role_codes
        }
        if not submitted_role_codes <= EMPLOYEE_DEPARTMENT_ROLE_CODES:
            raise ManagedUserAccessInvalidError("部门角色不在可分配目录中")
        if account_type == AccountType.DEPARTMENT_MANAGER:
            if len(department_items) != 1 or submitted_role_codes:
                raise ManagedUserAccessInvalidError(
                    "部门主管账号必须只有一个主部门，且主管角色由服务端自动绑定"
                )
        required_role_codes = set(submitted_role_codes)
        if account_type == AccountType.DEPARTMENT_MANAGER:
            required_role_codes.add(RoleCode.DEPARTMENT_MANAGER.value)
        if account_type == AccountType.ADMIN:
            required_role_codes.add(RoleCode.SYSTEM_ADMIN.value)
        roles_by_code = await self._repository.get_roles_by_codes(required_role_codes)
        if set(roles_by_code) != required_role_codes:
            raise ManagedUserAccessInvalidError("系统角色目录不完整，无法保存访问快照")

        permission_codes = set(direct_permission_codes)
        if len(permission_codes) != len(direct_permission_codes):
            raise ManagedUserAccessInvalidError("直接权限不能包含重复 code")
        actor_assignable_permissions = (
            DIRECT_PERMISSION_CODES_ADMIN
            if actor_is_admin
            else DIRECT_PERMISSION_CODES_MANAGER
        )
        if not permission_codes <= actor_assignable_permissions:
            raise AccessManagementPermissionDeniedError(
                "直接权限包含当前 actor 不可下放的 code"
            )
        permissions_by_code = await self._repository.get_permissions_by_codes(
            permission_codes
        )
        if set(permissions_by_code) != permission_codes:
            raise ManagedUserAccessInvalidError("直接权限包含未知 code")

        normalized_departments: list[tuple[str, bool, set[str]]] = []
        for item in department_items:
            role_codes = set(item.role_codes)
            if account_type == AccountType.DEPARTMENT_MANAGER and item.is_primary:
                role_codes.add(RoleCode.DEPARTMENT_MANAGER.value)
            normalized_departments.append(
                (item.department_code, item.is_primary, role_codes)
            )
        return _ValidatedAccessSnapshot(
            departments=normalized_departments,
            roles_by_code=roles_by_code,
            permission_codes=permission_codes,
            permissions_by_code=permissions_by_code,
        )

    async def _apply_access_snapshot(
        self,
        *,
        actor_user_id: str,
        target_user_id: str,
        account_type: AccountType,
        validated: _ValidatedAccessSnapshot,
        system_admin_role: RoleTable | None = None,
    ) -> None:
        roles_by_code = validated.roles_by_code
        if system_admin_role is None:
            if account_type == AccountType.ADMIN:
                system_admin_role = roles_by_code[RoleCode.SYSTEM_ADMIN.value]
            else:
                system_admin_role = await self._repository.lock_system_admin_role()
        await self._repository.replace_system_admin_role(
            user_id=target_user_id,
            enabled=account_type == AccountType.ADMIN,
            role=system_admin_role,
        )
        await self._repository.replace_department_access(
            user_id=target_user_id,
            departments=validated.departments,
            roles_by_code=roles_by_code,
        )
        await self._repository.replace_direct_permissions(
            user_id=target_user_id,
            permission_codes=validated.permission_codes,
            permissions_by_code=validated.permissions_by_code,
            actor_user_id=actor_user_id,
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


def _safe_access_snapshot(
    account_type: AccountType,
    validated: _ValidatedAccessSnapshot,
) -> dict[str, object]:
    return {
        "account_type": account_type.value,
        "department_access": [
            {
                "department_code": department_code,
                "is_primary": is_primary,
                "role_codes": sorted(role_codes),
            }
            for department_code, is_primary, role_codes in validated.departments
        ],
        "direct_permission_codes": sorted(validated.permission_codes),
    }


def _safe_detail_access(detail: ManagedUserDetail) -> dict[str, object]:
    return {
        "account_type": detail.account_type.value,
        "department_access": [
            {
                "department_code": item.department_code,
                "is_primary": item.is_primary,
                "role_codes": list(item.role_codes),
            }
            for item in detail.department_access
        ],
        "direct_permission_codes": list(detail.direct_permission_codes),
    }


__all__ = [
    "DIRECT_PERMISSION_CODES_ADMIN",
    "DIRECT_PERMISSION_CODES_MANAGER",
    "EMPLOYEE_DEPARTMENT_ROLE_CODES",
    "UserAdministrationService",
]
