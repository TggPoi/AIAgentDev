from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from fast_app.domain.agent_task_plan import (
    AgentTaskKind,
    AgentTaskPlan,
    AgentTaskPlanStatus,
    AgentTaskType,
    AgentToolStepStatus,
)
from fast_app.domain.research_task_plan import ResearchTaskPlanPublicView


DocumentTaskPlanRiskLevel = Literal[
    "low",
    "medium",
    "high",
    "critical",
    "unknown",
]


class AgentTaskPlanListItem(BaseModel):
    """任务中心列表使用的安全 TaskPlan 摘要。"""

    model_config = ConfigDict(extra="forbid")

    task_plan_id: str = Field(description="TaskPlan 唯一 ID。")
    task_kind: AgentTaskKind = Field(description="研究分析或知识文档管理任务类型。")
    status: AgentTaskPlanStatus = Field(description="TaskPlan 当前生命周期状态。")
    session_id: str | None = Field(
        default=None,
        description="创建该 TaskPlan 的外部会话 ID；旧任务或非会话任务为空。",
    )
    summary: str = Field(description="经过长度限制的任务目标摘要。")
    requires_confirmation: bool = Field(
        description="当前状态是否等待用户确认后继续执行。"
    )
    error_code: str | None = Field(
        default=None,
        description="失败任务的稳定公开错误码；没有公开错误码时为空。",
    )
    created_at: datetime = Field(description="TaskPlan 创建时间。")
    updated_at: datetime = Field(description="TaskPlan 最近更新时间。")


class AgentTaskPlanListResponse(BaseModel):
    """当前用户 TaskPlan 的 keyset 分页结果。"""

    model_config = ConfigDict(extra="forbid")

    items: list[AgentTaskPlanListItem] = Field(description="本页 TaskPlan 安全摘要。")
    next_cursor: str | None = Field(
        default=None,
        description="下一页不透明 cursor；没有更多数据时为空。",
    )


class DocumentTaskPlanStepPublicView(BaseModel):
    """文档 TaskPlan 步骤的安全公开元数据。"""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(description="当前 TaskPlan 内稳定的步骤 ID。")
    tool_name: str = Field(description="供用户识别步骤用途的工具名。")
    status: AgentToolStepStatus = Field(description="步骤当前执行状态。")
    risk_level: DocumentTaskPlanRiskLevel = Field(
        description="服务端评估的稳定公开风险等级；未知内部值统一为 unknown。"
    )
    requires_confirmation: bool = Field(description="步骤是否需要人工确认。")
    error_code: str | None = Field(
        default=None,
        description="步骤失败时的稳定公开错误码；不包含原始错误正文。",
    )


class DocumentTaskPlanResultSummary(BaseModel):
    """不包含工具输出的文档 TaskPlan 计数摘要。"""

    model_config = ConfigDict(extra="forbid")

    total_steps: int = Field(ge=0, description="计划步骤总数。")
    completed_steps: int = Field(ge=0, description="已完成步骤数量。")
    failed_steps: int = Field(ge=0, description="失败步骤数量。")
    skipped_steps: int = Field(ge=0, description="跳过步骤数量。")


class DocumentTaskPlanPublicView(BaseModel):
    """排除工具参数、原始输出和内部 owner 信息的文档 TaskPlan。"""

    model_config = ConfigDict(extra="forbid")

    task_plan_id: str = Field(description="TaskPlan 唯一 ID。")
    task_kind: Literal["knowledge_document_management"] = Field(
        description="知识文档管理任务类型。"
    )
    session_id: str | None = Field(
        default=None,
        max_length=128,
        description="创建该计划的外部会话 ID；旧计划或非会话任务为空。",
    )
    objective: str = Field(description="用户可见的任务目标。")
    task_type: AgentTaskType = Field(description="用户可见的任务分类。")
    status: AgentTaskPlanStatus = Field(description="TaskPlan 当前生命周期状态。")
    requires_confirmation: bool = Field(description="当前是否等待用户确认。")
    steps: list[DocumentTaskPlanStepPublicView] = Field(
        description="不包含 input、output 或原始错误正文的安全步骤列表。"
    )
    result_summary: DocumentTaskPlanResultSummary = Field(
        description="不包含 final_output 的计数摘要。"
    )
    created_at: datetime = Field(description="TaskPlan 创建时间。")
    updated_at: datetime = Field(description="TaskPlan 最近更新时间。")
    error_code: str | None = Field(
        default=None,
        description="计划失败时的稳定公开错误码；不包含原始错误正文。",
    )


AgentTaskPlanDetailResponse = Annotated[
    ResearchTaskPlanPublicView | DocumentTaskPlanPublicView,
    Field(discriminator="task_kind"),
]


def build_document_task_plan_public_view(
    plan: AgentTaskPlan,
) -> DocumentTaskPlanPublicView:
    """从内部文档 TaskPlan 构造显式 allowlist 的公开视图。"""

    steps = [
        DocumentTaskPlanStepPublicView(
            step_id=step.step_id,
            tool_name=step.tool_name,
            status=step.status,
            risk_level=_public_document_risk_level(step.risk_level),
            requires_confirmation=step.requires_confirmation,
            error_code=(
                "AGENT_TASK_STEP_FAILED"
                if step.status == AgentToolStepStatus.FAILED
                else None
            ),
        )
        for step in plan.steps
    ]
    return DocumentTaskPlanPublicView(
        task_plan_id=plan.task_plan_id,
        task_kind="knowledge_document_management",
        session_id=plan.session_id,
        objective=plan.objective,
        task_type=plan.task_type,
        status=plan.status,
        requires_confirmation=(
            plan.status == AgentTaskPlanStatus.WAITING_CONFIRMATION
        ),
        steps=steps,
        result_summary=DocumentTaskPlanResultSummary(
            total_steps=len(steps),
            completed_steps=sum(
                step.status == AgentToolStepStatus.COMPLETED for step in steps
            ),
            failed_steps=sum(
                step.status == AgentToolStepStatus.FAILED for step in steps
            ),
            skipped_steps=sum(
                step.status == AgentToolStepStatus.SKIPPED for step in steps
            ),
        ),
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        error_code=(
            "AGENT_TASK_PLAN_FAILED"
            if plan.status == AgentTaskPlanStatus.FAILED
            else None
        ),
    )


def _public_document_risk_level(value: str) -> DocumentTaskPlanRiskLevel:
    if value == "low":
        return "low"
    if value == "medium":
        return "medium"
    if value == "high":
        return "high"
    if value == "critical":
        return "critical"
    return "unknown"


__all__ = [
    "AgentTaskPlanDetailResponse",
    "AgentTaskPlanListItem",
    "AgentTaskPlanListResponse",
    "DocumentTaskPlanPublicView",
    "DocumentTaskPlanRiskLevel",
    "DocumentTaskPlanResultSummary",
    "DocumentTaskPlanStepPublicView",
    "build_document_task_plan_public_view",
]
