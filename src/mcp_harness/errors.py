"""Exception hierarchy for mcp-harness.

All harness-raised errors derive from :class:`HarnessError`. Middleware raises these to reject
a tool call before (or instead of) invoking the user's tool. When running under the official MCP
SDK, the FastMCP runtime surfaces a raised exception to the client as a tool error, so these
propagate naturally across the wire without any special handling.
"""

from __future__ import annotations


class HarnessError(Exception):
    """Base class for every error raised by mcp-harness."""


class MCPNotInstalled(HarnessError):
    """Raised when an operation needs the optional ``mcp`` SDK but it is not installed."""

    def __init__(self, what: str = "This operation") -> None:
        super().__init__(
            f"{what} requires the official MCP SDK, which is not installed. "
            "Install it with:  pip install 'mcp-harness[server]'   (or  pip install mcp)."
        )


class AuthenticationError(HarnessError):
    """The caller could not be authenticated (missing/invalid credentials)."""


class AuthorizationError(HarnessError):
    """The caller was authenticated but is not permitted to perform the action."""


class PolicyDenied(AuthorizationError):
    """A policy middleware (allow/deny list, schema guard) rejected the call."""

    def __init__(self, tool: str, reason: str) -> None:
        self.tool = tool
        self.reason = reason
        super().__init__(f"Policy denied call to tool '{tool}': {reason}")


class QuotaExceeded(HarnessError):
    """A rate limit, concurrency limit, or aggregate cap was exceeded."""

    def __init__(self, scope: str, detail: str, retry_after: float | None = None) -> None:
        self.scope = scope
        self.detail = detail
        self.retry_after = retry_after
        suffix = f" (retry after {retry_after:.1f}s)" if retry_after is not None else ""
        super().__init__(f"Quota exceeded [{scope}]: {detail}{suffix}")


class CircuitOpen(HarnessError):
    """A circuit breaker is open and is short-circuiting calls to a downstream dependency."""

    def __init__(self, name: str, retry_after: float | None = None) -> None:
        self.name = name
        self.retry_after = retry_after
        suffix = f"; retry after {retry_after:.1f}s" if retry_after is not None else ""
        super().__init__(f"Circuit '{name}' is open{suffix}")


__all__ = [
    "HarnessError",
    "MCPNotInstalled",
    "AuthenticationError",
    "AuthorizationError",
    "PolicyDenied",
    "QuotaExceeded",
    "CircuitOpen",
]
