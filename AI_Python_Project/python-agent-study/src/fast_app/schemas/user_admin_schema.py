from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from fast_app.domain.auth_models import AccountType, UserStatus


class AccessCatalogItem(BaseModel):
    code: str = Field(description="服务端稳定 code，提交管理表单时使用。")
    name: str = Field(description="面向管理界面的展示名称。")
    description: str | None = Field(default=None, description="能力、角色或部门说明；没有说明时为空。")
    risk_level: str | None = Field(default=None, description="权限风险等级；部门和账号类型为空。")


class AccessCatalogResponse(BaseModel):
    departments: list[AccessCatalogItem] = Field(description="当前 actor 可以管理的部门目录。")
    account_types: list[AccessCatalogItem] = Field(description="当前 actor 可以创建或分配的账号类型。")
    direct_permissions: list[AccessCatalogItem] = Field(description="当前 actor 可以直接下放给目标用户的功能权限。")
    department_roles: list[AccessCatalogItem] = Field(description="可分配给普通员工的部门文档角色。")


class ManagedUserSummary(BaseModel):
    user_id: str = Field(description="目标用户唯一 ID。")
    username: str = Field(description="目标用户稳定登录用户名。")
    email: str | None = Field(default=None, description="目标用户邮箱；未设置时为空。")
    display_name: str | None = Field(default=None, description="目标用户展示名称；未设置时为空。")
    status: UserStatus = Field(description="目标用户账号状态：active 或 disabled。")
    account_type: AccountType = Field(description="由服务端角色事实推导的账号类型。")
    department_codes: list[str] = Field(description="目标用户当前所属部门 code。")
    primary_department_code: str | None = Field(description="目标用户主归属部门；没有部门时为空。")
    updated_at: datetime = Field(description="用户记录最近更新时间，也是列表稳定排序依据。")


class ManagedUserListResponse(BaseModel):
    items: list[ManagedUserSummary] = Field(description="当前页中 actor 有权查看的用户摘要。")
    next_cursor: str | None = Field(default=None, description="下一页不透明游标；没有更多数据时为空。")


class ManagedDepartmentAccess(BaseModel):
    department_code: str = Field(description="部门作用域 code。")
    is_primary: bool = Field(description="该部门是否为目标用户主归属部门。")
    role_codes: list[str] = Field(description="目标用户在该部门绑定的角色 code。")
    permission_codes: list[str] = Field(description="由部门角色实时展开的有效权限 code。")


class ManagedUserDetail(BaseModel):
    user_id: str = Field(description="目标用户唯一 ID。")
    username: str = Field(description="目标用户稳定登录用户名。")
    email: str | None = Field(default=None, description="目标用户邮箱；未设置时为空。")
    display_name: str | None = Field(default=None, description="目标用户展示名称；未设置时为空。")
    status: UserStatus = Field(description="目标用户账号状态。")
    account_type: AccountType = Field(description="由服务端角色事实推导的账号类型。")
    global_role_codes: list[str] = Field(description="目标用户当前全局角色 code。")
    direct_permission_codes: list[str] = Field(description="目标用户 active 的直接功能权限，不包含角色展开。")
    effective_global_permission_codes: list[str] = Field(description="全局角色权限和直接权限合并后的有效权限。")
    department_access: list[ManagedDepartmentAccess] = Field(description="目标用户各部门的成员关系、角色和有效权限。")
    created_at: datetime = Field(description="目标用户创建时间。")
    updated_at: datetime = Field(description="目标用户最近更新时间。")
    last_login_at: datetime | None = Field(default=None, description="最近成功登录时间；从未登录时为空。")


class ManagedDepartmentAccessInput(BaseModel):
    """创建或替换账号访问快照时提交的部门作用域。"""

    model_config = ConfigDict(extra="forbid")

    department_code: str = Field(
        min_length=1,
        max_length=64,
        description="目标用户所属部门 code，必须来自当前 actor 的 access catalog。",
    )
    is_primary: bool = Field(
        description="是否为目标用户主归属部门；整个快照必须且只能有一个 true。",
    )
    role_codes: list[str] = Field(
        default_factory=list,
        description="该部门内的完整角色 code 集合；账号类型需要的系统角色由服务端补充。",
    )


class CreateManagedUserRequest(BaseModel):
    """管理员或部门主管创建受控账号的完整初始快照。"""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        min_length=1,
        max_length=64,
        description="登录用户名；服务端会去除首尾空白并转换为小写。",
    )
    password: str = Field(
        min_length=1,
        max_length=128,
        description="只用于本次创建的初始明文密码；服务端校验强度后仅保存 Argon2 hash。",
    )
    email: str | None = Field(
        default=None,
        max_length=255,
        description="可选登录邮箱；服务端规范化为空或小写地址。",
    )
    display_name: str | None = Field(
        default=None,
        max_length=128,
        description="可选展示名称；全空白值会规范化为空。",
    )
    account_type: AccountType = Field(
        description="服务端要建立的账号类型：admin、department_manager 或 employee。",
    )
    department_access: list[ManagedDepartmentAccessInput] = Field(
        min_length=1,
        description="完整部门成员关系和部门角色快照，必须包含唯一主部门。",
    )
    direct_permission_codes: list[str] = Field(
        default_factory=list,
        description="初始 active 直接功能权限 code 完整集合，不包含角色自动展开权限。",
    )


class ReplaceManagedUserAccessRequest(BaseModel):
    """原子替换目标账号类型、部门作用域和直接权限。"""

    model_config = ConfigDict(extra="forbid")

    account_type: AccountType = Field(
        description="替换后的账号类型，由服务端映射为可信系统角色事实。",
    )
    department_access: list[ManagedDepartmentAccessInput] = Field(
        min_length=1,
        description="替换后的完整部门成员关系和部门角色快照，必须包含唯一主部门。",
    )
    direct_permission_codes: list[str] = Field(
        default_factory=list,
        description="替换后的 active 直接功能权限 code 完整集合。",
    )


class UpdateManagedUserStatusRequest(BaseModel):
    """启用或禁用目标账号。"""

    model_config = ConfigDict(extra="forbid")

    status: UserStatus = Field(
        description="目标账号新状态，只允许 active 或 disabled。",
    )


class ResetManagedUserPasswordRequest(BaseModel):
    """由有权 actor 设置目标账号的新初始密码。"""

    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(
        min_length=1,
        max_length=128,
        description="新的明文密码；仅用于本次请求，服务端只保存 Argon2 hash。",
    )


class ManagedUserStatusResponse(BaseModel):
    user: ManagedUserDetail = Field(description="状态变更提交后的目标用户完整访问快照。")
    revoked_refresh_token_count: int = Field(
        ge=0,
        description="本次禁用实际撤销的 active refresh token 数量；启用或无可撤销凭证时为 0。",
    )
    revoked_api_key_count: int = Field(
        ge=0,
        description="本次禁用实际撤销的 active API Key 数量；启用或无可撤销凭证时为 0。",
    )


class ManagedUserPasswordResetResponse(BaseModel):
    password_reset: bool = Field(description="密码 hash 和凭证撤销是否已在同一事务提交。")
    revoked_refresh_token_count: int = Field(
        ge=0,
        description="本次重置实际撤销的 active refresh token 数量。",
    )
    revoked_api_key_count: int = Field(
        ge=0,
        description="本次重置实际撤销的 active API Key 数量。",
    )


__all__ = [
    "AccessCatalogItem",
    "AccessCatalogResponse",
    "CreateManagedUserRequest",
    "ManagedDepartmentAccess",
    "ManagedDepartmentAccessInput",
    "ManagedUserDetail",
    "ManagedUserListResponse",
    "ManagedUserPasswordResetResponse",
    "ManagedUserStatusResponse",
    "ManagedUserSummary",
    "ReplaceManagedUserAccessRequest",
    "ResetManagedUserPasswordRequest",
    "UpdateManagedUserStatusRequest",
]
