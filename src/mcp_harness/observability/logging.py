"""Structured JSON logging with correlation IDs for every tool call."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from ..core.context import ToolCallContext
from ..core.middleware import RecordingMiddleware


class JSONFormatter(logging.Formatter):
    """Render log records as single-line JSON, merging any ``extra`` fields."""

    _RESERVED = set(logging.makeLogRecord({}).__dict__.keys()) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def get_json_logger(name: str = "mcp_harness", *, stream: Any | None = None) -> logging.Logger:
    """A logger that emits JSON lines. Idempotent: safe to call repeatedly.

    Defaults to ``stderr`` so it never collides with the stdio MCP transport on stdout.
    """
    logger = logging.getLogger(name)
    if not any(getattr(h, "_mcp_harness", False) for h in logger.handlers):
        handler = logging.StreamHandler(stream or sys.stderr)
        handler.setFormatter(JSONFormatter())
        handler._mcp_harness = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


class StructuredLogging(RecordingMiddleware):
    """Log one structured line per tool call, with a stable ``trace_id`` correlating start/finish.

    Args:
        logger: A logger to use; defaults to a JSON logger on stderr.
        level: Log level for successful calls (failures always log at ``ERROR``).
        log_start: Emit a ``tool_call.start`` line in addition to the completion line.
    """

    name = "structured_logging"

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        level: int = logging.INFO,
        log_start: bool = False,
    ) -> None:
        super().__init__()
        self.logger = logger or get_json_logger()
        self.level = level
        self.log_start = log_start

    def _fields(self, ctx: ToolCallContext) -> dict[str, Any]:
        fields = {
            "trace_id": ctx.trace_id,
            "tool": ctx.tool,
            **ctx.principal.to_log_fields(),
        }
        return fields

    async def on_start(self, ctx: ToolCallContext) -> None:
        if self.log_start:
            self.logger.log(self.level, "tool_call.start", extra=self._fields(ctx))

    async def on_finish(self, ctx: ToolCallContext) -> None:
        fields = self._fields(ctx)
        fields.update(
            status=ctx.status.value,
            duration_ms=round(ctx.duration_ms, 3),
            input_tokens=ctx.input_tokens,
            output_tokens=ctx.output_tokens,
        )
        if ctx.error is not None:
            fields["error"] = str(ctx.error)
            fields["error_type"] = type(ctx.error).__name__
            self.logger.error("tool_call.finish", extra=fields)
        else:
            self.logger.log(self.level, "tool_call.finish", extra=fields)


__all__ = ["StructuredLogging", "JSONFormatter", "get_json_logger"]
