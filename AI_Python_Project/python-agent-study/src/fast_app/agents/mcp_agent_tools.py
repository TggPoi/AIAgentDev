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

MCP_TOOL_NAME_PREFIX = "mcp__"


def build_mcp_agent_tool_name(
    mcp_tool_name: str,
    prefix: str = MCP_TOOL_NAME_PREFIX,
) -> str:
    """Convert an MCP tool name into a LangChain-safe tool name."""
    normalized = re.sub(r"[^a-zA-Z0-9_]", "_", mcp_tool_name).strip("_")
    if not normalized:
        normalized = "tool"
    return f"{prefix}{normalized}"


def _json_schema_type_to_python_type(schema: dict[str, object]) -> type[Any]:
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
    parts = re.split(r"[^a-zA-Z0-9]+", tool_name)
    suffix = "".join(part.capitalize() for part in parts if part) or "Tool"
    return f"Mcp{suffix}Input"


def build_mcp_tool_args_schema(tool_info: McpToolInfo) -> type[BaseModel]:
    """Build a Pydantic args schema from an MCP tool input schema."""
    input_schema = tool_info.input_schema or {}
    raw_properties = input_schema.get("properties", {})
    raw_required = input_schema.get("required", [])

    properties = raw_properties if isinstance(raw_properties, dict) else {}
    required = set(raw_required) if isinstance(raw_required, list) else set()

    fields: dict[str, tuple[object, object]] = {}
    for raw_name, raw_schema in properties.items():
        if not isinstance(raw_name, str):
            continue

        field_schema = raw_schema if isinstance(raw_schema, dict) else {}
        py_type = _json_schema_type_to_python_type(field_schema)
        description = field_schema.get("description", "")
        default = ... if raw_name in required else None

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
        fields["arguments"] = (
            dict[str, object],
            Field(
                default_factory=dict,
                description="MCP tool arguments",
            ),
        )

    return create_model(_build_tool_input_model_name(tool_info.name), **fields)


def build_mcp_tool_description(tool_info: McpToolInfo) -> str:
    description = tool_info.description.strip()
    if description:
        return f"MCP tool `{tool_info.name}`: {description}"

    return f"MCP tool `{tool_info.name}`"


def build_mcp_agent_tool(
    mcp_client: McpClientBoundary,
    tool_info: McpToolInfo,
    name_prefix: str = MCP_TOOL_NAME_PREFIX,
) -> BaseTool:
    """Wrap one MCP tool as a LangChain StructuredTool."""
    args_schema = build_mcp_tool_args_schema(tool_info)
    agent_tool_name = build_mcp_agent_tool_name(tool_info.name, prefix=name_prefix)

    async def call_mcp_tool(**kwargs: object) -> str:
        if set(kwargs.keys()) == {"arguments"} and isinstance(kwargs["arguments"], dict):
            arguments = dict(kwargs["arguments"])
        else:
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

        result = await mcp_client.call_tool(
            McpToolCallRequest(
                tool_name=tool_info.name,
                arguments=arguments,
            )
        )

        if result.is_error:
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


async def build_mcp_agent_tools(
    mcp_client: McpClientBoundary,
    name_prefix: str = MCP_TOOL_NAME_PREFIX,
) -> list[BaseTool]:
    """Discover MCP tools and wrap them as LangChain tools."""
    tool_infos = await mcp_client.list_tools()
    return [
        build_mcp_agent_tool(
            mcp_client=mcp_client,
            tool_info=tool_info,
            name_prefix=name_prefix,
        )
        for tool_info in tool_infos
    ]
