"""Research 与文档 Tool Loop 共用的无状态协议辅助函数。"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.tools import BaseTool
from fast_app.agents.mcp.mcp_agent_tools import build_mcp_agent_tools
from fast_app.agents.mcp.mcp_client_boundary import McpStdioClientBoundary
from fast_app.agents.mcp.mcp_tool_contracts import McpStdioServerConfig
from fast_app.core.config import Settings
from fast_app.domain.rag_models import RetrievedDoc
from fast_app.services.exceptions import AppServiceError
from fast_app.services.rag.rag_pipeline_service import build_content_preview


async def build_mcp_task_tools(settings: Settings) -> list[BaseTool]:
    """发现配置允许的 MCP stdio 工具并构造 LangChain 工具。"""

    if not settings.agent_task_mcp_enabled:
        return []
    tools: list[BaseTool] = []
    for config in load_mcp_stdio_server_configs(
        settings.agent_task_mcp_stdio_servers_json
    ):
        client = McpStdioClientBoundary(
            server_config=McpStdioServerConfig(
                command=config["command"],
                args=config.get("args", []),
                env=config.get("env"),
            ),
            allowed_tool_names=set(config.get("allowed_tool_names") or []),
        )
        tools.extend(await build_mcp_agent_tools(client))
    return tools


def normalize_tool_input(value: object) -> dict[str, Any]:
    """把模型返回的工具参数收敛为字典。"""

    return value if isinstance(value, dict) else {}


def coerce_int(value: object, default: int, minimum: int, maximum: int) -> int:
    """把不可信工具整数参数限制在服务端允许范围。"""

    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def find_registered_tool(tool_name: str, tools: list[BaseTool]) -> BaseTool:
    """只从已注册白名单取工具。"""

    for tool in tools:
        if tool.name == tool_name:
            return tool
    raise AppServiceError(f"LLM 选择了未注册工具: {tool_name}")


def parallel_batch_error(
    *,
    tool_names: list[str],
    registered_tool_names: set[str],
    parallel_safe_tool_names: set[str],
    max_parallel_calls: int,
    remaining_calls: int,
) -> str | None:
    """整批启动前验证工具存在、预算和并行安全性。"""

    if len(tool_names) > remaining_calls:
        return f"本轮 ToolCall 数超过剩余总调用预算: {len(tool_names)}>{remaining_calls}"
    unknown = [name for name in tool_names if name not in registered_tool_names]
    if unknown:
        return "本轮包含未注册工具: " + ", ".join(unknown)
    if len(tool_names) <= 1:
        return None
    if len(tool_names) > max_parallel_calls:
        return f"本轮 ToolCall 数超过并行上限: {len(tool_names)}>{max_parallel_calls}"
    unsafe = [name for name in tool_names if name not in parallel_safe_tool_names]
    if unsafe:
        return "同轮包含必须串行执行的工具，请按依赖分轮重试: " + ", ".join(unsafe)
    return None


def load_mcp_stdio_server_configs(raw_value: str) -> list[dict[str, Any]]:
    """解析并验证 MCP stdio server 配置。"""

    try:
        payload = json.loads(raw_value or "[]")
    except json.JSONDecodeError as exc:
        raise AppServiceError("AGENT_TASK_MCP_STDIO_SERVERS_JSON 不是合法 JSON") from exc
    if not isinstance(payload, list):
        raise AppServiceError("AGENT_TASK_MCP_STDIO_SERVERS_JSON 必须是数组")
    configs: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise AppServiceError("MCP stdio server 配置项必须是对象")
        command = item.get("command")
        if not isinstance(command, str) or not command.strip():
            raise AppServiceError("MCP stdio server 缺少 command")
        args = item.get("args", [])
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise AppServiceError("MCP stdio server args 必须是字符串数组")
        env = item.get("env")
        if env is not None and (
            not isinstance(env, dict)
            or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in env.items()
            )
        ):
            raise AppServiceError("MCP stdio server env 必须是字符串字典")
        allowed = item.get("allowed_tool_names", [])
        if not isinstance(allowed, list) or not all(isinstance(name, str) for name in allowed):
            raise AppServiceError("MCP stdio server allowed_tool_names 必须是字符串数组")
        configs.append(
            {
                "name": str(item.get("name") or command),
                "command": command,
                "args": args,
                "env": env,
                "allowed_tool_names": allowed,
            }
        )
    return configs


def extract_first_url(text: str) -> str | None:
    """提取子问题中第一个 HTTP(S) URL。"""

    match = re.search(r"https?://[^\s，。；、）)]+", text)
    return match.group(0) if match else None


def doc_to_evidence(doc: RetrievedDoc) -> dict[str, Any]:
    """把检索结果压缩成可保存到 TaskPlan 的证据摘要。"""

    return {
        "id": doc.id,
        "source": doc.source,
        "title": doc.title,
        "score": doc.score,
        "metadata": doc.metadata,
        "content_preview": build_content_preview(doc.content),
    }


__all__ = [
    "build_mcp_task_tools",
    "coerce_int",
    "doc_to_evidence",
    "extract_first_url",
    "find_registered_tool",
    "normalize_tool_input",
    "parallel_batch_error",
]
