from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

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


__all__ = [
    "AccessCatalogItem",
    "AccessCatalogResponse",
    "ManagedDepartmentAccess",
    "ManagedUserDetail",
    "ManagedUserListResponse",
    "ManagedUserSummary",
]
