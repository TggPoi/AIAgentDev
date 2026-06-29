from typing import Literal

from pydantic import BaseModel, Field


AuthSource = Literal["anonymous", "demo_header", "api_key", "bearer_token", "jwt"]


class CurrentUserContext(BaseModel):
    """当前请求的用户上下文。

    阶段 15-1 后，RAG 主接口优先通过 API Key / Bearer Token 生成可信用户。
    阶段 15-2 后，数据库 API Key / JWT 会继续补充 role 和 permissions。
    demo_header 只保留给本地学习和阶段 14-9 的隔离验证。
    """

    user_id: str = Field(min_length=1, max_length=128)
    is_authenticated: bool = False
    auth_source: AuthSource = "anonymous"
    role: str | None = None
    permissions: list[str] = Field(default_factory=list)
    # 权限范围字段，参与知识库检索权限判断，一个用户可以拥有多个部门权限
    department_codes: list[str] = Field(default_factory=list)
    # 主归属字段，表达用户默认部门，目前不参与检索权限判断 为后续扩展留边界保留
    primary_department_code: str | None = None
    email: str | None = None
    display_name: str | None = None
    token_id: str | None = None
    api_key_id: str | None = None


__all__ = ["AuthSource", "CurrentUserContext"]
