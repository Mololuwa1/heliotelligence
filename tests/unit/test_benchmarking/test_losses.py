"""Unit tests for heliotelligence.benchmarking.losses.

Tests
-----
1. All returned loss buckets are non-negative floats (given underperforming plant)
2. Buckets sum to (E_exp_stc - E_actual) / E_exp_stc × 100 within 2 %
3. unaccounted_pct is present in the result dict
4. When expected_df is empty, result contains all None buckets
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from heliotelligence.benchmarking.losses import _compute_losses
from heliotelligence.config.site import InverterConfig, ModuleConfig, SiteConfig

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_START = datetime(2024, 6, 21, 0, tzinfo=timezone.utc)
_END = datetime(2024, 6, 21, 4, tzinfo=timezone.utc)


def _idx(n: int = 4) -> pd.DatetimeIndex:
    return pd.date_range("2024-06-21 00:00", periods=n, freq="h", tz="UTC")


def _site(
    soiling: float = 2.0,
    lid: float = 1.0,
    wiring_dc: float = 0.5,
    mismatch: float = 1.0,
    eta_nom: float = 0.95,
    wiring_ac: float = 0.5,
    pnom_kwac: float = 10_000.0,  # large → no clipping
) -> SiteConfig:
    return SiteConfig(
        id="test-losses",
        name="Losses Test",
        latitude=52.0,
        longitude=1.0,
        timezone="UTC",
        capacity_kwp=100.0,
        solcast_resource_id="x",
        module=ModuleConfig(
            soiling_loss_pct=soiling,
            lid_loss_pct=lid,
            wiring_loss_dc_pct=wiring_dc,
            mismatch_loss_pct=mismatch,
        ),
        inverter=InverterConfig(
            pvlib_model="pvwatts",
            eta_nom=eta_nom,
            wiring_loss_ac_pct=wiring_ac,
            pnom_kwac=pnom_kwac,
            num_units=1,
            grid_limit_kwac=None,
        ),
    )


def _expected_df(
    p_dc_stc_kw: float = 25.0,
    p_dc_kw: float = 23.5,
    p_ac_kw: float = 22.5,
    t_cell_c: float = 45.0,
    n: int = 4,
) -> pd.DataFrame:
    """
    Default values give (4-hour window, 1-h intervals):
      E_exp_stc = 100 kWh
      E_exp_dc  =  94 kWh  (DC gap = 6 %)
      E_exp_ac  =  90 kWh  (inv+clip gap = 4 %)
      t_cell_c  =  45 °C  → temperature_pct = 0.29 × (45-25) = 5.8 %
    """
    idx = _idx(n)
    return pd.DataFrame(
        {
            "p_dc_stc_kw": [p_dc_stc_kw] * n,
            "p_dc_kw": [p_dc_kw] * n,
            "p_ac_kw": [p_ac_kw] * n,
            "t_cell_c": [t_cell_c] * n,
        },
        index=idx,
    )


def _meter_df(e_exported_kwh: float = 22.0, n: int = 4) -> pd.DataFrame:
    """E_actual = e_exported_kwh × n  (default: 88 kWh for 4 rows)."""
    idx = _idx(n)
    return pd.DataFrame(
        {"p_ac_kw": [np.nan] * n, "e_exported_kwh": [e_exported_kwh] * n},
        index=idx,
    )


# ---------------------------------------------------------------------------
# Test 1 — All loss buckets are non-negative floats
# ---------------------------------------------------------------------------

def test_all_buckets_non_negative():
    """Every numeric loss bucket must be >= 0 when the plant underperforms."""
    exp_df = _expected_df()
    met_df = _meter_df()
    site = _site()

    result = _compute_losses(exp_df, met_df, site, 100.0, _START, _END)

    float_buckets = [
        "optical_pct", "temperature_pct", "dc_losses_pct",
        "inverter_pct", "clipping_pct", "availability_pct",
    ]
    for key in float_buckets:
        val = result[key]
        assert val is not None, f"{key} must not be None when site config is provided"
        assert val >= 0.0, f"{key} = {val} must be >= 0"


# ---------------------------------------------------------------------------
# Test 2 — Buckets sum to total gap within 2 %
# ---------------------------------------------------------------------------

def test_buckets_sum_to_total_gap():
    """Sum of all loss buckets must equal (E_exp_stc - E_actual) / E_exp_stc × 100 ± 2."""
    exp_df = _expected_df()   # E_exp_stc=100, E_exp_ac=90
    met_df = _meter_df(e_exported_kwh=22.0)  # E_actual = 88 kWh
    site = _site()
    availability_level_pct = 100.0  # no availability loss

    result = _compute_losses(exp_df, met_df, site, availability_level_pct, _START, _END)

    total_gap_pct = (
        (result["e_exp_stc_kwh"] - result["e_actual_kwh"])
        / result["e_exp_stc_kwh"]
        * 100.0
    )

    bucket_keys = [
        "optical_pct", "temperature_pct", "dc_losses_pct",
        "inverter_pct", "clipping_pct", "availability_pct", "unaccounted_pct",
    ]
    bucket_sum = sum(result[k] for k in bucket_keys if result[k] is not None)

    assert bucket_sum == pytest.approx(total_gap_pct, abs=2.0), (
        f"Bucket sum {bucket_sum:.3f}% != total gap {total_gap_pct:.3f}%"
    )


# ---------------------------------------------------------------------------
# Test 3 — unaccounted_pct is present and not named as a known cause
# ---------------------------------------------------------------------------

def test_unaccounted_pct_present():
    """unaccounted_pct must be a key in the result dict."""
    exp_df = _expected_df()
    met_df = _meter_df()
    site = _site()

    result = _compute_losses(exp_df, met_df, site, 100.0, _START, _END)

    assert "unaccounted_pct" in result, "unaccounted_pct key must be in result"
    # Must not be labelled as a known cause (soiling, temperature, etc.)
    # This is a structural check: the key exists and is separate from named buckets.
    named_buckets = {
        "optical_pct", "temperature_pct", "dc_losses_pct",
        "inverter_pct", "clipping_pct", "availability_pct",
    }
    assert "unaccounted_pct" not in named_buckets


# ---------------------------------------------------------------------------
# Test 4 — Empty expected_df returns all-None buckets
# ---------------------------------------------------------------------------

def test_empty_expected_returns_none_buckets():
    """When expected_df is empty, all loss buckets must be None."""
    exp_df = pd.DataFrame(columns=["p_dc_stc_kw", "p_dc_kw", "p_ac_kw", "t_cell_c"])
    met_df = _meter_df()
    site = _site()

    result = _compute_losses(exp_df, met_df, site, 100.0, _START, _END)

    for key in ["optical_pct", "temperature_pct", "dc_losses_pct",
                "inverter_pct", "clipping_pct", "availability_pct", "unaccounted_pct"]:
        assert result[key] is None, f"{key} should be None for empty input"

    assert result["e_exp_stc_kwh"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Test 5 — No site config → config-based buckets are None
# ---------------------------------------------------------------------------

def test_no_site_config_gives_partial_result():
    """When site config is None, config-based buckets must be None; inverter_pct non-None."""
    exp_df = _expected_df()
    met_df = _meter_df()

    result = _compute_losses(exp_df, met_df, None, 100.0, _START, _END)

    assert result["optical_pct"] is None
    assert result["dc_losses_pct"] is None
    assert result["clipping_pct"] is None
    # inverter_pct should still be computable from data alone
    assert result["inverter_pct"] is not None
    assert result["inverter_pct"] >= 0.0
