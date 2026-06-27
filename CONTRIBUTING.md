# Contributing to mcp-harness

Thanks for your interest! This is a small, focused library — the goal is to do a few things well.

## Development setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    |    Unix: source .venv/bin/activate
pip install -e ".[dev]"
```

The `dev` extra includes the MCP SDK, pytest, ruff, mypy, and the build tooling.

## Checks

Run the same checks CI does before opening a PR:

```bash
ruff check .      # lint
mypy src          # type check
pytest -q         # tests
```

Tests should pass both with and without the MCP SDK installed — the core pipeline must never
hard-depend on `mcp`. The FastMCP integration tests auto-skip when `mcp` is absent.

## Design principles

- **Decoupled core.** Everything under `mcp_harness.core` and the middleware must work without the
  MCP SDK. Import `mcp` lazily, inside functions, behind `Harness.mcp_available()`.
- **Opt-in, composable middleware.** Each layer is independently useful and testable. Prefer
  subclassing `BaseMiddleware` (gate/transform) or `RecordingMiddleware` (observe).
- **Optional integrations degrade gracefully.** OpenTelemetry, Prometheus, tiktoken, and JWT are
  optional extras; absence is a warning + fallback, never an import error.
- **Don't break MCP wire-compatibility.** No protocol changes.

## Cutting a release

1. Bump the version in `pyproject.toml` and `mcp_harness.__version__`, update `CHANGELOG.md`.
2. Tag and push: `git tag v0.1.0 && git push origin v0.1.0`.
3. The `release.yml` workflow builds and publishes to PyPI via Trusted Publishing (no tokens).
   This requires a one-time trusted-publisher setup on the PyPI project settings page.

## License

By contributing you agree your contributions are licensed under [Apache-2.0](LICENSE).
