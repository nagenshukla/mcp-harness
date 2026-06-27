"""Per-call context (:class:`ToolCallContext`) and tool registration record (:class:`ToolSpec`).

A single ``ToolCallContext`` is created for every tool invocation and threaded through the whole
middleware pipeline. Middleware reads and mutates it: auth populates ``principal``, cost tracking
fills ``input_tokens``/``output_tokens``, observability stamps timings, and so on.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .principal import Principal


class CallStatus(str, Enum):
    PENDING = "pending"
    OK = "ok"
    ERROR = "error"
    DENIED = "denied"


@dataclass(slots=True)
class ToolSpec:
    """A registered tool: the user's callable plus metadata the harness needs."""

    name: str
    fn: Callable[..., Any]
    description: str = ""
    is_async: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolCallContext:
    """Mutable state for a single tool invocation, shared across all middleware."""

    tool: str
    arguments: dict[str, Any]
    principal: Principal
    headers: dict[str, str] = field(default_factory=dict)
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: float = field(default_factory=time.monotonic)
    started_wall: float = field(default_factory=time.time)
    status: CallStatus = CallStatus.PENDING
    result: Any = None
    error: BaseException | None = None
    # Cost-tracking scratch space (filled by CostTracking middleware).
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cost_center: str | None = None
    # Free-form bag for middleware to stash correlation data.
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        """Elapsed wall-clock time since the context was created, in milliseconds."""
        return (time.monotonic() - self.started_at) * 1000.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def header(self, name: str, default: str | None = None) -> str | None:
        """Case-insensitive header lookup (HTTP transports normalise header case)."""
        lname = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lname:
                return value
        return default


# A middleware calls the next layer via this continuation.
NextCall = Callable[[ToolCallContext], Awaitable[Any]]


def classify_status(exc: BaseException) -> CallStatus:
    """Map an exception to a terminal call status for recording middleware.

    Governance rejections (policy/quota/auth) are ``DENIED``; anything else is ``ERROR``.
    """
    from ..errors import (
        AuthenticationError,
        AuthorizationError,
        QuotaExceeded,
    )

    if isinstance(exc, (AuthenticationError, AuthorizationError, QuotaExceeded)):
        return CallStatus.DENIED
    return CallStatus.ERROR


__all__ = ["CallStatus", "ToolSpec", "ToolCallContext", "NextCall", "classify_status"]
