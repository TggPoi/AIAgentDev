from pydantic import BaseModel, Field

# 对接MCP SDK 的原始对象

# MCP SDK 的原始返回对象不应该扩散到 Graph state、API schema 或业务服务里。
# 当前工程需要一个自己的稳定 contract，后续 SDK 版本变化时只改 boundary 层。


# MCP server 返回的工具名称、描述和输入 schema。把 MCP SDK 的工具描述转换成当前工程自己的 Pydantic model
class McpToolInfo(BaseModel):
    """MCP tool metadata normalized for the FastAPI RAG project."""

    name: str
    description: str = ""
    input_schema: dict[str, object] = Field(default_factory=dict)


# 一次 MCP 工具调用请求
class McpToolCallRequest(BaseModel):
    """Internal request model for one MCP tool call."""

    tool_name: str
    arguments: dict[str, object] = Field(default_factory=dict)


# MCP server 的工具调用返回值
class McpToolCallResult(BaseModel):
    """Internal result model for one MCP tool call."""

    tool_name: str
    content: str
    is_error: bool = False
    raw_result: object | None = None


# 真实 stdio MCP server 不是一个已经存在的 Python 对象。需要通过 command + args 启动。这个配置模型把启动信息显式化，避免把命令参数散落在 adapter 代码里
class McpStdioServerConfig(BaseModel):
    """Configuration for connecting to an MCP server over stdio."""

    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
