from fastapi import Depends, Header

from fast_app.core.config import Settings, get_settings
from fast_app.dependencies.rag_dependencies import get_auth_service
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.auth.auth_service import AuthService
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

    bearer_token = _extract_bearer_token(authorization)
    if bearer_token is not None:
        try:
            jwt_user = await auth_service.authenticate_jwt(bearer_token)
        except AuthenticationError:
            jwt_user = None

        if jwt_user is not None:
            return jwt_user

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


def _normalize_header_value(value: object) -> str | None:
    """把 FastAPI Header 解析结果收窄成字符串或 None。

    Header 理论上会返回字符串，但这里显式做类型保护，避免异常值继续进入认证逻辑。
    """

    return value if isinstance(value, str) else None


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
