from typing import Literal

from pydantic import BaseModel

from fast_app.services.exceptions import (
    AppServiceError,
    ExternalServiceError,
    ExternalServiceTimeoutError,
    LLMCallError,
    NoSearchResultError,
)


AgentErrorKind = Literal[
    "no_search_result",
    "retrieval_error",
    "rerank_error",
    "llm_error",
    "tool_error",
    "loop_limit_error",
    "unknown_error",
]
AgentErrorAction = Literal[
    "continue_with_fallback",
    "final_answer",
    "fail_request",
]


class AgentErrorDecision(BaseModel):
    """Agent 内部错误分支的稳定决策对象。"""

    kind: AgentErrorKind
    action: AgentErrorAction
    error_code: str
    error_category: str
    public_message: str
    error_node: str | None = None
    tool_name: str | None = None
    is_recoverable: bool = False


def classify_agent_error(
    exc: Exception,
    *,
    error_node: str | None = None,
    tool_name: str | None = None,
) -> AgentErrorDecision:
    """把底层异常分类为 Agent graph 可以使用的错误分支决策。"""
    if isinstance(exc, NoSearchResultError):
        return AgentErrorDecision(
            kind="no_search_result",
            action="final_answer",
            error_code=exc.error_code,
            error_category=exc.error_category,
            public_message=exc.public_message,
            error_node=error_node,
            tool_name=tool_name,
            is_recoverable=True,
        )

    if isinstance(exc, LLMCallError):
        return AgentErrorDecision(
            kind="llm_error",
            action="fail_request",
            error_code=exc.error_code,
            error_category=exc.error_category,
            public_message=exc.public_message,
            error_node=error_node,
            tool_name=tool_name,
            is_recoverable=False,
        )

    if isinstance(exc, ExternalServiceTimeoutError):
        kind: AgentErrorKind = "tool_error" if tool_name else "retrieval_error"
        action: AgentErrorAction = "fail_request"
        is_recoverable = False
        if error_node == "rerank":
            kind = "rerank_error"
            action = "continue_with_fallback"
            is_recoverable = True

        return AgentErrorDecision(
            kind=kind,
            action=action,
            error_code=exc.error_code,
            error_category=exc.error_category,
            public_message=exc.public_message,
            error_node=error_node,
            tool_name=tool_name,
            is_recoverable=is_recoverable,
        )

    if isinstance(exc, ExternalServiceError):
        kind: AgentErrorKind = "tool_error" if tool_name else "retrieval_error"
        action: AgentErrorAction = "fail_request"
        is_recoverable = False
        if error_node == "rerank":
            kind = "rerank_error"
            action = "continue_with_fallback"
            is_recoverable = True

        return AgentErrorDecision(
            kind=kind,
            action=action,
            error_code=exc.error_code,
            error_category=exc.error_category,
            public_message=exc.public_message,
            error_node=error_node,
            tool_name=tool_name,
            is_recoverable=is_recoverable,
        )

    if isinstance(exc, AppServiceError):
        return AgentErrorDecision(
            kind="unknown_error",
            action="fail_request",
            error_code=exc.error_code,
            error_category=exc.error_category,
            public_message=exc.public_message,
            error_node=error_node,
            tool_name=tool_name,
            is_recoverable=False,
        )

    return AgentErrorDecision(
        kind="unknown_error",
        action="fail_request",
        error_code="INTERNAL_SERVER_ERROR",
        error_category="system_error",
        public_message="服务器内部错误",
        error_node=error_node,
        tool_name=tool_name,
        is_recoverable=False,
    )


def build_agent_error_answer(decision: AgentErrorDecision) -> str:
    """把适合由 Agent 解释的错误决策转换为最终回答文本。"""
    if decision.kind == "no_search_result":
        return (
            "我没有在当前知识库中找到足够相关的资料，"
            "因此不能基于可靠来源回答这个问题。"
        )

    if decision.kind == "loop_limit_error":
        return "本次 Agent 执行已达到步骤上限，已停止继续调用工具。"

    return decision.public_message


__all__ = [
    "AgentErrorAction",
    "AgentErrorDecision",
    "AgentErrorKind",
    "build_agent_error_answer",
    "classify_agent_error",
]
