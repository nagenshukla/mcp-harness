"""The :class:`Principal` — the authenticated identity behind a tool call.

Auth backends resolve inbound transport credentials into a ``Principal``. Every downstream
middleware (cost attribution, quotas, allow-listing, audit) keys off this object, so it is
deliberately small, immutable-ish, and backend-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Principal:
    """An authenticated caller.

    Attributes:
        id: Stable unique identifier (subject claim, API-key id, cert thumbprint, ...).
        display_name: Human-friendly label for logs and reports. Defaults to ``id``.
        claims: Arbitrary attributes from the auth backend (e.g. JWT claims). The conventional
            keys ``team``, ``cost_center``, and ``email`` are recognised by built-in middleware.
        scopes: Granted scopes/permissions, used by policy middleware.
        auth_method: Name of the backend that produced this principal (e.g. ``"api_key"``).
        anonymous: ``True`` when no real credential was presented.
    """

    id: str
    display_name: str = ""
    claims: dict[str, Any] = field(default_factory=dict)
    scopes: tuple[str, ...] = ()
    auth_method: str = "unknown"
    anonymous: bool = False

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.id

    @property
    def team(self) -> str | None:
        """Best-effort team, read from the ``team`` claim."""
        value = self.claims.get("team")
        return str(value) if value is not None else None

    @property
    def email(self) -> str | None:
        value = self.claims.get("email")
        return str(value) if value is not None else None

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def to_log_fields(self) -> dict[str, Any]:
        """Compact, non-sensitive representation for structured logs / audit records."""
        fields: dict[str, Any] = {
            "principal_id": self.id,
            "auth_method": self.auth_method,
        }
        if self.team:
            fields["team"] = self.team
        return fields

    @classmethod
    def anonymous_principal(cls) -> Principal:
        return cls(
            id="anonymous",
            display_name="anonymous",
            auth_method="anonymous",
            anonymous=True,
        )


__all__ = ["Principal"]
