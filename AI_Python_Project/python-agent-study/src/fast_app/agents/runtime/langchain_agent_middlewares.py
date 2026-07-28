"""LangChain/Deep Agents 共用的横切 Middleware 装配。"""

from threading import Lock

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    PIIMiddleware,
    ToolCallLimitMiddleware,
)

from fast_app.core.config import Settings
from fast_app.core.logging import format_log_fields, get_logger


logger = get_logger(__name__)


class SharedModelCallBudgetExceededError(RuntimeError):
    """一次多 Agent 工作流已耗尽所有角色共享的模型调用预算。"""

    def __init__(self, used_calls: int, limit: int) -> None:
        self.used_calls = used_calls
        self.limit = limit
        super().__init__(f"文档 Agent 总模型调用预算已耗尽（{used_calls}/{limit}）")


class SharedModelCallBudgetMiddleware(AgentMiddleware):
    """让 Coordinator 与全部临时 SubAgent 共用同一个进程内调用计数器。"""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._used_calls = 0
        self._lock = Lock()

    @property
    def used_calls(self) -> int:
        """返回本次工作流已经启动的模型调用数。"""

        with self._lock:
            return self._used_calls

    def _reserve(self) -> None:
        """在请求发往模型前原子占用一个名额，失败调用也计入预算。"""

        with self._lock:
            if self._used_calls >= self.limit:
                raise SharedModelCallBudgetExceededError(
                    used_calls=self._used_calls,
                    limit=self.limit,
                )
            self._used_calls += 1

    def wrap_model_call(self, request, handler):
        """同步 Agent 调用共享同一预算。"""

        self._reserve()
        return handler(request)

    async def awrap_model_call(self, request, handler):
        """异步 Agent 调用共享同一预算。"""

        self._reserve()
        return await handler(request)


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
    *,
    model_run_limit: int | None = None,
    tool_run_limits: dict[str, int] | None = None,
) -> list[AgentMiddleware]:
    """复用框架安全与预算 Middleware，并可限制指定文档工具的单次调用数。

    ``tool_run_limits`` 主要供 Researcher 使用。例如限制重复检索时，仍由
    LangChain 官方 ``ToolCallLimitMiddleware`` 返回可继续处理的 ToolMessage，
    不在业务工具中重复实现另一套计数器。
    """

    return [
        *build_agent_safety_middlewares(),
        # 默认模型循环使用 AGENT_MAX_STEPS；只有负责派发多个子 Agent 的
        # Coordinator 会显式传入更高上限。工具总预算始终独立使用
        # AGENT_MAX_TOOL_CALLS，不能把高上限扩散到每个 SubAgent。
        *build_agent_limit_middlewares(
            settings,
            model_run_limit=model_run_limit,
        ),
        *[
            ToolCallLimitMiddleware(
                tool_name=tool_name,
                run_limit=run_limit,
                exit_behavior="continue",
            )
            for tool_name, run_limit in (tool_run_limits or {}).items()
        ],
        log_agent_model_call,
    ]


__all__ = [
    "SharedModelCallBudgetExceededError",
    "SharedModelCallBudgetMiddleware",
    "build_agent_limit_middlewares",
    "build_agent_safety_middlewares",
    "build_default_create_agent_middlewares",
    "build_document_deep_agent_middlewares",
    "log_agent_model_call",
]
