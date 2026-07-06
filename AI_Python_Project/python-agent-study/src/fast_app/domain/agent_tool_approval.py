from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fast_app.domain.agent_tool_permissions import AgentToolPermissionDecision
from fast_app.domain.knowledge_document_actions import (
    KnowledgeDocumentActionPreview,
    KnowledgeDocumentOperation,
)


class AgentToolApprovalStatus(StrEnum):
    """Agent 工具执行确认单状态。"""

    # 已生成确认单，正在等待人工确认。
    PENDING_CONFIRMATION = "pending_confirmation"
    # 确认单已确认并执行完成。
    EXECUTED = "executed"
    # 确认单已被拒绝。
    REJECTED = "rejected"
    # 确认单已过期，不能再执行。
    EXPIRED = "expired"


class AgentToolExecutionApproval(BaseModel):
    """高风险工具执行确认单的机器事实源。

    `.md` 文件只给人看；确认执行时必须读取这个结构化模型，不能反解析 Markdown。
    """

    # approval JSON 是确认执行的机器事实源，禁止保存未声明字段。
    model_config = ConfigDict(extra="forbid")

    approval_kind: Literal["tool_execution_approval"] = Field(
        description="确认单类型：高风险工具执行确认单，不是后续 TaskPlan。",
    )
    approval_id: str = Field(description="工具执行确认单唯一 ID，也是确认接口的路径参数。")
    user_id: str = Field(description="创建该确认单的用户 ID，用于确认阶段校验归属。")
    tool_name: str = Field(description="确认单准备调用的 Agent 工具名。")
    operation: KnowledgeDocumentOperation = Field(
        description="确认单对应的文档动作：create / update / delete。",
    )
    target_path: str = Field(description="工具执行确认单作用的知识库相对目标路径。")
    target_department_codes: list[str] = Field(
        default_factory=list,
        description="目标文档所属部门范围，是确认阶段重新鉴权的事实输入。",
    )
    content_hash: str | None = Field(
        default=None,
        description="create/update 目标内容的 SHA256；delete 时通常为空。",
    )
    permission_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="approval 生成时根据目标路径推断出的权限 metadata 快照。",
    )
    confirmation_text_hash: str = Field(
        description="确认口令的 SHA256；只保存 hash，不保存明文确认口令。",
    )
    status: AgentToolApprovalStatus = Field(
        default=AgentToolApprovalStatus.PENDING_CONFIRMATION,
        description="当前确认单状态，用于防止重复执行、过期执行或错误状态执行。",
    )
    created_at: datetime = Field(description="确认单创建时间。")
    expires_at: datetime = Field(description="确认单过期时间，过期后拒绝确认执行。")
    markdown_path: str = Field(description="给人复查的 Markdown approval 文件路径。")
    json_path: str = Field(description="机器事实源 JSON approval 文件路径。")
    reason: str = Field(description="planner 识别或用户请求中给出的动作原因。")
    action_request: dict[str, Any] = Field(
        description="原始文档动作请求快照，确认执行时从这里重建请求。",
    )
    preview: KnowledgeDocumentActionPreview = Field(
        description="执行前预览结果，包括风险、hash、影响 chunk 和 warnings。",
    )
    permission_decision: AgentToolPermissionDecision = Field(
        description="生成 approval 时的权限裁决快照，用于复查和审计。",
    )
    executed_at: datetime | None = Field(
        default=None,
        description="确认单实际执行时间；尚未执行时为空。",
    )


class AgentToolApprovalCreateResult(BaseModel):
    """创建执行确认单后返回给 Agent / API 层的结构化结果。"""

    approval: AgentToolExecutionApproval = Field(
        description="已持久化的工具执行确认单模型。",
    )
    confirmation_text: str = Field(
        description="本次返回给用户的明文确认口令，只在创建 approval 时展示。",
    )
    markdown_path: str = Field(description="Markdown 展示文件路径。")
    json_path: str = Field(description="JSON 事实文件路径。")


class AgentToolApprovalConfirmResult(BaseModel):
    """确认执行接口返回的业务结果。"""

    approval_id: str = Field(description="被确认执行的工具执行确认单 ID。")
    status: AgentToolApprovalStatus = Field(description="确认后的确认单状态。")
    executed: bool = Field(description="是否已经执行真实工具动作。")
    message: str = Field(description="执行结果说明，面向 API 调用方展示。")
    result: dict[str, Any] = Field(
        default_factory=dict,
        description="底层文档动作执行结果的结构化详情。",
    )


__all__ = [
    "AgentToolExecutionApproval",
    "AgentToolApprovalConfirmResult",
    "AgentToolApprovalCreateResult",
    "AgentToolApprovalStatus",
]
