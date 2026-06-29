from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class UserRole(StrEnum):
    """系统内置角色。

    当前阶段先用轻量 role 字段承载权限层级，避免过早引入完整 RBAC 表结构。
    """

    ADMIN = "admin"
    USER = "user"
    VIEWER = "viewer"


class UserStatus(StrEnum):
    """用户账号状态。"""

    ACTIVE = "active"
    DISABLED = "disabled"


class CredentialStatus(StrEnum):
    """API Key / refresh token 的状态。"""

    ACTIVE = "active"
    REVOKED = "revoked"


class DepartmentCode(StrEnum):
    """系统内置部门 code。

    权限字段中使用稳定英文 code，展示层再翻译成中文部门名，避免中文名称调整影响权限判断。
    """

    ART = "art"
    PRODUCT_PLANNING = "product_planning"
    DEVELOPMENT = "development"


class Department(BaseModel):
    """部门领域模型。"""

    id: str
    code: DepartmentCode
    name: str
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UserDepartment(BaseModel):
    """用户与部门的多对多关系。"""

    id: str
    user_id: str
    department_code: DepartmentCode
    is_primary: bool = False
    created_at: datetime | None = None


class AuthUser(BaseModel):
    """认证业务使用的用户领域模型。"""

    id: str
    username: str
    email: str | None = None
    display_name: str | None = None
    password_hash: str
    role: UserRole = UserRole.USER
    status: UserStatus = UserStatus.ACTIVE
    permissions: list[str] = Field(default_factory=list)
    department_codes: list[DepartmentCode] = Field(default_factory=list)
    primary_department_code: DepartmentCode | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_login_at: datetime | None = None


class ApiKeyCredential(BaseModel):
    """API Key 的持久化视图，不包含原始 key。"""

    id: str
    user_id: str
    name: str
    key_prefix: str
    key_fingerprint: str
    key_hash: str
    status: CredentialStatus = CredentialStatus.ACTIVE
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime | None = None
    revoked_at: datetime | None = None


class RefreshTokenRecord(BaseModel):
    """Refresh token 的持久化视图，只保存 hash。"""

    id: str
    user_id: str
    token_hash: str
    status: CredentialStatus = CredentialStatus.ACTIVE
    expires_at: datetime
    created_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class TokenSubject(BaseModel):
    """从 JWT access token 中解析出的核心身份声明。"""

    user_id: str
    role: UserRole
    permissions: list[str] = Field(default_factory=list)
    token_id: str
    expires_at: datetime


class JwtTokenPair(BaseModel):
    """登录或刷新后返回给客户端的 token 组合。"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class CreatedApiKey(BaseModel):
    """创建 API Key 后返回的结果。

    api_key 是唯一一次返回的原始凭证，数据库只保存 hash / fingerprint。
    """

    id: str
    name: str
    api_key: str
    key_prefix: str
    key_fingerprint: str
    expires_at: datetime | None = None


__all__ = [
    "ApiKeyCredential",
    "AuthUser",
    "CreatedApiKey",
    "CredentialStatus",
    "Department",
    "DepartmentCode",
    "JwtTokenPair",
    "RefreshTokenRecord",
    "TokenSubject",
    "UserDepartment",
    "UserRole",
    "UserStatus",
]
