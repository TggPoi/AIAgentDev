from __future__ import annotations

from dataclasses import dataclass

from fast_app.domain.agent_tool_permissions import (
    EffectivePermissionSet,
    PermissionCode,
    RoleCode,
)
from fast_app.domain.auth_models import AccountType, UserManagementScope
from fast_app.domain.user_context import CurrentUserContext


@dataclass(frozen=True, slots=True)
class AuthCapabilitySnapshot:
    """面向 React 展示控制的非敏感能力快照。"""

    can_manage_users: bool
    user_management_scope: UserManagementScope
    can_manage_document_grants: bool
    can_use_web_search: bool
    can_use_nl2sql: bool
    can_read_documents: bool
    can_manage_documents: bool


def resolve_account_type(
    effective: EffectivePermissionSet,
    *,
    primary_department_code: str | None,
) -> AccountType:
    """从实时角色事实推导账号类型，不接受 JWT 或请求体中的账号类型。"""

    if effective.has_global_role(RoleCode.SYSTEM_ADMIN):
        return AccountType.ADMIN

    if primary_department_code is not None:
        primary_scope = effective.scope_for_department(primary_department_code)
        if primary_scope is not None and RoleCode.DEPARTMENT_MANAGER.value in (
            primary_scope.role_codes
        ):
            return AccountType.DEPARTMENT_MANAGER

    return AccountType.EMPLOYEE


def resolve_auth_capabilities(user: CurrentUserContext) -> AuthCapabilitySnapshot:
    """把可信身份和权限快照转换为前端可消费的布尔能力。"""

    is_admin = user.account_type == AccountType.ADMIN
    is_department_manager = user.account_type == AccountType.DEPARTMENT_MANAGER
    can_manage_users = is_admin or is_department_manager
    management_scope = (
        UserManagementScope.ALL
        if is_admin
        else UserManagementScope.OWN_DEPARTMENT
        if is_department_manager
        else UserManagementScope.NONE
    )

    department_permissions = {
        permission
        for permissions in user.department_permission_codes.values()
        for permission in permissions
    }
    document_management_permissions = {
        PermissionCode.KNOWLEDGE_DOCUMENT_CREATE.value,
        PermissionCode.KNOWLEDGE_DOCUMENT_UPDATE.value,
        PermissionCode.KNOWLEDGE_DOCUMENT_DELETE.value,
    }
    can_read_documents = user.is_authenticated and (
        is_admin
        or user.has_global_permission(PermissionCode.KNOWLEDGE_READ_ALL.value)
        or bool(user.department_codes)
        or PermissionCode.KNOWLEDGE_DOCUMENT_READ.value in department_permissions
    )

    return AuthCapabilitySnapshot(
        can_manage_users=can_manage_users,
        user_management_scope=management_scope,
        can_manage_document_grants=can_manage_users,
        can_use_web_search=user.has_global_permission(
            PermissionCode.AGENT_TOOL_WEB_SEARCH.value
        ),
        can_use_nl2sql=user.has_global_permission(
            PermissionCode.DATA_QUERY_EXECUTE.value
        ),
        can_read_documents=can_read_documents,
        can_manage_documents=is_admin
        or bool(document_management_permissions & department_permissions),
    )


__all__ = [
    "AuthCapabilitySnapshot",
    "resolve_account_type",
    "resolve_auth_capabilities",
]
