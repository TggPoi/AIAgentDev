from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt

from fast_app.core.config import Settings
from fast_app.domain.auth_models import AuthUser, TokenSubject, UserRole
from fast_app.services.auth.auth_crypto import generate_token_id
from fast_app.services.exceptions import AuthenticationError


class JwtService:
    """封装 JWT access token 的签发和校验。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create_access_token(self, user: AuthUser) -> tuple[str, int, str]:
        """签发短期 access token。

        返回 token、有效秒数和 jti，便于上层写入 CurrentUserContext。
        """

        self._require_jwt_secret()
        issued_at = datetime.now(UTC)
        expires_delta = timedelta(
            minutes=self._settings.jwt_access_token_expire_minutes
        )
        expires_at = issued_at + expires_delta
        token_id = generate_token_id()
        claims = {
            "sub": user.id,
            "role": user.role.value,
            "permissions": list(user.permissions),
            "iss": self._settings.jwt_issuer,
            "aud": self._settings.jwt_audience,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": token_id,
            "typ": "access",
        }
        token = jwt.encode(
            claims,
            self._settings.jwt_secret_key,
            algorithm=self._settings.jwt_algorithm,
        )
        return token, int(expires_delta.total_seconds()), token_id

    def decode_access_token(self, token: str) -> TokenSubject:
        """校验 access token 并提取身份声明。"""

        self._require_jwt_secret()
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret_key,
                algorithms=[self._settings.jwt_algorithm],
                issuer=self._settings.jwt_issuer,
                audience=self._settings.jwt_audience,
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("JWT 校验失败或已过期") from exc

        if payload.get("typ") != "access":
            raise AuthenticationError("JWT 类型不正确")

        user_id = payload.get("sub")
        token_id = payload.get("jti")
        role = payload.get("role")
        exp = payload.get("exp")
        if not isinstance(user_id, str) or not isinstance(token_id, str):
            raise AuthenticationError("JWT 缺少必要身份声明")

        if not isinstance(role, str):
            raise AuthenticationError("JWT 缺少角色声明")

        if not isinstance(exp, int):
            raise AuthenticationError("JWT 缺少过期时间")

        permissions = payload.get("permissions", [])
        if not isinstance(permissions, list):
            permissions = []

        return TokenSubject(
            user_id=user_id,
            role=UserRole(role),
            permissions=[item for item in permissions if isinstance(item, str)],
            token_id=token_id,
            expires_at=datetime.fromtimestamp(exp, UTC),
        )

    def _require_jwt_secret(self) -> None:
        if self._settings.jwt_secret_key.strip():
            return

        raise AuthenticationError("JWT_SECRET_KEY 未配置，无法使用 JWT 认证")


__all__ = ["JwtService"]
