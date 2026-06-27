"""A retry decorator with exponential backoff and jitter."""

from __future__ import annotations

import asyncio
import functools
import inspect
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class Retry:
    """Retry a tool on failure with exponential backoff and full jitter.

    Delays follow ``base_delay * factor ** attempt`` capped at ``max_delay``; with ``jitter`` the
    actual sleep is uniform in ``[0, delay]`` (full jitter) to avoid thundering herds.

    Works on sync and async tools::

        @harness.tool()
        @Retry(max_attempts=3, base_delay=0.2, exceptions=(TimeoutError,))
        async def fetch(id: str) -> dict: ...
    """

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        base_delay: float = 0.1,
        max_delay: float = 10.0,
        factor: float = 2.0,
        jitter: bool = True,
        exceptions: tuple[type[BaseException], ...] = (Exception,),
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.factor = factor
        self.jitter = jitter
        self.exceptions = exceptions

    def _delay_for(self, attempt: int) -> float:
        delay = min(self.max_delay, self.base_delay * (self.factor**attempt))
        if self.jitter:
            return random.uniform(0, delay)
        return delay

    def __call__(self, fn: F) -> F:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                last_exc: BaseException | None = None
                for attempt in range(self.max_attempts):
                    try:
                        return await fn(*args, **kwargs)
                    except self.exceptions as exc:
                        last_exc = exc
                        if attempt + 1 >= self.max_attempts:
                            break
                        await asyncio.sleep(self._delay_for(attempt))
                assert last_exc is not None
                raise last_exc

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: BaseException | None = None
            for attempt in range(self.max_attempts):
                try:
                    return fn(*args, **kwargs)
                except self.exceptions as exc:
                    last_exc = exc
                    if attempt + 1 >= self.max_attempts:
                        break
                    time.sleep(self._delay_for(attempt))
            assert last_exc is not None
            raise last_exc

        return sync_wrapper  # type: ignore[return-value]


__all__ = ["Retry"]
