"""Unit tests for heliotelligence.analysis.degradation.

Tests
-----
1. Negative slope detected in a declining PR series
2. Flat series produces rate close to 0
3. Fewer than 30 days returns confidence=None and rate=None
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from heliotelligence.analysis.degradation import _compute_degradation

_START = datetime(2022, 1, 1, tzinfo=timezone.utc)


def _daily_series(values: list[float]) -> pd.Series:
    """Build a daily PR Series starting at _START."""
    idx = pd.date_range(_START, periods=len(values), freq="D", tz="UTC")
    return pd.Series(values, index=idx)


def _end(n_days: int) -> datetime:
    from datetime import timedelta
    return _START + timedelta(days=n_days)


# ---------------------------------------------------------------------------
# Test 1 — Declining PR series produces negative rate
# ---------------------------------------------------------------------------

def test_negative_rate_for_declining_pr():
    """A steadily declining PR series must produce a negative rate_pct_per_year."""
    n = 90
    # PR drops linearly from 1.0 to 0.8 over 90 days
    values = list(np.linspace(1.0, 0.8, n))
    series = _daily_series(values)

    result = _compute_degradation(series, _START, _end(n))

    assert result["rate_pct_per_year"] is not None
    assert result["rate_pct_per_year"] < 0.0, (
        f"Expected negative rate, got {result['rate_pct_per_year']}"
    )
    assert result["confidence"] == "medium"


def test_steeply_declining_pr_has_high_r_squared():
    """A perfectly linear decline must produce r_squared close to 1.0."""
    n = 180
    values = list(np.linspace(0.95, 0.70, n))
    series = _daily_series(values)

    result = _compute_degradation(series, _START, _end(n))

    assert result["r_squared"] == pytest.approx(1.0, abs=1e-3)
    assert result["confidence"] == "high"


# ---------------------------------------------------------------------------
# Test 2 — Flat series produces rate close to 0
# ---------------------------------------------------------------------------

def test_flat_series_rate_near_zero():
    """A constant PR series must produce rate_pct_per_year ≈ 0."""
    n = 60
    values = [0.85] * n
    series = _daily_series(values)

    result = _compute_degradation(series, _START, _end(n))

    assert result["rate_pct_per_year"] == pytest.approx(0.0, abs=0.01)
    assert result["confidence"] == "low"


# ---------------------------------------------------------------------------
# Test 3 — Fewer than 30 days returns None
# ---------------------------------------------------------------------------

def test_fewer_than_30_days_returns_none():
    """With < 30 daily PR values, all metrics must be None."""
    n = 15
    values = list(np.linspace(0.90, 0.85, n))
    series = _daily_series(values)

    result = _compute_degradation(series, _START, _end(n))

    assert result["rate_pct_per_year"] is None
    assert result["r_squared"] is None
    assert result["confidence"] is None
    assert result["first_pr"] is None
    assert result["last_pr"] is None


def test_empty_series_returns_none():
    """Empty daily PR series must return all None without raising."""
    series = pd.Series(dtype=float)

    result = _compute_degradation(series, _START, _end(0))

    assert result["rate_pct_per_year"] is None
    assert result["window_days"] == 0


# ---------------------------------------------------------------------------
# Test 4 — first_pr and last_pr correct
# ---------------------------------------------------------------------------

def test_first_and_last_pr_correct():
    """first_pr and last_pr must match the actual first and last series values."""
    n = 90
    values = list(np.linspace(0.92, 0.88, n))
    series = _daily_series(values)

    result = _compute_degradation(series, _START, _end(n))

    assert result["first_pr"] == pytest.approx(0.92, rel=1e-3)
    assert result["last_pr"] == pytest.approx(0.88, rel=1e-3)


# ---------------------------------------------------------------------------
# Test 5 — Confidence thresholds
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n_days,expected_confidence", [
    (180, "high"),
    (90,  "medium"),
    (30,  "low"),
    (29,  None),
])
def test_confidence_thresholds(n_days, expected_confidence):
    """Confidence level must match window_days thresholds."""
    values = [0.85] * n_days
    series = _daily_series(values)

    result = _compute_degradation(series, _START, _end(n_days))

    assert result["confidence"] == expected_confidence
