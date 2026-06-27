"""Wrapping an existing FastMCP server with Harness.from_fastmcp. Skipped without ``mcp``."""

from __future__ import annotations

import pytest

from mcp_harness import Harness
from mcp_harness.governance import CostTracking

pytestmark = pytest.mark.skipif(
    not Harness.mcp_available(),
    reason="requires the optional 'mcp' SDK (pip install 'mcp-harness[server]')",
)


async def test_from_fastmcp_adopts_existing_tools(list_sink):
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("existing")

    @server.tool()
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    @server.tool()
    async def greet(name: str) -> str:
        """Greet someone."""
        return f"hi {name}"

    harness = Harness.from_fastmcp(server, middleware=[CostTracking(sink=list_sink)])

    # Both pre-existing tools are now known to the harness.
    assert set(harness.tools) == {"add", "greet"}

    # The original input schema is preserved on the server (not flattened to *args/**kwargs).
    tools = await server.list_tools()
    add_tool = next(t for t in tools if t.name == "add")
    assert set(add_tool.inputSchema["properties"]) == {"a", "b"}

    # Calling through FastMCP's own manager runs governance and returns the right result.
    result = await server._tool_manager.call_tool("add", {"a": 2, "b": 3})
    assert result == 5
    assert any(r["tool"] == "add" and r["status"] == "ok" for r in list_sink.records)

    # The sync tool was marked async after wrapping (our wrapper is always a coroutine).
    assert server._tool_manager._tools["add"].is_async is True

    # The SDK-free dispatch path works on adopted tools too.
    assert await harness.dispatch("greet", {"name": "ada"}) == "hi ada"


async def test_from_fastmcp_inherits_server_name():
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("payments-mcp")
    harness = Harness.from_fastmcp(server)
    assert harness.name == "payments-mcp"
    assert harness.fastmcp is server
