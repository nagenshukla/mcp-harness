"""The :class:`Harness` — the user-facing entry point.

A ``Harness`` owns:

* a **middleware pipeline** (auth + whatever governance layers the user declared), and
* a **registry of tools** the user defined with ``@harness.tool()``.

It is deliberately split from the MCP SDK. Defining tools, building the pipeline, and dispatching
calls via :meth:`dispatch` work with **zero** dependency on ``mcp`` — which is what makes the whole
governance stack unit-testable in isolation. Only :meth:`run` (and the lazy FastMCP registration
behind it) needs the optional ``mcp`` package installed.
"""

from __future__ import annotations

import asyncio
import functools
import importlib.util
import inspect
from collections.abc import Callable, Sequence
from typing import Any

from ..errors import HarnessError, MCPNotInstalled
from .context import CallStatus, NextCall, ToolCallContext, ToolSpec
from .middleware import Middleware, Pipeline
from .principal import Principal


class Harness:
    """Wraps the official MCP SDK with a composable governance pipeline.

    Args:
        name: Server name, surfaced to MCP clients and used as a default service name.
        auth: An auth backend (any :class:`mcp_harness.auth.base.BaseAuth`). Defaults to
            :class:`~mcp_harness.auth.anonymous.AnonymousAuth`.
        middleware: Ordered governance layers. Index 0 is the outermost layer (after auth).
        fastmcp_settings: Extra keyword arguments forwarded to ``FastMCP(...)`` when the server
            is created (e.g. ``stateless_http=True``).
    """

    def __init__(
        self,
        name: str = "mcp-harness",
        *,
        auth: Any | None = None,
        middleware: Sequence[Middleware] | None = None,
        fastmcp_settings: dict[str, Any] | None = None,
    ) -> None:
        # Local imports keep the auth package off the core import path (avoids a cycle).
        from ..auth.anonymous import AnonymousAuth
        from ..auth.base import AuthMiddleware, BaseAuth

        self.name = name
        self.auth: BaseAuth = auth if auth is not None else AnonymousAuth()
        self._pipeline = Pipeline(middleware)
        # Auth always runs first so downstream middleware see a resolved principal.
        self._pipeline.prepend(AuthMiddleware(self.auth))

        self._tools: dict[str, ToolSpec] = {}
        self._fastmcp: Any | None = None
        self._fastmcp_settings = dict(fastmcp_settings or {})
        self._fastmcp_registered: set[str] = set()

    @classmethod
    def from_fastmcp(
        cls,
        server: Any,
        *,
        name: str | None = None,
        auth: Any | None = None,
        middleware: Sequence[Middleware] | None = None,
    ) -> Harness:
        """Wrap an **existing** ``FastMCP`` server, routing its tools through the pipeline.

        This is the one-line "add governance to the MCP server I already have" path: keep your
        ``@server.tool()`` definitions exactly as they are, then::

            from mcp.server.fastmcp import FastMCP
            from mcp_harness import Harness
            from mcp_harness.governance import CostTracking, Quotas

            server = FastMCP("my-mcp")

            @server.tool()
            async def search(q: str) -> dict: ...

            harness = Harness.from_fastmcp(server, middleware=[CostTracking(), Quotas(...)])
            harness.run()

        Every already-registered tool keeps its original input schema, title, and annotations —
        only its execution is re-routed through auth, policy, quotas, cost, and audit.
        """
        resolved_name = name or getattr(server, "name", None) or "mcp-harness"
        harness = cls(name=str(resolved_name), auth=auth, middleware=middleware)
        harness._fastmcp = server
        harness._adopt_fastmcp_tools()
        return harness

    def _adopt_fastmcp_tools(self) -> None:
        server = self._fastmcp
        manager = getattr(server, "_tool_manager", None)
        existing = getattr(manager, "_tools", None)
        if manager is None or not isinstance(existing, dict):
            raise HarnessError(
                "Could not read tools from this FastMCP server; the installed 'mcp' version "
                "may be incompatible with Harness.from_fastmcp(). Register tools via "
                "@harness.tool() instead, or open an issue with your mcp version."
            )
        for tool_name, tool in list(existing.items()):
            original_fn = getattr(tool, "fn", None)
            if original_fn is None:
                continue
            spec = ToolSpec(
                name=tool_name,
                fn=original_fn,
                description=getattr(tool, "description", "") or "",
                is_async=bool(getattr(tool, "is_async", False)),
            )
            self._tools[tool_name] = spec
            # Swap the tool's callable for our pipeline wrapper. The wrapper is always async, so
            # tell FastMCP to await it; arg validation still uses the original schema.
            tool.fn = self._make_fastmcp_wrapper(spec)
            tool.is_async = True
            self._fastmcp_registered.add(tool_name)

    # -- registration -----------------------------------------------------------------------

    def tool(
        self,
        name: str | None = None,
        *,
        description: str | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator registering a tool, mirroring ``FastMCP.tool()``.

        The original function is returned unchanged, so it remains directly callable (and unit
        testable) outside the harness. The governance pipeline is applied when the tool is reached
        through :meth:`dispatch` or through a live MCP client.
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or fn.__name__
            spec = ToolSpec(
                name=tool_name,
                fn=fn,
                description=description or (inspect.getdoc(fn) or ""),
                is_async=inspect.iscoroutinefunction(fn),
            )
            self._tools[tool_name] = spec
            # If a FastMCP server already exists, register immediately; otherwise it will be
            # registered lazily when the server is first created.
            if self._fastmcp is not None:
                self._register_with_fastmcp(spec)
            return fn

        return decorator

    @property
    def tools(self) -> dict[str, ToolSpec]:
        return dict(self._tools)

    def add_middleware(self, mw: Middleware) -> None:
        """Append a middleware after the existing layers (inner-most, before the tool)."""
        self._pipeline.add(mw)

    # -- dispatch ---------------------------------------------------------------------------

    async def dispatch(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
        principal: Principal | None = None,
    ) -> Any:
        """Run a tool through the full middleware pipeline and return its result.

        This is the SDK-independent entry point used by the FastMCP wrapper, the testing client,
        and direct callers. Pass ``principal=`` to bypass authentication (useful in tests).
        """
        spec = self._tools.get(tool_name)
        if spec is None:
            raise KeyError(f"No tool registered named '{tool_name}'")

        ctx = ToolCallContext(
            tool=tool_name,
            arguments=dict(arguments or {}),
            principal=principal or Principal.anonymous_principal(),
            headers=dict(headers or {}),
        )
        if principal is not None:
            ctx.metadata["principal_preauthenticated"] = True

        async def terminal(ctx: ToolCallContext) -> Any:
            return await self._invoke_tool(spec, ctx)

        return await self._pipeline.run(ctx, terminal)

    async def _invoke_tool(self, spec: ToolSpec, ctx: ToolCallContext) -> Any:
        if spec.is_async:
            result = await spec.fn(**ctx.arguments)
        else:
            # Run blocking user code off the event loop so one slow tool can't stall the server.
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, functools.partial(spec.fn, **ctx.arguments))
        ctx.result = result
        ctx.status = CallStatus.OK
        return result

    # -- MCP SDK integration ----------------------------------------------------------------

    @staticmethod
    def mcp_available() -> bool:
        """True if the optional ``mcp`` SDK is importable."""
        try:
            return importlib.util.find_spec("mcp.server.fastmcp") is not None
        except ModuleNotFoundError:
            # Raised when the top-level ``mcp`` package itself is absent.
            return False

    @property
    def fastmcp(self) -> Any:
        """The underlying ``FastMCP`` server, created lazily. Requires the ``mcp`` SDK."""
        if self._fastmcp is None:
            FastMCP = self._import_fastmcp()
            self._fastmcp = FastMCP(self.name, **self._fastmcp_settings)
            for spec in self._tools.values():
                self._register_with_fastmcp(spec)
        return self._fastmcp

    @staticmethod
    def _import_fastmcp() -> Any:
        try:
            from mcp.server.fastmcp import FastMCP
        except ImportError as exc:  # pragma: no cover - exercised only without mcp installed
            raise MCPNotInstalled("Serving tools over MCP") from exc
        return FastMCP

    def _register_with_fastmcp(self, spec: ToolSpec) -> None:
        server = self._fastmcp
        if server is None or spec.name in self._fastmcp_registered:
            return
        wrapper = self._make_fastmcp_wrapper(spec)
        # FastMCP introspects ``wrapper`` for the schema; ``functools.wraps`` + ``__wrapped__``
        # make ``inspect.signature`` resolve to the user's real parameters.
        server.add_tool(wrapper, name=spec.name, description=spec.description or None)
        self._fastmcp_registered.add(spec.name)

    def _make_fastmcp_wrapper(self, spec: ToolSpec) -> Callable[..., Any]:
        harness = self

        @functools.wraps(spec.fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            arguments = dict(kwargs)
            if args:
                # FastMCP calls with keywords, but bind positionals defensively just in case.
                bound = inspect.signature(spec.fn).bind_partial(*args)
                arguments.update(bound.arguments)
            headers = harness._current_headers()
            return await harness.dispatch(spec.name, arguments, headers=headers)

        # Async wrapper regardless of whether the user's tool was sync (dispatch handles both).
        return wrapper

    @staticmethod
    def _current_headers() -> dict[str, str]:
        """Best-effort fetch of inbound HTTP headers from the active FastMCP request.

        Returns an empty mapping for the stdio transport (no headers) or if the running ``mcp``
        version does not expose the helper. Never raises.
        """
        try:
            from mcp.server.fastmcp.server import get_http_headers  # type: ignore
        except Exception:
            return {}
        try:
            return dict(get_http_headers() or {})
        except Exception:
            return {}

    def run(self, transport: str = "stdio", **kwargs: Any) -> None:
        """Serve the harnessed tools over MCP. Requires the ``mcp`` SDK (``mcp-harness[server]``).

        Args:
            transport: ``"stdio"`` (default), ``"streamable-http"``, or ``"sse"``.
            **kwargs: Forwarded to ``FastMCP.run``.
        """
        # Touching the property creates the server and registers every tool defined so far.
        server = self.fastmcp
        server.run(transport=transport, **kwargs)

    def __repr__(self) -> str:
        return (
            f"Harness(name={self.name!r}, tools={len(self._tools)}, "
            f"layers={len(self._pipeline)}, auth={type(self.auth).__name__})"
        )


__all__ = ["Harness", "HarnessError", "NextCall"]
