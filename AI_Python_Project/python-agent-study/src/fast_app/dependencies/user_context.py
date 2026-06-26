import hashlib
import secrets

from fastapi import Depends, Header

from fast_app.core.config import Settings, get_settings
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.exceptions import AppServiceError, AuthenticationError


API_KEY_HEADER = "X-API-Key"
AUTHORIZATION_HEADER = "Authorization"
DEMO_USER_HEADER = "X-Demo-User-Id"
DEFAULT_ANONYMOUS_USER_ID = "anonymous"


def get_current_user_context(
    settings: Settings = Depends(get_settings),
    x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
    authorization: str | None = Header(default=None, alias=AUTHORIZATION_HEADER),
    x_demo_user_id: str | None = Header(default=None, alias=DEMO_USER_HEADER),
) -> CurrentUserContext:
    """解析并校验当前请求用户。

    AUTH_ENABLED=false 时保留本地匿名/演示用户。
    AUTH_ENABLED=true 时优先校验 X-API-Key 或 Authorization: Bearer。
    """

    x_api_key = _normalize_header_value(x_api_key)
    authorization = _normalize_header_value(authorization)
    x_demo_user_id = _normalize_header_value(x_demo_user_id)

    api_key_user = _authenticate_api_key(
        candidate=x_api_key,
        allowed_values=settings.auth_api_key_list,
    )
    if api_key_user is not None:
        return api_key_user

    bearer_user = _authenticate_bearer_token(
        authorization=authorization,
        allowed_values=settings.auth_bearer_token_list,
    )
    if bearer_user is not None:
        return bearer_user

    if x_demo_user_id is not None and (
        not settings.auth_enabled or settings.auth_allow_demo_user_header
    ):
        return _build_demo_user_context(x_demo_user_id)

    if settings.auth_enabled:
        raise AuthenticationError(
            f"认证失败，请提供有效的 {API_KEY_HEADER} 或 Bearer Token"
        )

    return CurrentUserContext(
        user_id=DEFAULT_ANONYMOUS_USER_ID,
        is_authenticated=False,
        auth_source="anonymous",
    )


def _authenticate_api_key(
    candidate: str | None,
    allowed_values: list[str],
) -> CurrentUserContext | None:
    if candidate is None:
        return None

    normalized = candidate.strip()
    if not normalized:
        return None

    if not _matches_any_secret(normalized, allowed_values):
        return None

    return CurrentUserContext(
        user_id=_build_credential_user_id("api_key", normalized),
        is_authenticated=True,
        auth_source="api_key",
    )


def _normalize_header_value(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _authenticate_bearer_token(
    authorization: str | None,
    allowed_values: list[str],
) -> CurrentUserContext | None:
    token = _extract_bearer_token(authorization)
    if token is None:
        return None

    if not _matches_any_secret(token, allowed_values):
        return None

    return CurrentUserContext(
        user_id=_build_credential_user_id("bearer", token),
        is_authenticated=True,
        auth_source="bearer_token",
    )


def _extract_bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None

    parts = authorization.strip().split(None, 1)
    if len(parts) != 2:
        return None

    scheme, token = parts
    if scheme.lower() != "bearer":
        return None

    normalized = token.strip()
    return normalized or None


def _build_demo_user_context(x_demo_user_id: str) -> CurrentUserContext:
    user_id = x_demo_user_id.strip()
    if not user_id:
        raise AppServiceError(f"{DEMO_USER_HEADER} 不能只包含空白字符")

    if len(user_id) > 128:
        raise AppServiceError(f"{DEMO_USER_HEADER} 长度不能超过 128")

    return CurrentUserContext(
        user_id=user_id,
        is_authenticated=False,
        auth_source="demo_header",
    )


def _matches_any_secret(candidate: str, allowed_values: list[str]) -> bool:
    return any(
        secrets.compare_digest(candidate, allowed_value)
        for allowed_value in allowed_values
    )


def _build_credential_user_id(prefix: str, credential: str) -> str:
    fingerprint = hashlib.sha256(credential.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{fingerprint}"


def get_anonymous_user_context() -> CurrentUserContext:
    """构造匿名用户上下文，便于脚本或单元测试直接复用。"""

    return CurrentUserContext(
        user_id=DEFAULT_ANONYMOUS_USER_ID,
        is_authenticated=False,
        auth_source="anonymous",
    )


def get_demo_user_context(x_demo_user_id: str | None) -> CurrentUserContext:
    """构造 demo 用户上下文，便于保留阶段 14-9 的本地隔离测试。"""

    if x_demo_user_id is None:
        return CurrentUserContext(
            user_id=DEFAULT_ANONYMOUS_USER_ID,
            is_authenticated=False,
            auth_source="anonymous",
        )

    return _build_demo_user_context(x_demo_user_id)


__all__ = [
    "API_KEY_HEADER",
    "AUTHORIZATION_HEADER",
    "DEFAULT_ANONYMOUS_USER_ID",
    "DEMO_USER_HEADER",
    "get_anonymous_user_context",
    "get_current_user_context",
    "get_demo_user_context",
]
