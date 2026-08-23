from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from fast_app.domain.agent_task_plan import AgentTaskKind, AgentTaskPlanStatus


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


__all__ = ["AgentTaskPlanListItem", "AgentTaskPlanListResponse"]
