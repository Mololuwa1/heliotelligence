"""Unit tests for heliotelligence.physics.irradiance.

Tests
-----
1. pvlib_azimuth property: azimuth_deg=-0.6 → pvlib_azimuth=179.4
2. Measured POA is used directly when poa_wm2 column is present and clean
3. bifacial=False gives poa_rear=0 everywhere
4. Perez transposition path produces positive POA during daytime
"""

from __future__ import annotations

import pandas as pd
import pytest

from heliotelligence.config.site import InverterConfig, ModuleConfig, SiteConfig
from heliotelligence.physics.irradiance import calculate_poa


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _bracon_ash(bifacial: bool = False) -> SiteConfig:
    return SiteConfig(
        id="site-001",
        name="Bracon Ash",
        latitude=52.56,
        longitude=1.21,
        altitude_m=47,
        timezone="Europe/London",
        capacity_kwp=28524.0,
        tilt_deg=15.0,
        azimuth_deg=-0.6,
        gcr=0.654,
        height_m=0.70,
        solcast_resource_id="test",
        module=ModuleConfig(
            local_module_name="JKM570N-72HL4-BDV",
            bifacial=bifacial,
            bifaciality_factor=0.80,
        ),
        inverter=InverterConfig(),
    )


def _daytime_index(n: int = 8, date: str = "2024-06-21") -> pd.DatetimeIndex:
    """Return a UTC DatetimeIndex covering 08:00–15:00 UTC (daytime at 52°N)."""
    return pd.date_range(f"{date} 08:00", periods=n, freq="h", tz="UTC")


def _weather_df(
    index: pd.DatetimeIndex,
    ghi: float = 600.0,
    dni: float = 700.0,
    dhi: float = 150.0,
    include_poa: bool = False,
    poa_value: float = 500.0,
) -> pd.DataFrame:
    data = {
        "ghi_wm2": ghi,
        "dni_wm2": dni,
        "dhi_wm2": dhi,
    }
    if include_poa:
        data["poa_wm2"] = poa_value
    return pd.DataFrame(data, index=index)


# ---------------------------------------------------------------------------
# Test 1 — pvlib_azimuth convention conversion
# ---------------------------------------------------------------------------

def test_pvlib_azimuth_conversion():
    """azimuth_deg=-0.6 (PVsyst, 0=South) → pvlib_azimuth=179.4 (0=North)."""
    site = _bracon_ash()
    assert site.azimuth_deg == pytest.approx(-0.6)
    assert site.pvlib_azimuth == pytest.approx(179.4)


def test_pvlib_azimuth_south_facing():
    """azimuth_deg=0.0 (PVsyst South) → pvlib_azimuth=180.0."""
    site = SiteConfig(
        id="s",
        name="S",
        latitude=52.0,
        longitude=1.0,
        timezone="UTC",
        capacity_kwp=1000.0,
        solcast_resource_id="x",
        azimuth_deg=0.0,
    )
    assert site.pvlib_azimuth == pytest.approx(180.0)


# ---------------------------------------------------------------------------
# Test 2 — Measured POA used directly when poa_wm2 present
# ---------------------------------------------------------------------------

def test_measured_poa_used_when_present():
    """When poa_wm2 column exists with clean data, poa_total == poa_wm2."""
    site = _bracon_ash(bifacial=False)
    idx = _daytime_index()
    df = _weather_df(idx, include_poa=True, poa_value=480.0)

    result = calculate_poa(site, df)

    # poa_total should match the measured poa_wm2 column exactly
    pd.testing.assert_series_equal(
        result["poa_total"].reset_index(drop=True),
        df["poa_wm2"].reset_index(drop=True),
        check_names=False,
        rtol=1e-6,
    )


# ---------------------------------------------------------------------------
# Test 3 — bifacial=False gives poa_rear=0
# ---------------------------------------------------------------------------

def test_non_bifacial_poa_rear_is_zero():
    """For a non-bifacial array, poa_rear must be 0.0 for all timesteps."""
    site = _bracon_ash(bifacial=False)
    idx = _daytime_index()
    df = _weather_df(idx)

    result = calculate_poa(site, df)

    assert (result["poa_rear"] == 0.0).all(), (
        "poa_rear must be 0 for a non-bifacial site"
    )


# ---------------------------------------------------------------------------
# Test 4 — Perez transposition gives positive POA during daytime
# ---------------------------------------------------------------------------

def test_perez_transposition_positive_daytime():
    """Perez transposition should produce positive poa_total during daytime hours."""
    site = _bracon_ash(bifacial=False)
    idx = _daytime_index()  # 08:00–15:00 UTC at 52.56°N in June — solar elevation >10°
    df = _weather_df(idx, ghi=600.0, dni=700.0, dhi=150.0)

    result = calculate_poa(site, df)

    # At least some daytime hours should have positive POA
    assert (result["poa_total"] > 0).any(), (
        "Perez transposition should produce positive POA during daytime"
    )
    # Solar zenith and azimuth should be populated
    assert result["solar_zenith"].notna().all()
    assert result["solar_azimuth"].notna().all()
