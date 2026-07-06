from typing import Literal

from pydantic import BaseModel, Field


AuthSource = Literal["anonymous", "demo_header", "api_key", "bearer_token", "jwt"]


class CurrentUserContext(BaseModel):
    """当前请求的用户上下文。

    阶段 15-1 后，RAG 主接口优先通过 API Key / Bearer Token 生成可信用户。
    阶段 15-2 后，数据库 API Key / JWT 会继续补充 role 和 permissions。
    demo_header 只保留给本地学习和阶段 14-9 的隔离验证。
    """

    user_id: str = Field(min_length=1, max_length=128, description="当前请求用户 ID。")
    is_authenticated: bool = Field(default=False, description="当前请求是否通过可信认证。")
    auth_source: AuthSource = Field(default="anonymous", description="当前用户上下文来源。")
    role: str | None = Field(default=None, description="当前用户角色 code。")
    permissions: list[str] = Field(default_factory=list, description="当前用户拥有的权限 code 列表。")
    department_codes: list[str] = Field(
        default_factory=list,
        description="当前用户可访问的部门 code 列表，用于知识库检索 ACL。",
    )
    primary_department_code: str | None = Field(
        default=None,
        description="当前用户主归属部门 code，目前主要用于展示和后续扩展。",
    )
    email: str | None = Field(default=None, description="当前用户邮箱。")
    display_name: str | None = Field(default=None, description="当前用户展示名称。")
    token_id: str | None = Field(default=None, description="当前 JWT token ID；非 JWT 认证时为空。")
    api_key_id: str | None = Field(default=None, description="当前 API Key ID；非 API Key 认证时为空。")


__all__ = ["AuthSource", "CurrentUserContext"]
