"""Agent assembly helpers for the FastAPI RAG project."""

from fast_app.agents.agent_error_policy import (
    AgentErrorAction,
    AgentErrorDecision,
    AgentErrorKind,
    build_agent_error_answer,
    classify_agent_error,
)
from fast_app.agents.agent_loop_control import (
    AgentLoopDecision,
    AgentLoopLimits,
    AgentLoopSnapshot,
    AgentLoopTerminationReason,
    build_agent_loop_limits_from_settings,
    should_continue_agent_loop,
)
from fast_app.agents.calculator_tools import (
    CALCULATOR_TOOL_NAME,
    CalculatorBasicOpsInput,
    CalculatorExpressionInput,
    build_calculator_tool,
    calculate_basic_ops,
    evaluate_safe_expression,
)
from fast_app.agents.langchain_agent_middlewares import (
    build_agent_limit_middlewares,
    build_agent_safety_middlewares,
    build_default_create_agent_middlewares,
    log_agent_model_call,
)
from fast_app.agents.document_management_tools import (
    KNOWLEDGE_DOCUMENT_CREATE_TOOL_NAME,
    KNOWLEDGE_DOCUMENT_DELETE_TOOL_NAME,
    KNOWLEDGE_DOCUMENT_UPDATE_TOOL_NAME,
    KnowledgeDocumentCreateToolInput,
    KnowledgeDocumentDeleteToolInput,
    KnowledgeDocumentUpdateToolInput,
    build_knowledge_document_create_tool,
    build_knowledge_document_delete_tool,
    build_knowledge_document_management_tools,
    build_knowledge_document_update_tool,
)
from fast_app.agents.mcp_agent_tools import (
    MCP_TOOL_NAME_PREFIX,
    build_mcp_agent_tool,
    build_mcp_agent_tool_name,
    build_mcp_agent_tools,
    build_mcp_tool_args_schema,
)
from fast_app.agents.mcp_client_boundary import McpClientBoundary, McpStdioClientBoundary
from fast_app.agents.mcp_tool_contracts import (
    McpStdioServerConfig,
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
from fast_app.agents.web_search_tools import (
    WEB_SEARCH_TOOL_NAME,
    WebSearchResult,
    WebSearchToolInput,
    build_web_search_tool,
    normalize_web_search_results,
    search_web_with_bocha,
    summarize_web_search_results,
)


__all__ = [
    "AgentErrorAction",
    "AgentErrorDecision",
    "AgentErrorKind",
    "AgentLoopDecision",
    "AgentLoopLimits",
    "AgentLoopSnapshot",
    "AgentLoopTerminationReason",
    "CALCULATOR_TOOL_NAME",
    "CalculatorBasicOpsInput",
    "CalculatorExpressionInput",
    "KNOWLEDGE_DOCUMENT_CREATE_TOOL_NAME",
    "KNOWLEDGE_DOCUMENT_DELETE_TOOL_NAME",
    "KNOWLEDGE_DOCUMENT_UPDATE_TOOL_NAME",
    "KNOWLEDGE_RETRIEVAL_TOOL_NAME",
    "KnowledgeDocumentCreateToolInput",
    "KnowledgeDocumentDeleteToolInput",
    "KnowledgeDocumentUpdateToolInput",
    "KnowledgeRetrievalToolInput",
    "MCP_TOOL_NAME_PREFIX",
    "McpClientBoundary",
    "McpStdioClientBoundary",
    "McpStdioServerConfig",
    "McpToolCallRequest",
    "McpToolCallResult",
    "McpToolInfo",
    "WEB_SEARCH_TOOL_NAME",
    "WebSearchResult",
    "WebSearchToolInput",
    "build_agent_limit_middlewares",
    "build_agent_error_answer",
    "build_agent_safety_middlewares",
    "build_default_create_agent_middlewares",
    "build_agent_loop_limits_from_settings",
    "build_calculator_tool",
    "build_knowledge_document_create_tool",
    "build_knowledge_document_delete_tool",
    "build_knowledge_document_management_tools",
    "build_knowledge_document_update_tool",
    "build_knowledge_retrieval_tool",
    "build_mcp_agent_tool",
    "build_mcp_agent_tool_name",
    "build_mcp_agent_tools",
    "build_mcp_tool_args_schema",
    "build_web_search_tool",
    "calculate_basic_ops",
    "classify_agent_error",
    "evaluate_safe_expression",
    "log_agent_model_call",
    "normalize_web_search_results",
    "retrieve_knowledge_docs",
    "search_web_with_bocha",
    "should_continue_agent_loop",
    "summarize_web_search_results",
]
