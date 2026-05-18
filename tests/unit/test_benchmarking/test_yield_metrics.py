"""Unit tests for heliotelligence.benchmarking.yield_metrics.

Tests
-----
1. specific_yield = e_actual_kwh / capacity_kwp
2. capacity_factor_pct in [0, 100] for a 24-hour window
3. hours_in_window correct for a 24-hour window
4. None metrics when capacity_kwp is None
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from heliotelligence.benchmarking.yield_metrics import _compute_yield

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_START_24H = datetime(2024, 6, 21, 0, tzinfo=timezone.utc)
_END_24H = datetime(2024, 6, 22, 0, tzinfo=timezone.utc)  # exactly 24 hours


# ---------------------------------------------------------------------------
# Test 1 — specific_yield = e_actual_kwh / capacity_kwp
# ---------------------------------------------------------------------------

def test_specific_yield_formula():
    """specific_yield_kwh_kwp = e_actual_kwh / capacity_kwp."""
    e_actual = 5000.0
    capacity = 28524.0

    result = _compute_yield(e_actual, capacity, _START_24H, _END_24H)

    expected_sy = e_actual / capacity
    assert result["specific_yield_kwh_kwp"] == pytest.approx(expected_sy, rel=1e-4)


# ---------------------------------------------------------------------------
# Test 2 — capacity_factor_pct in [0, 100] for 24-hour window
# ---------------------------------------------------------------------------

def test_capacity_factor_in_bounds():
    """capacity_factor_pct must be in [0, 100] for any realistic input."""
    # 28524 kWp × 24 h = 684576 kWh at 100% CF → use realistic value
    e_actual = 100_000.0  # 100 MWh in 24 h for ~28.5 MWp → CF ≈ 14.6%
    capacity = 28524.0

    result = _compute_yield(e_actual, capacity, _START_24H, _END_24H)

    cf = result["capacity_factor_pct"]
    assert cf is not None
    assert 0.0 <= cf <= 100.0, f"capacity_factor_pct={cf} out of [0, 100]"


def test_capacity_factor_value():
    """capacity_factor_pct = e_actual / (capacity × hours) × 100."""
    capacity = 100.0   # kWp
    hours = 24.0
    # If e_actual = 50% of maximum possible → CF = 50%
    e_actual = capacity * hours * 0.50   # = 1200 kWh

    result = _compute_yield(e_actual, capacity, _START_24H, _END_24H)

    assert result["capacity_factor_pct"] == pytest.approx(50.0, rel=1e-4)


# ---------------------------------------------------------------------------
# Test 3 — hours_in_window correct for 24-hour window
# ---------------------------------------------------------------------------

def test_hours_in_window_24h():
    """hours_in_window must be 24.0 for a midnight-to-midnight window."""
    result = _compute_yield(0.0, 100.0, _START_24H, _END_24H)

    assert result["hours_in_window"] == pytest.approx(24.0)


def test_hours_in_window_arbitrary():
    """hours_in_window must equal the exact difference in hours."""
    start = datetime(2024, 6, 21, 6, tzinfo=timezone.utc)
    end = datetime(2024, 6, 21, 18, tzinfo=timezone.utc)  # 12 hours

    result = _compute_yield(0.0, 100.0, start, end)

    assert result["hours_in_window"] == pytest.approx(12.0)


# ---------------------------------------------------------------------------
# Test 4 — None metrics when capacity_kwp is None
# ---------------------------------------------------------------------------

def test_none_when_capacity_unknown():
    """specific_yield and capacity_factor must be None when capacity_kwp is None."""
    result = _compute_yield(1000.0, None, _START_24H, _END_24H)

    assert result["specific_yield_kwh_kwp"] is None
    assert result["capacity_factor_pct"] is None


def test_none_when_capacity_zero():
    """specific_yield and capacity_factor must be None when capacity_kwp = 0."""
    result = _compute_yield(1000.0, 0.0, _START_24H, _END_24H)

    assert result["specific_yield_kwh_kwp"] is None
    assert result["capacity_factor_pct"] is None


# ---------------------------------------------------------------------------
# Test 5 — e_actual_kwh and target_specific_yield pass through correctly
# ---------------------------------------------------------------------------

def test_e_actual_and_target_passthrough():
    """e_actual_kwh must match input; target_specific_yield must be None (reserved)."""
    e_actual = 12345.678
    result = _compute_yield(e_actual, 100.0, _START_24H, _END_24H)

    assert result["e_actual_kwh"] == pytest.approx(12345.678, rel=1e-5)
    assert result["target_specific_yield_kwh_kwp"] is None
