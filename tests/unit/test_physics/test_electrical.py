"""Unit tests for heliotelligence.physics.electrical.

Tests
-----
1. At STC (1000 W/m², 25 °C), output is within 2% of pnom_wp * n_modules (gross)
2. Loss cascade reduces power: with all losses set to 1%, output < gross DC
3. Non-c-Si technology flag logs a WARNING
4. tier_used and fit_quality columns exist in output DataFrame
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from heliotelligence.config.site import InverterConfig, ModuleConfig, SiteConfig
from heliotelligence.physics.electrical import calculate_dc_power

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _stc_series(value: float, n: int = 1) -> pd.Series:
    """Return a constant pd.Series with a UTC DatetimeIndex."""
    idx = pd.date_range("2024-06-21 12:00", periods=n, freq="h", tz="UTC")
    return pd.Series(value, index=idx)


def _bracon_ash_site(
    *,
    soiling: float = 0.0,
    lid: float = 0.0,
    mismatch: float = 0.0,
    wiring: float = 0.0,
    technology: str = "mono_si",
) -> SiteConfig:
    """Return a minimal Bracon Ash SiteConfig for testing."""
    return SiteConfig(
        id="test-001",
        name="Test Site",
        latitude=52.56,
        longitude=1.21,
        timezone="Europe/London",
        capacity_kwp=28524.0,
        solcast_resource_id="test",
        module=ModuleConfig(
            local_module_name="JKM570N-72HL4-BDV",
            technology=technology,
            soiling_loss_pct=soiling,
            lid_loss_pct=lid,
            mismatch_loss_pct=mismatch,
            wiring_loss_dc_pct=wiring,
            modules_per_string=24,
            num_strings=2076,
        ),
        inverter=InverterConfig(pvlib_model="pvwatts"),
    )


# ---------------------------------------------------------------------------
# Test 1 — STC output within 2% of nameplate
# ---------------------------------------------------------------------------

def test_stc_output_within_2pct_of_nameplate():
    """At STC conditions, gross DC output should be within 2% of rated power.

    Gross = pnom_wp * num_strings * modules_per_string (losses zeroed out).
    The SDM (tier 3 via local library) is used; STC output is compared to
    the pnom_wp sum at the module level.
    """
    site = _bracon_ash_site()  # all losses = 0.0

    poa = _stc_series(1000.0)
    t_cell = _stc_series(25.0)
    aoi = _stc_series(0.0)

    result = calculate_dc_power(site, poa, t_cell, aoi)

    n_modules = site.module.num_strings * site.module.modules_per_string  # 24 * 2076
    pnom_wp = 570.0  # from local library JKM570N-72HL4-BDV
    expected_kw = pnom_wp * n_modules / 1000.0

    # p_dc_kw should be within 2% of rated — the SDM at STC is very close
    # to nameplate but may differ slightly due to fitting tolerance.
    actual_kw = float(result["p_dc_kw"].iloc[0])
    assert abs(actual_kw - expected_kw) / expected_kw < 0.02, (
        f"STC output {actual_kw:.1f} kW is >2% from nameplate {expected_kw:.1f} kW"
    )


# ---------------------------------------------------------------------------
# Test 2 — Loss cascade reduces output
# ---------------------------------------------------------------------------

def test_loss_cascade_reduces_power():
    """Enabling losses should reduce p_dc_kw compared to zero-loss baseline."""
    site_lossless = _bracon_ash_site(soiling=0.0, lid=0.0, mismatch=0.0, wiring=0.0)
    site_lossy = _bracon_ash_site(soiling=1.0, lid=1.0, mismatch=1.0, wiring=1.0)

    poa = _stc_series(800.0)
    t_cell = _stc_series(40.0)
    aoi = _stc_series(10.0)

    result_lossless = calculate_dc_power(site_lossless, poa, t_cell, aoi)
    result_lossy = calculate_dc_power(site_lossy, poa, t_cell, aoi)

    p_lossless = float(result_lossless["p_dc_kw"].iloc[0])
    p_lossy = float(result_lossy["p_dc_kw"].iloc[0])

    assert p_lossy < p_lossless, (
        "Applying losses should reduce p_dc_kw, but lossy output "
        f"({p_lossy:.2f}) >= lossless ({p_lossless:.2f})"
    )
    # 4 × 1% losses compound to ≈3.96% reduction
    expected_reduction = 1.0 - (0.99 ** 4)
    actual_reduction = (p_lossless - p_lossy) / p_lossless
    assert abs(actual_reduction - expected_reduction) < 0.005, (
        f"Loss cascade reduction {actual_reduction:.4f} differs from "
        f"expected {expected_reduction:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 3 — Non-c-Si technology logs WARNING
# ---------------------------------------------------------------------------

def test_non_csi_technology_logs_warning(caplog):
    """CdTe or CIGS technology should trigger an SDM accuracy WARNING."""
    site = SiteConfig(
        id="test-cdte",
        name="CdTe Test",
        latitude=52.56,
        longitude=1.21,
        timezone="Europe/London",
        capacity_kwp=1000.0,
        solcast_resource_id="test",
        module=ModuleConfig(
            technology="cdte",
            pnom_wp=430.0,
            gamma_pmp=-0.32,
        ),
        inverter=InverterConfig(),
    )

    poa = _stc_series(600.0)
    t_cell = _stc_series(35.0)
    aoi = _stc_series(5.0)

    with caplog.at_level(logging.WARNING, logger="heliotelligence.physics.electrical"):
        calculate_dc_power(site, poa, t_cell, aoi)

    warning_messages = " ".join(caplog.messages)
    assert "Non c-Si" in warning_messages or "non c-si" in warning_messages.lower(), (
        "Non c-Si technology should log a WARNING about reduced SDM accuracy"
    )


# ---------------------------------------------------------------------------
# Test 4 — Output DataFrame has required columns
# ---------------------------------------------------------------------------

def test_output_dataframe_has_required_columns():
    """Result DataFrame must contain tier_used and fit_quality columns."""
    site = _bracon_ash_site()
    poa = _stc_series(900.0)
    t_cell = _stc_series(30.0)
    aoi = _stc_series(8.0)

    result = calculate_dc_power(site, poa, t_cell, aoi)

    for col in ("p_dc_kw", "p_dc_stc_kw", "v_mp", "i_mp", "tier_used", "fit_quality"):
        assert col in result.columns, f"Column '{col}' missing from calculate_dc_power output"

    import numpy as np
    assert isinstance(result["tier_used"].iloc[0], (int, float, np.integer, np.floating))
    assert isinstance(result["fit_quality"].iloc[0], str)
