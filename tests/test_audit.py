"""Async audit logging: shape-only records, flush, and value capture."""

from __future__ import annotations

from mcp_harness import Harness
from mcp_harness.governance import AuditLog
from mcp_harness.testing import HarnessTestClient, MockPrincipal


async def test_audit_records_shape_only_by_default(list_sink):
    sink = list_sink
    audit = AuditLog(sink=sink)
    h = Harness(name="t", middleware=[audit])

    @h.tool()
    async def search(customer_id: str, limit: int = 5) -> dict:
        return {"hits": []}

    client = HarnessTestClient(h, principal=MockPrincipal("svc-a", team="finance"))
    await client.call("search", {"customer_id": "c1", "limit": 3})
    await audit.flush()

    assert len(sink.records) == 1
    rec = sink.records[0]
    assert rec["tool"] == "search"
    assert rec["principal_id"] == "svc-a"
    assert rec["team"] == "finance"
    assert rec["status"] == "ok"
    assert sorted(rec["arg_names"]) == ["customer_id", "limit"]
    assert rec["arg_types"] == {"customer_id": "str", "limit": "int"}
    # Values are NOT captured by default.
    assert "arguments" not in rec


async def test_audit_can_include_argument_values(list_sink):
    sink = list_sink
    audit = AuditLog(sink=sink, include_arguments=True)
    h = Harness(name="t", middleware=[audit])

    @h.tool()
    async def search(customer_id: str) -> dict:
        return {}

    client = HarnessTestClient(h, principal=MockPrincipal())
    await client.call("search", {"customer_id": "c1"})
    await audit.flush()
    assert sink.records[0]["arguments"] == {"customer_id": "c1"}


async def test_audit_records_errors(list_sink):
    sink = list_sink
    audit = AuditLog(sink=sink)
    h = Harness(name="t", middleware=[audit])

    @h.tool()
    async def boom() -> None:
        raise ValueError("nope")

    client = HarnessTestClient(h, principal=MockPrincipal())
    try:
        await client.call("boom")
    except ValueError:
        pass
    await audit.flush()
    rec = sink.records[0]
    assert rec["status"] == "error"
    assert "nope" in rec["error"]
