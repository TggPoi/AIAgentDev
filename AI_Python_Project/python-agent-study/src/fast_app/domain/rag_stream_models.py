from dataclasses import dataclass
from typing import Any, Literal


RagStreamEventName = Literal[
    "sources",
    "answer_delta",
    "guard_sanitized",
    "guard_blocked",
    "token",
    "done",
    "error",
    "tool_approval_created",
    "tool_confirmation_required",
    "tool_execution_result",
    "agent_task_plan_created",
    "agent_task_step_started",
    "agent_task_step_completed",
    "agent_task_waiting_approval",
]

# 在 Pipeline 层和 API 层之间传递结构化事件。
# sources / answer_delta 是正常业务事件；guard_* 用于表达流式输出安全处理结果。
# token 保留为兼容事件名，新主线使用 answer_delta。
# tool_* 事件用于 TaskPlan 高风险步骤的执行确认单和人审确认，不进入 legacy token stream。
@dataclass(frozen=True)
class RagStreamEvent:
    # 结构化事件名称，API 层会把它写成 SSE 的 event 字段。
    event: RagStreamEventName
    # 事件 payload，内容由具体事件决定，例如 sources、answer_delta 或工具执行确认单信息。
    data: dict[str, Any]
