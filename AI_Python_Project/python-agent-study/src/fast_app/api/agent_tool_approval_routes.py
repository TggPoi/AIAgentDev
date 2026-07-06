from fastapi import APIRouter, Depends

from fast_app.dependencies.rag_dependencies import (
    get_agent_tool_audit_service,
    get_agent_tool_permission_service,
    get_agent_tool_approval_service,
    get_knowledge_document_management_service,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.agent_tool_approval_schema import (
    AgentToolApprovalConfirmRequest,
    AgentToolApprovalConfirmResponse,
)
from fast_app.services.agent_tool_audit_service import AgentToolAuditService
from fast_app.services.agent_tool_permission_service import AgentToolPermissionService
from fast_app.services.agent_tool_approval_service import AgentToolApprovalService
from fast_app.services.knowledge_document_management_service import (
    KnowledgeDocumentManagementService,
)
from fast_app.core.request_context import get_request_id, get_trace_id


router = APIRouter(prefix="/agent/tool-approvals", tags=["agent-tool-approvals"])


@router.post("/{approval_id}/confirm", response_model=AgentToolApprovalConfirmResponse)
async def confirm_agent_tool_approval_endpoint(
    approval_id: str,
    req: AgentToolApprovalConfirmRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
    tool_approval_service: AgentToolApprovalService = Depends(get_agent_tool_approval_service),
    tool_permission_service: AgentToolPermissionService = Depends(
        get_agent_tool_permission_service
    ),
    document_management_service: KnowledgeDocumentManagementService = Depends(
        get_knowledge_document_management_service
    ),
    audit_service: AgentToolAuditService = Depends(get_agent_tool_audit_service),
) -> AgentToolApprovalConfirmResponse:
    """确认并执行高风险 Agent 工具执行确认单。"""

    result = await tool_approval_service.confirm_approval(
        approval_id=approval_id,
        confirmation_text=req.confirmation_text,
        user=user,
        tool_permission_service=tool_permission_service,
        document_management_service=document_management_service,
        audit_service=audit_service,
    )
    return AgentToolApprovalConfirmResponse(
        approval_id=result.approval_id,
        status=result.status.value,
        executed=result.executed,
        message=result.message,
        result=result.result,
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )


__all__ = ["router"]
