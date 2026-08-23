from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.db.auth_tables import (
    PermissionTable,
    RolePermissionTable,
    RoleTable,
    UserDepartmentRoleTable,
    UserPermissionGrantTable,
    UserRoleTable,
)


class PermissionRepository:
    """权限模块 PostgreSQL 仓储。

    它只负责查询权限事实表，不在这里实现业务裁决。工具能不能调用由
    PermissionService 和 AgentToolPermissionService 决定。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_global_roles_for_user(self, user_id: str) -> list[str]:
        stmt: Select[tuple[str]] = (
            select(RoleTable.code)
            .join(UserRoleTable, UserRoleTable.role_id == RoleTable.id)
            .where(UserRoleTable.user_id == user_id)
            .order_by(RoleTable.code.asc())
        )
        return list((await self._session.scalars(stmt)).all())

    async def list_global_permissions_for_user(self, user_id: str) -> set[str]:
        stmt: Select[tuple[str]] = (
            select(PermissionTable.code)
            .join(RolePermissionTable, RolePermissionTable.permission_id == PermissionTable.id)
            .join(RoleTable, RoleTable.id == RolePermissionTable.role_id)
            .join(UserRoleTable, UserRoleTable.role_id == RoleTable.id)
            .where(UserRoleTable.user_id == user_id)
        )
        return set((await self._session.scalars(stmt)).all())

    async def list_direct_permissions_for_user(self, user_id: str) -> set[str]:
        """读取用户当前 active 的直接功能权限，不包含角色展开结果。"""

        stmt: Select[tuple[str]] = (
            select(PermissionTable.code)
            .join(
                UserPermissionGrantTable,
                UserPermissionGrantTable.permission_id == PermissionTable.id,
            )
            .where(
                UserPermissionGrantTable.user_id == user_id,
                UserPermissionGrantTable.status == "active",
                UserPermissionGrantTable.revoked_at.is_(None),
            )
        )
        return set((await self._session.scalars(stmt)).all())

    async def list_department_role_codes_for_user(
        self,
        user_id: str,
    ) -> dict[str, list[str]]:
        stmt: Select[tuple[str, str]] = (
            select(UserDepartmentRoleTable.department_code, RoleTable.code)
            .join(RoleTable, RoleTable.id == UserDepartmentRoleTable.role_id)
            .where(UserDepartmentRoleTable.user_id == user_id)
            .order_by(
                UserDepartmentRoleTable.department_code.asc(),
                RoleTable.code.asc(),
            )
        )
        rows = (await self._session.execute(stmt)).all()
        result: dict[str, list[str]] = {}
        for department_code, role_code in rows:
            result.setdefault(department_code, []).append(role_code)
        return result

    async def list_department_permissions_for_user(
        self,
        user_id: str,
    ) -> dict[str, set[str]]:
        stmt: Select[tuple[str, str]] = (
            select(UserDepartmentRoleTable.department_code, PermissionTable.code)
            .join(RoleTable, RoleTable.id == UserDepartmentRoleTable.role_id)
            .join(RolePermissionTable, RolePermissionTable.role_id == RoleTable.id)
            .join(PermissionTable, PermissionTable.id == RolePermissionTable.permission_id)
            .where(UserDepartmentRoleTable.user_id == user_id)
        )
        rows = (await self._session.execute(stmt)).all()
        result: dict[str, set[str]] = {}
        for department_code, permission_code in rows:
            result.setdefault(department_code, set()).add(permission_code)
        return result

    async def add_user_role(self, user_id: str, role_code: str) -> None:
        role = await self._get_role_by_code(role_code)
        row = UserRoleTable(
            id=f"user_role_{uuid4().hex}",
            user_id=user_id,
            role_id=role.id,
        )
        self._session.add(row)
        await self._commit_or_rollback()

    async def add_user_department_role(
        self,
        user_id: str,
        department_code: str,
        role_code: str,
    ) -> None:
        role = await self._get_role_by_code(role_code)
        row = UserDepartmentRoleTable(
            id=f"user_dept_role_{uuid4().hex}",
            user_id=user_id,
            department_code=department_code,
            role_id=role.id,
        )
        self._session.add(row)
        await self._commit_or_rollback()

    async def add_user_permission(
        self,
        user_id: str,
        permission_code: str,
        *,
        granted_by_user_id: str,
    ) -> None:
        """新增一条 active 用户直接权限；管理接口负责更高层幂等策略。"""

        permission = await self._get_permission_by_code(permission_code)
        row = UserPermissionGrantTable(
            id=f"user_permission_{uuid4().hex}",
            user_id=user_id,
            permission_id=permission.id,
            granted_by_user_id=granted_by_user_id,
        )
        self._session.add(row)
        await self._commit_or_rollback()

    async def _get_role_by_code(self, role_code: str) -> RoleTable:
        stmt: Select[tuple[RoleTable]] = select(RoleTable).where(
            RoleTable.code == role_code
        )
        row = await self._session.scalar(stmt)
        if row is None:
            raise ValueError(f"未知角色: {role_code}")
        return row

    async def _get_permission_by_code(self, permission_code: str) -> PermissionTable:
        stmt: Select[tuple[PermissionTable]] = select(PermissionTable).where(
            PermissionTable.code == permission_code
        )
        row = await self._session.scalar(stmt)
        if row is None:
            raise ValueError(f"未知权限: {permission_code}")
        return row

    async def _commit_or_rollback(self) -> None:
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise


__all__ = ["PermissionRepository"]
