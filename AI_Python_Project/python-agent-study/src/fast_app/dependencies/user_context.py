from fastapi import Header

from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.exceptions import AppServiceError


DEMO_USER_HEADER = "X-Demo-User-Id"
DEFAULT_ANONYMOUS_USER_ID = "anonymous"


def get_current_user_context(
    x_demo_user_id: str | None = Header(default=None, alias=DEMO_USER_HEADER),
) -> CurrentUserContext:
    """解析当前请求用户。

    当前阶段只提供演示用 header，目的是让多轮记忆具备 user/session 隔离。
    这不是认证系统；真实 API Key / Bearer Token 应在阶段 15 替换这里。
    """

    if x_demo_user_id is None:
        return CurrentUserContext(
            user_id=DEFAULT_ANONYMOUS_USER_ID,
            is_authenticated=False,
            auth_source="anonymous",
        )

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


__all__ = [
    "DEFAULT_ANONYMOUS_USER_ID",
    "DEMO_USER_HEADER",
    "get_current_user_context",
]
