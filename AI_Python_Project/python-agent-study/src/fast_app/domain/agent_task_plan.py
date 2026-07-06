from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


AgentTaskKind = Literal["knowledge_report_to_document"]


class AgentTaskPlanStatus(StrEnum):
    """LLM 多步骤任务计划状态。"""

    CREATED = "created"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentToolStepStatus(StrEnum):
    """TaskPlan 中单个工具步骤的执行状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    WAITING_APPROVAL = "waiting_approval"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentToolStep(BaseModel):
    """Agent 多步骤任务中的一个工具步骤。"""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(description="步骤唯一 ID，当前 task plan 内稳定。")
    tool_name: str = Field(description="本步骤调用的工具名。")
    status: AgentToolStepStatus = Field(
        default=AgentToolStepStatus.PENDING,
        description="本步骤当前执行状态。",
    )
    input: dict[str, Any] = Field(
        default_factory=dict,
        description="工具调用输入，必须是 JSON 可序列化结构。",
    )
    output: dict[str, Any] = Field(
        default_factory=dict,
        description="工具调用输出摘要，供后续步骤和 React 展示使用。",
    )
    risk_level: str = Field(default="low", description="步骤风险等级。")
    requires_approval: bool = Field(
        default=False,
        description="该步骤是否必须生成工具执行确认单。",
    )
    approval_id: str | None = Field(
        default=None,
        description="该步骤关联的工具执行确认单 ID；没有确认单时为空。",
    )
    error: str | None = Field(default=None, description="步骤失败原因。")


class AgentTaskPlan(BaseModel):
    """LLM 生成的 Agent 多步骤任务计划。"""

    model_config = ConfigDict(extra="forbid")

    task_plan_id: str = Field(description="任务计划唯一 ID。")
    task_kind: AgentTaskKind = Field(
        description="白名单任务类型；v1 只支持 knowledge_report_to_document。",
    )
    user_id: str | None = Field(
        default=None,
        description="创建该任务计划的用户 ID，用于查询和审计。",
    )
    goal: str = Field(description="用户希望完成的业务目标。")
    source_query: str = Field(description="用于知识库检索的查询文本。")
    target_path: str = Field(description="报告要保存到的知识库相对路径。")
    report_title: str = Field(default="知识库报告", description="报告标题。")
    status: AgentTaskPlanStatus = Field(
        default=AgentTaskPlanStatus.CREATED,
        description="任务计划整体状态。",
    )
    steps: list[AgentToolStep] = Field(description="顺序执行的工具步骤列表。")
    final_output: dict[str, Any] = Field(
        default_factory=dict,
        description="任务最终输出摘要，例如 approval_id 或报告长度。",
    )
    created_at: datetime = Field(description="任务计划创建时间。")
    updated_at: datetime = Field(description="任务计划最后更新时间。")
    error: str | None = Field(default=None, description="任务失败原因。")


__all__ = [
    "AgentTaskKind",
    "AgentTaskPlan",
    "AgentTaskPlanStatus",
    "AgentToolStep",
    "AgentToolStepStatus",
]
