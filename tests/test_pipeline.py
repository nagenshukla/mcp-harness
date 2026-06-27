"""Core pipeline: registration, dispatch, ordering, sync/async, error propagation."""

from __future__ import annotations

import pytest

from mcp_harness import Harness
from mcp_harness.core.context import NextCall, ToolCallContext
from mcp_harness.core.middleware import BaseMiddleware
from mcp_harness.testing import HarnessTestClient, MockPrincipal


class RecorderMiddleware(BaseMiddleware):
    def __init__(self, label: str, log: list[str]) -> None:
        super().__init__()
        self.label = label
        self.log = log

    async def __call__(self, ctx: ToolCallContext, call_next: NextCall):
        self.log.append(f"{self.label}:before")
        try:
            return await call_next(ctx)
        finally:
            self.log.append(f"{self.label}:after")


async def test_async_tool_dispatch_returns_result():
    h = Harness(name="t")

    @h.tool()
    async def add(a: int, b: int) -> int:
        """Add."""
        return a + b

    assert await h.dispatch("add", {"a": 2, "b": 3}) == 5


async def test_sync_tool_runs_off_loop():
    h = Harness(name="t")

    @h.tool()
    def shout(text: str) -> str:
        return text.upper()

    client = HarnessTestClient(h, principal=MockPrincipal())
    assert await client.call("shout", {"text": "hi"}) == "HI"


async def test_tool_function_is_returned_unchanged():
    h = Harness(name="t")

    @h.tool()
    async def echo(x: int) -> int:
        return x

    # The decorator returns the original callable so it stays directly usable.
    assert await echo(7) == 7


async def test_middleware_ordering_is_onion():
    log: list[str] = []
    h = Harness(
        name="t",
        middleware=[RecorderMiddleware("outer", log), RecorderMiddleware("inner", log)],
    )

    @h.tool()
    async def noop() -> str:
        log.append("tool")
        return "ok"

    await h.dispatch("noop", {})
    assert log == [
        "outer:before",
        "inner:before",
        "tool",
        "inner:after",
        "outer:after",
    ]


async def test_unknown_tool_raises():
    h = Harness(name="t")
    with pytest.raises(KeyError):
        await h.dispatch("missing", {})


async def test_tool_exception_propagates():
    h = Harness(name="t")

    @h.tool()
    async def boom() -> None:
        raise ValueError("kaboom")

    with pytest.raises(ValueError, match="kaboom"):
        await h.dispatch("boom", {})


def test_repr_mentions_tools_and_layers():
    h = Harness(name="svc")

    @h.tool()
    async def t() -> int:
        return 1

    text = repr(h)
    assert "svc" in text and "tools=1" in text
