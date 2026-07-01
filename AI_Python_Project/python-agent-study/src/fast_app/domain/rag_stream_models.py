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
]

# 在 Pipeline 层和 API 层之间传递结构化事件。
# sources / answer_delta 是正常业务事件；guard_* 用于表达流式输出安全处理结果。
# token 保留为兼容事件名，新主线使用 answer_delta。
@dataclass(frozen=True)
class RagStreamEvent:
    event: RagStreamEventName
    data: dict[str, Any]
