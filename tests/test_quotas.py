"""Rate limits, team caps, and concurrency limits."""

from __future__ import annotations

import asyncio

import pytest

from mcp_harness import Harness, QuotaExceeded
from mcp_harness.governance import Quotas
from mcp_harness.governance.quotas import InMemoryQuotaStore, RedisQuotaStore
from mcp_harness.testing import HarnessTestClient, MockPrincipal


async def test_per_principal_rate_limit_trips():
    h = Harness(name="t", middleware=[Quotas(per_principal_per_minute=2)])

    @h.tool()
    async def ping() -> str:
        return "pong"

    client = HarnessTestClient(h, principal=MockPrincipal("svc-a"))
    assert await client.call("ping") == "pong"
    assert await client.call("ping") == "pong"
    with pytest.raises(QuotaExceeded) as exc:
        await client.call("ping")
    assert exc.value.scope == "principal"
    assert exc.value.retry_after is not None


async def test_team_cap_shared_across_principals():
    h = Harness(name="t", middleware=[Quotas(per_team_per_minute=1)])

    @h.tool()
    async def ping() -> str:
        return "pong"

    a = HarnessTestClient(h, principal=MockPrincipal("svc-a", team="finance"))
    b = HarnessTestClient(h, principal=MockPrincipal("svc-b", team="finance"))
    assert await a.call("ping") == "pong"
    with pytest.raises(QuotaExceeded) as exc:
        await b.call("ping")
    assert exc.value.scope == "team"


async def test_concurrency_limit_rejects_second_caller():
    release = asyncio.Event()
    started = asyncio.Event()
    h = Harness(name="t", middleware=[Quotas(concurrency={"slow": 1})])

    @h.tool()
    async def slow() -> str:
        started.set()
        await release.wait()
        return "done"

    client = HarnessTestClient(h, principal=MockPrincipal("svc-a"))
    first = asyncio.create_task(client.call("slow"))
    await started.wait()  # first call is in-flight, holding the only slot

    with pytest.raises(QuotaExceeded) as exc:
        await client.call("slow")
    assert exc.value.scope == "concurrency"

    release.set()
    assert await first == "done"
    # Slot released -> a subsequent call succeeds (release event is already set).
    assert await client.call("slow") == "done"


def test_release_slot_decrements_without_clearing_when_others_held():
    store = InMemoryQuotaStore()
    assert store.acquire_slot("k", limit=2)
    assert store.acquire_slot("k", limit=2)
    store.release_slot("k")
    # One slot still held -> the next acquire must respect the remaining count.
    assert store.acquire_slot("k", limit=2)
    assert not store.acquire_slot("k", limit=2)


def test_redis_quota_store_is_unimplemented_extension_point():
    store = RedisQuotaStore(client=object())
    with pytest.raises(NotImplementedError):
        store.rate_check("k", 10)
    with pytest.raises(NotImplementedError):
        store.acquire_slot("k", 1)
    with pytest.raises(NotImplementedError):
        store.release_slot("k")


async def test_no_limits_passes_through():
    h = Harness(name="t", middleware=[Quotas()])

    @h.tool()
    async def ping() -> str:
        return "pong"

    client = HarnessTestClient(h, principal=MockPrincipal())
    for _ in range(100):
        assert await client.call("ping") == "pong"
