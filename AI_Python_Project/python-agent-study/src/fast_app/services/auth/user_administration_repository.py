from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.db.auth_tables import (
    DepartmentTable,
    PermissionTable,
    RoleTable,
    UserDepartmentRoleTable,
    UserDepartmentTable,
    UserPermissionGrantTable,
    UserRoleTable,
    UserTable,
)


class UserAdministrationRepository:
    """用户管理模块的 PostgreSQL 事实查询 adapter。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_departments(self, codes: set[str] | None = None) -> list[DepartmentTable]:
        stmt: Select[tuple[DepartmentTable]] = select(DepartmentTable)
        if codes is not None:
            stmt = stmt.where(DepartmentTable.code.in_(codes))
        stmt = stmt.order_by(DepartmentTable.code.asc())
        return list((await self._session.scalars(stmt)).all())

    async def list_permissions(self, codes: set[str]) -> list[PermissionTable]:
        if not codes:
            return []
        stmt: Select[tuple[PermissionTable]] = (
            select(PermissionTable)
            .where(PermissionTable.code.in_(codes))
            .order_by(PermissionTable.category.asc(), PermissionTable.code.asc())
        )
        return list((await self._session.scalars(stmt)).all())

    async def list_roles(self, codes: set[str]) -> list[RoleTable]:
        if not codes:
            return []
        stmt: Select[tuple[RoleTable]] = (
            select(RoleTable)
            .where(RoleTable.code.in_(codes))
            .order_by(RoleTable.code.asc())
        )
        return list((await self._session.scalars(stmt)).all())

    async def list_users(
        self,
        *,
        limit: int,
        query: str | None,
        status: str | None,
        department_code: str | None,
        cursor_updated_at: datetime | None,
        cursor_user_id: str | None,
        employee_only: bool,
    ) -> tuple[list[UserTable], bool]:
        stmt: Select[tuple[UserTable]] = select(UserTable)
        if query:
            pattern = f"%{query}%"
            stmt = stmt.where(
                or_(
                    UserTable.username.ilike(pattern),
                    UserTable.email.ilike(pattern),
                    UserTable.display_name.ilike(pattern),
                )
            )
        if status:
            stmt = stmt.where(UserTable.status == status)
        if department_code:
            stmt = stmt.where(
                exists(
                    select(UserDepartmentTable.id).where(
                        UserDepartmentTable.user_id == UserTable.id,
                        UserDepartmentTable.department_code == department_code,
                    )
                )
            )
        if employee_only:
            stmt = stmt.where(
                ~exists(
                    select(UserRoleTable.id)
                    .join(RoleTable, RoleTable.id == UserRoleTable.role_id)
                    .where(
                        UserRoleTable.user_id == UserTable.id,
                        RoleTable.code == "system_admin",
                    )
                ),
                ~exists(
                    select(UserDepartmentRoleTable.id)
                    .join(
                        RoleTable,
                        RoleTable.id == UserDepartmentRoleTable.role_id,
                    )
                    .where(
                        UserDepartmentRoleTable.user_id == UserTable.id,
                        RoleTable.code == "department_manager",
                    )
                ),
            )
        if cursor_updated_at is not None and cursor_user_id is not None:
            stmt = stmt.where(
                or_(
                    UserTable.updated_at < cursor_updated_at,
                    and_(
                        UserTable.updated_at == cursor_updated_at,
                        UserTable.id < cursor_user_id,
                    ),
                )
            )
        stmt = stmt.order_by(UserTable.updated_at.desc(), UserTable.id.desc()).limit(
            limit + 1
        )
        rows = list((await self._session.scalars(stmt)).all())
        return rows[:limit], len(rows) > limit

    async def get_user(self, user_id: str) -> UserTable | None:
        return await self._session.get(UserTable, user_id)

    async def list_user_departments(
        self,
        user_id: str,
    ) -> list[UserDepartmentTable]:
        stmt: Select[tuple[UserDepartmentTable]] = (
            select(UserDepartmentTable)
            .where(UserDepartmentTable.user_id == user_id)
            .order_by(
                UserDepartmentTable.is_primary.desc(),
                UserDepartmentTable.department_code.asc(),
            )
        )
        return list((await self._session.scalars(stmt)).all())

    async def list_direct_permission_codes(self, user_id: str) -> list[str]:
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
            .order_by(PermissionTable.code.asc())
        )
        return list((await self._session.scalars(stmt)).all())

    async def list_department_role_codes(self, user_id: str) -> dict[str, list[str]]:
        stmt: Select[tuple[str, str]] = (
            select(UserDepartmentRoleTable.department_code, RoleTable.code)
            .join(RoleTable, RoleTable.id == UserDepartmentRoleTable.role_id)
            .where(UserDepartmentRoleTable.user_id == user_id)
            .order_by(
                UserDepartmentRoleTable.department_code.asc(),
                RoleTable.code.asc(),
            )
        )
        result: dict[str, list[str]] = {}
        for department_code, role_code in (await self._session.execute(stmt)).all():
            result.setdefault(department_code, []).append(role_code)
        return result


__all__ = ["UserAdministrationRepository"]
