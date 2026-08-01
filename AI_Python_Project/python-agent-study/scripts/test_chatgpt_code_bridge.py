from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from chatgpt_code_bridge import (
    BridgeAccessError,
    ReadOnlyCodeBridge,
    create_action_app,
    create_mcp_server,
)


def expect_denied(action) -> None:
    try:
        action()
    except BridgeAccessError:
        return
    raise AssertionError("expected BridgeAccessError")


async def check_stdio_server(root: Path) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).with_name("chatgpt_code_bridge.py")), "--root", str(root)],
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "list_files",
                "read_file",
                "search_code",
            }
            result = await session.call_tool(
                "read_file",
                {"relative_path": "src/app.py", "start_line": 1, "end_line": 1},
            )
            assert not result.isError
            assert result.structuredContent["content"] == "def hello():"


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_directory:
        root = Path(temp_directory, "repo")
        root.mkdir()
        (root / "src").mkdir()
        (root / "src" / "app.py").write_text(
            "def hello():\n    return 'hello bridge'\n", encoding="utf-8"
        )
        (root / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
        (root / ".venv").mkdir()
        (root / ".venv" / "secret.py").write_text("secret = True\n", encoding="utf-8")

        bridge = ReadOnlyCodeBridge(root)
        listed = bridge.list_files(file_glob="*.py")
        assert listed["files"] == ["src/app.py"]

        read = bridge.read_file("src/app.py", 2, 2)
        assert read["content"] == "    return 'hello bridge'"

        searched = bridge.search_code("HELLO BRIDGE", file_glob="*.py")
        assert searched["matches"][0]["line"] == 2

        tools = asyncio.run(create_mcp_server(bridge).list_tools())
        assert {tool.name for tool in tools} == {"list_files", "read_file", "search_code"}
        for tool in tools:
            assert tool.annotations.readOnlyHint is True
            assert tool.annotations.destructiveHint is False
            assert tool.annotations.openWorldHint is False
            assert all(
                field.get("description")
                for field in tool.inputSchema.get("properties", {}).values()
            )

        expect_denied(lambda: bridge.read_file(".env"))
        expect_denied(lambda: bridge.read_file(".venv/secret.py"))
        expect_denied(lambda: bridge.read_file("../outside.py"))

        client = TestClient(create_action_app(bridge, "test-key"))
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/file", params={"relative_path": "src/app.py"}).status_code == 401
        response = client.get(
            "/file",
            params={"relative_path": "src/app.py", "start_line": 1, "end_line": 1},
            headers={"Authorization": "Bearer test-key"},
        )
        assert response.status_code == 200
        assert response.json()["content"] == "def hello():"
        assert client.get(
            "/file",
            params={"relative_path": ".env"},
            headers={"Authorization": "Bearer test-key"},
        ).status_code == 403
        schema_response = client.get(
            "/openapi.json",
            headers={"host": "bridge.example.test", "x-forwarded-proto": "https"},
        )
        schema = schema_response.json()
        assert schema["servers"] == [{"url": "https://bridge.example.test"}]
        assert set(schema["paths"]) == {"/files", "/file", "/search"}
        schemas = schema["components"]["schemas"]
        assert set(schemas["FileListResponse"]["properties"]) == {
            "root",
            "files",
            "truncated",
        }
        assert set(schemas["FileReadResponse"]["properties"]) == {
            "path",
            "start_line",
            "end_line",
            "total_lines",
            "content",
            "truncated",
        }
        assert set(schemas["CodeSearchResponse"]["properties"]) == {
            "matches",
            "truncated",
        }
        asyncio.run(check_stdio_server(root))

    print("chatgpt_code_bridge checks passed")


if __name__ == "__main__":
    main()
