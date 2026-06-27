# Changelog

All notable changes to `mcp-harness` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-27

Initial public release. v0.1 MVP plus the surrounding governance core.

### Added
- **Core** — `Harness` with an onion middleware pipeline that is fully decoupled from the MCP
  SDK. `@harness.tool()` registration, `harness.dispatch()` for direct/testing invocation, and
  `harness.run()` which integrates with the official `mcp` SDK (FastMCP) when installed.
- **`Harness.from_fastmcp(server, ...)`** — wrap an existing `FastMCP` server, routing its
  already-registered tools through the governance pipeline while preserving their input schemas.
  The one-line "add governance to the server I already have" path.
- **CLI scaffolding** — `mcp-harness wrap <server.py>` generates a governed companion file for an
  existing FastMCP server (original untouched), and `mcp-harness init [name]` scaffolds a new
  governed server.
- **Auth** — `AnonymousAuth` (default), `APIKeyAuth` (with rotation hook + principal resolver),
  `ChainedAuth`, and an experimental `AzureADAuth` (JWT validation, requires the `auth` extra).
- **Governance** — `CostTracking` (token counting, pluggable pricing, cost-center resolution,
  pluggable sinks), `Quotas` (per-principal token bucket, per-team caps, per-tool concurrency),
  and `AuditLog` (async, non-blocking, shape-only records).
- **Observability** — `StructuredLogging` (JSON + correlation ids), `OTELTracing` (optional,
  `otel` extra), `Metrics` (Prometheus when available, else in-memory).
- **Policy** — `AllowList` / `DenyList` (YAML-loadable, optional argument constraints) and a
  basic `PIIRedactor`.
- **Resilience** — `CircuitBreaker` and `Retry` decorators for individual tools.
- **Testing** — `HarnessTestClient`, `MockPrincipal`, and pytest fixtures (auto-registered as a
  pytest plugin).
- **CLI** — `mcp-harness daily-rollup` to produce per-cost-center spend reports from cost JSONL.
- Examples: `quickstart_server.py`, `local_governed_server.py`, `azure_governed_server.py`.

[Unreleased]: https://github.com/nagenshukla/mcp-harness/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nagenshukla/mcp-harness/releases/tag/v0.1.0
