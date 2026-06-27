"""Structured logging and metrics."""

from __future__ import annotations

import logging

from mcp_harness import Harness
from mcp_harness.observability import Metrics, StructuredLogging
from mcp_harness.testing import HarnessTestClient, MockPrincipal


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


async def test_structured_logging_emits_correlated_fields():
    logger = logging.getLogger("test.harness")
    logger.handlers.clear()
    handler = _CaptureHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    h = Harness(name="t", middleware=[StructuredLogging(logger=logger)])

    @h.tool()
    async def ping() -> str:
        return "pong"

    client = HarnessTestClient(h, principal=MockPrincipal("svc-a", team="finance"))
    await client.call("ping")

    finish = [r for r in handler.records if r.getMessage() == "tool_call.finish"]
    assert finish, "expected a finish log line"
    rec = finish[0]
    assert rec.trace_id  # correlation id present
    assert rec.tool == "ping"
    assert rec.principal_id == "svc-a"
    assert rec.team == "finance"
    assert rec.status == "ok"


async def test_metrics_snapshot_counts_calls():
    metrics = Metrics()
    h = Harness(name="t", middleware=[metrics])

    @h.tool()
    async def ping() -> str:
        return "pong"

    client = HarnessTestClient(h, principal=MockPrincipal(team="finance"))
    await client.call("ping")
    await client.call("ping")

    if metrics.prometheus_available:
        # Prometheus backend: snapshot is empty, but the registry is populated.
        assert metrics.registry is not None
    else:
        snap = metrics.snapshot()
        total = sum(snap["tool_calls_total"].values())
        assert total == 2
        assert snap["tool_call_duration_seconds_count"]["ping"] == 2
