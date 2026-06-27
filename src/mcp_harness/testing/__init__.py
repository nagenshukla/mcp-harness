"""Testing utilities: an in-process client and pytest fixtures.

The :class:`HarnessTestClient` and :class:`MockPrincipal` are importable without pytest. The
pytest fixtures live in :mod:`mcp_harness.testing.fixtures` and auto-register via the ``pytest11``
entry point when pytest runs.
"""

from .client import HarnessTestClient, MockPrincipal

__all__ = ["HarnessTestClient", "MockPrincipal"]
