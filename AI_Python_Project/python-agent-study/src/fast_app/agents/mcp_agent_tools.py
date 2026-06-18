import re
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, create_model

from fast_app.agents.mcp_client_boundary import McpClientBoundary
from fast_app.agents.mcp_tool_contracts import McpToolCallRequest, McpToolInfo
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.services.exceptions import ExternalServiceError

# 负责把 `McpToolInfo.input_schema` 转成 Pydantic args schema
# 负责把 MCP tool 包装成 LangChain `StructuredTool`

logger = get_logger(__name__)

# 增加前缀避免和本地的工具名称冲突
MCP_TOOL_NAME_PREFIX = "mcp__"


def build_mcp_agent_tool_name(
    mcp_tool_name: str,
    prefix: str = MCP_TOOL_NAME_PREFIX,
) -> str:
    """把 MCP 原始工具名转换成 LangChain 可安全使用的工具名。

    MCP server 暴露的工具名可能包含连字符、空格、点号等字符。
    LangChain tool name 更适合使用字母、数字和下划线，所以这里统一归一化。
    同时加上 mcp__ 前缀，避免和工程内部工具名冲突。
    """
    normalized = re.sub(r"[^a-zA-Z0-9_]", "_", mcp_tool_name).strip("_")
    if not normalized:
        normalized = "tool"
    return f"{prefix}{normalized}"


def _json_schema_type_to_python_type(schema: dict[str, object]) -> type[Any]:
    """把 MCP input schema 中的 JSON Schema type 映射成 Python 类型。

    LangChain StructuredTool 需要 Pydantic args_schema。
    Pydantic 字段类型来自 Python 类型，所以这里做一层最小类型转换。
    当前只覆盖常见基础类型；复杂嵌套 schema 后续可以继续增强。
    """
    schema_type = schema.get("type")

    if schema_type == "string":
        return str
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        return list[object]
    if schema_type == "object":
        return dict[str, object]

    return object


def _build_tool_input_model_name(tool_name: str) -> str:
    """根据 MCP 工具名生成动态 Pydantic 输入模型名称。

    create_model() 需要一个模型名。这里把工具名拆成可读的 PascalCase 后缀，
    方便调试、报错和日志中识别是哪个 MCP tool 的输入 schema。
    """
    parts = re.split(r"[^a-zA-Z0-9]+", tool_name)
    suffix = "".join(part.capitalize() for part in parts if part) or "Tool"
    return f"Mcp{suffix}Input"


# MCP 工具的元信息
# McpToolInfo(
#     name="search-docs",
#     description="Search documents by query",
    # input_schema = {
    #     "type": "object",
    #     "properties": {
    #         "query": {
    #             "type": "string",
    #             "description": "检索关键词"
    #         },
    #         "limit": {
    #             "type": "integer",
    #             "description": "最多返回多少条"
    #         }
    #     },
    #     "required": ["query"]
    # }
# )
def build_mcp_tool_args_schema(tool_info: McpToolInfo) -> type[BaseModel]:
    """把 MCP tool 的参数要求 input_schema 封装为 LangChain tool 可用的 Pydantic schema。

    MCP tool metadata 里通常使用 JSON Schema 描述参数列表
    LangChain StructuredTool 则通过 Pydantic BaseModel 描述参数，需要进行一层转换
    """
    input_schema = tool_info.input_schema or {}
    raw_properties = input_schema.get("properties", {})
    raw_required = input_schema.get("required", [])

    properties = raw_properties if isinstance(raw_properties, dict) else {}
    required = set(raw_required) if isinstance(raw_required, list) else set()

    fields: dict[str, tuple[object, object]] = {}
    for raw_name, raw_schema in properties.items():
        # 非字符串字段名无法成为稳定的 Pydantic 字段，直接跳过。
        if not isinstance(raw_name, str):
            continue

        field_schema = raw_schema if isinstance(raw_schema, dict) else {}
        py_type = _json_schema_type_to_python_type(field_schema)
        description = field_schema.get("description", "")
        default = ... if raw_name in required else None

        # 非必填字段允许 None，这样 Agent 不传该参数时不会被 Pydantic 拒绝。
        if raw_name not in required:
            py_type = py_type | None

        fields[raw_name] = (
            py_type,
            Field(
                default,
                description=description if isinstance(description, str) else "",
            ),
        )

    if not fields:
        # 如果 MCP tool 没有声明 properties，就提供一个兜底 arguments 字段。
        # 这样仍然可以调用工具，只是参数校验精度会降低。
        fields["arguments"] = (
            dict[str, object],
            Field(
                default_factory=dict,
                description="MCP tool arguments",
            ),
        )

    # 动态创建 Pydantic 模型 ；假设`_build_tool_input_model_name()` 会生成 McpSearchDocsInput，create_model动态生成class：
    # class McpSearchDocsInput(BaseModel):
    #     query: str = Field(..., description="检索关键词")
    #     limit: int | None = Field(None, description="最多返回多少条")
    return create_model(_build_tool_input_model_name(tool_info.name), **fields)


# tool_info.name = "search-docs"
# tool_info.description = "Search documents by query"
# =>
# MCP tool `search-docs`: Search documents by query
def build_mcp_tool_description(tool_info: McpToolInfo) -> str:
    """生成给 Agent 看的工具描述。

    description 会影响 Agent 判断什么时候调用这个工具。
    这里保留 MCP 原始工具名，方便日志、trace、调试时和 MCP server 对齐。
    """
    description = tool_info.description.strip()
    if description:
        return f"MCP tool `{tool_info.name}`: {description}"

    return f"MCP tool `{tool_info.name}`"


def build_mcp_agent_tool(
    mcp_client: McpClientBoundary,
    tool_info: McpToolInfo,
    name_prefix: str = MCP_TOOL_NAME_PREFIX,
) -> BaseTool:
    """把单个 MCP tool 的原参数格式 包装成 LangChain StructuredTool。

    这个函数不直接连接 MCP server。它只把 tool metadata、args_schema、实际调用闭包组合成 LangChain Agent 能识别和调用的 BaseTool 对象格式
    """
    args_schema = build_mcp_tool_args_schema(tool_info)
    agent_tool_name = build_mcp_agent_tool_name(tool_info.name, prefix=name_prefix)

    # kwargs = {
    #     "query": "MCP resource"
    # }
    # 真正执行了工具的函数；LangChain Agent 真正调用工具时会执行的逻辑
    async def call_mcp_tool(**kwargs: object) -> str:
        """StructuredTool 实际执行时调用的异步函数。

        LangChain 会把 Pydantic 校验后的参数以 kwargs 形式传进来。
        这里再转换成 McpToolCallRequest，交给 McpClientBoundary 执行真实 MCP 调用。
        """

        # 把参数按照两个模式处理：模式 1-正常 schema 模式；模式 2-兜底 schema 模式
        if set(kwargs.keys()) == {"arguments"} and isinstance(kwargs["arguments"], dict):
            # 兜底 schema 模式：所有参数都被放进 arguments 这个 dict。
            arguments = dict(kwargs["arguments"])
        else:
            # 正常 schema 模式：过滤 None，避免把未传的可选参数发给 MCP server。
            arguments = {key: value for key, value in kwargs.items() if value is not None}

        logger.info(
            "mcp_agent_tool %s",
            format_log_fields(
                event="mcp.agent_tool.call.start",
                agent_tool_name=agent_tool_name,
                mcp_tool_name=tool_info.name,
                argument_keys=sorted(arguments.keys()),
            ),
        )

        # 这里必须使用 MCP 原始工具名，不使用加了 mcp__ 前缀的 Agent 工具名。
        result = await mcp_client.call_tool(
            McpToolCallRequest(
                tool_name=tool_info.name,
                arguments=arguments,
            )
        )

        if result.is_error:
            # MCP 协议层返回 is_error 时，把它提升成工程统一的外部服务异常。
            raise ExternalServiceError(
                f"MCP tool 调用失败: {tool_info.name}: {result.content}"
            )

        logger.info(
            "mcp_agent_tool %s",
            format_log_fields(
                event="mcp.agent_tool.call.finish",
                agent_tool_name=agent_tool_name,
                mcp_tool_name=tool_info.name,
                content_length=len(result.content),
            ),
        )
        return result.content

    return StructuredTool.from_function(
        coroutine=call_mcp_tool,
        name=agent_tool_name,
        description=build_mcp_tool_description(tool_info),
        args_schema=args_schema,
    )


# 整个文件的对外入口
async def build_mcp_agent_tools(
    mcp_client: McpClientBoundary,
    name_prefix: str = MCP_TOOL_NAME_PREFIX,
) -> list[BaseTool]:
    """发现 MCP server 上的工具，并批量包装成 LangChain tools。

    先通过 boundary list_tools() 获取 MCP tool metadata，再逐个调用 build_mcp_agent_tool() 生成 Agent 可调用工具。
    """
    tool_infos = await mcp_client.list_tools()
    return [
        build_mcp_agent_tool(
            mcp_client=mcp_client,
            tool_info=tool_info,
            name_prefix=name_prefix,
        )
        for tool_info in tool_infos
    ]
