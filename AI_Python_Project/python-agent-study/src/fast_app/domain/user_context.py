from typing import Literal

from pydantic import BaseModel, Field


class CurrentUserContext(BaseModel):
    """当前请求的用户上下文。

    阶段 14-9 只建立会话隔离边界；这里的 demo_header 不是完整认证，
    后续阶段 15 可以把来源替换成 API Key / Bearer Token。
    """

    user_id: str = Field(min_length=1, max_length=128)
    is_authenticated: bool = False
    auth_source: Literal["anonymous", "demo_header"] = "anonymous"


__all__ = ["CurrentUserContext"]
