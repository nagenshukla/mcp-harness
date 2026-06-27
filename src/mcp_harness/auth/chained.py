"""Try several auth backends in order; accept the first that succeeds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..core.principal import Principal
from .base import BaseAuth


class ChainedAuth(BaseAuth):
    """Compose multiple backends, returning the first non-``None`` principal.

    Order matters: put stronger schemes first and an optional
    :class:`~mcp_harness.auth.anonymous.AnonymousAuth` last to allow an unauthenticated fallback.

    Example:
        >>> auth = ChainedAuth([APIKeyAuth(keys=...), AnonymousAuth()])
    """

    name = "chained"

    def __init__(self, backends: Sequence[BaseAuth]) -> None:
        if not backends:
            raise ValueError("ChainedAuth requires at least one backend")
        self.backends = list(backends)

    async def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        for backend in self.backends:
            principal = await backend.authenticate(headers)
            if principal is not None:
                return principal
        return None


__all__ = ["ChainedAuth"]
