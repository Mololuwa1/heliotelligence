"""Unit tests for heliotelligence.analysis.string_health.

Tests
-----
1. String significantly below inverter mean is flagged
2. String within normal range not flagged
3. Single-string inverter returns no flags (no peer comparison)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from heliotelligence.analysis.string_health import _compute_string_health

_START = datetime(2024, 6, 21, 0, tzinfo=timezone.utc)
_END = datetime(2024, 6, 22, 0, tzinfo=timezone.utc)


def _df(rows: list[tuple]) -> pd.DataFrame:
    """Build a string_readings DataFrame from (inverter_id, string_id, current) rows.

    Uses a single shared timestamp so mean current == per-row current.
    """
    idx = pd.DatetimeIndex(
        [pd.Timestamp("2024-06-21 12:00", tz="UTC")] * len(rows)
    )
    data = {
        "inverter_id": [r[0] for r in rows],
        "string_id": [r[1] for r in rows],
        "str_current_a": [r[2] for r in rows],
    }
    return pd.DataFrame(data, index=idx)


# ---------------------------------------------------------------------------
# Test 1 — Under-performing string is flagged
# ---------------------------------------------------------------------------

def test_weak_string_flagged():
    """A string 3σ below the inverter mean must appear in flagged_strings."""
    # inv01: strings A-E at 10A, string F at 1A (clearly weak)
    rows = [
        ("inv01", "A", 10.0),
        ("inv01", "B", 10.0),
        ("inv01", "C", 10.0),
        ("inv01", "D", 10.0),
        ("inv01", "E", 10.0),
        ("inv01", "F", 1.0),   # weak
    ]
    df = _df(rows)

    result = _compute_string_health(df, threshold_sigma=2.0,
                                    start=_START, end=_END)

    flagged_ids = [f["string_id"] for f in result["flagged_strings"]]
    assert "F" in flagged_ids, "Weak string F must be flagged"
    assert result["inverter_count"] == 1
    assert result["string_count"] == 6


def test_flagged_string_has_correct_inverter_id():
    """Flagged string must reference the correct inverter_id."""
    # Five strings at 10A, one at 1A — deviation ≈ (9.17-1)/1.63 ≈ 5σ
    rows = [
        ("inv02", "A", 10.0),
        ("inv02", "B", 10.0),
        ("inv02", "C", 10.0),
        ("inv02", "D", 10.0),
        ("inv02", "E", 10.0),
        ("inv02", "F", 1.0),   # clearly weak
    ]
    df = _df(rows)

    result = _compute_string_health(df, threshold_sigma=2.0,
                                    start=_START, end=_END)

    assert len(result["flagged_strings"]) >= 1
    for flag in result["flagged_strings"]:
        assert flag["inverter_id"] == "inv02"


# ---------------------------------------------------------------------------
# Test 2 — Healthy strings not flagged
# ---------------------------------------------------------------------------

def test_uniform_strings_not_flagged():
    """When all strings have identical current, flagged_strings must be empty."""
    rows = [
        ("inv01", "A", 10.0),
        ("inv01", "B", 10.0),
        ("inv01", "C", 10.0),
        ("inv01", "D", 10.0),
    ]
    df = _df(rows)

    result = _compute_string_health(df, threshold_sigma=2.0,
                                    start=_START, end=_END)

    assert result["flagged_strings"] == []


def test_small_spread_not_flagged():
    """Strings within 2σ must not be flagged."""
    # Currents clustered between 9.5 and 10.5 A — tight spread
    rows = [
        ("inv01", "A", 10.5),
        ("inv01", "B", 10.2),
        ("inv01", "C", 9.8),
        ("inv01", "D", 9.5),
    ]
    df = _df(rows)

    result = _compute_string_health(df, threshold_sigma=2.0,
                                    start=_START, end=_END)

    assert result["flagged_strings"] == []


# ---------------------------------------------------------------------------
# Test 3 — Single-string inverter returns no flags
# ---------------------------------------------------------------------------

def test_single_string_inverter_no_flags():
    """An inverter with only one string must produce no flags (no peer comparison)."""
    rows = [("inv01", "A", 5.0)]
    df = _df(rows)

    result = _compute_string_health(df, threshold_sigma=2.0,
                                    start=_START, end=_END)

    assert result["flagged_strings"] == []
    assert result["string_count"] == 1


# ---------------------------------------------------------------------------
# Test 4 — Empty DataFrame
# ---------------------------------------------------------------------------

def test_empty_df_returns_empty_result():
    """Empty DataFrame must return zero counts and empty flags without raising."""
    df = pd.DataFrame(columns=["inverter_id", "string_id", "str_current_a"])

    result = _compute_string_health(df, threshold_sigma=2.0,
                                    start=_START, end=_END)

    assert result["inverter_count"] == 0
    assert result["string_count"] == 0
    assert result["flagged_strings"] == []


# ---------------------------------------------------------------------------
# Test 5 — Flag dict has required keys
# ---------------------------------------------------------------------------

def test_flag_dict_has_required_keys():
    """Each flagged string dict must contain all required keys."""
    rows = [
        ("inv01", "A", 10.0),
        ("inv01", "B", 10.0),
        ("inv01", "C", 1.0),
    ]
    df = _df(rows)

    result = _compute_string_health(df, threshold_sigma=2.0,
                                    start=_START, end=_END)

    for flag in result["flagged_strings"]:
        for key in ("inverter_id", "string_id", "mean_current_a",
                    "inverter_mean_a", "deviation_sigma"):
            assert key in flag, f"Key '{key}' missing from flag dict"
