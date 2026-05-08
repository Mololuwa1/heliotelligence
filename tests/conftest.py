"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def bracon_ash_csv() -> Path:
    """Path to the Bracon Ash sample CSV fixture."""
    p = FIXTURES_DIR / "bracon_ash_sample.csv"
    assert p.exists(), f"Fixture not found: {p}"
    return p
