"""Auth backend contract and the middleware that runs it first in the pipeline."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from ..core.context import NextCall, ToolCallContext
from ..core.middleware import BaseMiddleware
from ..core.principal import Principal
from ..errors import AuthenticationError


class BaseAuth(ABC):
    """A pluggable authentication backend.

    Implementations resolve inbound transport metadata (HTTP headers, typically) into a
    :class:`~mcp_harness.core.principal.Principal`. Return ``None`` to signal "no valid credential
    presented" — the :class:`AuthMiddleware` turns that into an :class:`AuthenticationError`.
    """

    #: Stable short name, stamped onto resolved principals and used in logs.
    name: str = "base"

    @abstractmethod
    async def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        """Resolve ``headers`` to a principal, or ``None`` if authentication fails."""
        raise NotImplementedError

    @staticmethod
    def _get_header(headers: Mapping[str, str], name: str) -> str | None:
        """Case-insensitive header lookup."""
        lname = name.lower()
        for key, value in headers.items():
            if key.lower() == lname:
                return value
        return None


class AuthMiddleware(BaseMiddleware):
    """Outermost pipeline layer: resolves the principal before anything else runs.

    A principal injected directly into :meth:`Harness.dispatch` (the testing path) is honoured and
    auth is skipped.
    """

    name = "auth"

    def __init__(self, auth: BaseAuth) -> None:
        super().__init__()
        self.auth = auth

    async def __call__(self, ctx: ToolCallContext, call_next: NextCall) -> Any:
        if ctx.metadata.get("principal_preauthenticated"):
            return await call_next(ctx)

        principal = await self.auth.authenticate(ctx.headers)
        if principal is None:
            raise AuthenticationError(
                f"Authentication failed for tool '{ctx.tool}' "
                f"using backend '{getattr(self.auth, 'name', type(self.auth).__name__)}'"
            )
        ctx.principal = principal
        return await call_next(ctx)


__all__ = ["BaseAuth", "AuthMiddleware"]
