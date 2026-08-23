from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fast_app.domain.auth_models import AccountType


AuthSource = Literal["anonymous", "demo_header", "api_key", "jwt"]


class CurrentUserContext(BaseModel):
    """当前请求的用户上下文。

    阶段 15-1 后，RAG 主接口优先通过 API Key / Bearer Token 生成可信用户。
    数据库 API Key / JWT 会从 RBAC 表补充全局角色和全局权限快照。
    demo_header 只保留给本地学习和阶段 14-9 的隔离验证。
    """

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=128, description="当前请求用户 ID。")
    username: str | None = Field(
        default=None,
        description="数据库中的稳定登录用户名；匿名和本地演示身份为空。",
    )
    account_type: AccountType = Field(
        default=AccountType.EMPLOYEE,
        description="由实时 RBAC 角色推导的账号类型，不读取客户端提交值。",
    )
    is_authenticated: bool = Field(default=False, description="当前请求是否通过可信认证。")
    auth_source: AuthSource = Field(default="anonymous", description="当前用户上下文来源。")
    global_role_codes: list[str] = Field(
        default_factory=list,
        description="认证阶段从 user_roles 实时计算的全局角色 code 快照。",
    )
    global_permission_codes: list[str] = Field(
        default_factory=list,
        description="认证阶段由全局角色权限和 active 用户直接授权合并的权限 code 快照。",
    )
    department_permission_codes: dict[str, list[str]] = Field(
        default_factory=dict,
        description="按部门 code 分组的作用域权限快照，只由服务端部门角色实时展开。",
    )
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

    def has_global_role(self, role_code: str) -> bool:
        """判断当前请求的 RBAC 全局角色快照是否包含指定角色。"""

        return role_code in self.global_role_codes

    def has_global_permission(self, permission_code: str) -> bool:
        """判断当前请求的 RBAC 全局权限快照是否包含指定权限。"""

        return permission_code in self.global_permission_codes

    def has_department_permission(
        self,
        department_code: str,
        permission_code: str,
    ) -> bool:
        """判断指定权限是否存在于目标部门的服务端作用域快照。"""

        return permission_code in self.department_permission_codes.get(
            department_code,
            [],
        )


__all__ = ["AuthSource", "CurrentUserContext"]
