"""The middleware contract and the pipeline that composes them.

Middleware follows the *onion* model used by ASGI/Starlette and the like: each layer receives the
call context and a ``call_next`` continuation, may do work before and after awaiting it, and may
short-circuit by raising or by returning without calling through.

```
async def __call__(self, ctx, call_next):
    # ... before ...
    result = await call_next(ctx)   # invoke inner layers + the tool
    # ... after ...
    return result
```

The pipeline is intentionally tiny and dependency-free so the whole governance stack is unit
testable without the MCP SDK.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from .context import CallStatus, NextCall, ToolCallContext, classify_status


@runtime_checkable
class Middleware(Protocol):
    """Structural type for a middleware layer.

    Implementations are usually classes with an ``async def __call__`` so they can hold config
    (sinks, limits, resolvers). A plain ``async`` function with the same signature also works.
    """

    async def __call__(self, ctx: ToolCallContext, call_next: NextCall) -> Any: ...


class BaseMiddleware:
    """Convenience base class. Subclass and override :meth:`__call__`.

    Provides a stable, debuggable ``name`` (used in tracing/log labels) and a no-op default that
    simply calls through, so a subclass can override only the half it cares about.
    """

    #: Override in subclasses for nicer labels; defaults to the class name.
    name: str = ""

    def __init__(self) -> None:
        if not self.name:
            self.name = type(self).__name__

    async def __call__(self, ctx: ToolCallContext, call_next: NextCall) -> Any:
        return await call_next(ctx)


class RecordingMiddleware(BaseMiddleware):
    """Base for middleware that *observe* a call (logging, cost, audit, metrics).

    Subclasses implement :meth:`on_start` and/or :meth:`on_finish`; the base guarantees
    ``on_finish`` runs exactly once on both the success and failure paths, with ``ctx.status``,
    ``ctx.error``, and timing populated. Recording layers should not swallow exceptions, so this
    base re-raises after recording.
    """

    async def __call__(self, ctx: ToolCallContext, call_next: NextCall) -> Any:
        await self.on_start(ctx)
        try:
            result = await call_next(ctx)
        except BaseException as exc:  # noqa: BLE001 - record everything, then re-raise
            if ctx.status is CallStatus.PENDING:
                ctx.status = classify_status(exc)
            if ctx.error is None:
                ctx.error = exc
            await self.on_finish(ctx)
            raise
        if ctx.status is CallStatus.PENDING:
            ctx.status = CallStatus.OK
        await self.on_finish(ctx)
        return result

    async def on_start(self, ctx: ToolCallContext) -> None:
        """Called before the inner layers run."""

    async def on_finish(self, ctx: ToolCallContext) -> None:
        """Called once after the inner layers complete or raise."""


class Pipeline:
    """An ordered stack of middleware wrapped around a terminal handler.

    The first middleware in the list is the *outermost* layer (runs first on the way in, last on
    the way out). :meth:`run` builds the composed coroutine chain for a given context.
    """

    def __init__(self, middleware: Sequence[Middleware] | None = None) -> None:
        self._middleware: list[Middleware] = list(middleware or [])

    def __len__(self) -> int:
        return len(self._middleware)

    @property
    def middleware(self) -> tuple[Middleware, ...]:
        return tuple(self._middleware)

    def add(self, mw: Middleware) -> None:
        """Append a middleware as the new innermost-but-one layer (before the terminal)."""
        self._middleware.append(mw)

    def prepend(self, mw: Middleware) -> None:
        """Insert a middleware as the new outermost layer (e.g. auth)."""
        self._middleware.insert(0, mw)

    async def run(self, ctx: ToolCallContext, terminal: NextCall) -> Any:
        """Execute the pipeline for ``ctx``, ending at ``terminal`` (which invokes the tool)."""
        chain: NextCall = terminal
        # Compose from the inside out so index 0 ends up outermost.
        for mw in reversed(self._middleware):
            chain = _bind(mw, chain)
        return await chain(ctx)


def _bind(mw: Middleware, call_next: NextCall) -> NextCall:
    async def bound(ctx: ToolCallContext) -> Any:
        return await mw(ctx, call_next)

    bound.__qualname__ = f"bound[{getattr(mw, 'name', type(mw).__name__)}]"
    return bound


__all__ = ["Middleware", "BaseMiddleware", "Pipeline"]
