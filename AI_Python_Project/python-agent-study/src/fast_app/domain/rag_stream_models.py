from dataclasses import dataclass
from typing import Any, Literal


RagStreamEventName = Literal["sources", "token"]

# 在 Pipeline 层和 API 层之间传递结构化事件 表达业务事件名称；done / error 属于 SSE 输出协议收尾，由api层负责处理
@dataclass(frozen=True)
class RagStreamEvent:
    event: RagStreamEventName
    data: dict[str, Any]