"""A circuit breaker decorator for tools that call flaky downstream services."""

from __future__ import annotations

import functools
import inspect
import time
from collections.abc import Callable
from enum import Enum
from typing import Any, TypeVar

from ..errors import CircuitOpen

F = TypeVar("F", bound=Callable[..., Any])


class CircuitState(str, Enum):
    CLOSED = "closed"  # calls flow; failures are counted
    OPEN = "open"  # calls short-circuit until the recovery timeout elapses
    HALF_OPEN = "half_open"  # one trial call is allowed to test recovery


class CircuitBreaker:
    """Wrap a tool so repeated downstream failures fail fast instead of piling up.

    After ``failure_threshold`` consecutive failures the circuit opens and calls raise
    :class:`~mcp_harness.errors.CircuitOpen` for ``recovery_timeout`` seconds, then a single trial
    is allowed (half-open). A success closes the circuit; a failure re-opens it.

    Works as a decorator on both sync and async tools::

        @harness.tool()
        @CircuitBreaker(failure_threshold=5, recovery_timeout=30)
        async def fetch(id: str) -> dict: ...
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        expected_exceptions: tuple[type[BaseException], ...] = (Exception,),
        name: str | None = None,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exceptions = expected_exceptions
        self.name = name
        self.state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at = 0.0

    # -- state machine ----------------------------------------------------------------------

    def _before_call(self) -> None:
        if self.state is CircuitState.OPEN:
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
            else:
                retry_after = self.recovery_timeout - elapsed
                raise CircuitOpen(self.name or "circuit", retry_after=retry_after)

    def _on_success(self) -> None:
        self._failures = 0
        self.state = CircuitState.CLOSED

    def _on_failure(self) -> None:
        self._failures += 1
        if self.state is CircuitState.HALF_OPEN or self._failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self._opened_at = time.monotonic()

    # -- decoration -------------------------------------------------------------------------

    def __call__(self, fn: F) -> F:
        self.name = self.name or getattr(fn, "__name__", "circuit")
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                self._before_call()
                try:
                    result = await fn(*args, **kwargs)
                except self.expected_exceptions:
                    self._on_failure()
                    raise
                self._on_success()
                return result

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            self._before_call()
            try:
                result = fn(*args, **kwargs)
            except self.expected_exceptions:
                self._on_failure()
                raise
            self._on_success()
            return result

        return sync_wrapper  # type: ignore[return-value]


__all__ = ["CircuitBreaker", "CircuitState"]
