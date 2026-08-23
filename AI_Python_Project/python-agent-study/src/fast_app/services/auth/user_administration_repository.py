from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Select, and_, delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.db.auth_tables import (
    ApiKeyTable,
    DepartmentTable,
    PermissionTable,
    RefreshTokenTable,
    RoleTable,
    UserAdministrationAuditTable,
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
            if department_code:
                stmt = stmt.where(
                    ~exists(
                        select(UserDepartmentTable.id).where(
                            UserDepartmentTable.user_id == UserTable.id,
                            UserDepartmentTable.department_code
                            != department_code,
                        )
                    )
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

    async def get_user_for_update(self, user_id: str) -> UserTable | None:
        stmt: Select[tuple[UserTable]] = (
            select(UserTable)
            .where(UserTable.id == user_id)
            .with_for_update()
        )
        return await self._session.scalar(stmt)

    async def get_departments_by_codes(
        self,
        codes: set[str],
    ) -> dict[str, DepartmentTable]:
        if not codes:
            return {}
        rows = (
            await self._session.scalars(
                select(DepartmentTable).where(DepartmentTable.code.in_(codes))
            )
        ).all()
        return {row.code: row for row in rows}

    async def get_roles_by_codes(self, codes: set[str]) -> dict[str, RoleTable]:
        if not codes:
            return {}
        rows = (
            await self._session.scalars(
                select(RoleTable).where(RoleTable.code.in_(codes))
            )
        ).all()
        return {row.code: row for row in rows}

    async def get_permissions_by_codes(
        self,
        codes: set[str],
    ) -> dict[str, PermissionTable]:
        if not codes:
            return {}
        rows = (
            await self._session.scalars(
                select(PermissionTable).where(PermissionTable.code.in_(codes))
            )
        ).all()
        return {row.code: row for row in rows}

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

    async def create_user(
        self,
        *,
        user_id: str,
        username: str,
        email: str | None,
        display_name: str | None,
        password_hash: str,
    ) -> UserTable:
        now = datetime.now(UTC)
        row = UserTable(
            id=user_id,
            username=username,
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            status="active",
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def replace_system_admin_role(
        self,
        *,
        user_id: str,
        enabled: bool,
        role: RoleTable,
    ) -> None:
        stmt: Select[tuple[UserRoleTable]] = select(UserRoleTable).where(
            UserRoleTable.user_id == user_id,
            UserRoleTable.role_id == role.id,
        )
        current = await self._session.scalar(stmt)
        if enabled and current is None:
            self._session.add(
                UserRoleTable(
                    id=f"user_role_{uuid4().hex}",
                    user_id=user_id,
                    role_id=role.id,
                )
            )
        elif not enabled and current is not None:
            await self._session.delete(current)

    async def replace_department_access(
        self,
        *,
        user_id: str,
        departments: list[tuple[str, bool, set[str]]],
        roles_by_code: dict[str, RoleTable],
    ) -> None:
        await self._session.execute(
            delete(UserDepartmentRoleTable).where(
                UserDepartmentRoleTable.user_id == user_id
            )
        )
        await self._session.execute(
            delete(UserDepartmentTable).where(
                UserDepartmentTable.user_id == user_id
            )
        )
        for department_code, is_primary, role_codes in departments:
            self._session.add(
                UserDepartmentTable(
                    id=f"user_dept_{uuid4().hex}",
                    user_id=user_id,
                    department_code=department_code,
                    is_primary=is_primary,
                )
            )
            for role_code in sorted(role_codes):
                self._session.add(
                    UserDepartmentRoleTable(
                        id=f"user_dept_role_{uuid4().hex}",
                        user_id=user_id,
                        department_code=department_code,
                        role_id=roles_by_code[role_code].id,
                    )
                )

    async def replace_direct_permissions(
        self,
        *,
        user_id: str,
        permission_codes: set[str],
        permissions_by_code: dict[str, PermissionTable],
        actor_user_id: str,
    ) -> None:
        stmt: Select[tuple[UserPermissionGrantTable, str]] = (
            select(UserPermissionGrantTable, PermissionTable.code)
            .join(
                PermissionTable,
                PermissionTable.id == UserPermissionGrantTable.permission_id,
            )
            .where(
                UserPermissionGrantTable.user_id == user_id,
                UserPermissionGrantTable.status == "active",
                UserPermissionGrantTable.revoked_at.is_(None),
            )
        )
        rows = (await self._session.execute(stmt)).all()
        active_by_code = {code: grant for grant, code in rows}
        now = datetime.now(UTC)
        for code, grant in active_by_code.items():
            if code not in permission_codes:
                grant.status = "revoked"
                grant.revoked_by_user_id = actor_user_id
                grant.revoked_at = now
        for code in sorted(permission_codes - set(active_by_code)):
            self._session.add(
                UserPermissionGrantTable(
                    id=f"user_permission_{uuid4().hex}",
                    user_id=user_id,
                    permission_id=permissions_by_code[code].id,
                    granted_by_user_id=actor_user_id,
                )
            )

    async def update_user_status(
        self,
        row: UserTable,
        status: str,
    ) -> None:
        row.status = status
        row.updated_at = datetime.now(UTC)

    async def update_password_hash(
        self,
        row: UserTable,
        password_hash: str,
    ) -> None:
        row.password_hash = password_hash
        row.updated_at = datetime.now(UTC)

    async def revoke_active_credentials(self, user_id: str) -> tuple[int, int]:
        now = datetime.now(UTC)
        refresh_result = await self._session.execute(
            update(RefreshTokenTable)
            .where(
                RefreshTokenTable.user_id == user_id,
                RefreshTokenTable.status == "active",
            )
            .values(status="revoked", revoked_at=now)
        )
        api_key_result = await self._session.execute(
            update(ApiKeyTable)
            .where(
                ApiKeyTable.user_id == user_id,
                ApiKeyTable.status == "active",
            )
            .values(status="revoked", revoked_at=now)
        )
        return int(refresh_result.rowcount or 0), int(api_key_result.rowcount or 0)

    async def lock_system_admin_role(self) -> RoleTable:
        stmt: Select[tuple[RoleTable]] = (
            select(RoleTable)
            .where(RoleTable.code == "system_admin")
            .with_for_update()
        )
        row = await self._session.scalar(stmt)
        if row is None:
            raise RuntimeError("系统缺少 system_admin 角色")
        return row

    async def count_active_system_admins(self, role_id: str) -> int:
        count = await self._session.scalar(
            select(func.count(UserRoleTable.id))
            .join(UserTable, UserTable.id == UserRoleTable.user_id)
            .where(
                UserRoleTable.role_id == role_id,
                UserTable.status == "active",
            )
        )
        return int(count or 0)

    async def add_audit(
        self,
        *,
        action: str,
        actor_user_id: str,
        target_user_id: str,
        request_id: str | None,
        details: dict[str, object],
    ) -> None:
        self._session.add(
            UserAdministrationAuditTable(
                id=f"user_admin_audit_{uuid4().hex}",
                action=action,
                actor_user_id=actor_user_id,
                target_user_id=target_user_id,
                request_id=request_id,
                details_json=details,
            )
        )

    async def touch_user(self, row: UserTable) -> None:
        row.updated_at = datetime.now(UTC)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


__all__ = ["UserAdministrationRepository"]
