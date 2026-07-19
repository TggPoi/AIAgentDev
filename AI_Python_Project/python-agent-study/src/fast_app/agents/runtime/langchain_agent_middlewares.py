"""LangChain/Deep Agents 共用的横切 Middleware 装配。"""

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    PIIMiddleware,
    ToolCallLimitMiddleware,
)

from fast_app.core.config import Settings
from fast_app.core.logging import format_log_fields, get_logger


logger = get_logger(__name__)


def build_agent_safety_middlewares() -> list[AgentMiddleware]:
    """Build safety middleware for create_agent based agents."""
    return [
        PIIMiddleware(
            "email",
            strategy="redact",
            apply_to_input=True,
            apply_to_output=True,
        )
    ]


def build_agent_limit_middlewares(
    settings: Settings | None = None,
    *,
    model_run_limit: int | None = None,
) -> list[AgentMiddleware]:
    """装配模型和工具调用预算；旧调用方未传配置时保持原默认值。"""
    return [
        ModelCallLimitMiddleware(
            run_limit=(
                model_run_limit
                if model_run_limit is not None
                else (settings.agent_max_steps if settings is not None else 8)
            ),
            exit_behavior="error",
        ),
        ToolCallLimitMiddleware(
            run_limit=(settings.agent_max_tool_calls if settings is not None else 10),
            exit_behavior="continue",
        ),
    ]


class _AgentModelCallLoggingMiddleware(AgentMiddleware):
    """同时支持同步和异步 Agent 的模型调用边界日志。"""

    @staticmethod
    def _log(event: str, request) -> None:
        logger.info(
            "agent_model_call %s",
            format_log_fields(
                event=event,
                message_count=len(getattr(request, "messages", []) or []),
                tool_count=len(getattr(request, "tools", []) or []),
            ),
        )

    def wrap_model_call(self, request, handler):
        self._log("agent.model_call.start", request)
        response = handler(request)
        self._log("agent.model_call.finish", request)
        return response

    async def awrap_model_call(self, request, handler):
        self._log("agent.model_call.start", request)
        response = await handler(request)
        self._log("agent.model_call.finish", request)
        return response


# 保持已有公开装配名称不变；对象现在可同时用于 invoke() 与 ainvoke()。
log_agent_model_call = _AgentModelCallLoggingMiddleware()


def build_default_create_agent_middlewares() -> list[AgentMiddleware]:
    """Build the default middleware list for the planned create_agent route."""
    return [
        *build_agent_safety_middlewares(),
        *build_agent_limit_middlewares(),
        log_agent_model_call,
    ]


def build_document_deep_agent_middlewares(
    settings: Settings,
) -> list[AgentMiddleware]:
    """复用已有安全、预算和日志 Middleware，不复制 Deep Agents 内置能力。"""

    return [
        *build_agent_safety_middlewares(),
        *build_agent_limit_middlewares(
            settings,
            model_run_limit=settings.agent_max_tool_calls,
        ),
        log_agent_model_call,
    ]


__all__ = [
    "build_agent_limit_middlewares",
    "build_agent_safety_middlewares",
    "build_default_create_agent_middlewares",
    "build_document_deep_agent_middlewares",
    "log_agent_model_call",
]
