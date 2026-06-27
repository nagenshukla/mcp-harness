"""Quickstart: the smallest governed MCP server worth shipping.

API-key auth + cost attribution + structured logging, in one screenful. This is the shape of the
design's "hello world" without any cloud dependencies.

Run it over stdio (needs the server extra: ``pip install 'mcp-harness[server]'``)::

    python examples/quickstart_server.py

Then point an MCP client at it (e.g. add it to Claude Desktop / Claude Code). Cost records are
written to ``./quickstart-costs.jsonl``; roll them up with::

    mcp-harness daily-rollup quickstart-costs.jsonl
"""

from __future__ import annotations

from mcp_harness import Harness
from mcp_harness.auth import APIKeyAuth
from mcp_harness.governance import CostTracking, PricingModel
from mcp_harness.observability import StructuredLogging

harness = Harness(
    name="quickstart-mcp",
    auth=APIKeyAuth(
        keys={
            # In production load these from a secret store via APIKeyAuth(key_loader=...).
            "sk-demo-finance": {"id": "svc-reports", "team": "finance"},
            "sk-demo-eng": {"id": "svc-eng", "team": "platform"},
        }
    ),
    middleware=[
        StructuredLogging(),
        CostTracking(
            sink="jsonl://quickstart-costs.jsonl",
            pricing=PricingModel.flat(input_per_1k=0.0025, output_per_1k=0.01),
            cost_center_resolver=lambda p: p.team or "unattributed",
        ),
    ],
)


@harness.tool()
async def search_customer(customer_id: str) -> dict:
    """Find a customer record by ID."""
    # Pretend this hits a database; the harness handles auth, cost, and logging around it.
    return {"id": customer_id, "name": "ACME Corp", "tier": "enterprise"}


@harness.tool()
async def list_orders(customer_id: str, limit: int = 10) -> dict:
    """List recent orders for a customer."""
    orders = [{"order_id": f"ord-{i}", "total_usd": 100 + i} for i in range(limit)]
    return {"customer_id": customer_id, "orders": orders}


if __name__ == "__main__":
    harness.run()  # transport="stdio" by default
