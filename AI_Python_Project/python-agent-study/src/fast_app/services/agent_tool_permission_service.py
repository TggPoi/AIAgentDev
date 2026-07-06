from __future__ import annotations

from fast_app.agents.document_management_tools import (
    KNOWLEDGE_DOCUMENT_CREATE_TOOL_NAME,
    KNOWLEDGE_DOCUMENT_DELETE_TOOL_NAME,
    KNOWLEDGE_DOCUMENT_UPDATE_TOOL_NAME,
)
from fast_app.domain.agent_tool_permissions import (
    AgentToolCallContext,
    AgentToolPermissionAction,
    AgentToolPermissionDecision,
    DocumentPermissionLevel,
    EffectivePermissionSet,
    PermissionCode,
    RoleCode,
)
from fast_app.domain.auth_models import UserRole
from fast_app.domain.knowledge_document_actions import (
    KnowledgeDocumentOperation,
    KnowledgeDocumentRiskLevel,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.permission_service import PermissionService


# 文档工具名 -> 需要具备的权限 code。
# 权限网关只认稳定 tool_name，不直接根据 LLM 文本决定权限。
DOCUMENT_TOOL_PERMISSION_MAP = {
    KNOWLEDGE_DOCUMENT_CREATE_TOOL_NAME: PermissionCode.KNOWLEDGE_DOCUMENT_CREATE,
    KNOWLEDGE_DOCUMENT_UPDATE_TOOL_NAME: PermissionCode.KNOWLEDGE_DOCUMENT_UPDATE,
    KNOWLEDGE_DOCUMENT_DELETE_TOOL_NAME: PermissionCode.KNOWLEDGE_DOCUMENT_DELETE,
}

# 文档动作 -> 具体工具名。
# planner 先识别 create / update / delete，再用这个映射找到后续要走的工具策略。
DOCUMENT_OPERATION_TOOL_MAP = {
    KnowledgeDocumentOperation.CREATE: KNOWLEDGE_DOCUMENT_CREATE_TOOL_NAME,
    KnowledgeDocumentOperation.UPDATE: KNOWLEDGE_DOCUMENT_UPDATE_TOOL_NAME,
    KnowledgeDocumentOperation.DELETE: KNOWLEDGE_DOCUMENT_DELETE_TOOL_NAME,
}


class AgentToolPermissionService:
    """Agent 工具权限网关。

    LLM 或 planner 只能提出工具意图；这个服务根据数据库有效权限和目标部门
    决定 allow / deny / confirmation_required / require_confirmation / execute_allowed。
    """

    def __init__(self, permission_service: PermissionService) -> None:
        # 复用已有 PermissionService，从数据库角色 / 部门关系中计算用户有效权限。
        self._permission_service = permission_service

    async def authorize(
        self,
        user: CurrentUserContext,
        context: AgentToolCallContext,
    ) -> AgentToolPermissionDecision:
        # HTTP / Agent 主链路通常走这个入口：先按 user_id 读取有效权限，再进入纯内存裁决。
        effective = await self._permission_service.get_effective_permissions(
            user.user_id
        )
        return self.authorize_with_effective_permissions(
            user=user,
            effective=effective,
            context=context,
        )

    def authorize_with_effective_permissions(
        self,
        user: CurrentUserContext,
        effective: EffectivePermissionSet,
        context: AgentToolCallContext,
    ) -> AgentToolPermissionDecision:
        # 当前只开放知识库文档管理工具；未登记的工具一律拒绝，避免 LLM 越权调用新工具。
        if context.tool_name in DOCUMENT_TOOL_PERMISSION_MAP:
            return self._authorize_document_tool(user, effective, context)

        return AgentToolPermissionDecision(
            action=AgentToolPermissionAction.DENY,
            allowed=False,
            reason=f"未配置工具权限策略: {context.tool_name}",
            risk_level=context.risk_level,
        )

    def _authorize_document_tool(
        self,
        user: CurrentUserContext,
        effective: EffectivePermissionSet,
        context: AgentToolCallContext,
    ) -> AgentToolPermissionDecision:
        # 根据工具名确定基础权限，例如 create 工具必须具备 knowledge:document:create。
        required_permission = DOCUMENT_TOOL_PERMISSION_MAP[context.tool_name]
        required_permissions = [required_permission]
        # confirmation_text 出现时，表示用户正在确认并尝试执行已有 TaskPlan。
        # 这一步除了动作权限，还必须具备 approve 权限，避免普通编辑者绕过人审。
        if context.confirmation_text is not None:
            required_permissions.append(PermissionCode.KNOWLEDGE_DOCUMENT_APPROVE)

        # 系统管理员走快速通道，但仍然保留 plan / confirmation 状态语义。
        if self._is_system_admin(user, effective):
            return self._admin_decision(context, required_permissions)

        # 部门权限必须来自服务端解析到的文档 metadata。
        # 如果目标文档没有部门信息，宁可拒绝，也不能默认放行到全库范围。
        target_departments = [
            item for item in context.target_department_codes if item.strip()
        ]
        if not target_departments:
            return AgentToolPermissionDecision(
                action=AgentToolPermissionAction.DENY,
                allowed=False,
                reason="目标文档没有可判断的部门权限 metadata，拒绝工具调用",
                risk_level=context.risk_level,
                required_permissions=required_permissions,
                missing_permissions=required_permissions,
                target_department_codes=[],
                requires_confirmation=False,
            )

        missing_permissions: list[PermissionCode] = []
        permission_level: DocumentPermissionLevel | None = None
        # 多部门文档需要逐个部门检查。只要任一目标部门缺权限，整体就不能执行。
        for department_code in target_departments:
            scope = effective.scope_for_department(department_code)
            if scope is None:
                missing_permissions.extend(required_permissions)
                continue

            permission_level = _document_permission_level(scope.permission_codes)
            for permission in required_permissions:
                if permission not in scope.permission_codes:
                    missing_permissions.append(permission)

        # 同一个权限可能在多个部门中缺失，这里去重后返回给前端 / 日志展示。
        missing_permissions = sorted(set(missing_permissions), key=str)
        if missing_permissions:
            return AgentToolPermissionDecision(
                action=AgentToolPermissionAction.DENY,
                allowed=False,
                reason="当前用户没有目标部门内的文档工具权限",
                risk_level=context.risk_level,
                required_permissions=required_permissions,
                missing_permissions=missing_permissions,
                permission_level=permission_level,
                target_department_codes=target_departments,
                requires_confirmation=False,
            )

        # 有 confirmation_text 且权限检查通过，表示确认阶段已完成，可以执行真实工具动作。
        if context.confirmation_text is not None:
            return AgentToolPermissionDecision(
                action=AgentToolPermissionAction.EXECUTE_ALLOWED,
                allowed=True,
                reason="权限和确认信息已通过，允许执行工具计划",
                risk_level=context.risk_level,
                required_permissions=required_permissions,
                permission_level=permission_level,
                target_department_codes=target_departments,
                requires_confirmation=False,
            )

        # 没有 confirmation_text，但工具本身标记为高风险，则只允许进入 TaskPlan 人工确认，不直接执行。
        if context.requires_confirmation:
            return AgentToolPermissionDecision(
                action=AgentToolPermissionAction.CONFIRMATION_REQUIRED,
                allowed=True,
                reason="用户具备发起 TaskPlan 权限，但高风险文档动作需要人工确认",
                risk_level=context.risk_level,
                required_permissions=required_permissions,
                permission_level=permission_level,
                target_department_codes=target_departments,
                requires_confirmation=True,
            )

        # 低风险或无需人工确认的工具，在权限满足后可以直接放行。
        return AgentToolPermissionDecision(
            action=AgentToolPermissionAction.ALLOW,
            allowed=True,
            reason="用户具备调用该文档工具的权限",
            risk_level=context.risk_level,
            required_permissions=required_permissions,
            permission_level=permission_level,
            target_department_codes=target_departments,
            requires_confirmation=False,
        )

    def _admin_decision(
        self,
        context: AgentToolCallContext,
        required_permissions: list[PermissionCode],
    ) -> AgentToolPermissionDecision:
        # 管理员仍然区分三种业务状态：
        # 1. confirmation_text 存在 -> 确认执行；
        # 2. requires_confirmation 为 true -> 等待 TaskPlan 人工确认；
        # 3. 否则直接允许调用。
        action = (
            AgentToolPermissionAction.EXECUTE_ALLOWED
            if context.confirmation_text is not None
            else AgentToolPermissionAction.CONFIRMATION_REQUIRED
            if context.requires_confirmation
            else AgentToolPermissionAction.ALLOW
        )
        return AgentToolPermissionDecision(
            action=action,
            allowed=True,
            reason="系统管理员通过工具权限检查",
            risk_level=context.risk_level,
            required_permissions=required_permissions,
            permission_level=DocumentPermissionLevel.READ_UPDATE_CREATE_DELETE,
            target_department_codes=context.target_department_codes,
            requires_confirmation=context.confirmation_text is None
            and context.requires_confirmation,
        )

    def _is_system_admin(
        self,
        user: CurrentUserContext,
        effective: EffectivePermissionSet,
    ) -> bool:
        # 兼容两种管理员来源：
        # - 当前用户上下文中的基础 role；
        # - 数据库有效权限集合中的 system_admin 全局角色。
        return (
            user.role == UserRole.ADMIN.value
            or effective.has_global_role(RoleCode.SYSTEM_ADMIN)
        )


def tool_name_for_document_operation(
    operation: KnowledgeDocumentOperation,
) -> str:
    """把 planner 识别出的文档动作转换为 Agent 工具名。"""

    return DOCUMENT_OPERATION_TOOL_MAP[operation]


def risk_level_for_document_operation(
    operation: KnowledgeDocumentOperation,
) -> KnowledgeDocumentRiskLevel:
    """根据文档动作给出默认风险等级。

    create 仍会进入权限检查，但风险低于 update / delete；
    update 改写已有知识，delete 可能造成不可逆影响，因此风险更高。
    """

    if operation == KnowledgeDocumentOperation.CREATE:
        return KnowledgeDocumentRiskLevel.MEDIUM
    if operation == KnowledgeDocumentOperation.UPDATE:
        return KnowledgeDocumentRiskLevel.HIGH
    return KnowledgeDocumentRiskLevel.CRITICAL


def _document_permission_level(
    permission_codes: set[PermissionCode],
) -> DocumentPermissionLevel:
    """把权限 code 集合压缩成前端更容易展示的文档权限级别。"""

    if PermissionCode.KNOWLEDGE_DOCUMENT_DELETE in permission_codes:
        return DocumentPermissionLevel.READ_UPDATE_CREATE_DELETE
    if PermissionCode.KNOWLEDGE_DOCUMENT_UPDATE in permission_codes:
        return DocumentPermissionLevel.READ_UPDATE
    return DocumentPermissionLevel.READ_ONLY


__all__ = [
    "AgentToolPermissionService",
    "risk_level_for_document_operation",
    "tool_name_for_document_operation",
]
