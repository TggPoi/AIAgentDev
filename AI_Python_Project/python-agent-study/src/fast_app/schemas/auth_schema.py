from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    """登录请求体：接收用户名/邮箱和密码，用于换取 access token 与 refresh token。"""

    username_or_email: str = Field(
        min_length=1,
        max_length=255,
        description="登录账号，可以是 username 或 email。",
    )
    password: str = Field(min_length=1, max_length=256, description="登录密码明文，只用于本次认证。")

    @field_validator("username_or_email")
    @classmethod
    def normalize_username_or_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("username_or_email 不能只包含空白字符")

        return normalized


class RefreshTokenRequest(BaseModel):
    """刷新 token 请求体：客户端提交 refresh token，用于轮换新的登录凭证。"""

    refresh_token: str = Field(min_length=1, description="客户端持有的 refresh token。")


class TokenPairResponse(BaseModel):
    """登录或刷新成功后的响应体：同时返回短期 access token 和长期 refresh token。"""

    access_token: str = Field(description="短期访问 token，用于 Authorization Bearer。")
    refresh_token: str = Field(description="长期刷新 token，用于换取新的 access token。")
    token_type: str = Field(default="bearer", description="token 类型，当前固定为 bearer。")
    expires_in: int = Field(description="access token 剩余有效秒数。")


class CurrentUserResponse(BaseModel):
    """当前用户响应体：把认证依赖解析出的用户身份返回给调用方。"""

    user_id: str = Field(description="当前用户 ID。")
    is_authenticated: bool = Field(description="当前请求是否已通过认证。")
    auth_source: str = Field(description="认证来源，例如数据库 jwt / api_key。")
    global_role_codes: list[str] = Field(
        default_factory=list,
        description="当前用户由 user_roles 提供的全局 RBAC 角色 code 列表。",
    )
    global_permission_codes: list[str] = Field(
        default_factory=list,
        description="当前用户由全局 RBAC 角色实时展开的权限 code 列表。",
    )
    department_codes: list[str] = Field(default_factory=list, description="当前用户可访问的部门 code 列表。")
    primary_department_code: str | None = Field(default=None, description="当前用户主归属部门 code。")
    email: str | None = Field(default=None, description="当前用户邮箱。")
    display_name: str | None = Field(default=None, description="当前用户展示名称。")
    token_id: str | None = Field(default=None, description="当前 JWT token ID；非 JWT 认证时为空。")
    api_key_id: str | None = Field(default=None, description="当前 API Key ID；非 API Key 认证时为空。")


class CreateApiKeyRequest(BaseModel):
    """创建 API Key 请求体：接收凭证名称和可选过期时间。"""

    name: str = Field(min_length=1, max_length=128, description="API Key 可读名称。")
    expires_at: datetime | None = Field(default=None, description="API Key 过期时间；为空表示不过期。")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name 不能只包含空白字符")

        return normalized


class CreateApiKeyResponse(BaseModel):
    """创建 API Key 响应体：只在创建时返回一次完整明文 api_key。"""

    id: str = Field(description="新建 API Key 记录 ID。")
    name: str = Field(description="API Key 可读名称。")
    api_key: str = Field(description="完整明文 API Key，只在创建成功时返回一次。")
    key_prefix: str = Field(description="API Key 前缀，用于展示和定位。")
    key_fingerprint: str = Field(description="API Key 指纹，用于审计。")
    expires_at: datetime | None = Field(default=None, description="API Key 过期时间；为空表示不过期。")


class ApiKeySummary(BaseModel):
    """API Key 列表项：只展示可审计的摘要信息，不返回明文密钥。"""

    id: str = Field(description="API Key 记录 ID。")
    name: str = Field(description="API Key 可读名称。")
    key_prefix: str = Field(description="API Key 前缀，用于展示和定位。")
    key_fingerprint: str = Field(description="API Key 指纹，用于审计。")
    status: str = Field(description="API Key 当前状态。")
    expires_at: datetime | None = Field(default=None, description="API Key 过期时间；为空表示不过期。")
    last_used_at: datetime | None = Field(default=None, description="API Key 最近一次使用时间。")
    created_at: datetime | None = Field(default=None, description="API Key 创建时间。")
    revoked_at: datetime | None = Field(default=None, description="API Key 撤销时间；未撤销时为空。")


class RevokeApiKeyResponse(BaseModel):
    """撤销 API Key 响应体：告诉调用方目标凭证是否已被撤销。"""

    api_key_id: str = Field(description="被撤销的 API Key 记录 ID。")
    revoked: bool = Field(description="目标 API Key 是否已成功撤销。")


__all__ = [
    "ApiKeySummary",
    "CreateApiKeyRequest",
    "CreateApiKeyResponse",
    "CurrentUserResponse",
    "LoginRequest",
    "RefreshTokenRequest",
    "RevokeApiKeyResponse",
    "TokenPairResponse",
]
