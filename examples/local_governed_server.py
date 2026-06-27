"""A fully governed MCP server that runs with zero cloud dependencies.

Stacks the whole core: API-key auth, OTEL tracing (no-op unless the ``otel`` extra is installed),
structured logging, metrics, an allow-list policy loaded from YAML, per-principal quotas, cost
attribution to JSONL, and async audit logging to JSONL.

Two ways to run it:

* ``python examples/local_governed_server.py`` — serve over stdio for a real MCP client
  (requires ``pip install 'mcp-harness[server]'``).
* ``python examples/local_governed_server.py --demo`` — drive it in-process with the bundled
  test client to *show the governance working* (allow-list denial, quota denial, cost records).
  This needs no MCP SDK.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp_harness import Harness, PolicyDenied, QuotaExceeded
from mcp_harness.auth import APIKeyAuth
from mcp_harness.governance import AuditLog, CostTracking, PricingModel, Quotas
from mcp_harness.observability import Metrics, OTELTracing, StructuredLogging
from mcp_harness.policy import AllowList
from mcp_harness.testing import HarnessTestClient, MockPrincipal

POLICY = Path(__file__).parent / "policies" / "tool-access.yaml"

harness = Harness(
    name="customer-data-mcp",
    auth=APIKeyAuth(
        keys={
            "sk-finance": {"id": "svc-reports", "team": "finance"},
            "sk-platform": {"id": "svc-platform", "team": "platform"},
        }
    ),
    middleware=[
        # Outermost first. Tracing wraps everything; audit records every outcome.
        OTELTracing(service_name="customer-data-mcp"),
        StructuredLogging(),
        Metrics(),
        AllowList.from_yaml(POLICY),
        Quotas(per_principal_per_minute=60, concurrency={"issue_refund": 1}),
        CostTracking(
            sink="jsonl://local-costs.jsonl",
            pricing=PricingModel.flat(input_per_1k=0.0025, output_per_1k=0.01),
            cost_center_resolver=lambda p: p.team or "unattributed",
        ),
        AuditLog(sink="jsonl://local-audit.jsonl"),
    ],
)


@harness.tool()
async def search_customer(customer_id: str) -> dict:
    """Find a customer record by ID."""
    return {"id": customer_id, "name": "ACME Corp", "tier": "enterprise"}


@harness.tool()
async def list_orders(customer_id: str, limit: int = 5) -> dict:
    """List recent orders for a customer."""
    return {"customer_id": customer_id, "orders": [f"ord-{i}" for i in range(limit)]}


@harness.tool()
async def issue_refund(customer_id: str, amount_usd: float, region: str) -> dict:
    """Issue a refund (sensitive: allow-listed + concurrency-limited)."""
    return {"customer_id": customer_id, "refunded_usd": amount_usd, "region": region}


async def _demo() -> None:
    """Exercise the governance layers in-process and narrate what happens."""
    finance = HarnessTestClient(harness, principal=MockPrincipal("svc-reports", team="finance"))
    platform = HarnessTestClient(harness, principal=MockPrincipal("svc-platform", team="platform"))

    print("1. finance -> search_customer (allowed):")
    print("   ", await finance.call("search_customer", {"customer_id": "c-42"}))

    print("2. platform -> search_customer (denied by allow-list):")
    try:
        await platform.call("search_customer", {"customer_id": "c-42"})
    except PolicyDenied as exc:
        print("   ", exc)

    refund_args = {"customer_id": "c-42", "amount_usd": 9.99}

    print("3. svc-reports -> issue_refund region=eu (denied by arg constraint):")
    try:
        await finance.call("issue_refund", {**refund_args, "region": "eu"})
    except PolicyDenied as exc:
        print("   ", exc)

    print("4. svc-reports -> issue_refund region=us (allowed):")
    print("   ", await finance.call("issue_refund", {**refund_args, "region": "us"}))

    print("5. burst 70 calls to trip the 60/min quota:")
    denied = 0
    for _ in range(70):
        try:
            await finance.call("list_orders", {"customer_id": "c-42"})
        except QuotaExceeded:
            denied += 1
    print(f"    {denied} calls rejected by the rate limit")

    # Flush async audit before exit so the JSONL is complete.
    for mw in harness._pipeline.middleware:  # type: ignore[attr-defined]
        if isinstance(mw, AuditLog):
            await mw.aclose()

    print("\nWrote local-costs.jsonl and local-audit.jsonl.")
    print("Try:  mcp-harness daily-rollup local-costs.jsonl")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        asyncio.run(_demo())
    else:
        harness.run()
