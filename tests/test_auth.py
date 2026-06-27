"""Authentication backends and the auth middleware."""

from __future__ import annotations

import pytest

from mcp_harness import AuthenticationError, Harness
from mcp_harness.auth import AnonymousAuth, APIKeyAuth, ChainedAuth


def _harness_with(auth) -> Harness:
    h = Harness(name="t", auth=auth)

    @h.tool()
    async def whoami(_marker: str = "x") -> str:
        return "ok"

    return h


async def test_api_key_resolves_principal_from_header():
    auth = APIKeyAuth(keys={"sk-1": {"id": "svc-a", "team": "finance", "scopes": ["mcp.tools"]}})
    principal = await auth.authenticate({"x-api-key": "sk-1"})
    assert principal is not None
    assert principal.id == "svc-a"
    assert principal.team == "finance"
    assert principal.has_scope("mcp.tools")


async def test_api_key_missing_or_wrong_is_rejected():
    h = _harness_with(APIKeyAuth(keys={"sk-1": {"id": "svc-a"}}))
    with pytest.raises(AuthenticationError):
        await h.dispatch("whoami", {}, headers={})  # no key
    with pytest.raises(AuthenticationError):
        await h.dispatch("whoami", {}, headers={"x-api-key": "nope"})


async def test_api_key_rotation_add_and_revoke():
    auth = APIKeyAuth(keys={})
    assert await auth.authenticate({"x-api-key": "sk-new"}) is None
    auth.add_key("sk-new", {"id": "svc-new"})
    assert (await auth.authenticate({"x-api-key": "sk-new"})).id == "svc-new"
    auth.revoke_key("sk-new")
    assert await auth.authenticate({"x-api-key": "sk-new"}) is None


async def test_anonymous_default_allows_calls():
    h = _harness_with(AnonymousAuth())
    assert await h.dispatch("whoami", {}, headers={}) == "ok"


async def test_chained_falls_back_to_anonymous():
    auth = ChainedAuth([APIKeyAuth(keys={"sk-1": {"id": "svc-a"}}), AnonymousAuth()])
    # Valid key -> first backend wins.
    assert (await auth.authenticate({"x-api-key": "sk-1"})).id == "svc-a"
    # No key -> anonymous fallback.
    anon = await auth.authenticate({})
    assert anon is not None and anon.anonymous


async def test_injected_principal_bypasses_auth():
    from mcp_harness.testing import MockPrincipal

    h = _harness_with(APIKeyAuth(keys={"sk-1": {"id": "svc-a"}}))
    # No headers, but an explicit principal -> auth is skipped.
    result = await h.dispatch("whoami", {}, principal=MockPrincipal("tester"))
    assert result == "ok"
