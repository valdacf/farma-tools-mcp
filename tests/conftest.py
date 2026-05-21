"""Shared test fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    """Load a JSON fixture by filename (with or without .json extension).

    All payloads under tests/fixtures/ were captured live from the upstream
    APIs (ARES, ČÚZK ArcGIS, Open-Meteo, Overpass). Refresh them with the
    matching curl snippet in tests/fixtures/README.md when the upstream
    schemas change.
    """
    fname = name if name.endswith(".json") else f"{name}.json"
    with (FIXTURES_DIR / fname).open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def fixture():
    """Provide load_fixture as a fixture for convenience."""
    return load_fixture


@pytest.fixture
def mock_http():
    """Yield a respx router that intercepts httpx traffic for the duration of the test."""
    with respx.mock(assert_all_called=False) as router:
        yield router
