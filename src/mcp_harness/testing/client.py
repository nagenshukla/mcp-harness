"""An in-process test client for driving a harness without an MCP transport."""

from __future__ import annotations

from typing import Any

from ..core.harness import Harness
from ..core.principal import Principal


class MockPrincipal(Principal):
    """A :class:`Principal` with convenient defaults for tests.

    >>> p = MockPrincipal("alice", team="finance", scopes=["mcp.tools"])
    """

    def __init__(
        self,
        id: str = "test-user",
        *,
        team: str | None = None,
        cost_center: str | None = None,
        scopes: tuple[str, ...] = (),
        claims: dict[str, Any] | None = None,
        auth_method: str = "mock",
    ) -> None:
        merged: dict[str, Any] = dict(claims or {})
        if team is not None:
            merged.setdefault("team", team)
        if cost_center is not None:
            merged.setdefault("cost_center", cost_center)
        super().__init__(
            id=id,
            display_name=id,
            claims=merged,
            scopes=tuple(scopes),
            auth_method=auth_method,
        )


class HarnessTestClient:
    """Drive a :class:`Harness` through its full middleware pipeline, in-process.

    This exercises the exact path a live MCP client would, minus the transport — so governance
    behaviour (auth, quotas, policy, cost, audit) is covered by ordinary unit tests.

    Args:
        harness: The harness under test.
        principal: Default principal injected on every call (bypasses auth). Pass ``headers`` to a
            call instead to exercise the real auth backend.
    """

    def __init__(self, harness: Harness, *, principal: Principal | None = None) -> None:
        self.harness = harness
        self.principal = principal

    async def call(
        self,
        tool: str,
        arguments: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
        principal: Principal | None = None,
    ) -> Any:
        """Invoke ``tool`` and return its result (or raise the harness error it produced)."""
        effective = principal if principal is not None else (None if headers else self.principal)
        return await self.harness.dispatch(
            tool, arguments or {}, headers=headers, principal=effective
        )


__all__ = ["HarnessTestClient", "MockPrincipal"]
