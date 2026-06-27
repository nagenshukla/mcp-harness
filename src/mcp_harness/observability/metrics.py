"""Tool-call metrics: counters and a latency histogram, with labels for tool/team/status.

Uses ``prometheus_client`` when installed (``pip install 'mcp-harness[metrics]'``); otherwise an
in-memory backend keeps the same counters so tests and lightweight deployments still work. Either
way the metric names match the Prometheus exposition conventions in the design:
``tool_calls_total``, ``tool_call_errors_total``, ``tool_call_duration_seconds``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..core.context import CallStatus, ToolCallContext
from ..core.middleware import RecordingMiddleware

try:  # pragma: no cover - presence depends on the optional extra
    from prometheus_client import CollectorRegistry, Counter, Histogram

    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover
    CollectorRegistry = Counter = Histogram = None  # type: ignore[assignment,misc]
    _PROM_AVAILABLE = False


class _MetricsBackend:
    """Abstracts over prometheus_client and a tiny in-memory fallback."""

    def inc_calls(self, tool: str, team: str, status: str) -> None: ...
    def inc_errors(self, tool: str, team: str) -> None: ...
    def observe_duration(self, tool: str, seconds: float) -> None: ...
    def snapshot(self) -> dict[str, Any]:
        return {}


class _InMemoryBackend(_MetricsBackend):
    def __init__(self) -> None:
        self.calls: dict[tuple[str, str, str], int] = defaultdict(int)
        self.errors: dict[tuple[str, str], int] = defaultdict(int)
        self.durations: dict[str, list[float]] = defaultdict(list)

    def inc_calls(self, tool: str, team: str, status: str) -> None:
        self.calls[(tool, team, status)] += 1

    def inc_errors(self, tool: str, team: str) -> None:
        self.errors[(tool, team)] += 1

    def observe_duration(self, tool: str, seconds: float) -> None:
        self.durations[tool].append(seconds)

    def snapshot(self) -> dict[str, Any]:
        return {
            "tool_calls_total": {",".join(k): v for k, v in self.calls.items()},
            "tool_call_errors_total": {",".join(k): v for k, v in self.errors.items()},
            "tool_call_duration_seconds_count": {k: len(v) for k, v in self.durations.items()},
            "tool_call_duration_seconds_sum": {k: sum(v) for k, v in self.durations.items()},
        }


class _PrometheusBackend(_MetricsBackend):  # pragma: no cover - requires the optional extra
    def __init__(self, registry: Any | None) -> None:
        self.registry = registry or CollectorRegistry()
        self._calls = Counter(
            "tool_calls_total",
            "Total MCP tool calls",
            ["tool", "team", "status"],
            registry=self.registry,
        )
        self._errors = Counter(
            "tool_call_errors_total",
            "Total failed MCP tool calls",
            ["tool", "team"],
            registry=self.registry,
        )
        self._duration = Histogram(
            "tool_call_duration_seconds",
            "MCP tool call duration in seconds",
            ["tool"],
            registry=self.registry,
        )

    def inc_calls(self, tool: str, team: str, status: str) -> None:
        self._calls.labels(tool=tool, team=team, status=status).inc()

    def inc_errors(self, tool: str, team: str) -> None:
        self._errors.labels(tool=tool, team=team).inc()

    def observe_duration(self, tool: str, seconds: float) -> None:
        self._duration.labels(tool=tool).observe(seconds)


class Metrics(RecordingMiddleware):
    """Record per-call metrics. Prometheus-backed when available, in-memory otherwise.

    Args:
        registry: A Prometheus ``CollectorRegistry`` to register into (Prometheus mode only).
    """

    name = "metrics"

    def __init__(self, *, registry: Any | None = None) -> None:
        super().__init__()
        if _PROM_AVAILABLE:
            self._backend: _MetricsBackend = _PrometheusBackend(registry)
        else:
            self._backend = _InMemoryBackend()

    @property
    def prometheus_available(self) -> bool:
        return _PROM_AVAILABLE

    async def on_finish(self, ctx: ToolCallContext) -> None:
        team = ctx.principal.team or "none"
        self._backend.inc_calls(ctx.tool, team, ctx.status.value)
        if ctx.status in (CallStatus.ERROR, CallStatus.DENIED):
            self._backend.inc_errors(ctx.tool, team)
        self._backend.observe_duration(ctx.tool, ctx.duration_ms / 1000.0)

    def snapshot(self) -> dict[str, Any]:
        """Return current metric values (in-memory backend only; empty in Prometheus mode)."""
        return self._backend.snapshot()

    @property
    def registry(self) -> Any | None:
        return getattr(self._backend, "registry", None)


__all__ = ["Metrics"]
