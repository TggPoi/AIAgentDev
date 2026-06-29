from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fast_app.core.config import Settings
from fast_app.domain.auth_models import (
    ApiKeyCredential,
    AuthUser,
    CreatedApiKey,
    CredentialStatus,
    JwtTokenPair,
    RefreshTokenRecord,
    UserRole,
    UserStatus,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.auth_crypto import (
    build_api_key_prefix,
    fingerprint_api_key,
    generate_api_key,
    generate_refresh_token,
    generate_token_id,
    generate_user_id,
    hash_api_key,
    hash_password,
    hash_refresh_token,
    verify_api_key_hash,
    verify_password,
)
from fast_app.services.exceptions import AppServiceError, AuthenticationError
from fast_app.services.jwt_service import JwtService
from fast_app.services.user_repository import UserRepository


class AuthService:
    """认证业务服务。

    它把数据库用户、密码哈希、API Key 和 JWT 组合成统一的 CurrentUserContext。
    RAG / Agent 主链路只依赖这个上下文，不关心认证协议细节。
    """

    def __init__(
        self,
        settings: Settings,
        repository: UserRepository,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._jwt_service = JwtService(settings)

    async def create_user(
        self,
        username: str,
        password: str,
        email: str | None = None,
        display_name: str | None = None,
        role: UserRole = UserRole.USER,
        permissions: list[str] | None = None,
    ) -> AuthUser:
        """创建用户，主要供初始化脚本或后续管理接口复用。"""

        now = datetime.now(UTC)
        user = AuthUser(
            id=generate_user_id(),
            username=username.strip().lower(),
            email=email.strip().lower() if email else None,
            display_name=display_name.strip() if display_name else None,
            password_hash=hash_password(password),
            role=role,
            status=UserStatus.ACTIVE,
            permissions=permissions or [],
            created_at=now,
            updated_at=now,
        )
        return await self._repository.create_user(user)

    async def login(
        self,
        username_or_email: str,
        password: str,
    ) -> JwtTokenPair:
        """校验用户名/邮箱和密码，成功后签发 token pair。"""

        user = await self._repository.get_user_by_username_or_email(
            username_or_email
        )
        if user is None or not verify_password(password, user.password_hash):
            raise AuthenticationError("用户名或密码不正确")

        self._ensure_active_user(user)
        await self._repository.update_last_login_at(user.id)
        return await self._issue_token_pair(user)

    async def refresh(self, refresh_token: str) -> JwtTokenPair:
        """使用 refresh token 轮换并签发新的 token pair。"""

        token_hash = hash_refresh_token(refresh_token, self._settings.api_key_pepper)
        record = await self._repository.get_refresh_token_by_hash(token_hash)
        if record is None:
            raise AuthenticationError("Refresh token 无效")

        self._ensure_active_credential(
            status=record.status,
            expires_at=record.expires_at,
            message="Refresh token 无效或已过期",
        )
        user = await self._repository.get_user_by_id(record.user_id)
        if user is None:
            raise AuthenticationError("Refresh token 对应用户不存在")

        self._ensure_active_user(user)
        await self._repository.mark_refresh_token_used(record.id)
        await self._repository.revoke_refresh_token(record.id)
        return await self._issue_token_pair(user)

    async def authenticate_api_key(
        self,
        raw_api_key: str,
    ) -> CurrentUserContext | None:
        """认证数据库 API Key，失败时返回 None。"""

        normalized = raw_api_key.strip()
        if not normalized:
            return None

        fingerprint = fingerprint_api_key(normalized)
        credential = await self._repository.get_api_key_by_fingerprint(fingerprint)
        if credential is None:
            return None

        if not verify_api_key_hash(
            normalized,
            credential.key_hash,
            self._settings.api_key_pepper,
        ):
            return None

        self._ensure_active_credential(
            status=credential.status,
            expires_at=credential.expires_at,
            message="API Key 无效或已过期",
        )
        user = await self._repository.get_user_by_id(credential.user_id)
        if user is None:
            raise AuthenticationError("API Key 对应用户不存在")

        self._ensure_active_user(user)
        await self._repository.update_api_key_last_used_at(credential.id)
        return self.build_current_user_context(
            user=user,
            auth_source="api_key",
            api_key_id=credential.id,
        )

    async def authenticate_jwt(self, access_token: str) -> CurrentUserContext | None:
        """认证 JWT access token，失败时抛出 AuthenticationError。"""

        normalized = access_token.strip()
        if not normalized:
            return None

        subject = self._jwt_service.decode_access_token(normalized)
        user = await self._repository.get_user_by_id(subject.user_id)
        if user is None:
            raise AuthenticationError("JWT 对应用户不存在")

        self._ensure_active_user(user)
        return self.build_current_user_context(
            user=user,
            auth_source="jwt",
            token_id=subject.token_id,
        )

    async def create_api_key(
        self,
        current_user: CurrentUserContext,
        name: str,
        expires_at: datetime | None = None,
    ) -> CreatedApiKey:
        """为当前用户创建 API Key，并只返回一次原始 key。"""

        if not current_user.is_authenticated:
            raise AuthenticationError("只有认证用户才能创建 API Key")

        user = await self._repository.get_user_by_id(current_user.user_id)
        if user is None:
            raise AuthenticationError("当前用户不存在")

        self._ensure_active_user(user)
        raw_api_key = generate_api_key()
        credential = ApiKeyCredential(
            id=generate_token_id(),
            user_id=user.id,
            name=name.strip(),
            key_prefix=build_api_key_prefix(raw_api_key),
            key_fingerprint=fingerprint_api_key(raw_api_key),
            key_hash=hash_api_key(raw_api_key, self._settings.api_key_pepper),
            status=CredentialStatus.ACTIVE,
            expires_at=expires_at,
            created_at=datetime.now(UTC),
        )
        saved = await self._repository.create_api_key(credential)
        return CreatedApiKey(
            id=saved.id,
            name=saved.name,
            api_key=raw_api_key,
            key_prefix=saved.key_prefix,
            key_fingerprint=saved.key_fingerprint,
            expires_at=saved.expires_at,
        )

    async def list_api_keys(
        self,
        current_user: CurrentUserContext,
    ) -> list[ApiKeyCredential]:
        """列出当前用户的 API Key 摘要。"""

        if not current_user.is_authenticated:
            raise AuthenticationError("只有认证用户才能查看 API Key")

        return await self._repository.list_api_keys_for_user(current_user.user_id)

    async def revoke_api_key(
        self,
        current_user: CurrentUserContext,
        api_key_id: str,
    ) -> bool:
        """撤销当前用户自己的 API Key。"""

        if not current_user.is_authenticated:
            raise AuthenticationError("只有认证用户才能撤销 API Key")

        return await self._repository.revoke_api_key(
            user_id=current_user.user_id,
            api_key_id=api_key_id,
        )

    def build_current_user_context(
        self,
        user: AuthUser,
        auth_source: str,
        token_id: str | None = None,
        api_key_id: str | None = None,
    ) -> CurrentUserContext:
        """把真实用户转换成 RAG 主链路使用的统一用户上下文。"""

        return CurrentUserContext(
            user_id=user.id,
            is_authenticated=True,
            auth_source=auth_source,  # type: ignore[arg-type]
            role=user.role.value,
            permissions=list(user.permissions),
            department_codes=[
                department_code.value
                for department_code in user.department_codes
            ],
            primary_department_code=(
                user.primary_department_code.value
                if user.primary_department_code is not None
                else None
            ),
            email=user.email,
            display_name=user.display_name,
            token_id=token_id,
            api_key_id=api_key_id,
        )

    async def _issue_token_pair(self, user: AuthUser) -> JwtTokenPair:
        """创建新的access token 和 refresh token"""

        access_token, expires_in, _ = self._jwt_service.create_access_token(user)
        refresh_token = generate_refresh_token()
        now = datetime.now(UTC)
        refresh_record = RefreshTokenRecord(
            id=generate_token_id(),
            user_id=user.id,
            token_hash=hash_refresh_token(
                refresh_token,
                self._settings.api_key_pepper,
            ),
            status=CredentialStatus.ACTIVE,
            expires_at=now
            + timedelta(days=self._settings.jwt_refresh_token_expire_days),
            created_at=now,
        )
        await self._repository.create_refresh_token(refresh_record)
        return JwtTokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )

    def _ensure_active_user(self, user: AuthUser) -> None:
        if user.status == UserStatus.ACTIVE:
            return

        raise AuthenticationError("用户已被禁用")

    def _ensure_active_credential(
        self,
        status: CredentialStatus,
        expires_at: datetime | None,
        message: str,
    ) -> None:
        now = datetime.now(UTC)
        if status != CredentialStatus.ACTIVE:
            raise AuthenticationError(message)

        if expires_at is not None and expires_at <= now:
            raise AuthenticationError(message)


def require_permission(
    user: CurrentUserContext,
    permission: str,
) -> None:
    """检查当前用户是否拥有某个权限。

    admin 角色默认通过；更细粒度的权限矩阵放到后续阶段继续扩展。
    """

    if user.role == UserRole.ADMIN.value:
        return

    if permission in user.permissions:
        return

    raise AppServiceError("当前用户没有执行该操作的权限")


__all__ = ["AuthService", "require_permission"]
