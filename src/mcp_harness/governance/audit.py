"""Append-only audit logging: who called what, when, with what shape of args, and the outcome.

By default audit records capture the *shape* of arguments and results (names and types), not their
values — full payloads are PII territory. Flip ``include_arguments=True`` to capture values when
your data classification allows it.

The sink runs on a background queue so audit never sits on a tool's latency path. Call
:meth:`AuditLog.flush` (e.g. in tests or graceful shutdown) to drain pending records.
"""

from __future__ import annotations

import asyncio
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..core.context import ToolCallContext
from ..core.middleware import RecordingMiddleware
from .sinks import Sink, resolve_sink


@dataclass
class AuditRecord:
    timestamp: str
    trace_id: str
    tool: str
    principal_id: str
    auth_method: str
    status: str
    duration_ms: float
    team: str | None = None
    arg_names: list[str] = field(default_factory=list)
    arg_types: dict[str, str] = field(default_factory=dict)
    result_type: str | None = None
    error: str | None = None
    arguments: dict[str, Any] | None = None  # populated only when include_arguments=True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data.get("arguments") is None:
            data.pop("arguments", None)
        return data


class AuditLog(RecordingMiddleware):
    """Emit one :class:`AuditRecord` per call to a sink, asynchronously.

    Args:
        sink: A :class:`Sink`, callable, ``"jsonl://path"`` URI, or ``None`` (stdout).
        include_arguments: Capture argument *values* (default: shape only).
        max_queue: Bound on buffered records; excess is dropped with a warning rather than
            blocking the tool.
    """

    name = "audit"

    def __init__(
        self,
        *,
        sink: Any | None = None,
        include_arguments: bool = False,
        max_queue: int = 10_000,
    ) -> None:
        super().__init__()
        self.sink: Sink = resolve_sink(sink)
        self.include_arguments = include_arguments
        self.max_queue = max_queue
        self._queue: asyncio.Queue[AuditRecord] | None = None
        self._worker: asyncio.Task[None] | None = None

    def _ensure_worker(self) -> asyncio.Queue[AuditRecord]:
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self.max_queue)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._drain(), name="mcp-harness-audit")
        return self._queue

    async def _drain(self) -> None:
        assert self._queue is not None
        while True:
            record = await self._queue.get()
            try:
                await self.sink.emit(record)
            except Exception as exc:  # never let a sink failure kill the worker
                warnings.warn(f"audit sink failed: {exc}", RuntimeWarning, stacklevel=2)
            finally:
                self._queue.task_done()

    async def on_finish(self, ctx: ToolCallContext) -> None:
        queue = self._ensure_worker()
        record = self._build_record(ctx)
        try:
            queue.put_nowait(record)
        except asyncio.QueueFull:
            warnings.warn(
                "audit queue full; dropping record (increase max_queue or use a faster sink)",
                RuntimeWarning,
                stacklevel=2,
            )

    def _build_record(self, ctx: ToolCallContext) -> AuditRecord:
        arg_types = {k: type(v).__name__ for k, v in ctx.arguments.items()}
        return AuditRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            trace_id=ctx.trace_id,
            tool=ctx.tool,
            principal_id=ctx.principal.id,
            auth_method=ctx.principal.auth_method,
            team=ctx.principal.team,
            status=ctx.status.value,
            duration_ms=round(ctx.duration_ms, 3),
            arg_names=list(ctx.arguments.keys()),
            arg_types=arg_types,
            result_type=type(ctx.result).__name__ if ctx.result is not None else None,
            error=str(ctx.error) if ctx.error is not None else None,
            arguments=dict(ctx.arguments) if self.include_arguments else None,
        )

    async def flush(self) -> None:
        """Wait until all buffered records have been emitted (no-op if nothing queued yet)."""
        if self._queue is not None:
            await self._queue.join()

    async def aclose(self) -> None:
        """Drain, stop the worker, and close the sink."""
        await self.flush()
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None
        await self.sink.aclose()


__all__ = ["AuditLog", "AuditRecord"]
