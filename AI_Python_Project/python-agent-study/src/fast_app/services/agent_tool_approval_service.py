from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fast_app.core.config import Settings
from fast_app.domain.agent_tool_permissions import (
    AgentToolCallContext,
    AgentToolPermissionAction,
    AgentToolPermissionDecision,
)
from fast_app.domain.agent_tool_approval import (
    AgentToolExecutionApproval,
    AgentToolApprovalConfirmResult,
    AgentToolApprovalCreateResult,
    AgentToolApprovalStatus,
)
from fast_app.domain.knowledge_document_actions import (
    KnowledgeDocumentActionRequest,
    KnowledgeDocumentActionResult,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_tool_audit_service import AgentToolAuditService
from fast_app.services.agent_tool_permission_service import AgentToolPermissionService
from fast_app.services.exceptions import AppServiceError, ToolPermissionDeniedError
from fast_app.services.knowledge_document_management_service import (
    KnowledgeDocumentManagementService,
)


class AgentToolApprovalService:
    """Agent 高风险工具执行确认单的双文件持久化服务。"""

    def __init__(self, settings: Settings) -> None:
        # approval 目录只保存本地文件事实源，不承担数据库事务语义。
        self._settings = settings
        # 每个 approval 同时落一个 .md 和一个 .json：前者给人看，后者给机器执行。
        self._approval_dir = Path(settings.agent_tool_approval_dir)

    async def create_approval(
        self,
        user: CurrentUserContext,
        tool_name: str,
        action_request: KnowledgeDocumentActionRequest,
        action_result: KnowledgeDocumentActionResult,
        permission_decision: AgentToolPermissionDecision,
    ) -> AgentToolApprovalCreateResult:
        """保存执行确认单的 `.md` 展示文件和 `.json` 机器事实文件。"""

        # 确保运行时目录存在；approval 文件属于 runtime 产物，不要求提前提交到仓库。
        self._approval_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC)
        # approval_id 带时间戳和随机短后缀，便于人工排查，同时避免同秒冲突。
        approval_id = f"tool_approval_{now.strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:12]}"
        # 明文确认口令只在 create_approval 返回时给用户；持久化时只保存 hash。
        confirmation_text = f"CONFIRM EXECUTE TOOL APPROVAL {approval_id}"
        # 文件名前缀用可排序时间，方便在 runtime 目录里按时间查找。
        file_stem = f"{now.strftime('%Y%m%d_%H%M%S')}_{approval_id}"
        markdown_path = self._approval_dir / f"{file_stem}.md"
        json_path = self._approval_dir / f"{file_stem}.json"

        # content_hash 记录目标内容快照，方便人审和审计对齐 create/update 内容。
        content = action_request.content or ""
        approval = AgentToolExecutionApproval(
            approval_kind="tool_execution_approval",
            approval_id=approval_id,
            user_id=user.user_id,
            tool_name=tool_name,
            operation=action_request.operation,
            target_path=action_request.target_path,
            target_department_codes=permission_decision.target_department_codes,
            content_hash=_sha256_text(content) if content else None,
            permission_metadata=action_result.preview.permission_metadata,
            confirmation_text_hash=_sha256_text(confirmation_text),
            status=AgentToolApprovalStatus.PENDING_CONFIRMATION,
            created_at=now,
            # 过期时间是执行保护边界，防止用户很久以后确认旧确认单。
            expires_at=now
            + timedelta(minutes=self._settings.agent_tool_approval_expire_minutes),
            markdown_path=markdown_path.as_posix(),
            json_path=json_path.as_posix(),
            reason=action_request.reason,
            action_request=action_request.model_dump(mode="json"),
            preview=action_result.preview,
            permission_decision=permission_decision,
        )

        # JSON 必须先写入：确认执行时只信任 JSON，不从 Markdown 反解析字段。
        json_path.write_text(approval.model_dump_json(indent=2), encoding="utf-8")
        # Markdown 是给用户复查的展示副本，不作为执行输入。
        markdown_path.write_text(
            self._render_markdown_approval(approval),
            encoding="utf-8",
        )

        return AgentToolApprovalCreateResult(
            approval=approval,
            confirmation_text=confirmation_text,
            markdown_path=markdown_path.as_posix(),
            json_path=json_path.as_posix(),
        )

    async def confirm_approval(
        self,
        approval_id: str,
        confirmation_text: str,
        user: CurrentUserContext,
        tool_permission_service: AgentToolPermissionService,
        document_management_service: KnowledgeDocumentManagementService,
        audit_service: AgentToolAuditService,
    ) -> AgentToolApprovalConfirmResult:
        """确认并执行高风险工具执行确认单。

        执行事实来自 `.json` 文件；Markdown 只用于人类复查。
        """

        # 先从 JSON 事实源加载 approval，避免用户修改 Markdown 影响执行参数。
        approval = self.load_approval(approval_id)
        # 普通用户只能确认自己创建的确认单；管理员保留跨用户处理能力。
        if approval.user_id != user.user_id and user.role != "admin":
            raise ToolPermissionDeniedError("只能确认自己创建的工具执行确认单")

        now = datetime.now(UTC)
        # 过期 approval 会写回 EXPIRED 状态，方便后续排查为什么确认失败。
        if approval.expires_at <= now:
            approval.status = AgentToolApprovalStatus.EXPIRED
            self._write_approval(approval)
            raise AppServiceError("工具执行确认单已过期，拒绝执行")

        # 只允许 pending_confirmation 执行，防止重复执行、拒绝后执行或过期后执行。
        if approval.status != AgentToolApprovalStatus.PENDING_CONFIRMATION:
            raise AppServiceError("工具执行确认单状态不是 pending_confirmation，拒绝执行")

        # 用户提交的是明文确认口令，服务端只和 JSON 中的 hash 比对。
        if _sha256_text(confirmation_text.strip()) != approval.confirmation_text_hash:
            raise ToolPermissionDeniedError("confirmation_text 不匹配，拒绝执行")

        # 确认阶段重新构造权限上下文，不直接复用创建 approval 时的旧裁决。
        # 这样用户权限被撤销或目标部门策略变化后，旧 approval 也不能绕过鉴权。
        context = AgentToolCallContext(
            tool_name=approval.tool_name,
            operation=approval.operation,
            risk_level=approval.preview.risk_level,
            target_path=approval.target_path,
            target_department_codes=approval.target_department_codes,
            requires_confirmation=False,
            approval_id=approval.approval_id,
            confirmation_text=confirmation_text.strip(),
            metadata={"source": "agent_tool_approval.confirm"},
        )
        decision = await tool_permission_service.authorize(user=user, context=context)
        # 审计先记录确认阶段的权限裁决，即使后续拒绝也能追踪原因。
        await audit_service.record_decision(user=user, context=context, decision=decision)
        if decision.action != AgentToolPermissionAction.EXECUTE_ALLOWED:
            raise ToolPermissionDeniedError(decision.reason)

        # 从 approval JSON 快照重建文档动作请求，并强制 dry_run=False。
        # 这一步把“确认执行”与普通 dry-run 预览明确分开。
        action_request = KnowledgeDocumentActionRequest.model_validate(
            {
                **approval.action_request,
                "dry_run": False,
            }
        )
        result = await document_management_service.execute_confirmed_action(
            request=action_request,
            user=user,
            # before_hash 用来检测 approval 生成后目标文件是否被别人改过。
            expected_before_hash=approval.preview.before_hash,
        )

        # 只有真实执行成功后才把 approval 标记为 EXECUTED。
        approval.status = AgentToolApprovalStatus.EXECUTED
        approval.executed_at = now
        self._write_approval(approval)
        # 执行审计和权限裁决审计分开记录，便于排查“允许了什么”和“最终做了什么”。
        await audit_service.record_execution(
            user=user,
            approval_id=approval.approval_id,
            tool_name=approval.tool_name,
            executed=True,
            message=result.message,
        )

        return AgentToolApprovalConfirmResult(
            approval_id=approval.approval_id,
            status=approval.status,
            executed=True,
            message=result.message,
            result=result.model_dump(mode="json"),
        )

    def load_approval(self, approval_id: str) -> AgentToolExecutionApproval:
        """读取 approval JSON，并反序列化为执行模型。"""

        json_path = self._find_approval_json_path(approval_id)
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        return AgentToolExecutionApproval.model_validate(payload)

    def _find_approval_json_path(self, approval_id: str) -> Path:
        """根据 approval_id 在 runtime 目录中定位 JSON 事实文件。"""

        # approval_id 必须使用服务端生成格式，避免把任意 glob 模式带入文件查找。
        if not approval_id.startswith("tool_approval_"):
            raise AppServiceError("非法 approval_id")

        self._approval_dir.mkdir(parents=True, exist_ok=True)
        # 文件名前面还有时间戳，所以通过 *_<approval_id>.json 定位。
        matches = sorted(self._approval_dir.glob(f"*_{approval_id}.json"))
        if not matches:
            raise AppServiceError("工具执行确认单不存在")
        # 理论上 approval_id 唯一；取最后一个是为了在异常重复文件时偏向最新文件。
        return matches[-1]

    def _write_approval(self, approval: AgentToolExecutionApproval) -> None:
        """把 approval 当前状态写回 JSON 事实文件。"""

        Path(approval.json_path).write_text(
            approval.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def _render_markdown_approval(self, approval: AgentToolExecutionApproval) -> str:
        """渲染给人复查的 Markdown 执行确认单。

        注意：Markdown 不包含明文 confirmation_text，也不作为执行事实源。
        """

        preview = approval.preview
        return "\n".join(
            [
                f"# Agent Tool Execution Approval: {approval.approval_id}",
                "",
                "## Summary",
                f"- Approval Kind: `{approval.approval_kind}`",
                f"- Tool: `{approval.tool_name}`",
                f"- Operation: `{approval.operation.value}`",
                f"- Target: `{approval.target_path}`",
                f"- Risk: `{preview.risk_level.value}`",
                f"- Status: `{approval.status.value}`",
                f"- Expires At: `{approval.expires_at.isoformat()}`",
                "",
                "## Boundary",
                "- 这是高风险工具执行确认单，不是 LLM 任务规划结果。",
                "- JSON 冻结已 dry-run 和鉴权后的执行事实；确认阶段不会重新调用 LLM 规划。",
                "",
                "## Permission",
                f"- Target Departments: `{', '.join(approval.target_department_codes)}`",
                f"- Decision: `{approval.permission_decision.action.value}`",
                f"- Reason: {approval.permission_decision.reason}",
                "",
                "## Impact",
                f"- Exists Before: `{preview.exists_before}`",
                f"- Affected Doc ID: `{preview.affected_doc_id}`",
                f"- Affected Chunk Count: `{preview.affected_chunk_count}`",
                f"- Before Hash: `{preview.before_hash}`",
                f"- After Hash: `{preview.after_hash}`",
                "",
                "## Warnings",
                *[f"- {warning}" for warning in preview.warnings],
                "",
                "## Confirmation",
                "请使用系统返回的 `confirmation_text` 调用独立确认接口。",
                "不要从本 Markdown 文件反解析执行参数。",
                "",
            ]
        )


def _sha256_text(text: str) -> str:
    """计算文本 SHA256，用于确认口令、内容快照和并发保护。"""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = ["AgentToolApprovalService"]
