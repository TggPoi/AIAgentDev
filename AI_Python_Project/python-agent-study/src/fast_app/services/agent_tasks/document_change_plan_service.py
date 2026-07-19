"""把 direct/agentic 文档建议统一转换成可确认 dry-run 的安全边界。"""

from __future__ import annotations

import json
from typing import Any

from fast_app.domain.agent_tool_permissions import (
    AgentToolCallContext,
    AgentToolPermissionAction,
)
from fast_app.domain.knowledge_document_actions import (
    KnowledgeDocumentActionRequest,
    KnowledgeDocumentOperation,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_tasks.agent_tool_audit_service import AgentToolAuditService
from fast_app.services.agent_tasks.agent_tool_permission_service import (
    AgentToolPermissionService,
)
from fast_app.services.exceptions import AppServiceError, ToolPermissionDeniedError
from fast_app.services.knowledge.knowledge_document_management_service import (
    KnowledgeDocumentManagementService,
)


class DocumentActionConflictError(AppServiceError):
    """同一 TaskPlan 对一个 doc_id 产生重复或冲突动作。"""


class DocumentChangePlanService:
    """只生成 dry-run 和权限审计事实，不提供任何真实写入入口。"""

    def __init__(
        self,
        *,
        document_management_service: KnowledgeDocumentManagementService,
        tool_permission_service: AgentToolPermissionService,
        tool_audit_service: AgentToolAuditService,
    ) -> None:
        self._document_management_service = document_management_service
        self._tool_permission_service = tool_permission_service
        self._tool_audit_service = tool_audit_service

    async def prepare_dry_run(
        self,
        *,
        user: CurrentUserContext,
        operation: KnowledgeDocumentOperation,
        target_path: str,
        content: str | None,
        reason: str,
        candidate: dict[str, Any] | None,
        selection_reason: str,
        replacements: list[dict[str, Any]],
        document_actions: dict[str, str],
        diff: str = "",
    ) -> str:
        """校验一个写动作并返回可冻结进 TaskPlan 的 ToolMessage JSON。"""

        # 无论建议来自旧 Tool Loop 还是 Deep Agents，都先收敛成同一个领域请求；
        # dry_run=True 保证这个阶段只产生预览，不修改文件或检索存储。
        request = KnowledgeDocumentActionRequest(
            operation=operation,
            target_path=target_path,
            content=content,
            reason=reason,
            dry_run=True,
            expected_department_codes=(
                [user.primary_department_code]
                if operation == KnowledgeDocumentOperation.CREATE
                and user.primary_department_code
                else []
            ),
        )
        # 路径规范化、doc_id、风险、before_hash 和 ACL metadata 均由确定性
        # ManagementService 计算，不能由模型传入。
        result = await self._document_management_service.plan_action(request, user=user)
        preview = result.preview
        doc_id = str(preview.affected_doc_id or "")
        if not doc_id:
            raise AppServiceError("文档 dry-run 未返回 doc_id")
        # document_actions 是本 TaskPlan 的服务端集合，阻止同一文档同时 update/delete
        # 或被多个交付物重复覆盖。
        previous = document_actions.get(doc_id)
        if previous is not None:
            raise DocumentActionConflictError(
                f"同一文档不能重复或冲突操作: doc_id={doc_id}, {previous}+{operation.value}"
            )
        # dry-run 也先经过权限网关和审计；这里允许的结果仍需用户稍后显式确认。
        context = AgentToolCallContext(
            tool_name=f"knowledge_document_{operation.value}",
            operation=operation,
            risk_level=preview.risk_level,
            target_path=target_path,
            target_department_codes=list(
                preview.permission_metadata.get("allowed_departments", []) or []
            ),
            requires_confirmation=True,
            metadata={"source": "rag_agent.document_native_tool"},
        )
        decision = await self._tool_permission_service.authorize(user=user, context=context)
        await self._tool_audit_service.record_decision(
            user=user,
            context=context,
            decision=decision,
        )
        if decision.action == AgentToolPermissionAction.DENY:
            raise ToolPermissionDeniedError(decision.reason)
        # 只有全部校验通过才登记动作并冻结给前端，失败调用不会污染冲突集合。
        document_actions[doc_id] = operation.value
        return json.dumps(
            {
                "operation": operation.value,
                "target_path": target_path,
                "action_request": request.model_dump(mode="json"),
                "preview": preview.model_dump(mode="json"),
                "permission_decision": decision.model_dump(mode="json"),
                "candidate": candidate,
                "selection_reason": selection_reason,
                "replacements": replacements,
                "diff": diff,
            },
            ensure_ascii=False,
        )


__all__ = ["DocumentActionConflictError", "DocumentChangePlanService"]
