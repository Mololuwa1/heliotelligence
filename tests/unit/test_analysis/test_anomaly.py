"""Unit tests for heliotelligence.analysis.anomaly.

Tests
-----
1. Timestamps beyond threshold_sigma flagged correctly
2. Timestamps within normal range not flagged
3. Nighttime rows (expected < 1.0 kW) not flagged even if residual is large
4. Empty input returns flagged_count=0
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from heliotelligence.analysis.anomaly import _compute_anomalies

_START = datetime(2024, 6, 21, 0, tzinfo=timezone.utc)
_END = datetime(2024, 6, 22, 0, tzinfo=timezone.utc)


def _idx(n: int = 24) -> pd.DatetimeIndex:
    return pd.date_range("2024-06-21 00:00", periods=n, freq="h", tz="UTC")


def _joined(
    actual_kw: list[float],
    expected_kw: list[float],
) -> pd.DataFrame:
    idx = _idx(len(actual_kw))
    return pd.DataFrame(
        {"actual_kw": actual_kw, "expected_kw": expected_kw},
        index=idx,
    )


# ---------------------------------------------------------------------------
# Test 1 — Outliers beyond threshold are flagged
# ---------------------------------------------------------------------------

def test_outlier_timestamps_flagged():
    """Timestamps with |residual| > 2σ must appear in flags."""
    # 23 normal daytime rows + 1 large outlier
    actual = [100.0] * 23 + [50.0]   # last row is a large drop
    expected = [100.0] * 24
    joined = _joined(actual, expected)

    result = _compute_anomalies(joined, threshold_sigma=2.0,
                                start=_START, end=_END)

    assert result["flagged_count"] >= 1
    # The outlier at position 23 should be in flags
    flag_times = [f["time"] for f in result["flags"]]
    assert joined.index[23] in flag_times


# ---------------------------------------------------------------------------
# Test 2 — Normal rows not flagged
# ---------------------------------------------------------------------------

def test_normal_rows_not_flagged():
    """When all residuals are within threshold, flagged_count must be 0."""
    # Uniform 100 kW actual and expected — zero residual
    actual = [100.0] * 24
    expected = [100.0] * 24
    joined = _joined(actual, expected)

    result = _compute_anomalies(joined, threshold_sigma=2.0,
                                start=_START, end=_END)

    assert result["flagged_count"] == 0
    assert result["flags"] == []


def test_small_residuals_not_flagged():
    """Residuals within 2σ must not be flagged."""
    # All rows at 100 kW expected; actual varies ±2 kW — well within any σ
    np.random.seed(42)
    actual = (100.0 + np.random.uniform(-2, 2, 24)).tolist()
    expected = [100.0] * 24
    joined = _joined(actual, expected)

    result = _compute_anomalies(joined, threshold_sigma=2.0,
                                start=_START, end=_END)

    assert result["flagged_count"] == 0


# ---------------------------------------------------------------------------
# Test 3 — Nighttime rows not flagged
# ---------------------------------------------------------------------------

def test_nighttime_rows_not_flagged():
    """Rows with expected_kw < 1.0 must not be flagged even with large residuals."""
    # Nighttime: expected = 0 kW, actual = 50 kW (huge residual)
    actual = [50.0] * 24
    expected = [0.0] * 24   # all nighttime
    joined = _joined(actual, expected)

    result = _compute_anomalies(joined, threshold_sigma=2.0,
                                start=_START, end=_END)

    assert result["flagged_count"] == 0
    assert result["total_count"] == 0  # no daytime rows


def test_mixed_day_night_only_daytime_flagged():
    """Only daytime rows (expected > 1 kW) can be flagged."""
    # 12 nighttime rows (expected=0) + 12 daytime rows (expected=100)
    # Daytime actual = 100 except last one = 10 (big drop)
    actual = [0.0] * 12 + [100.0] * 11 + [10.0]
    expected = [0.0] * 12 + [100.0] * 12
    joined = _joined(actual, expected)

    result = _compute_anomalies(joined, threshold_sigma=2.0,
                                start=_START, end=_END)

    # Nighttime rows must not be in flags
    for flag in result["flags"]:
        ts = flag["time"]
        assert joined.loc[ts, "expected_kw"] > 1.0, (
            f"Nighttime row flagged at {ts}"
        )


# ---------------------------------------------------------------------------
# Test 4 — Empty input
# ---------------------------------------------------------------------------

def test_empty_input_returns_zero_flags():
    """Empty joined DataFrame must return flagged_count=0 without raising."""
    joined = pd.DataFrame(columns=["actual_kw", "expected_kw"])

    result = _compute_anomalies(joined, threshold_sigma=2.0,
                                start=_START, end=_END)

    assert result["flagged_count"] == 0
    assert result["total_count"] == 0
    assert result["flags"] == []


# ---------------------------------------------------------------------------
# Test 5 — flag dict has required keys
# ---------------------------------------------------------------------------

def test_flag_dict_has_required_keys():
    """Each flag dict must contain time, actual_kw, expected_kw, residual_kw, sigma."""
    actual = [100.0] * 23 + [10.0]
    expected = [100.0] * 24
    joined = _joined(actual, expected)

    result = _compute_anomalies(joined, threshold_sigma=2.0,
                                start=_START, end=_END)

    assert result["flagged_count"] >= 1
    for flag in result["flags"]:
        for key in ("time", "actual_kw", "expected_kw", "residual_kw", "sigma"):
            assert key in flag, f"Key '{key}' missing from flag dict"
