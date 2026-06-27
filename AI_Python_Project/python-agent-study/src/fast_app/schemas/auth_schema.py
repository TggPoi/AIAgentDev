from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    """登录请求体：接收用户名/邮箱和密码，用于换取 access token 与 refresh token。"""

    username_or_email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("username_or_email")
    @classmethod
    def normalize_username_or_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("username_or_email 不能只包含空白字符")

        return normalized


class RefreshTokenRequest(BaseModel):
    """刷新 token 请求体：客户端提交 refresh token，用于轮换新的登录凭证。"""

    refresh_token: str = Field(min_length=1)


class TokenPairResponse(BaseModel):
    """登录或刷新成功后的响应体：同时返回短期 access token 和长期 refresh token。"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class CurrentUserResponse(BaseModel):
    """当前用户响应体：把认证依赖解析出的用户身份返回给调用方。"""

    user_id: str
    is_authenticated: bool
    auth_source: str
    role: str | None = None
    permissions: list[str] = Field(default_factory=list)
    email: str | None = None
    display_name: str | None = None
    token_id: str | None = None
    api_key_id: str | None = None


class CreateApiKeyRequest(BaseModel):
    """创建 API Key 请求体：接收凭证名称和可选过期时间。"""

    name: str = Field(min_length=1, max_length=128)
    expires_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name 不能只包含空白字符")

        return normalized


class CreateApiKeyResponse(BaseModel):
    """创建 API Key 响应体：只在创建时返回一次完整明文 api_key。"""

    id: str
    name: str
    api_key: str
    key_prefix: str
    key_fingerprint: str
    expires_at: datetime | None = None


class ApiKeySummary(BaseModel):
    """API Key 列表项：只展示可审计的摘要信息，不返回明文密钥。"""

    id: str
    name: str
    key_prefix: str
    key_fingerprint: str
    status: str
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime | None = None
    revoked_at: datetime | None = None


class RevokeApiKeyResponse(BaseModel):
    """撤销 API Key 响应体：告诉调用方目标凭证是否已被撤销。"""

    api_key_id: str
    revoked: bool


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
