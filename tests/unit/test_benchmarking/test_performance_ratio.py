"""Unit tests for heliotelligence.benchmarking.performance_ratio.

Tests
-----
1. PR = 1.0 when E_actual == E_expected
2. PR < 1.0 when E_actual < E_expected
3. PR = None when coverage < 10 %
4. e_actual_kwh computed from e_exported_kwh when available (not p_ac_kw)
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from heliotelligence.benchmarking.performance_ratio import _compute_pr

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_START = datetime(2024, 6, 21, 10, tzinfo=timezone.utc)
_END = datetime(2024, 6, 21, 14, tzinfo=timezone.utc)  # 4-hour window


def _idx(n: int = 4, start: str = "2024-06-21 10:00") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="h", tz="UTC")


def _expected(p_ac_kw: float = 100.0, n: int = 4) -> pd.DataFrame:
    """Hourly expected_energy DataFrame: n rows × p_ac_kw kW each = n×p_ac_kw kWh."""
    idx = _idx(n)
    return pd.DataFrame({"p_ac_kw": [p_ac_kw] * n}, index=idx)


def _meter(
    p_ac_kw: float | None = None,
    e_exported_kwh: float | None = None,
    n: int = 4,
) -> pd.DataFrame:
    """Hourly meter_readings DataFrame."""
    idx = _idx(n)
    return pd.DataFrame(
        {
            "p_ac_kw": [p_ac_kw] * n,
            "e_exported_kwh": [e_exported_kwh] * n,
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# Test 1 — PR = 1.0 when E_actual == E_expected
# ---------------------------------------------------------------------------

def test_pr_equals_one_when_actual_matches_expected():
    """PR must be 1.0 when E_actual == E_expected."""
    # E_expected = 4 × 100 kW × 1 h = 400 kWh
    # E_actual   = 4 × 100 kWh (via e_exported_kwh) = 400 kWh
    exp_df = _expected(p_ac_kw=100.0)
    met_df = _meter(p_ac_kw=np.nan, e_exported_kwh=100.0)

    result = _compute_pr(exp_df, met_df, _START, _END)

    assert result["pr"] == pytest.approx(1.0, rel=1e-4)
    assert result["e_actual_kwh"] == pytest.approx(400.0)
    assert result["e_expected_kwh"] == pytest.approx(400.0)
    assert result["coverage_pct"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Test 2 — PR < 1.0 when E_actual < E_expected
# ---------------------------------------------------------------------------

def test_pr_less_than_one_when_actual_below_expected():
    """PR must be < 1.0 and correctly scaled when plant underperforms."""
    # E_expected = 400 kWh; E_actual = 320 kWh → PR = 0.80
    exp_df = _expected(p_ac_kw=100.0)
    met_df = _meter(p_ac_kw=np.nan, e_exported_kwh=80.0)

    result = _compute_pr(exp_df, met_df, _START, _END)

    assert result["pr"] == pytest.approx(0.8, rel=1e-4)
    assert result["e_actual_kwh"] == pytest.approx(320.0)
    assert result["pr"] < 1.0


# ---------------------------------------------------------------------------
# Test 3 — PR = None when coverage < 10 %
# ---------------------------------------------------------------------------

def test_pr_is_none_when_coverage_below_threshold():
    """PR must be None when fewer than 10 % of expected timestamps have actual data."""
    # 100 expected timestamps; only 5 have meter data → 5 % coverage
    idx_exp = pd.date_range("2024-06-21", periods=100, freq="h", tz="UTC")
    exp_df = pd.DataFrame({"p_ac_kw": [100.0] * 100}, index=idx_exp)

    # Meter data for only the first 5 timestamps
    idx_met = idx_exp[:5]
    met_df = pd.DataFrame(
        {"p_ac_kw": [np.nan] * 5, "e_exported_kwh": [100.0] * 5},
        index=idx_met,
    )

    start = idx_exp[0].to_pydatetime()
    end = (idx_exp[-1] + pd.Timedelta(hours=1)).to_pydatetime()
    result = _compute_pr(exp_df, met_df, start, end)

    assert result["pr"] is None
    assert result["coverage_pct"] == pytest.approx(5.0)


def test_pr_is_none_when_meter_empty():
    """PR must be None when meter_readings returns no rows."""
    exp_df = _expected(p_ac_kw=100.0)
    met_df = pd.DataFrame(columns=["p_ac_kw", "e_exported_kwh"])

    result = _compute_pr(exp_df, met_df, _START, _END)

    assert result["pr"] is None
    assert result["coverage_pct"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Test 4 — e_actual_kwh uses e_exported_kwh, not p_ac_kw
# ---------------------------------------------------------------------------

def test_e_actual_prefers_e_exported_kwh():
    """E_actual must come from e_exported_kwh, ignoring p_ac_kw when both present."""
    # e_exported_kwh = 95 kWh; p_ac_kw = 90 kW → should use 95, not 90
    exp_df = _expected(p_ac_kw=100.0)
    met_df = _meter(p_ac_kw=90.0, e_exported_kwh=95.0)

    result = _compute_pr(exp_df, met_df, _START, _END)

    # E_actual = 4 × 95 = 380 kWh (not 4 × 90 = 360 kWh)
    assert result["e_actual_kwh"] == pytest.approx(380.0)
    assert result["pr"] == pytest.approx(380.0 / 400.0, rel=1e-4)


def test_e_actual_falls_back_to_p_ac_kw_when_no_exported():
    """When e_exported_kwh is NULL, integrate p_ac_kw × interval_h instead."""
    exp_df = _expected(p_ac_kw=100.0)
    # e_exported_kwh all NULL, p_ac_kw = 80 kW, intervals = 1 h
    met_df = _meter(p_ac_kw=80.0, e_exported_kwh=np.nan)

    result = _compute_pr(exp_df, met_df, _START, _END)

    # E_actual = 4 × 80 kW × 1 h = 320 kWh
    assert result["e_actual_kwh"] == pytest.approx(320.0)


# ---------------------------------------------------------------------------
# Test 5 — Empty expected_energy
# ---------------------------------------------------------------------------

def test_empty_expected_returns_null_pr():
    """Empty expected_df must return PR=None without raising."""
    exp_df = pd.DataFrame(columns=["p_ac_kw"])
    met_df = _meter(e_exported_kwh=100.0)

    result = _compute_pr(exp_df, met_df, _START, _END)

    assert result["pr"] is None
    assert result["e_expected_kwh"] == pytest.approx(0.0)
