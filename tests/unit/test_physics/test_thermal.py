"""Unit tests for heliotelligence.physics.thermal.

Tests
-----
1. Faiman model returns higher cell temp than ambient at positive irradiance
2. Measured module temp path is used when provided (< 10% NaN)
3. NOCT fallback (calculate_cell_temp_noct) works and gives higher temp than ambient
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from heliotelligence.config.site import ModuleConfig, SiteConfig, InverterConfig
from heliotelligence.physics.thermal import calculate_cell_temp, calculate_cell_temp_noct


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _series(value: float, n: int = 5) -> pd.Series:
    idx = pd.date_range("2024-06-21 10:00", periods=n, freq="h", tz="UTC")
    return pd.Series(value, index=idx)


def _test_site(u_c: float = 29.0, u_v: float = 0.0, noct_c: float = 45.0) -> SiteConfig:
    return SiteConfig(
        id="test-thermal",
        name="Thermal Test Site",
        latitude=52.56,
        longitude=1.21,
        timezone="Europe/London",
        capacity_kwp=1000.0,
        solcast_resource_id="test",
        module=ModuleConfig(
            u_c=u_c,
            u_v=u_v,
            noct_c=noct_c,
            pnom_wp=570.0,
        ),
        inverter=InverterConfig(),
    )


# ---------------------------------------------------------------------------
# Test 1 — Faiman: cell temp > ambient at positive POA
# ---------------------------------------------------------------------------

def test_faiman_cell_temp_above_ambient():
    """Faiman model must give t_cell > t_amb when poa > 0."""
    site = _test_site()
    poa = _series(800.0)
    t_amb = _series(20.0)
    wind = _series(2.0)

    t_cell = calculate_cell_temp(site, poa, t_amb, wind)

    assert (t_cell > t_amb).all(), (
        "Faiman model should give cell temp > ambient at 800 W/m² irradiance"
    )
    # At 800 W/m² with u_c=29 W/m²K: ΔT = 800/29 ≈ 27.6 °C above ambient
    expected_min_delta = 800.0 / 29.0 * 0.8  # allow 20% tolerance
    assert (t_cell - t_amb).mean() > expected_min_delta


# ---------------------------------------------------------------------------
# Test 2 — Measured module temp path is used when data is clean
# ---------------------------------------------------------------------------

def test_measured_module_temp_path_used():
    """When measured module temp is provided with <10% NaN, it should be used.

    The cell temperature output should be close to (but slightly above)
    the measured module temperature due to the conduction delta correction.
    """
    site = _test_site()
    n = 10
    idx = pd.date_range("2024-06-21 09:00", periods=n, freq="h", tz="UTC")
    poa = pd.Series(700.0, index=idx)
    t_amb = pd.Series(22.0, index=idx)
    wind = pd.Series(1.5, index=idx)
    t_mod = pd.Series(50.0, index=idx)  # 0% NaN — all clean

    t_cell = calculate_cell_temp(site, poa, t_amb, wind, temp_module_measured=t_mod)

    # t_cell = t_mod + poa * 0.03 / 1000 = 50 + 700 * 0.03/1000 = 50.021
    expected = 50.0 + 700.0 * 0.03 / 1000.0
    assert t_cell.mean() == pytest.approx(expected, rel=1e-3), (
        "Measured module temp path should apply conduction delta, not Faiman model"
    )
    # Cell temp should be above ambient (50.02 >> 22)
    assert (t_cell > t_amb).all()


def test_measured_module_temp_high_nan_falls_back_to_faiman():
    """Measured module temp with ≥10% NaN should fall back to Faiman."""
    site = _test_site()
    n = 20
    idx = pd.date_range("2024-06-21 09:00", periods=n, freq="h", tz="UTC")
    poa = pd.Series(600.0, index=idx)
    t_amb = pd.Series(18.0, index=idx)
    wind = pd.Series(1.0, index=idx)

    # 50% NaN — should trigger fallback
    t_mod_values = [45.0] * 10 + [float("nan")] * 10
    t_mod = pd.Series(t_mod_values, index=idx)

    t_cell = calculate_cell_temp(site, poa, t_amb, wind, temp_module_measured=t_mod)

    # Faiman at 600 W/m², u_c=29: ΔT = 600/29 ≈ 20.7°C; t_cell ≈ 38.7°C
    faiman_delta = 600.0 / 29.0
    assert float(t_cell.mean()) == pytest.approx(18.0 + faiman_delta, rel=0.05)


# ---------------------------------------------------------------------------
# Test 3 — NOCT fallback via calculate_cell_temp_noct
# ---------------------------------------------------------------------------

def test_noct_fallback_returns_higher_than_ambient():
    """NOCT model must return t_cell > t_amb at positive irradiance."""
    site = _test_site(noct_c=45.0)
    poa = _series(700.0)
    t_amb = _series(25.0)
    wind = _series(1.0)

    t_cell = calculate_cell_temp_noct(site, poa, t_amb, wind)

    assert (t_cell > t_amb).all(), (
        "NOCT model should give cell temp > ambient at 700 W/m²"
    )
