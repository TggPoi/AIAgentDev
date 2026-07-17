import inspect
from collections.abc import Iterable
from typing import Protocol

from fast_app.agents.mcp.mcp_tool_contracts import (
    McpStdioServerConfig,
    McpToolCallRequest,
    McpToolCallResult,
    McpToolInfo,
)
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.services.exceptions import ExternalServiceError


logger = get_logger(__name__)


class McpSessionProtocol(Protocol):
    """MCP SDK session 的最小形状。

    当前阶段不直接依赖具体 MCP SDK 类型，只要求注入对象具备
    list_tools / call_tool 两个动作。后续真实 SDK 接入时，只要适配到
    这个协议，Graph / Agent 侧就不需要感知 SDK 细节。
    """

    def list_tools(self) -> object:
        """列出 MCP server 暴露的工具。"""
        ...

    def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        """调用指定 MCP 工具。"""
        ...


async def _maybe_await(value: object) -> object:
    """兼容同步返回值和异步返回值。

    fake session 可能直接返回普通对象，真实 MCP SDK 通常返回 awaitable。
    这里统一处理，避免 list_tools / call_tool 主流程里到处写判断。
    """
    if inspect.isawaitable(value):
        return await value

    return value


# 兼容 dict 和对象属性如果 value 是 dict，就用 value[name] 取。如果 value 是对象，就用 getattr(value, name) 取。
# 都取不到，就返回 default。
def _get_field(value: object, *names: str, default: object = None) -> object:
    """从 dict 或对象属性中读取字段。

    MCP SDK 返回值可能是 dict、Pydantic model、dataclass 或普通对象。
    这个 helper 用多个候选字段名做兼容，例如 input_schema / inputSchema。
    """
    if isinstance(value, dict):
        for name in names:
            if name in value:
                return value[name]
        return default

    for name in names:
        if hasattr(value, name):
            return getattr(value, name)

    return default


def _as_dict(value: object) -> dict[str, object]:
    """只接受 dict 类型的 schema，其他类型先降级为空 dict。"""
    if isinstance(value, dict):
        return dict(value)

    return {}


# MCP SDK 返回的工具可能长这样：
# {
#     "tools": [
#         {
#             "name": "search",
#             "description": "search something",
#             "inputSchema": {...}
#         }
#     ]
# }
# 也可能是对象：
# ListToolsResult(
#     tools=[
#         Tool(
#             name="search",
#             description="search something",
#             input_schema={...}
#         )
#     ]
# )
def _normalize_tools(raw_result: object) -> list[McpToolInfo]:
    """把 MCP list_tools 原始结果转换成工程内部的 McpToolInfo 列表。

    这里是 SDK 类型隔离层：无论真实 SDK 返回对象结构如何，下游只接触
    McpToolInfo，不直接依赖 MCP SDK 的原始 Tool 对象。
    """
    raw_tools = _get_field(raw_result, "tools", default=raw_result)

    if raw_tools is None:
        return []

    if isinstance(raw_tools, (str, bytes)) or not isinstance(raw_tools, Iterable):
        raise ExternalServiceError("MCP list_tools 返回格式不正确")

    tools: list[McpToolInfo] = []

    for raw_tool in raw_tools:
        # 没有名称的工具无法被后续 adapter 或 Agent 稳定调用，直接跳过。
        name = _get_field(raw_tool, "name", default="")
        if not isinstance(name, str) or not name:
            continue

        description = _get_field(raw_tool, "description", default="")
        input_schema = _get_field(
            raw_tool,
            "input_schema",
            "inputSchema",
            "schema",
            default={},
        )
        tools.append(
            McpToolInfo(
                name=name,
                description=description if isinstance(description, str) else "",
                input_schema=_as_dict(input_schema),
            )
        )

    return tools


def _normalize_content_item(item: object) -> str:
    """把单个 MCP content item 转成文本。

    MCP 工具结果可能是 text content 列表，也可能直接返回字符串。
    当前 13-6 只建立基础边界，先统一成 Agent 最容易消费的文本。
    """
    text = _get_field(item, "text", default=None)
    if isinstance(text, str):
        return text

    if isinstance(item, str):
        return item

    return str(item)


def _normalize_tool_result(
    tool_name: str,
    raw_result: object,
) -> McpToolCallResult:
    """把 MCP call_tool 原始结果转换成内部 McpToolCallResult。

    content 负责给后续 Agent tool adapter 使用；is_error 负责给后续错误分支
    使用；raw_result 保留原始对象，方便调试和未来扩展结构化返回。
    """
    raw_content = _get_field(raw_result, "content", default=raw_result)
    raw_is_error = _get_field(raw_result, "is_error", "isError", default=False)

    if isinstance(raw_content, list):
        content = "\n".join(_normalize_content_item(item) for item in raw_content)
    elif isinstance(raw_content, str):
        content = raw_content
    elif raw_content is None:
        content = ""
    else:
        content = str(raw_content)

    return McpToolCallResult(
        tool_name=tool_name,
        content=content,
        is_error=bool(raw_is_error),
        raw_result=raw_result,
    )

# MCP client boundary 把 MCP SDK 返回值转换成内部模型
class McpClientBoundary:
    """MCP client 的薄边界。

    这个类只负责协议访问和结果归一化，不负责把 MCP tool 包装成
    LangChain BaseTool，也不负责决定 Agent 什么时候调用工具。
    """

    def __init__(
        self,
        session: McpSessionProtocol | None = None,
        allowed_tool_names: set[str] | None = None,
    ):
        """保存 MCP session 和可选工具白名单。

        session 可以是真实 MCP SDK session，也可以是测试用 fake session。
        allowed_tool_names 是后续权限边界的最小入口。
        """
        self.session = session
        self.allowed_tool_names = allowed_tool_names

    def _require_session(self) -> McpSessionProtocol:
        """确保 boundary 已经注入可用 session。"""
        if self.session is None:
            raise ExternalServiceError("MCP client session 尚未配置")

        return self.session

    def _ensure_allowed(self, tool_name: str) -> None:
        """检查工具是否在白名单中。

        allowed_tool_names 为 None 表示当前阶段不启用白名单限制；
        一旦传入集合，就只允许调用集合中的工具。
        """
        if self.allowed_tool_names is None:
            return

        if tool_name not in self.allowed_tool_names:
            raise ExternalServiceError(f"MCP tool 不在允许列表中: {tool_name}")

    async def list_tools(self) -> list[McpToolInfo]:
        """列出 MCP server 工具，并转换成内部稳定 contract。"""
        session = self._require_session()
        raw_result = await _maybe_await(session.list_tools())
        tools = _normalize_tools(raw_result)

        logger.info(
            "mcp_client %s",
            format_log_fields(
                event="mcp.list_tools.finish",
                tool_count=len(tools),
                tool_names=[tool.name for tool in tools],
            ),
        )
        return tools

    async def call_tool(
        self,
        request: McpToolCallRequest,
    ) -> McpToolCallResult:
        """调用 MCP 工具，并转换成内部稳定结果模型。

        这里接收 McpToolCallRequest，而不是裸 tool_name / dict，是为了给
        后续参数校验、审计、权限控制留下统一入口。
        """
        self._ensure_allowed(request.tool_name)
        session = self._require_session()

        logger.info(
            "mcp_client %s",
            format_log_fields(
                event="mcp.call_tool.start",
                tool_name=request.tool_name,
                argument_keys=sorted(request.arguments.keys()),
            ),
        )

        raw_result = await _maybe_await(
            session.call_tool(request.tool_name, request.arguments)
        )
        result = _normalize_tool_result(request.tool_name, raw_result)

        logger.info(
            "mcp_client %s",
            format_log_fields(
                event="mcp.call_tool.finish",
                tool_name=result.tool_name,
                is_error=result.is_error,
                content_length=len(result.content),
            ),
        )
        return result


class McpStdioClientBoundary(McpClientBoundary):
    """MCP client boundary backed by a real stdio MCP server.

    The first version opens a short-lived MCP session for each operation. This
    keeps lifecycle handling explicit and avoids leaking subprocesses while the
    project is still learning the MCP integration boundary.
    """

    def __init__(
        self,
        server_config: McpStdioServerConfig,
        allowed_tool_names: set[str] | None = None,
    ):
        # session=None ：每次 list_tools 或 call_tool 时，临时启动一个 MCP stdio session。用完之后关闭
        # 生命周期清晰，不容易泄漏子进程。但是每次调用都要重新启动 MCP server，性能可能差一些。
        super().__init__(session=None, allowed_tool_names=allowed_tool_names)
        self.server_config = server_config

    # 打开真实 MCP stdio session
    # 懒加载 MCP SDK 只有真正使用 stdio boundary 时才导入
    async def _with_session(self):
        """Open and initialize a real MCP stdio session."""
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise ExternalServiceError(
                "MCP SDK 未安装，请先安装 mcp==1.28.0"
            ) from exc

        server_params = StdioServerParameters(
            command=self.server_config.command,
            args=self.server_config.args,
            env=self.server_config.env,
        )

        # 自定义异步上下文管理器
        class _SessionContext:
            # 进入 async with 时：启动 MCP server，创建 session，初始化 session。
            async def __aenter__(context_self):
                context_self.stdio_context = stdio_client(server_params)
                # read_stream: 从 MCP server 读数据
                # write_stream: 向 MCP server 写数据
                read_stream, write_stream = await context_self.stdio_context.__aenter__()
                context_self.session_context = ClientSession(
                    read_stream,
                    write_stream,
                )
                session = await context_self.session_context.__aenter__()

                # 调用 session.initialize() 完成 MCP 初始化握手
                await session.initialize()
                return session

            # 离开 async with 时：关闭 session，关闭 stdio 连接，释放子进程资源。
            async def __aexit__(context_self, exc_type, exc, tb):
                # 关闭 ClientSession
                await context_self.session_context.__aexit__(exc_type, exc, tb)
                # 关闭 stdio_client 上下文
                await context_self.stdio_context.__aexit__(exc_type, exc, tb)

        return _SessionContext()


    # 真实列出 MCP server 工具
    async def list_tools(self) -> list[McpToolInfo]:
        """List tools from a real stdio MCP server."""

        # async with await 等价于：
        # session_context = await self._with_session()
        # async with session_context as session:
        async with await self._with_session() as session:

            raw_result = await session.list_tools()
            tools = _normalize_tools(raw_result)

        if self.allowed_tool_names is not None:
            tools = [tool for tool in tools if tool.name in self.allowed_tool_names]

        logger.info(
            "mcp_client %s",
            format_log_fields(
                event="mcp.stdio.list_tools.finish",
                command=self.server_config.command,
                tool_count=len(tools),
                tool_names=[tool.name for tool in tools],
            ),
        )
        return tools

    async def call_tool(
        self,
        request: McpToolCallRequest,
    ) -> McpToolCallResult:
        """Call a tool on a real stdio MCP server."""
        self._ensure_allowed(request.tool_name)

        logger.info(
            "mcp_client %s",
            format_log_fields(
                event="mcp.stdio.call_tool.start",
                command=self.server_config.command,
                tool_name=request.tool_name,
                argument_keys=sorted(request.arguments.keys()),
            ),
        )

        async with await self._with_session() as session:
            raw_result = await session.call_tool(
                request.tool_name,
                request.arguments,
            )
            result = _normalize_tool_result(request.tool_name, raw_result)

        logger.info(
            "mcp_client %s",
            format_log_fields(
                event="mcp.stdio.call_tool.finish",
                tool_name=result.tool_name,
                is_error=result.is_error,
                content_length=len(result.content),
            ),
        )
        return result
