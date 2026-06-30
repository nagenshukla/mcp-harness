"""OpenTelemetry tracing: one span per tool call.

Optional. With ``pip install 'mcp-harness[otel]'`` and a configured OTLP exporter, each tool call
becomes a span carrying principal, tool, status, and token attributes — compatible with any OTLP
collector. Without OpenTelemetry installed, this middleware is a no-op (warned once) so the same
code runs everywhere.
"""

from __future__ import annotations

import warnings
from typing import Any

from ..core.context import CallStatus, NextCall, ToolCallContext
from ..core.middleware import BaseMiddleware

try:  # pragma: no cover - presence depends on the optional extra
    from opentelemetry import trace as _otel_trace
    from opentelemetry.trace import Status, StatusCode

    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _otel_trace = None  # type: ignore[assignment]
    Status = StatusCode = None  # type: ignore[assignment,misc]
    _OTEL_AVAILABLE = False


class OTELTracing(BaseMiddleware):
    """Wrap each tool call in an OpenTelemetry span.

    Args:
        service_name: Logical service name recorded on spans.
        tracer_provider: Optional provider; defaults to the globally configured one.
        record_arguments: Attach argument *names* (never values) as a span attribute.
    """

    name = "otel_tracing"

    def __init__(
        self,
        *,
        service_name: str = "mcp-harness",
        tracer_provider: Any | None = None,
        record_arguments: bool = True,
    ) -> None:
        super().__init__()
        self.service_name = service_name
        self.record_arguments = record_arguments
        self._tracer: Any | None
        if _OTEL_AVAILABLE:
            self._tracer = _otel_trace.get_tracer("mcp_harness", tracer_provider=tracer_provider)
        else:
            self._tracer = None
            warnings.warn(
                "OTELTracing is a no-op because OpenTelemetry is not installed. "
                "Install it with:  pip install 'mcp-harness[otel]'.",
                RuntimeWarning,
                stacklevel=2,
            )

    async def __call__(self, ctx: ToolCallContext, call_next: NextCall) -> Any:
        if self._tracer is None:
            return await call_next(ctx)

        with self._tracer.start_as_current_span(f"mcp.tool.{ctx.tool}") as span:
            span.set_attribute("service.name", self.service_name)
            span.set_attribute("mcp.tool", ctx.tool)
            span.set_attribute("mcp.trace_id", ctx.trace_id)
            span.set_attribute("enduser.id", ctx.principal.id)
            if ctx.principal.team:
                span.set_attribute("enduser.team", ctx.principal.team)
            if self.record_arguments and ctx.arguments:
                span.set_attribute("mcp.arg_names", list(ctx.arguments.keys()))
            try:
                result = await call_next(ctx)
            except BaseException as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.set_attribute("mcp.status", ctx.status.value)
                raise
            span.set_attribute("mcp.status", ctx.status.value)
            span.set_attribute("mcp.input_tokens", ctx.input_tokens)
            span.set_attribute("mcp.output_tokens", ctx.output_tokens)
            if ctx.status is not CallStatus.OK:
                span.set_status(Status(StatusCode.ERROR, ctx.status.value))
            return result


__all__ = ["OTELTracing"]
