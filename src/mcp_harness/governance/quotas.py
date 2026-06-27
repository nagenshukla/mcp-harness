"""Rate limits, aggregate caps, and concurrency limits.

All limiters are evaluated *before* the tool runs; concurrency slots are released afterwards.
The default backend is in-process. A :class:`RedisQuotaStore` extension point is provided for
distributed deployments.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..core.context import NextCall, ToolCallContext
from ..core.middleware import BaseMiddleware
from ..errors import QuotaExceeded


@dataclass
class _TokenBucket:
    """Classic token bucket: ``capacity`` tokens, refilling at ``refill_per_sec``."""

    capacity: float
    refill_per_sec: float
    tokens: float
    updated: float

    def _refill(self, now: float) -> None:
        elapsed = now - self.updated
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
            self.updated = now

    def try_consume(self, amount: float = 1.0) -> tuple[bool, float | None]:
        now = time.monotonic()
        self._refill(now)
        if self.tokens >= amount:
            self.tokens -= amount
            return True, None
        deficit = amount - self.tokens
        retry_after = deficit / self.refill_per_sec if self.refill_per_sec > 0 else None
        return False, retry_after


class QuotaStore(ABC):
    """Backend for rate buckets and concurrency slots."""

    @abstractmethod
    def rate_check(self, key: str, per_minute: int) -> tuple[bool, float | None]:
        """Consume one unit from per-minute bucket ``key``; returns ``(allowed, retry_after)``."""

    @abstractmethod
    def acquire_slot(self, key: str, limit: int) -> bool:
        """Try to take one concurrency slot for ``key`` (max ``limit``)."""

    @abstractmethod
    def release_slot(self, key: str) -> None:
        """Return a previously acquired concurrency slot."""


class InMemoryQuotaStore(QuotaStore):
    """Single-process backend. Operations are atomic on the asyncio event loop (no awaits)."""

    def __init__(self) -> None:
        self._buckets: dict[str, _TokenBucket] = {}
        self._slots: dict[str, int] = {}

    def rate_check(self, key: str, per_minute: int) -> tuple[bool, float | None]:
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _TokenBucket(
                capacity=float(per_minute),
                refill_per_sec=per_minute / 60.0,
                tokens=float(per_minute),
                updated=time.monotonic(),
            )
            self._buckets[key] = bucket
        return bucket.try_consume(1.0)

    def acquire_slot(self, key: str, limit: int) -> bool:
        current = self._slots.get(key, 0)
        if current >= limit:
            return False
        self._slots[key] = current + 1
        return True

    def release_slot(self, key: str) -> None:
        current = self._slots.get(key, 0)
        if current <= 1:
            self._slots.pop(key, None)
        else:
            self._slots[key] = current - 1


class RedisQuotaStore(QuotaStore):
    """Distributed backend (extension point).

    Requires ``pip install 'mcp-harness[redis]'`` and a configured client. Implementing a correct
    distributed token bucket (e.g. a small Lua script for atomic refill+consume) is intentionally
    left to the deploying team; the in-memory store is the supported default for v0.1.
    """

    def __init__(self, client: Any, *, namespace: str = "mcp-harness:quota") -> None:
        self.client = client
        self.namespace = namespace

    def _not_implemented(self) -> QuotaExceeded:
        raise NotImplementedError(
            "RedisQuotaStore is an extension point in v0.1. Subclass it and implement "
            "rate_check / acquire_slot / release_slot against your Redis deployment."
        )

    def rate_check(self, key: str, per_minute: int) -> tuple[bool, float | None]:
        raise self._not_implemented()

    def acquire_slot(self, key: str, limit: int) -> bool:
        raise self._not_implemented()

    def release_slot(self, key: str) -> None:
        raise self._not_implemented()


class Quotas(BaseMiddleware):
    """Enforce per-principal rate limits, per-team caps, and per-tool concurrency limits.

    Args:
        per_principal_per_minute: Max calls per principal per minute (token bucket).
        per_team_per_minute: Max calls per team per minute (aggregate cap).
        concurrency: ``{tool_name: max_concurrent}`` limit, applied per principal.
        default_concurrency: Concurrency limit for tools not in ``concurrency``.
        store: Backend; defaults to :class:`InMemoryQuotaStore`.
    """

    name = "quotas"

    def __init__(
        self,
        *,
        per_principal_per_minute: int | None = None,
        per_team_per_minute: int | None = None,
        concurrency: Mapping[str, int] | None = None,
        default_concurrency: int | None = None,
        store: QuotaStore | None = None,
    ) -> None:
        super().__init__()
        self.per_principal_per_minute = per_principal_per_minute
        self.per_team_per_minute = per_team_per_minute
        self.concurrency = dict(concurrency or {})
        self.default_concurrency = default_concurrency
        self.store = store or InMemoryQuotaStore()

    def _concurrency_limit(self, tool: str) -> int | None:
        return self.concurrency.get(tool, self.default_concurrency)

    async def __call__(self, ctx: ToolCallContext, call_next: NextCall) -> Any:
        principal = ctx.principal

        if self.per_principal_per_minute is not None:
            allowed, retry = self.store.rate_check(
                f"principal:{principal.id}", self.per_principal_per_minute
            )
            if not allowed:
                raise QuotaExceeded(
                    "principal",
                    f"{principal.id} exceeded {self.per_principal_per_minute}/min",
                    retry,
                )

        if self.per_team_per_minute is not None and principal.team:
            allowed, retry = self.store.rate_check(
                f"team:{principal.team}", self.per_team_per_minute
            )
            if not allowed:
                raise QuotaExceeded(
                    "team",
                    f"team '{principal.team}' exceeded {self.per_team_per_minute}/min",
                    retry,
                )

        limit = self._concurrency_limit(ctx.tool)
        if limit is None:
            return await call_next(ctx)

        slot_key = f"{principal.id}:{ctx.tool}"
        if not self.store.acquire_slot(slot_key, limit):
            raise QuotaExceeded(
                "concurrency",
                f"{principal.id} already at {limit} concurrent call(s) to '{ctx.tool}'",
            )
        try:
            return await call_next(ctx)
        finally:
            self.store.release_slot(slot_key)


__all__ = [
    "Quotas",
    "QuotaStore",
    "InMemoryQuotaStore",
    "RedisQuotaStore",
]
