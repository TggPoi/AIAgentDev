from pydantic import BaseModel, Field


class McpToolInfo(BaseModel):
    """MCP tool metadata normalized for the FastAPI RAG project."""

    name: str
    description: str = ""
    input_schema: dict[str, object] = Field(default_factory=dict)


class McpToolCallRequest(BaseModel):
    """Internal request model for one MCP tool call."""

    tool_name: str
    arguments: dict[str, object] = Field(default_factory=dict)


class McpToolCallResult(BaseModel):
    """Internal result model for one MCP tool call."""

    tool_name: str
    content: str
    is_error: bool = False
    raw_result: object | None = None
