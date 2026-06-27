"""Microsoft Entra ID (Azure AD) bearer-token authentication.

.. note::
   **Experimental.** Validates real Entra ID access tokens via the tenant's JWKS endpoint and
   requires the ``auth`` extra (``pip install 'mcp-harness[auth]'`` -> PyJWT + cryptography).
   Token validation runs in a thread so it does not block the event loop. The full Entra hardening
   surface (multi-tenant issuers, app-roles, CAE) is intentionally left as an extension point.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from ..core.principal import Principal
from ..errors import AuthenticationError, HarnessError
from .base import BaseAuth


def _require_jwt() -> Any:
    try:
        import jwt  # type: ignore

        return jwt
    except ImportError as exc:  # pragma: no cover - exercised only without the extra installed
        raise HarnessError(
            "AzureADAuth requires PyJWT and cryptography. "
            "Install them with:  pip install 'mcp-harness[auth]'."
        ) from exc


class AzureADAuth(BaseAuth):
    """Validate Entra ID access tokens and expose their claims as a principal.

    Args:
        tenant_id: Directory (tenant) GUID.
        audience: Expected ``aud`` claim (your API's app-id-uri or client id).
        required_scopes: Scopes that must all be present in the token's ``scp``/``roles``.
        header: Header carrying the bearer token. Defaults to ``authorization``.
        team_claim: Claim used to populate ``principal.team`` for cost attribution.
        jwks_url / issuer: Override the discovery endpoints (defaults derive from ``tenant_id``).
    """

    name = "azure_ad"

    def __init__(
        self,
        *,
        tenant_id: str,
        audience: str | None = None,
        required_scopes: Sequence[str] = (),
        header: str = "authorization",
        team_claim: str = "team",
        jwks_url: str | None = None,
        issuer: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.audience = audience
        self.required_scopes = tuple(required_scopes)
        self.header = header
        self.team_claim = team_claim
        self.jwks_url = jwks_url or f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        self.issuer = issuer or f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        self._jwks_client: Any | None = None

    def _client(self) -> Any:
        jwt = _require_jwt()
        if self._jwks_client is None:
            self._jwks_client = jwt.PyJWKClient(self.jwks_url)
        return self._jwks_client

    async def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        raw = self._get_header(headers, self.header)
        if not raw:
            return None
        token = raw[7:].strip() if raw.lower().startswith("bearer ") else raw.strip()
        if not token:
            return None
        # Network + crypto: keep it off the event loop.
        claims = await asyncio.to_thread(self._validate, token)
        self._check_scopes(claims)
        return self._principal_from_claims(claims)

    def _validate(self, token: str) -> dict[str, Any]:
        jwt = _require_jwt()
        try:
            signing_key = self._client().get_signing_key_from_jwt(token)
            options = {"verify_aud": self.audience is not None}
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options=options,
            )
        except Exception as exc:  # PyJWT raises a family of exceptions; normalise them.
            raise AuthenticationError(f"Invalid Entra ID token: {exc}") from exc

    def _check_scopes(self, claims: Mapping[str, Any]) -> None:
        if not self.required_scopes:
            return
        granted: set[str] = set()
        scp = claims.get("scp")
        if isinstance(scp, str):
            granted.update(scp.split())
        roles = claims.get("roles")
        if isinstance(roles, (list, tuple)):
            granted.update(roles)
        missing = [s for s in self.required_scopes if s not in granted]
        if missing:
            raise AuthenticationError(f"Token missing required scopes: {', '.join(missing)}")

    def _principal_from_claims(self, claims: Mapping[str, Any]) -> Principal:
        principal_id = str(claims.get("oid") or claims.get("sub") or "unknown")
        display = str(claims.get("name") or claims.get("preferred_username") or principal_id)
        normalised = dict(claims)
        if self.team_claim in claims and "team" not in normalised:
            normalised["team"] = claims[self.team_claim]
        scp = claims.get("scp")
        scopes = tuple(scp.split()) if isinstance(scp, str) else ()
        return Principal(
            id=principal_id,
            display_name=display,
            claims=normalised,
            scopes=scopes,
            auth_method=self.name,
        )


__all__ = ["AzureADAuth"]
