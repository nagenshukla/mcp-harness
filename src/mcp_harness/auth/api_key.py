"""API-key authentication with built-in rotation hooks."""

from __future__ import annotations

import hmac
from collections.abc import Callable, Mapping
from typing import Any

from ..core.principal import Principal
from .base import BaseAuth

# Per-key metadata. Recognised keys: id, display_name, team, email, cost_center, scopes, claims.
KeyInfo = Mapping[str, Any]
KeyMap = Mapping[str, KeyInfo]


class APIKeyAuth(BaseAuth):
    """Authenticate callers by a shared secret presented in a header.

    Args:
        keys: Mapping of secret -> metadata describing the principal it represents.
        header: Header carrying the key. Defaults to ``x-api-key``.
        key_loader: Optional callable returning the *current* key map on each authentication.
            Use this to rotate keys without restarting (e.g. read from a secrets store). When
            given, it takes precedence over ``keys``.
        principal_factory: Optional override mapping ``(key, info) -> Principal``.

    Example:
        >>> auth = APIKeyAuth(keys={
        ...     "sk-finance-1": {"id": "svc-reports", "team": "finance", "scopes": ["mcp.tools"]},
        ... })
    """

    name = "api_key"

    def __init__(
        self,
        keys: KeyMap | None = None,
        *,
        header: str = "x-api-key",
        key_loader: Callable[[], KeyMap] | None = None,
        principal_factory: Callable[[str, KeyInfo], Principal] | None = None,
    ) -> None:
        self._keys: dict[str, dict[str, Any]] = {k: dict(v) for k, v in (keys or {}).items()}
        self.header = header
        self._key_loader = key_loader
        self._principal_factory = principal_factory

    # -- rotation API -----------------------------------------------------------------------

    def add_key(self, key: str, info: KeyInfo) -> None:
        """Add or replace a key at runtime."""
        self._keys[key] = dict(info)

    def revoke_key(self, key: str) -> None:
        """Remove a key at runtime. No-op if it was not present."""
        self._keys.pop(key, None)

    # -- auth -------------------------------------------------------------------------------

    def _current_keys(self) -> Mapping[str, KeyInfo]:
        if self._key_loader is not None:
            return self._key_loader()
        return self._keys

    async def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        presented = self._get_header(headers, self.header)
        if not presented:
            return None
        # Constant-time comparison against each known key to avoid leaking timing on the secret.
        for key, info in self._current_keys().items():
            if hmac.compare_digest(presented, key):
                if self._principal_factory is not None:
                    return self._principal_factory(key, info)
                return self._principal_from_info(key, info)
        return None

    def _principal_from_info(self, key: str, info: KeyInfo) -> Principal:
        info = dict(info or {})
        claims: dict[str, Any] = dict(info.get("claims", {}))
        for promoted in ("team", "email", "cost_center"):
            if promoted in info:
                claims.setdefault(promoted, info[promoted])
        return Principal(
            id=str(info.get("id") or f"apikey:{key[:8]}"),
            display_name=str(info.get("display_name", "")),
            claims=claims,
            scopes=tuple(info.get("scopes", ())),
            auth_method=self.name,
        )


__all__ = ["APIKeyAuth"]
