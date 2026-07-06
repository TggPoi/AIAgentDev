from __future__ import annotations

from fast_app.domain.agent_tool_permissions import (
    DepartmentPermissionScope,
    EffectivePermissionSet,
    PermissionCode,
)
from fast_app.services.permission_repository import PermissionRepository


class PermissionService:
    """根据数据库 RBAC 表计算用户有效权限。"""

    def __init__(self, repository: PermissionRepository) -> None:
        self._repository = repository

    async def get_effective_permissions(self, user_id: str) -> EffectivePermissionSet:
        """加载全局角色、全局权限和部门作用域权限。"""

        global_role_codes = await self._repository.list_global_roles_for_user(user_id)
        global_permission_codes = _to_permission_codes(
            await self._repository.list_global_permissions_for_user(user_id)
        )
        department_roles = await self._repository.list_department_role_codes_for_user(
            user_id
        )
        department_permissions = (
            await self._repository.list_department_permissions_for_user(user_id)
        )

        department_codes = sorted(
            set(department_roles.keys()) | set(department_permissions.keys())
        )
        department_scopes = [
            DepartmentPermissionScope(
                department_code=department_code,
                role_codes=department_roles.get(department_code, []),
                permission_codes=_to_permission_codes(
                    department_permissions.get(department_code, set())
                ),
            )
            for department_code in department_codes
        ]

        return EffectivePermissionSet(
            user_id=user_id,
            global_role_codes=global_role_codes,
            global_permission_codes=global_permission_codes,
            department_scopes=department_scopes,
        )


def _to_permission_codes(raw_codes: set[str]) -> set[PermissionCode]:
    result: set[PermissionCode] = set()
    for raw_code in raw_codes:
        try:
            result.add(PermissionCode(raw_code))
        except ValueError:
            continue
    return result


__all__ = ["PermissionService"]
