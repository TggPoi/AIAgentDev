from mcp.server.fastmcp import FastMCP


mcp = FastMCP("python-agent-study-demo")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@mcp.tool()
def echo(text: str) -> str:
    """Echo input text."""
    return f"echo: {text}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
