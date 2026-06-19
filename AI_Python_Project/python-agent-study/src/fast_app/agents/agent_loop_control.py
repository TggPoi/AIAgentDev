from typing import Literal

from pydantic import BaseModel, Field

from fast_app.core.config import Settings


AgentLoopTerminationReason = Literal[
    "continue",
    "final_answer_ready",
    "max_steps_reached",
    "max_tool_calls_reached",
    "tool_error",
    "model_error",
]


class AgentLoopLimits(BaseModel):
    """单次 Agent loop 的硬性上限配置。"""

    max_steps: int = Field(default=6, ge=1, le=50)
    max_tool_calls: int = Field(default=4, ge=0, le=50)


class AgentLoopSnapshot(BaseModel):
    """一次循环判断所需的最小状态快照。"""

    step_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    final_answer_ready: bool = False
    has_tool_error: bool = False
    has_model_error: bool = False


class AgentLoopDecision(BaseModel):
    """Agent loop 是否继续，以及停止或继续的原因。"""

    should_continue: bool
    reason: AgentLoopTerminationReason


def should_continue_agent_loop(
    snapshot: AgentLoopSnapshot,
    limits: AgentLoopLimits,
) -> AgentLoopDecision:
    """根据当前快照和上限判断 Agent loop 是否允许继续。

    这个函数只做纯判断，不调用模型、不调用工具，也不依赖具体 Graph state。
    后续显式 LangGraph Agent 或 create_agent wrapper 都可以把自己的状态转换成
    AgentLoopSnapshot，再复用这里的终止规则。
    """
    if snapshot.final_answer_ready:
        return AgentLoopDecision(
            should_continue=False,
            reason="final_answer_ready",
        )

    if snapshot.has_tool_error:
        return AgentLoopDecision(
            should_continue=False,
            reason="tool_error",
        )

    if snapshot.has_model_error:
        return AgentLoopDecision(
            should_continue=False,
            reason="model_error",
        )

    if snapshot.step_count >= limits.max_steps:
        return AgentLoopDecision(
            should_continue=False,
            reason="max_steps_reached",
        )

    if snapshot.tool_call_count >= limits.max_tool_calls:
        return AgentLoopDecision(
            should_continue=False,
            reason="max_tool_calls_reached",
        )

    return AgentLoopDecision(
        should_continue=True,
        reason="continue",
    )


def build_agent_loop_limits_from_settings(settings: Settings) -> AgentLoopLimits:
    """从全局 Settings 构造 Agent loop 上限配置。"""
    return AgentLoopLimits(
        max_steps=settings.agent_max_steps,
        max_tool_calls=settings.agent_max_tool_calls,
    )


__all__ = [
    "AgentLoopDecision",
    "AgentLoopLimits",
    "AgentLoopSnapshot",
    "AgentLoopTerminationReason",
    "build_agent_loop_limits_from_settings",
    "should_continue_agent_loop",
]
