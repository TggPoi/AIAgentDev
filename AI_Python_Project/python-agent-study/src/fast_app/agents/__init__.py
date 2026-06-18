"""Agent assembly helpers for the FastAPI RAG project."""

from fast_app.agents.langchain_agent_middlewares import (
    build_agent_limit_middlewares,
    build_agent_safety_middlewares,
    build_default_create_agent_middlewares,
    log_agent_model_call,
)
from fast_app.agents.mcp_client_boundary import McpClientBoundary
from fast_app.agents.mcp_tool_contracts import (
    McpToolCallRequest,
    McpToolCallResult,
    McpToolInfo,
)
from fast_app.agents.rag_agent_tools import (
    KNOWLEDGE_RETRIEVAL_TOOL_NAME,
    KnowledgeRetrievalToolInput,
    build_knowledge_retrieval_tool,
    retrieve_knowledge_docs,
)


__all__ = [
    "KNOWLEDGE_RETRIEVAL_TOOL_NAME",
    "KnowledgeRetrievalToolInput",
    "McpClientBoundary",
    "McpToolCallRequest",
    "McpToolCallResult",
    "McpToolInfo",
    "build_agent_limit_middlewares",
    "build_agent_safety_middlewares",
    "build_default_create_agent_middlewares",
    "build_knowledge_retrieval_tool",
    "log_agent_model_call",
    "retrieve_knowledge_docs",
]
