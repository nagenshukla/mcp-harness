"""The default, do-nothing auth backend."""

from __future__ import annotations

from collections.abc import Mapping

from ..core.principal import Principal
from .base import BaseAuth


class AnonymousAuth(BaseAuth):
    """Resolves every caller to a single anonymous principal.

    This is the default when no ``auth=`` is supplied. Use it for local development, trusted
    networks, or as the final link in a :class:`~mcp_harness.auth.chained.ChainedAuth` to allow an
    unauthenticated fallback.
    """

    name = "anonymous"

    def __init__(self, *, principal_id: str = "anonymous", team: str | None = None) -> None:
        self._principal_id = principal_id
        self._team = team

    async def authenticate(self, headers: Mapping[str, str]) -> Principal:
        claims = {"team": self._team} if self._team else {}
        return Principal(
            id=self._principal_id,
            display_name=self._principal_id,
            claims=claims,
            auth_method=self.name,
            anonymous=True,
        )


__all__ = ["AnonymousAuth"]
