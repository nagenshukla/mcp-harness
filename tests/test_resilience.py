"""Circuit breaker and retry decorators."""

from __future__ import annotations

import pytest

from mcp_harness import CircuitOpen
from mcp_harness.resilience import CircuitBreaker, CircuitState, Retry


async def test_circuit_opens_after_threshold_and_short_circuits():
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0)

    @breaker
    async def flaky() -> None:
        raise RuntimeError("down")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await flaky()
    assert breaker.state is CircuitState.OPEN
    # Now calls fail fast without invoking the function.
    with pytest.raises(CircuitOpen):
        await flaky()


async def test_circuit_half_open_recovers_on_success():
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
    calls = {"n": 0}

    @breaker
    async def sometimes() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first fails")
        return "ok"

    with pytest.raises(RuntimeError):
        await sometimes()
    assert breaker.state is CircuitState.OPEN
    # recovery_timeout=0 -> immediately half-open; the trial succeeds and closes it.
    assert await sometimes() == "ok"
    assert breaker.state is CircuitState.CLOSED


async def test_retry_succeeds_after_transient_failures():
    attempts = {"n": 0}

    @Retry(max_attempts=3, base_delay=0.0, jitter=False, exceptions=(ValueError,))
    async def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ValueError("transient")
        return "ok"

    assert await flaky() == "ok"
    assert attempts["n"] == 3


async def test_retry_exhausts_and_reraises():
    @Retry(max_attempts=2, base_delay=0.0, jitter=False)
    async def always_fails() -> None:
        raise RuntimeError("permanent")

    with pytest.raises(RuntimeError, match="permanent"):
        await always_fails()


def test_retry_works_on_sync_functions():
    attempts = {"n": 0}

    @Retry(max_attempts=2, base_delay=0.0, jitter=False)
    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("x")
        return "ok"

    assert flaky() == "ok"
