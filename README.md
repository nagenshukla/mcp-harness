# mcp-harness

**Enterprise governance middleware for MCP servers.** Cost attribution, auth, observability,
quotas, audit, and policy — composable around the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).

[![CI](https://github.com/nagenshukla/mcp-harness/actions/workflows/test.yml/badge.svg)](https://github.com/nagenshukla/mcp-harness/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/mcp-harness.svg)](https://pypi.org/project/mcp-harness/)
[![Python](https://img.shields.io/pypi/pyversions/mcp-harness.svg)](https://pypi.org/project/mcp-harness/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

---

## Why this exists

Most public MCP servers are toy examples. The gap between *"works on my laptop"* and *"I can ship
this to 500 engineers under SOC 2, GDPR, and a Finance team that wants per-business-unit cost
allocation"* is enormous — and almost none of that gap is in the protocol. It's in the boring
middleware around it.

`mcp-harness` **is** that middleware. It doesn't fork the protocol, doesn't reinvent the SDK, and
doesn't try to be an agent framework. It's a set of composable decorators and middleware that wrap
the official SDK so the resulting server can be safely run inside a company.

The headline use case: **your CFO asks who's spending the AI budget, and you can answer by end of
week one.**

## Install

```bash
pip install mcp-harness            # core pipeline (no MCP SDK required)
pip install 'mcp-harness[server]'  # + the official MCP SDK, to actually serve tools
pip install 'mcp-harness[all]'     # + OpenTelemetry, Prometheus, tiktoken, JWT
```

The core middleware pipeline has **no hard dependency** on `mcp`, so you can unit-test all your
governance behaviour without a transport. Install the `server` extra to run a live server.

## Hello, governed world

The same MCP server you'd write anyway, with the governance layer declared once at the top:

```python
from mcp_harness import Harness
from mcp_harness.auth import APIKeyAuth
from mcp_harness.governance import CostTracking, Quotas, AuditLog
from mcp_harness.observability import OTELTracing, StructuredLogging
from mcp_harness.policy import AllowList

harness = Harness(
    name="customer-data-mcp",
    auth=APIKeyAuth(keys={"sk-finance": {"id": "svc-reports", "team": "finance"}}),
    middleware=[
        OTELTracing(service_name="customer-data-mcp"),
        StructuredLogging(),
        AllowList.from_yaml("policies/tool-access.yaml"),
        Quotas(per_principal_per_minute=60),
        CostTracking(
            cost_center_resolver=lambda p: p.team,
            sink="jsonl://costs.jsonl",
        ),
        AuditLog(sink="jsonl://audit.jsonl"),
    ],
)

@harness.tool()
async def search_customer(customer_id: str) -> dict:
    """Find a customer record by ID."""
    return {"id": customer_id, "name": "ACME Corp"}

if __name__ == "__main__":
    harness.run()  # stdio by default; transport="streamable-http" for HTTP
```

## Already have a server? Wrap it in one line

Keep every `@server.tool()` exactly as it is — `from_fastmcp` adopts an existing `FastMCP`
instance and routes its tools through the pipeline, preserving their schemas:

```python
from mcp.server.fastmcp import FastMCP
from mcp_harness import Harness
from mcp_harness.governance import CostTracking, Quotas

server = FastMCP("my-mcp")

@server.tool()
async def search(q: str) -> dict:
    return {"hits": []}

harness = Harness.from_fastmcp(server, middleware=[CostTracking(), Quotas(per_principal_per_minute=60)])
harness.run()
```

Or scaffold it from the CLI, without touching your file:

```bash
mcp-harness wrap server.py     # writes governed_server.py next to it
mcp-harness init my-mcp        # scaffold a fresh governed server
```

Then attribute spend:

```console
$ mcp-harness daily-rollup costs.jsonl
cost_center     calls      in_tok     out_tok      cost_usd
----------------------------------------------------------
finance            42        5\,210       9\,830        0.1284
platform           18        1\,940       3\,110        0.0451
----------------------------------------------------------
TOTAL              60        7\,150      12\,940        0.1735
```

## How it works

A tiny **onion middleware pipeline**, decoupled from the SDK. `@harness.tool()` registers your
function; calls flow through each layer and into your tool. The same path runs whether the call
arrives from a live MCP client or from the in-process test client.

```
client ─▶ FastMCP ─▶ wrapper ─┐
                              ├─▶ auth ─▶ policy ─▶ quotas ─▶ tracing ─▶ cost ─▶ audit ─▶ your tool
test/direct ─▶ dispatch ──────┘
```

Each layer is independently useful, independently testable, and opt-in. Adopt just `CostTracking`,
or stack the whole thing.

## Modules

| Module | What you get |
| --- | --- |
| `mcp_harness.auth` | `APIKeyAuth` (with rotation), `AnonymousAuth`, `ChainedAuth`, experimental `AzureADAuth` (Entra ID JWT) |
| `mcp_harness.governance` | **`CostTracking`** (tokens → \$ → cost center), `Quotas` (rate / team cap / concurrency), `AuditLog` (async, shape-only) |
| `mcp_harness.observability` | `StructuredLogging` (JSON + correlation ids), `OTELTracing`, `Metrics` (Prometheus or in-memory) |
| `mcp_harness.policy` | `AllowList` / `DenyList` (YAML, argument constraints), `PIIRedactor` |
| `mcp_harness.resilience` | `CircuitBreaker`, `Retry` decorators for individual tools |
| `mcp_harness.testing` | `HarnessTestClient`, `MockPrincipal`, pytest fixtures |
| `mcp-harness` CLI | `daily-rollup` spend reports, `wrap` an existing server, `init` a new one |

Optional integrations degrade gracefully: `OTELTracing` is a no-op (warned once) without the
`otel` extra; `Metrics` falls back to an in-memory backend without `prometheus-client`; cost token
counting uses a heuristic without `tiktoken`.

## Testing your server

Governance is covered by ordinary unit tests — no transport, no mocks of the SDK:

```python
from mcp_harness.testing import HarnessTestClient, MockPrincipal
from myserver import harness

async def test_finance_can_search(harness_client):  # fixture auto-registered
    client = harness_client(harness, principal=MockPrincipal("svc-a", team="finance"))
    assert await client.call("search_customer", {"customer_id": "c-1"})
```

## Examples

- [`examples/quickstart_server.py`](examples/quickstart_server.py) — smallest governed server.
- [`examples/local_governed_server.py`](examples/local_governed_server.py) — full stack, zero
  cloud deps. Run `python examples/local_governed_server.py --demo` to watch the governance layers
  reject calls in real time.
- [`examples/azure_governed_server.py`](examples/azure_governed_server.py) — the design's
  Azure-centric reference server.

## Scope

**In scope:** auth, observability, cost attribution, quotas, audit, policy, resilience, testing.

**Out of scope (by design):** agent orchestration, a UI/dashboard, a tool registry, and anything
that breaks MCP wire-compatibility. A library that does a few things well beats one that does
fifteen poorly.

## Compatibility & status

- Python **3.10+**. Wraps the official `mcp` SDK (`FastMCP`) without modifying the wire protocol.
- **Beta (v0.1).** The `Harness`, auth, `CostTracking`, `Quotas`, observability, `AllowList`, and
  `AuditLog` APIs are real and tested. Cloud sinks (Azure Monitor, Event Hubs, Kinesis, Kafka),
  Redis-backed quotas, `SchemaGuard`, and `AzureADAuth` hardening are extension points — base
  interfaces ship, full wiring is on the roadmap. See [CHANGELOG.md](CHANGELOG.md).

## License

[Apache-2.0](LICENSE).
