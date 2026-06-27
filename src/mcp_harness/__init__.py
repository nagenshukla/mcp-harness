"""mcp-harness — enterprise governance middleware for MCP servers.

Compose auth, cost attribution, quotas, observability, audit, and policy around the official MCP
Python SDK. The core pipeline has no hard dependency on ``mcp``; install the ``server`` extra to
serve tools (``pip install 'mcp-harness[server]'``).

Quick start::

    from mcp_harness import Harness
    from mcp_harness.auth import APIKeyAuth
    from mcp_harness.governance import CostTracking
    from mcp_harness.observability import StructuredLogging

    harness = Harness(
        name="my-mcp",
        auth=APIKeyAuth(keys={"k-123": {"id": "svc-reports", "team": "finance"}}),
        middleware=[StructuredLogging(), CostTracking()],
    )

    @harness.tool()
    async def search(q: str) -> dict:
        '''Search the corpus.'''
        return {"hits": []}

    if __name__ == "__main__":
        harness.run()
"""

from __future__ import annotations

from .core import Harness, Principal, ToolCallContext
from .errors import (
    AuthenticationError,
    AuthorizationError,
    CircuitOpen,
    HarnessError,
    MCPNotInstalled,
    PolicyDenied,
    QuotaExceeded,
)

__version__ = "0.1.0"

__all__ = [
    "Harness",
    "Principal",
    "ToolCallContext",
    "HarnessError",
    "MCPNotInstalled",
    "AuthenticationError",
    "AuthorizationError",
    "PolicyDenied",
    "QuotaExceeded",
    "CircuitOpen",
    "__version__",
]
