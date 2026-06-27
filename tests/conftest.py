"""Shared test helpers and fixtures."""

from __future__ import annotations

from typing import Any

import pytest

from mcp_harness.governance.sinks import Sink


class ListSink(Sink):
    """A sink that records emitted dicts in a list, for assertions."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def emit(self, record: Any) -> None:
        self.records.append(record.to_dict())


@pytest.fixture
def list_sink() -> ListSink:
    """A fresh capturing sink per test."""
    return ListSink()
