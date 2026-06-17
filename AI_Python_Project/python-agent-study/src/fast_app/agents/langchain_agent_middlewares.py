"""Middleware builders for the future LangChain create_agent route."""

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    PIIMiddleware,
    ToolCallLimitMiddleware,
    wrap_model_call,
)

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


def build_agent_limit_middlewares() -> list[AgentMiddleware]:
    """Build call limit middleware for create_agent based agents."""
    return [
        ModelCallLimitMiddleware(
            run_limit=8,
            exit_behavior="error",
        ),
        ToolCallLimitMiddleware(
            run_limit=10,
            exit_behavior="continue",
        ),
    ]


@wrap_model_call(name="log_agent_model_call")
def log_agent_model_call(request, handler):
    """Log model-call boundaries for create_agent based agents."""
    message_count = len(getattr(request, "messages", []) or [])
    tool_count = len(getattr(request, "tools", []) or [])

    logger.info(
        "agent_model_call %s",
        format_log_fields(
            event="agent.model_call.start",
            message_count=message_count,
            tool_count=tool_count,
        ),
    )

    response = handler(request)

    logger.info(
        "agent_model_call %s",
        format_log_fields(
            event="agent.model_call.finish",
            message_count=message_count,
            tool_count=tool_count,
        ),
    )

    return response


def build_default_create_agent_middlewares() -> list[AgentMiddleware]:
    """Build the default middleware list for the planned create_agent route."""
    return [
        *build_agent_safety_middlewares(),
        *build_agent_limit_middlewares(),
        log_agent_model_call,
    ]


__all__ = [
    "build_agent_limit_middlewares",
    "build_agent_safety_middlewares",
    "build_default_create_agent_middlewares",
    "log_agent_model_call",
]
