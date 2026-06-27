"""Pluggable output sinks shared by cost tracking and audit logging.

A sink consumes serializable records (anything with a ``to_dict()`` method). Built-in sinks cover
local development and self-hosting; cloud sinks (Azure Monitor, Event Hubs, Kinesis, Kafka) are
left as extension points — implement :class:`Sink` and pass it in.
"""

from __future__ import annotations

import asyncio
import json
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TextIO, runtime_checkable


@runtime_checkable
class Record(Protocol):
    """Anything emittable: a structured record that knows how to serialize itself."""

    def to_dict(self) -> dict[str, Any]: ...


class Sink(ABC):
    """Destination for records. Implement :meth:`emit` (and optionally :meth:`aclose`)."""

    @abstractmethod
    async def emit(self, record: Record) -> None:
        """Persist or forward one record. Should not raise on transient failures in production."""

    async def aclose(self) -> None:  # noqa: B027 - intentional optional no-op hook
        """Flush and release resources. Default is a no-op; override if needed."""
        return None


class NullSink(Sink):
    """Discards everything. Useful as a default or in tests."""

    async def emit(self, record: Record) -> None:
        return None


class StdoutSink(Sink):
    """Writes one JSON object per line to a text stream (stdout by default).

    Note: with the stdio MCP transport, stdout carries the protocol — route records to
    ``sys.stderr`` (``StdoutSink(stream=sys.stderr)``) or a file sink to avoid corrupting it.
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stdout

    async def emit(self, record: Record) -> None:
        line = json.dumps(record.to_dict(), default=str, separators=(",", ":"))
        self._stream.write(line + "\n")
        self._stream.flush()


class JSONLSink(Sink):
    """Appends newline-delimited JSON to a file. Safe for concurrent emitters in one process."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def emit(self, record: Record) -> None:
        line = json.dumps(record.to_dict(), default=str, separators=(",", ":"))
        async with self._lock:
            await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


class CallableSink(Sink):
    """Adapts a plain function ``record_dict -> None`` into a sink (sync or async)."""

    def __init__(self, fn: Callable[[dict[str, Any]], Any]) -> None:
        self._fn = fn

    async def emit(self, record: Record) -> None:
        result = self._fn(record.to_dict())
        if asyncio.iscoroutine(result):
            await result


def resolve_sink(sink: Sink | Callable[[dict[str, Any]], Any] | str | None) -> Sink:
    """Normalise a user-supplied sink spec into a :class:`Sink`.

    Accepts a ``Sink``, a callable, ``None`` (-> stdout), or a ``"jsonl://path"`` /
    ``"stdout://"`` / ``"stderr://"`` URI string.
    """
    if sink is None:
        return StdoutSink()
    if isinstance(sink, Sink):
        return sink
    if callable(sink):
        return CallableSink(sink)
    if isinstance(sink, str):
        if sink.startswith("jsonl://"):
            return JSONLSink(sink[len("jsonl://") :])
        if sink in ("stdout://", "stdout"):
            return StdoutSink(sys.stdout)
        if sink in ("stderr://", "stderr"):
            return StdoutSink(sys.stderr)
        # Treat any other bare string as a JSONL file path.
        return JSONLSink(sink)
    raise TypeError(f"Cannot interpret {sink!r} as a sink")


__all__ = [
    "Record",
    "Sink",
    "NullSink",
    "StdoutSink",
    "JSONLSink",
    "CallableSink",
    "resolve_sink",
]
