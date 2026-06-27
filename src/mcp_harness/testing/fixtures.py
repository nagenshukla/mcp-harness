"""pytest fixtures for testing MCP servers built with mcp-harness.

Registered as a pytest plugin via the ``pytest11`` entry point, so simply having ``mcp-harness``
installed makes these fixtures available — no ``conftest.py`` wiring required.

Available fixtures:
    mock_principal   -> a default :class:`MockPrincipal`
    make_principal   -> factory for customised principals
    harness_client   -> factory: ``harness_client(harness, principal=...)`` -> HarnessTestClient
"""

from __future__ import annotations

from typing import Any

import pytest

from ..core.harness import Harness
from ..core.principal import Principal
from .client import HarnessTestClient, MockPrincipal


@pytest.fixture
def mock_principal() -> MockPrincipal:
    """A ready-to-use authenticated test principal."""
    return MockPrincipal(team="test-team")


@pytest.fixture
def make_principal():
    """Factory fixture for building :class:`MockPrincipal` instances with custom attributes."""

    def _make(id: str = "test-user", **kwargs: Any) -> MockPrincipal:
        return MockPrincipal(id, **kwargs)

    return _make


@pytest.fixture
def harness_client():
    """Factory fixture returning a :class:`HarnessTestClient` for a given harness."""

    def _make(harness: Harness, *, principal: Principal | None = None) -> HarnessTestClient:
        return HarnessTestClient(harness, principal=principal)

    return _make


__all__ = ["mock_principal", "make_principal", "harness_client"]
