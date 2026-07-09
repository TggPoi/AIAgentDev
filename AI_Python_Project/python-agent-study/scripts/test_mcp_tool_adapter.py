import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.agents import (
    McpStdioClientBoundary,
    McpStdioServerConfig,
    build_mcp_agent_tools,
)


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    server_path = repo_root / "scripts" / "mcp_demo_server.py"

    client = McpStdioClientBoundary(
        server_config=McpStdioServerConfig(
            command=sys.executable,
            args=[str(server_path)],
        ),
        allowed_tool_names={"add", "echo"},
    )

    tool_infos = await client.list_tools()
    print("mcp tools:", [tool.name for tool in tool_infos])

    tools = await build_mcp_agent_tools(client)
    print("agent tools:", [tool.name for tool in tools])

    add_tool = next(tool for tool in tools if tool.name == "mcp__add")
    add_result = await add_tool.ainvoke({"a": 2, "b": 3})
    print("mcp__add result:", add_result)

    echo_tool = next(tool for tool in tools if tool.name == "mcp__echo")
    echo_result = await echo_tool.ainvoke({"text": "hello mcp"})
    print("mcp__echo result:", echo_result)


if __name__ == "__main__":
    asyncio.run(main())
