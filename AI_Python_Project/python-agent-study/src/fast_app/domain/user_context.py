from typing import Literal

from pydantic import BaseModel, Field


AuthSource = Literal["anonymous", "demo_header", "api_key", "bearer_token"]


class CurrentUserContext(BaseModel):
    """当前请求的用户上下文。

    阶段 15-1 后，RAG 主接口优先通过 API Key / Bearer Token 生成可信用户。
    demo_header 只保留给本地学习和阶段 14-9 的隔离验证。
    """

    user_id: str = Field(min_length=1, max_length=128)
    is_authenticated: bool = False
    auth_source: AuthSource = "anonymous"


__all__ = ["AuthSource", "CurrentUserContext"]
