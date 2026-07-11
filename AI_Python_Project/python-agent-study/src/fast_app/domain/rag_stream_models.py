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
    "tool_execution_result",
    "agent_task_plan_created",
    "agent_task_step_started",
    "agent_task_step_completed",
    "agent_task_waiting_confirmation",
    "agent_task_status",
    "agent_task_execution_started",
    "agent_task_sub_question_started",
    "agent_task_sub_question_completed",
    "agent_task_tool_selected",
    "agent_task_tool_call_started",
    "agent_task_tool_call_completed",
    "agent_task_tool_call_failed",
    "agent_task_final_synthesis_completed",
]

# 在 Pipeline 层和 API 层之间传递结构化事件。
# sources / answer_delta 是正常业务事件；guard_* 用于表达流式输出安全处理结果。
# token 保留为兼容事件名，新主线使用 answer_delta。
@dataclass(frozen=True)
class RagStreamEvent:
    # 结构化事件名称，API 层会把它写成 SSE 的 event 字段。
    event: RagStreamEventName
    # 事件 payload，内容由具体事件决定，例如 sources、answer_delta 或 TaskPlan 状态信息。
    data: dict[str, Any]
