from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.agent_tool_permissions import (
    AgentToolCallContext,
    AgentToolPermissionDecision,
)
from fast_app.domain.user_context import CurrentUserContext


logger = get_logger(__name__)


class AgentToolAuditService:
    """Agent 工具调用审计服务。

    当前阶段先写结构化日志，后续可以升级为 PostgreSQL 审计表。
    """

    async def record_decision(
        self,
        user: CurrentUserContext,
        context: AgentToolCallContext,
        decision: AgentToolPermissionDecision,
    ) -> str:
        audit_id = f"tool_audit_{uuid4().hex}"
        logger.info(
            "agent_tool_audit %s",
            format_log_fields(
                event="agent_tool.audit.decision",
                audit_id=audit_id,
                user_id=user.user_id,
                auth_source=user.auth_source,
                tool_name=context.tool_name,
                operation=str(context.operation) if context.operation else None,
                risk_level=str(context.risk_level),
                target_path=context.target_path,
                target_department_codes=context.target_department_codes,
                decision_action=decision.action.value,
                allowed=decision.allowed,
                reason=decision.reason,
                created_at=datetime.now(UTC).isoformat(),
            ),
        )
        return audit_id

    async def record_execution(
        self,
        user: CurrentUserContext,
        task_plan_id: str,
        tool_name: str,
        executed: bool,
        message: str,
    ) -> str:

        # 日志记录 任务执行操作
        audit_id = f"tool_audit_{uuid4().hex}"
        logger.info(
            "agent_tool_audit %s",
            format_log_fields(
                event="agent_tool.audit.execution",
                audit_id=audit_id,
                user_id=user.user_id,
                auth_source=user.auth_source,
                task_plan_id=task_plan_id,
                tool_name=tool_name,
                executed=executed,
                message=message,
                created_at=datetime.now(UTC).isoformat(),
            ),
        )
        return audit_id


__all__ = ["AgentToolAuditService"]
