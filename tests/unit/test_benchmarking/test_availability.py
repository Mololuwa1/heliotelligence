"""Unit tests for heliotelligence.benchmarking.availability.

Tests
-----
1. 100 % availability when all inverters report 100 %
2. 0 % availability when all inverters report 0 %
3. Weighted method used when site config provides pnom_kwac
4. Count-average method used when no site config
5. Empty DataFrame returns availability_pct = None
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from heliotelligence.benchmarking.availability import _compute_availability
from heliotelligence.config.site import InverterConfig, SiteConfig

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_START = datetime(2024, 6, 21, 0, tzinfo=timezone.utc)
_END = datetime(2024, 6, 21, 4, tzinfo=timezone.utc)


def _avail_df(
    avail_values: list[float],
    inverter_ids: list[str] | None = None,
) -> pd.DataFrame:
    n = len(avail_values)
    idx = pd.date_range("2024-06-21 00:00", periods=n, freq="h", tz="UTC")
    if inverter_ids is None:
        inverter_ids = ["inv01"] * n
    return pd.DataFrame(
        {"inverter_id": inverter_ids, "inv_avail_pct": avail_values},
        index=idx,
    )


def _site_with_capacity(pnom_kwac: float = 320.0) -> SiteConfig:
    return SiteConfig(
        id="test-avail",
        name="Avail Test",
        latitude=52.0,
        longitude=1.0,
        timezone="UTC",
        capacity_kwp=100.0,
        solcast_resource_id="x",
        inverter=InverterConfig(
            pvlib_model="pvwatts",
            pnom_kwac=pnom_kwac,
            num_units=1,
        ),
    )


# ---------------------------------------------------------------------------
# Test 1 — 100 % availability
# ---------------------------------------------------------------------------

def test_full_availability():
    """availability_pct must equal 100.0 when all inverters report 100 %."""
    df = _avail_df([100.0, 100.0, 100.0, 100.0])

    result = _compute_availability(df, None, _START, _END)

    assert result["availability_pct"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Test 2 — 0 % availability
# ---------------------------------------------------------------------------

def test_zero_availability():
    """availability_pct must equal 0.0 when all inverters report 0 %."""
    df = _avail_df([0.0, 0.0, 0.0, 0.0])

    result = _compute_availability(df, None, _START, _END)

    assert result["availability_pct"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Test 3 — Weighted method when pnom_kwac is set
# ---------------------------------------------------------------------------

def test_weighted_method_when_capacity_available():
    """method must be 'weighted_equal_capacity' when site.inverter.pnom_kwac is set."""
    site = _site_with_capacity(pnom_kwac=320.0)
    df = _avail_df([95.0, 97.0, 96.0, 98.0])

    result = _compute_availability(df, site, _START, _END)

    assert result["method"] == "weighted_equal_capacity"


def test_weighted_mean_equals_simple_mean_for_equal_capacity():
    """For equal-capacity inverters, weighted mean must equal simple mean."""
    # Two inverters, both with 4 readings
    site = _site_with_capacity(pnom_kwac=320.0)
    df = _avail_df(
        [100.0, 80.0, 100.0, 80.0],
        inverter_ids=["inv01", "inv01", "inv02", "inv02"],
    )
    # inv01 mean = 90%, inv02 mean = 90% → weighted = 90%

    result = _compute_availability(df, site, _START, _END)

    assert result["availability_pct"] == pytest.approx(90.0)
    assert result["inverter_count"] == 2


# ---------------------------------------------------------------------------
# Test 4 — Count-average when no site config
# ---------------------------------------------------------------------------

def test_count_average_when_no_site():
    """method must be 'count_average' when site is None."""
    df = _avail_df([80.0, 90.0, 100.0, 90.0])

    result = _compute_availability(df, None, _START, _END)

    assert result["method"] == "count_average"
    assert result["availability_pct"] == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# Test 5 — Empty DataFrame
# ---------------------------------------------------------------------------

def test_empty_df_returns_none():
    """Empty avail_df must return availability_pct = None without raising."""
    df = pd.DataFrame(columns=["inverter_id", "inv_avail_pct"])

    result = _compute_availability(df, None, _START, _END)

    assert result["availability_pct"] is None
    assert result["method"] == "no_data"
    assert result["inverter_count"] == 0


# ---------------------------------------------------------------------------
# Test 6 — Partial availability between 0 and 100
# ---------------------------------------------------------------------------

def test_partial_availability():
    """Verify correct mean for a mixed availability dataset."""
    df = _avail_df([100.0, 50.0, 100.0, 50.0])
    # mean = 75 %

    result = _compute_availability(df, None, _START, _END)

    assert result["availability_pct"] == pytest.approx(75.0)
