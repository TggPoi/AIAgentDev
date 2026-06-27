import hashlib
import secrets

from fastapi import Depends, Header

from fast_app.core.config import Settings, get_settings
from fast_app.dependencies.rag_dependencies import get_auth_service
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.auth_service import AuthService
from fast_app.services.exceptions import AppServiceError, AuthenticationError


API_KEY_HEADER = "X-API-Key"
AUTHORIZATION_HEADER = "Authorization"
DEMO_USER_HEADER = "X-Demo-User-Id"
DEFAULT_ANONYMOUS_USER_ID = "anonymous"


async def get_current_user_context(
    settings: Settings = Depends(get_settings),
    auth_service: AuthService = Depends(get_auth_service),
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

    if x_api_key is not None:
        api_key_user = await auth_service.authenticate_api_key(x_api_key)
        if api_key_user is not None:
            return api_key_user

    api_key_user = _authenticate_legacy_api_key(
        candidate=x_api_key,
        allowed_values=settings.auth_api_key_list,
    )
    if api_key_user is not None:
        return api_key_user

    bearer_token = _extract_bearer_token(authorization)
    if bearer_token is not None:
        try:
            jwt_user = await auth_service.authenticate_jwt(bearer_token)
        except AuthenticationError:
            jwt_user = None

        if jwt_user is not None:
            return jwt_user

        bearer_user = _authenticate_legacy_bearer_token(
            token=bearer_token,
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


def _authenticate_legacy_api_key(
    candidate: str | None,
    allowed_values: list[str],
) -> CurrentUserContext | None:
    """兼容阶段 15-1 的静态 API Key 白名单认证。

    阶段 15-2 已经接入数据库 API Key，这个函数只负责保留旧的
    AUTH_API_KEYS 配置方式，方便本地开发或迁移期间继续使用静态密钥。
    """

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
    """把 FastAPI Header 解析结果收窄成字符串或 None。

    Header 理论上会返回字符串，但这里显式做类型保护，避免异常值继续进入认证逻辑。
    """

    return value if isinstance(value, str) else None


def _authenticate_legacy_bearer_token(
    token: str,
    allowed_values: list[str],
) -> CurrentUserContext | None:
    """兼容阶段 15-1 的静态 Bearer Token 白名单认证。

    数据库 JWT 校验失败后才会走到这里，用于保留 AUTH_BEARER_TOKENS 这种
    早期学习阶段的轻量认证方式。
    """

    if not _matches_any_secret(token, allowed_values):
        return None

    return CurrentUserContext(
        user_id=_build_credential_user_id("bearer", token),
        is_authenticated=True,
        auth_source="bearer_token",
    )


def _extract_bearer_token(authorization: str | None) -> str | None:
    """从 Authorization 请求头中解析 Bearer token。

    只接受标准的 ``Authorization: Bearer <token>`` 形式，其他 scheme 或格式
    都返回 None，让上层继续走后续认证分支。
    """

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
    """根据 X-Demo-User-Id 构造演示用户上下文。

    demo 用户不代表真实登录，只用于本地多用户隔离测试；因此返回的
    is_authenticated 仍然是 False。
    """

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
    """使用恒定时间比较判断候选密钥是否命中白名单。

    ``secrets.compare_digest`` 可以降低普通字符串比较带来的时序侧信道风险。
    """

    return any(
        secrets.compare_digest(candidate, allowed_value)
        for allowed_value in allowed_values
    )


def _build_credential_user_id(prefix: str, credential: str) -> str:
    """为静态凭证生成稳定但不暴露明文的 user_id。

    旧静态 API Key / Bearer Token 没有数据库用户记录，因此使用凭证 hash 前缀
    构造一个可重复识别的演示级 user_id。
    """

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
