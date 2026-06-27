"""Integration with the official MCP SDK (FastMCP). Skipped when ``mcp`` is not installed."""

from __future__ import annotations

import pytest

from mcp_harness import Harness
from mcp_harness.governance import CostTracking

pytestmark = pytest.mark.skipif(
    not Harness.mcp_available(),
    reason="requires the optional 'mcp' SDK (pip install 'mcp-harness[server]')",
)


async def test_wrapper_preserves_tool_schema():
    h = Harness(name="schema-test")

    @h.tool()
    async def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    server = h.fastmcp
    tools = await server.list_tools()
    tool = next(t for t in tools if t.name == "add")

    # The signature-preserving wrapper means FastMCP sees the real parameters, not *args/**kwargs.
    props = tool.inputSchema["properties"]
    assert set(props) == {"a", "b"}
    assert (tool.description or "").startswith("Add two integers")


async def test_call_through_fastmcp_runs_governance(list_sink):
    sink = list_sink
    h = Harness(name="gov-test", middleware=[CostTracking(sink=sink)])

    @h.tool()
    async def greet(name: str) -> str:
        """Greet someone."""
        return f"hello {name}"

    server = h.fastmcp
    try:
        await server.call_tool("greet", {"name": "ada"})
    except Exception:
        # We only care that the governance pipeline ran; FastMCP result conversion varies by
        # version and is outside the harness's responsibility.
        pass

    assert len(sink.records) == 1
    assert sink.records[0]["tool"] == "greet"
    assert sink.records[0]["status"] == "ok"
