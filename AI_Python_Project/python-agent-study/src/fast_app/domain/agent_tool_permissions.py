from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from fast_app.domain.knowledge_document_actions import (
    KnowledgeDocumentOperation,
    KnowledgeDocumentRiskLevel,
)


class PermissionCode(StrEnum):
    """代码层权限常量，值必须和数据库 permissions.code 保持一致。"""

    # 允许读取知识库文档。
    KNOWLEDGE_DOCUMENT_READ = "knowledge:document:read"
    # 允许更新已有知识库文档。
    KNOWLEDGE_DOCUMENT_UPDATE = "knowledge:document:update"
    # 允许创建新的知识库文档。
    KNOWLEDGE_DOCUMENT_CREATE = "knowledge:document:create"
    # 允许删除知识库文档。
    KNOWLEDGE_DOCUMENT_DELETE = "knowledge:document:delete"
    # 允许审批或确认高风险文档动作。
    KNOWLEDGE_DOCUMENT_APPROVE = "knowledge:document:approve"
    # 允许跨用户、跨部门读取全部知识库内容。
    KNOWLEDGE_READ_ALL = "knowledge:read:all"
    # 允许管理 GitLab 文档源和同步任务。
    GITLAB_SOURCE_MANAGE = "gitlab:source:manage"
    # 允许读取所有部门的 GitLab 知识变更事件。
    GITLAB_CHANGE_READ_ALL = "gitlab:change:read_all"
    # 允许调用计算器类低风险 Agent 工具。
    AGENT_TOOL_CALCULATOR = "agent:tool:calculator"
    # 允许调用 Web Search 类外部检索工具。
    AGENT_TOOL_WEB_SEARCH = "agent:tool:web_search"
    # 允许调用 MCP 工具。
    AGENT_TOOL_MCP = "agent:tool:mcp"


class RoleCode(StrEnum):
    """系统内置角色 code，真实授权关系仍来自数据库角色表。"""

    # 系统管理员角色，通常拥有全局管理权限。
    SYSTEM_ADMIN = "system_admin"
    # 全局知识库读者，可以跨用户、跨部门读取知识内容。
    KNOWLEDGE_GLOBAL_READER = "knowledge_global_reader"
    # Agent 工具操作员，可以调用计算、Web Search 和白名单 MCP 工具。
    AGENT_TOOL_OPERATOR = "agent_tool_operator"
    # GitLab 文档源管理员，可以管理同步任务并读取全部知识变更。
    GITLAB_MANAGER = "gitlab_manager"
    # 部门只读角色，只能读取本部门文档。
    DEPARTMENT_READER = "department_reader"
    # 部门编辑角色，可以更新本部门文档。
    DEPARTMENT_EDITOR = "department_editor"
    # 部门文档管理员角色，可以创建、更新、删除本部门文档。
    DEPARTMENT_DOCUMENT_MANAGER = "department_document_manager"


class DocumentPermissionLevel(StrEnum):
    """部门内文档权限级别，用于解释当前用户在目标部门能做什么。"""

    # 只能读取部门文档。
    READ_ONLY = "read_only"
    # 可以读取和更新部门文档。
    READ_UPDATE = "read_update"
    # 可以读取、更新、创建和删除部门文档。
    READ_UPDATE_CREATE_DELETE = "read_update_create_delete"


class AgentToolPermissionAction(StrEnum):
    """工具权限网关的裁决动作。"""

    # 允许继续执行当前工具链路。
    ALLOW = "allow"
    # 拒绝当前工具调用。
    DENY = "deny"
    # 必须等待人工确认。
    CONFIRMATION_REQUIRED = "confirmation_required"
    # 当前动作还需要用户确认。
    REQUIRE_CONFIRMATION = "require_confirmation"
    # 确认通过，可以执行真实工具动作。
    EXECUTE_ALLOWED = "execute_allowed"


class ToolRiskLevel(StrEnum):
    """Agent 工具风险分级。"""

    # 低风险工具，例如只读或纯计算。
    LOW = "low"
    # 中风险工具，需要审计但通常不需要人工确认。
    MEDIUM = "medium"
    # 高风险工具，需要 TaskPlan 人工确认。
    HIGH = "high"
    # 关键风险工具，通常代表删除或不可逆动作。
    CRITICAL = "critical"


class DepartmentPermissionScope(BaseModel):
    """用户在某个部门内拥有的角色和权限集合。"""

    department_code: str = Field(description="部门 code，例如 development / art。")
    role_codes: list[str] = Field(
        default_factory=list,
        description="用户在该部门下绑定的角色 code 列表。",
    )
    permission_codes: set[PermissionCode] = Field(
        default_factory=set,
        description="由该部门角色展开得到的文档工具权限集合。",
    )


class EffectivePermissionSet(BaseModel):
    """PermissionService 根据数据库授权关系计算出的有效权限。"""

    user_id: str = Field(description="当前用户 ID，对应 users.id。")
    global_role_codes: list[str] = Field(
        default_factory=list,
        description="用户绑定的全局角色 code，例如 system_admin。",
    )
    global_permission_codes: set[PermissionCode] = Field(
        default_factory=set,
        description="由全局角色展开得到的全局权限集合。",
    )
    department_scopes: list[DepartmentPermissionScope] = Field(
        default_factory=list,
        description="用户在各部门下的作用域角色和权限集合。",
    )

    def has_global_permission(self, permission: PermissionCode) -> bool:
        return permission in self.global_permission_codes

    def has_global_role(self, role_code: RoleCode | str) -> bool:
        return str(role_code) in self.global_role_codes

    def scope_for_department(
        self,
        department_code: str,
    ) -> DepartmentPermissionScope | None:
        return next(
            (
                scope
                for scope in self.department_scopes
                if scope.department_code == department_code
            ),
            None,
        )


class DocumentActionIntent(BaseModel):
    """文档动作 planner 输出的候选意图。

    它只表示“用户可能想做什么”，不代表已授权，也不代表已确认。
    """

    # planner 输出必须是严格结构，避免下游误用额外字段。
    model_config = ConfigDict(extra="forbid")

    operation: KnowledgeDocumentOperation = Field(
        description="用户想执行的文档动作：create / update / delete。",
    )
    target_path: str = Field(
        min_length=1,
        max_length=512,
        description="知识库内相对目标路径，例如 development/demo.md。",
    )
    reason: str = Field(
        min_length=1,
        max_length=1000,
        description="planner 识别该文档动作的原因，用于调试和审计。",
    )
    content: str | None = Field(
        default=None,
        max_length=200_000,
        description="create/update 的目标完整内容；delete 时为空。",
    )
    expected_department_codes: list[str] = Field(
        default_factory=list,
        description="用户话术中显式提到的目标部门，用于和服务端 metadata 推断结果对比。",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="planner 对该意图的置信度，低置信度结果不会进入工具链路。",
    )

    @field_validator("target_path", "reason")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized

    @field_validator("expected_department_codes")
    @classmethod
    def normalize_departments(cls, value: list[str]) -> list[str]:
        return sorted({item.strip() for item in value if item.strip()})


class AgentToolCallContext(BaseModel):
    """工具权限网关的输入上下文。"""

    # 权限网关输入必须是严格结构，避免未声明上下文影响裁决。
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(description="Agent 准备调用的工具名。")
    operation: KnowledgeDocumentOperation | None = Field(
        default=None,
        description="文档工具对应的 create/update/delete 操作；非文档工具可为空。",
    )
    risk_level: KnowledgeDocumentRiskLevel | ToolRiskLevel = Field(
        description="本次工具调用的风险等级，用于决定是否需要 TaskPlan 人工确认。",
    )
    target_path: str | None = Field(
        default=None,
        description="工具作用的目标文档路径；无具体文档目标的工具可为空。",
    )
    target_department_codes: list[str] = Field(
        default_factory=list,
        description="目标文档 metadata 推断出的部门范围，是部门权限判断的事实输入。",
    )
    requires_confirmation: bool = Field(
        default=False,
        description="该工具动作是否必须等待 TaskPlan 人工确认。",
    )
    confirmation_text: str | None = Field(
        default=None,
        description="确认阶段的服务端确认标记；存在时表示正在尝试执行已确认的高风险动作。",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="权限判断的附加上下文，主要用于审计和排查。",
    )


class AgentToolPermissionDecision(BaseModel):
    """工具权限网关的结构化裁决结果。"""

    # 权限裁决结果必须稳定，便于 API、stream event 和审计统一消费。
    model_config = ConfigDict(extra="forbid")

    action: AgentToolPermissionAction = Field(
        description="权限网关裁决动作，例如 deny / confirmation_required / execute_allowed。",
    )
    allowed: bool = Field(
        default=False,
        description="当前裁决是否允许继续进入后续链路。",
    )
    reason: str = Field(description="面向日志、调试和前端展示的裁决原因。")
    risk_level: KnowledgeDocumentRiskLevel | ToolRiskLevel = Field(
        description="本次工具调用的风险等级，原样回传便于审计。",
    )
    required_permissions: list[PermissionCode] = Field(
        default_factory=list,
        description="完成该动作需要具备的权限 code 列表。",
    )
    missing_permissions: list[PermissionCode] = Field(
        default_factory=list,
        description="当前用户缺失的权限 code 列表；允许时为空。",
    )
    permission_level: DocumentPermissionLevel | None = Field(
        default=None,
        description="当前用户在目标部门内的文档权限级别，用于解释裁决。",
    )
    target_department_codes: list[str] = Field(
        default_factory=list,
        description="参与本次裁决的目标部门 code 列表。",
    )
    requires_confirmation: bool = Field(
        default=False,
        description="是否需要前端展示人工确认流程。",
    )


__all__ = [
    "AgentToolCallContext",
    "AgentToolPermissionAction",
    "AgentToolPermissionDecision",
    "DepartmentPermissionScope",
    "DocumentActionIntent",
    "DocumentPermissionLevel",
    "EffectivePermissionSet",
    "PermissionCode",
    "RoleCode",
    "ToolRiskLevel",
]
