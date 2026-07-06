from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class UserRole(StrEnum):
    """系统内置角色。

    当前阶段先用轻量 role 字段承载权限层级，避免过早引入完整 RBAC 表结构。
    """

    # 系统管理员，拥有管理和调试类高权限。
    ADMIN = "admin"
    # 普通登录用户，拥有默认业务访问权限。
    USER = "user"
    # 只读访问用户，用于限制性查看场景。
    VIEWER = "viewer"


class UserStatus(StrEnum):
    """用户账号状态。"""

    # 可正常登录和使用接口的账号。
    ACTIVE = "active"
    # 已禁用账号，认证层应拒绝其继续使用。
    DISABLED = "disabled"


class CredentialStatus(StrEnum):
    """API Key / refresh token 的状态。"""

    # 凭证仍然有效，可以继续用于认证或刷新。
    ACTIVE = "active"
    # 凭证已撤销，后续请求必须拒绝。
    REVOKED = "revoked"


class DepartmentCode(StrEnum):
    """系统内置部门 code。

    权限字段中使用稳定英文 code，展示层再翻译成中文部门名，避免中文名称调整影响权限判断。
    """

    # 美术部门知识库权限范围。
    ART = "art"
    # 产品策划部门知识库权限范围。
    PRODUCT_PLANNING = "product_planning"
    # 开发部门知识库权限范围。
    DEVELOPMENT = "development"


class Department(BaseModel):
    """部门领域模型。"""

    id: str = Field(description="部门记录唯一 ID，对应 departments.id。")
    code: DepartmentCode = Field(description="稳定部门 code，用于权限判断和文档 metadata 匹配。")
    name: str = Field(description="部门展示名称，面向前端或管理界面。")
    description: str | None = Field(default=None, description="部门说明文本，可为空。")
    created_at: datetime | None = Field(default=None, description="部门记录创建时间。")
    updated_at: datetime | None = Field(default=None, description="部门记录最近更新时间。")


class UserDepartment(BaseModel):
    """用户与部门的多对多关系。"""

    id: str = Field(description="用户部门关系记录唯一 ID。")
    user_id: str = Field(description="用户 ID，对应 users.id。")
    department_code: DepartmentCode = Field(description="用户被授权访问的部门 code。")
    is_primary: bool = Field(default=False, description="该部门是否为用户主归属部门。")
    created_at: datetime | None = Field(default=None, description="关系记录创建时间。")


class AuthUser(BaseModel):
    """认证业务使用的用户领域模型。"""

    id: str = Field(description="用户唯一 ID，对应 users.id。")
    username: str = Field(description="登录用户名，认证时可作为账号标识。")
    email: str | None = Field(default=None, description="用户邮箱，认证时也可作为账号标识。")
    display_name: str | None = Field(default=None, description="用户展示名称。")
    password_hash: str = Field(description="用户密码 hash，不能保存明文密码。")
    role: UserRole = Field(default=UserRole.USER, description="用户基础角色，用于粗粒度权限层级。")
    status: UserStatus = Field(default=UserStatus.ACTIVE, description="用户账号状态。")
    permissions: list[str] = Field(default_factory=list, description="用户直接拥有或聚合出的权限 code 列表。")
    department_codes: list[DepartmentCode] = Field(
        default_factory=list,
        description="用户可访问的部门 code 列表，用于知识库权限范围。",
    )
    primary_department_code: DepartmentCode | None = Field(
        default=None,
        description="用户主归属部门 code；为空表示未指定主部门。",
    )
    created_at: datetime | None = Field(default=None, description="用户记录创建时间。")
    updated_at: datetime | None = Field(default=None, description="用户记录最近更新时间。")
    last_login_at: datetime | None = Field(default=None, description="用户最近一次登录时间。")


class ApiKeyCredential(BaseModel):
    """API Key 的持久化视图，不包含原始 key。"""

    id: str = Field(description="API Key 记录唯一 ID。")
    user_id: str = Field(description="API Key 归属用户 ID。")
    name: str = Field(description="用户给 API Key 设置的可读名称。")
    key_prefix: str = Field(description="API Key 前缀，用于展示和快速定位，不用于认证。")
    key_fingerprint: str = Field(description="API Key 指纹，用于审计和排查。")
    key_hash: str = Field(description="API Key hash，认证时用它校验原始 key。")
    status: CredentialStatus = Field(default=CredentialStatus.ACTIVE, description="API Key 当前状态。")
    expires_at: datetime | None = Field(default=None, description="API Key 过期时间；为空表示不过期。")
    last_used_at: datetime | None = Field(default=None, description="API Key 最近一次使用时间。")
    created_at: datetime | None = Field(default=None, description="API Key 创建时间。")
    revoked_at: datetime | None = Field(default=None, description="API Key 撤销时间；未撤销时为空。")


class RefreshTokenRecord(BaseModel):
    """Refresh token 的持久化视图，只保存 hash。"""

    id: str = Field(description="Refresh token 记录唯一 ID。")
    user_id: str = Field(description="Refresh token 归属用户 ID。")
    token_hash: str = Field(description="Refresh token hash，数据库不保存原始 token。")
    status: CredentialStatus = Field(default=CredentialStatus.ACTIVE, description="Refresh token 当前状态。")
    expires_at: datetime = Field(description="Refresh token 过期时间。")
    created_at: datetime | None = Field(default=None, description="Refresh token 创建时间。")
    last_used_at: datetime | None = Field(default=None, description="Refresh token 最近一次使用时间。")
    revoked_at: datetime | None = Field(default=None, description="Refresh token 撤销时间；未撤销时为空。")
    metadata: dict[str, object] = Field(default_factory=dict, description="刷新凭证附加审计信息。")


class TokenSubject(BaseModel):
    """从 JWT access token 中解析出的核心身份声明。"""

    user_id: str = Field(description="JWT 代表的用户 ID。")
    role: UserRole = Field(description="JWT 中携带的用户基础角色。")
    permissions: list[str] = Field(default_factory=list, description="JWT 中携带的权限 code 列表。")
    token_id: str = Field(description="JWT 唯一 token ID，用于审计和撤销扩展。")
    expires_at: datetime = Field(description="JWT access token 过期时间。")


class JwtTokenPair(BaseModel):
    """登录或刷新后返回给客户端的 token 组合。"""

    access_token: str = Field(description="短期访问 token，用于 Authorization Bearer。")
    refresh_token: str = Field(description="长期刷新 token，用于换取新的 access token。")
    token_type: str = Field(default="bearer", description="token 类型，当前固定为 bearer。")
    expires_in: int = Field(description="access token 剩余有效秒数。")


class CreatedApiKey(BaseModel):
    """创建 API Key 后返回的结果。

    api_key 是唯一一次返回的原始凭证，数据库只保存 hash / fingerprint。
    """

    id: str = Field(description="新建 API Key 记录 ID。")
    name: str = Field(description="API Key 可读名称。")
    api_key: str = Field(description="完整明文 API Key，只在创建成功时返回一次。")
    key_prefix: str = Field(description="API Key 前缀，用于展示和定位。")
    key_fingerprint: str = Field(description="API Key 指纹，用于审计。")
    expires_at: datetime | None = Field(default=None, description="API Key 过期时间；为空表示不过期。")


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
