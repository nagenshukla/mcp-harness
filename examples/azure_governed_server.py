"""The design doc's reference server: governed for an Azure-centric enterprise.

This mirrors the "hello world" from the design sketch. It is **illustrative** — it needs real
Entra ID configuration and the relevant extras to run end to end::

    pip install 'mcp-harness[server,otel,auth]'

`AzureADAuth` is experimental (validates real Entra tokens via JWKS). Swap in `APIKeyAuth` or
`AnonymousAuth` to try the rest of the stack locally without an identity provider — see
`local_governed_server.py` for a fully runnable, cloud-free version.
"""

from __future__ import annotations

import os

from mcp_harness import Harness
from mcp_harness.auth import AzureADAuth
from mcp_harness.governance import AuditLog, CostTracking, PricingModel, Quotas
from mcp_harness.observability import OTELTracing, StructuredLogging
from mcp_harness.policy import AllowList

harness = Harness(
    name="customer-data-mcp",
    auth=AzureADAuth(
        tenant_id=os.environ.get("AZURE_TENANT_ID", "<tenant-guid>"),
        audience=os.environ.get("MCP_AUDIENCE", "api://customer-data-mcp"),
        required_scopes=["mcp.tools"],
        team_claim="department",  # map your directory's team claim for cost attribution
    ),
    middleware=[
        OTELTracing(service_name="customer-data-mcp"),
        StructuredLogging(),
        AllowList.from_yaml(
            os.path.join(os.path.dirname(__file__), "policies", "tool-access.yaml")
        ),
        Quotas(per_principal_per_minute=60, concurrency={"issue_refund": 1}),
        CostTracking(
            # Resolve the principal's team claim to a Finance cost center.
            cost_center_resolver=lambda p: p.claims.get("cost_center") or p.team or "unattributed",
            # In production point this at Azure Monitor / Event Hubs via a custom Sink.
            sink="jsonl://azure-costs.jsonl",
            pricing=PricingModel.flat(input_per_1k=0.0025, output_per_1k=0.01),
        ),
        AuditLog(sink="jsonl://azure-audit.jsonl"),
    ],
)


@harness.tool()
async def search_customer(customer_id: str) -> dict:
    """Find a customer record by ID."""
    # return await db.fetch(customer_id)
    return {"id": customer_id, "name": "ACME Corp"}


if __name__ == "__main__":
    # Serve over Streamable HTTP so Entra bearer tokens arrive in the Authorization header.
    harness.run(transport="streamable-http")
