"""Unit tests for heliotelligence.engine.inverter.

Tests
-----
1. Clipping fires when p_dc exceeds inverter AC capacity
2. Grid limit curtailment caps output at grid_limit_kwac
3. AC wiring loss reduces output
4. No clipping when p_dc is below inverter capacity
"""

from __future__ import annotations

import pandas as pd
import pytest

from heliotelligence.config.site import InverterConfig, ModuleConfig, SiteConfig
from heliotelligence.engine.inverter import calculate_ac_power


def _series(value: float, n: int = 4) -> pd.Series:
    idx = pd.date_range("2024-06-21 10:00", periods=n, freq="h", tz="UTC")
    return pd.Series(value, index=idx)


def _site(
    eta_nom: float = 0.9842,
    pnom_kwac: float | None = 320.0,
    num_units: int = 1,
    grid_limit_kwac: float | None = None,
    wiring_loss_ac_pct: float = 0.0,
) -> SiteConfig:
    return SiteConfig(
        id="test-inv",
        name="Inverter Test",
        latitude=52.0,
        longitude=1.0,
        timezone="UTC",
        capacity_kwp=500.0,
        solcast_resource_id="x",
        inverter=InverterConfig(
            pvlib_model="pvwatts",
            eta_nom=eta_nom,
            pnom_kwac=pnom_kwac,
            num_units=num_units,
            grid_limit_kwac=grid_limit_kwac,
            wiring_loss_ac_pct=wiring_loss_ac_pct,
        ),
    )


# ---------------------------------------------------------------------------
# Test 1 — Clipping fires when p_dc > inverter capacity
# ---------------------------------------------------------------------------

def test_clipping_fires_when_above_capacity():
    """p_ac must be capped at pnom_kwac * num_units when p_dc*eta exceeds it."""
    site = _site(eta_nom=1.0, pnom_kwac=300.0, num_units=1)
    # 350 kW DC with 100% efficiency → 350 kW AC → capped at 300 kW
    p_dc = _series(350.0)

    result = calculate_ac_power(site, p_dc)

    assert result["p_ac_kw"].tolist() == pytest.approx([300.0] * 4), (
        "p_ac_kw should be clipped to inverter capacity (300 kW)"
    )
    assert result["clipped"].all(), "clipped column must be True when capacity exceeded"


def test_no_clipping_when_below_capacity():
    """p_ac must not be clipped when p_dc*eta is below capacity."""
    site = _site(eta_nom=1.0, pnom_kwac=500.0, num_units=1)
    p_dc = _series(300.0)

    result = calculate_ac_power(site, p_dc)

    assert result["p_ac_kw"].tolist() == pytest.approx([300.0] * 4)
    assert not result["clipped"].any(), "clipped should be False when below capacity"


def test_clipping_uses_num_units():
    """Total inverter capacity is pnom_kwac * num_units."""
    # 2 inverters × 300 kW = 600 kW capacity; 650 kW DC should clip to 600 kW
    site = _site(eta_nom=1.0, pnom_kwac=300.0, num_units=2)
    p_dc = _series(650.0)

    result = calculate_ac_power(site, p_dc)

    assert result["p_ac_kw"].tolist() == pytest.approx([600.0] * 4)
    assert result["clipped"].all()


# ---------------------------------------------------------------------------
# Test 2 — Grid limit curtailment
# ---------------------------------------------------------------------------

def test_grid_limit_curtailment():
    """p_ac must be further capped at grid_limit_kwac after clipping."""
    # Inverter capacity 500 kW, grid limit 400 kW → capped at 400
    site = _site(eta_nom=1.0, pnom_kwac=500.0, num_units=1, grid_limit_kwac=400.0)
    p_dc = _series(480.0)  # 480 kW DC → 480 kW AC (below inverter cap, above grid limit)

    result = calculate_ac_power(site, p_dc)

    assert result["p_ac_kw"].tolist() == pytest.approx([400.0] * 4), (
        "Grid limit of 400 kW should curtail output from 480 kW"
    )


def test_grid_limit_not_applied_when_none():
    """When grid_limit_kwac is None, no grid curtailment is applied."""
    site = _site(eta_nom=1.0, pnom_kwac=600.0, num_units=1, grid_limit_kwac=None)
    p_dc = _series(500.0)

    result = calculate_ac_power(site, p_dc)

    assert result["p_ac_kw"].tolist() == pytest.approx([500.0] * 4)


# ---------------------------------------------------------------------------
# Test 3 — AC wiring loss reduces output
# ---------------------------------------------------------------------------

def test_ac_wiring_loss_reduces_output():
    """AC wiring loss must reduce p_ac proportionally."""
    # 2% wiring loss; 1.0 efficiency, no clipping, no grid limit
    site = _site(eta_nom=1.0, pnom_kwac=1000.0, num_units=1,
                 grid_limit_kwac=None, wiring_loss_ac_pct=2.0)
    p_dc = _series(400.0)

    result = calculate_ac_power(site, p_dc)

    expected = 400.0 * (1.0 - 2.0 / 100.0)  # 392.0 kW
    assert result["p_ac_kw"].tolist() == pytest.approx([expected] * 4), (
        f"2% AC wiring loss should reduce 400 kW to {expected} kW"
    )


def test_combined_eta_and_wiring():
    """eta_nom and wiring_loss_ac_pct both applied in sequence."""
    # eta=0.98, wiring=1%: 100 kW → 98 kW → 98 * 0.99 = 97.02 kW
    site = _site(eta_nom=0.98, pnom_kwac=1000.0, num_units=1,
                 grid_limit_kwac=None, wiring_loss_ac_pct=1.0)
    p_dc = _series(100.0)

    result = calculate_ac_power(site, p_dc)

    expected = 100.0 * 0.98 * 0.99
    assert result["p_ac_kw"].iloc[0] == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# Test 4 — Output shape
# ---------------------------------------------------------------------------

def test_output_has_required_columns():
    """Output DataFrame must contain p_ac_kw, p_dc_kw_input, clipped."""
    site = _site()
    p_dc = _series(200.0)
    result = calculate_ac_power(site, p_dc)

    for col in ("p_ac_kw", "p_dc_kw_input", "clipped"):
        assert col in result.columns, f"Column '{col}' missing from inverter output"

    assert (result["p_dc_kw_input"] == p_dc).all(), (
        "p_dc_kw_input should pass through DC power unchanged"
    )
