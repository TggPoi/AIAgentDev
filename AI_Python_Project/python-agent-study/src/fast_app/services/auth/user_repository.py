from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.db.auth_tables import (
    ApiKeyTable,
    DepartmentTable,
    RefreshTokenTable,
    UserDepartmentTable,
    UserTable,
)
from fast_app.domain.auth_models import (
    ApiKeyCredential,
    AuthUser,
    CredentialStatus,
    Department,
    DepartmentCode,
    RefreshTokenRecord,
    UserDepartment,
    UserStatus,
)


class UserRepository:
    """用户、API Key、refresh token 的 PostgreSQL 仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_user(self, user: AuthUser) -> AuthUser:
        """创建用户并返回领域模型。"""

        row = _user_to_table(user)
        self._session.add(row)
        await self._commit_or_rollback()
        return _table_to_user(row)

    async def get_user_by_id(self, user_id: str) -> AuthUser | None:
        """按用户 ID 查询用户。"""

        row = await self._session.get(UserTable, user_id)
        if row is None:
            return None

        return await self._table_to_user_with_departments(row)

    async def get_user_by_username_or_email(
        self,
        username_or_email: str,
    ) -> AuthUser | None:
        """按 username 或 email 查询用户。"""

        normalized = username_or_email.strip().lower()
        stmt: Select[tuple[UserTable]] = select(UserTable).where(
            or_(
                UserTable.username == normalized,
                UserTable.email == normalized,
            )
        )
        row = await self._session.scalar(stmt)
        if row is None:
            return None

        return await self._table_to_user_with_departments(row)

    async def list_departments(self) -> list[Department]:
        """列出系统内所有部门。"""

        stmt: Select[tuple[DepartmentTable]] = select(DepartmentTable).order_by(
            DepartmentTable.code.asc()
        )
        rows = (await self._session.scalars(stmt)).all()
        return [_table_to_department(row) for row in rows]

    async def get_user_department_codes(
        self,
        user_id: str,
    ) -> tuple[list[DepartmentCode], DepartmentCode | None]:
        """查询用户所属部门 code 和主部门。"""

        stmt: Select[tuple[UserDepartmentTable]] = (
            select(UserDepartmentTable)
            .where(UserDepartmentTable.user_id == user_id)
            .order_by(UserDepartmentTable.is_primary.desc(), UserDepartmentTable.department_code.asc())
        )
        rows = (await self._session.scalars(stmt)).all()
        department_codes = [
            DepartmentCode(row.department_code)
            for row in rows
        ]
        primary_department_code = next(
            (
                DepartmentCode(row.department_code)
                for row in rows
                if row.is_primary
            ),
            department_codes[0] if department_codes else None,
        )
        return department_codes, primary_department_code

    async def add_user_department(
        self,
        user_id: str,
        department_code: DepartmentCode,
        is_primary: bool = False,
    ) -> UserDepartment:
        """给用户绑定一个部门。"""

        if is_primary:
            await self._clear_primary_department(user_id)

        row = UserDepartmentTable(
            id=f"user_dept_{user_id}_{department_code.value}",
            user_id=user_id,
            department_code=department_code.value,
            is_primary=is_primary,
        )
        self._session.add(row)
        await self._commit_or_rollback()
        return _table_to_user_department(row)

    async def update_last_login_at(self, user_id: str) -> None:
        """记录用户最近一次登录时间。"""

        row = await self._session.get(UserTable, user_id)
        if row is None:
            return

        # 更新审计字段 处理事务
        row.last_login_at = datetime.now(UTC)
        await self._commit_or_rollback()

    async def create_api_key(
        self,
        credential: ApiKeyCredential,
    ) -> ApiKeyCredential:
        """保存 API Key hash 记录。"""

        row = _api_key_to_table(credential)
        self._session.add(row)
        await self._commit_or_rollback()
        return _table_to_api_key(row)

    async def get_api_key_by_fingerprint(
        self,
        fingerprint: str,
    ) -> ApiKeyCredential | None:
        """按 API Key 指纹查询凭证记录。"""

        stmt: Select[tuple[ApiKeyTable]] = select(ApiKeyTable).where(
            ApiKeyTable.key_fingerprint == fingerprint
        )
        row = await self._session.scalar(stmt)
        return _table_to_api_key(row) if row is not None else None

    async def list_api_keys_for_user(
        self,
        user_id: str,
    ) -> list[ApiKeyCredential]:
        """列出某个用户创建过的 API Key。"""

        stmt: Select[tuple[ApiKeyTable]] = (
            select(ApiKeyTable)
            .where(ApiKeyTable.user_id == user_id)
            .order_by(ApiKeyTable.created_at.desc(), ApiKeyTable.id.desc())
        )
        rows = (await self._session.scalars(stmt)).all()
        return [_table_to_api_key(row) for row in rows]

    async def update_api_key_last_used_at(self, api_key_id: str) -> None:
        """记录 API Key 最近一次使用时间。"""

        row = await self._session.get(ApiKeyTable, api_key_id)
        if row is None:
            return

        row.last_used_at = datetime.now(UTC)
        await self._commit_or_rollback()

    async def revoke_api_key(self, user_id: str, api_key_id: str) -> bool:
        """撤销某个用户自己的 API Key。"""

        stmt: Select[tuple[ApiKeyTable]] = select(ApiKeyTable).where(
            ApiKeyTable.id == api_key_id,
            ApiKeyTable.user_id == user_id,
        )
        row = await self._session.scalar(stmt)
        if row is None:
            return False

        row.status = CredentialStatus.REVOKED.value
        row.revoked_at = datetime.now(UTC)
        await self._commit_or_rollback()
        return True

    async def create_refresh_token(
        self,
        record: RefreshTokenRecord,
    ) -> RefreshTokenRecord:
        """保存 refresh token hash 记录。"""

        row = _refresh_token_to_table(record)
        self._session.add(row)
        await self._commit_or_rollback()
        return _table_to_refresh_token(row)

    async def get_refresh_token_by_hash(
        self,
        token_hash: str,
    ) -> RefreshTokenRecord | None:
        """按 refresh token hash 查询记录。"""

        stmt: Select[tuple[RefreshTokenTable]] = select(RefreshTokenTable).where(
            RefreshTokenTable.token_hash == token_hash
        )
        row = await self._session.scalar(stmt)
        return _table_to_refresh_token(row) if row is not None else None

    async def mark_refresh_token_used(self, token_id: str) -> None:
        """记录 refresh token 最近使用时间。"""

        row = await self._session.get(RefreshTokenTable, token_id)
        if row is None:
            return

        row.last_used_at = datetime.now(UTC)
        await self._commit_or_rollback()

    async def revoke_refresh_token(self, token_id: str) -> None:
        """撤销 refresh token。"""

        row = await self._session.get(RefreshTokenTable, token_id)
        if row is None:
            return

        row.status = CredentialStatus.REVOKED.value
        row.revoked_at = datetime.now(UTC)
        await self._commit_or_rollback()

    # 事务处理
    async def _commit_or_rollback(self) -> None:
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

    async def _clear_primary_department(self, user_id: str) -> None:
        stmt: Select[tuple[UserDepartmentTable]] = select(UserDepartmentTable).where(
            UserDepartmentTable.user_id == user_id,
            UserDepartmentTable.is_primary.is_(True),
        )
        rows = (await self._session.scalars(stmt)).all()
        for row in rows:
            row.is_primary = False

    async def _table_to_user_with_departments(self, row: UserTable) -> AuthUser:
        user = _table_to_user(row)
        department_codes, primary_department_code = await self.get_user_department_codes(
            user.id
        )
        user.department_codes = department_codes
        user.primary_department_code = primary_department_code
        return user


def _user_to_table(user: AuthUser) -> UserTable:
    return UserTable(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        password_hash=user.password_hash,
        status=user.status.value,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )

# 查询到数据库中的ORM对象后，转换为用于认证模块的领域模型
def _table_to_user(row: UserTable) -> AuthUser:
    return AuthUser(
        id=row.id,
        username=row.username,
        email=row.email,
        display_name=row.display_name,
        password_hash=row.password_hash,
        status=UserStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_login_at=row.last_login_at,
    )


def _table_to_department(row: DepartmentTable) -> Department:
    return Department(
        id=row.id,
        code=DepartmentCode(row.code),
        name=row.name,
        description=row.description,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _table_to_user_department(row: UserDepartmentTable) -> UserDepartment:
    return UserDepartment(
        id=row.id,
        user_id=row.user_id,
        department_code=DepartmentCode(row.department_code),
        is_primary=row.is_primary,
        created_at=row.created_at,
    )


def _api_key_to_table(credential: ApiKeyCredential) -> ApiKeyTable:
    return ApiKeyTable(
        id=credential.id,
        user_id=credential.user_id,
        name=credential.name,
        key_prefix=credential.key_prefix,
        key_fingerprint=credential.key_fingerprint,
        key_hash=credential.key_hash,
        status=credential.status.value,
        expires_at=credential.expires_at,
        last_used_at=credential.last_used_at,
        created_at=credential.created_at,
        revoked_at=credential.revoked_at,
    )


def _table_to_api_key(row: ApiKeyTable) -> ApiKeyCredential:
    return ApiKeyCredential(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        key_prefix=row.key_prefix,
        key_fingerprint=row.key_fingerprint,
        key_hash=row.key_hash,
        status=CredentialStatus(row.status),
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
    )


def _refresh_token_to_table(record: RefreshTokenRecord) -> RefreshTokenTable:
    return RefreshTokenTable(
        id=record.id,
        user_id=record.user_id,
        token_hash=record.token_hash,
        status=record.status.value,
        expires_at=record.expires_at,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        revoked_at=record.revoked_at,
        metadata_json=record.metadata,
    )


def _table_to_refresh_token(row: RefreshTokenTable) -> RefreshTokenRecord:
    return RefreshTokenRecord(
        id=row.id,
        user_id=row.user_id,
        token_hash=row.token_hash,
        status=CredentialStatus(row.status),
        expires_at=row.expires_at,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        metadata=row.metadata_json or {},
    )


__all__ = ["UserRepository"]
