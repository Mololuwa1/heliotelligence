"""Tests for the voltage-dependent Stage 4 module I-V contract."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from heliotelligence.config.site import ModuleConfig, SiteConfig
from heliotelligence.physics.electrical import (
    calculate_module_iv_curves,
    calculate_module_operating_point,
)

IV_COLUMNS = [
    "timestamp",
    "curve_point",
    "voltage_v",
    "current_a",
    "power_w",
    "effective_irradiance_wm2",
    "tier_used",
    "fit_quality",
]


def _site(module: ModuleConfig) -> SiteConfig:
    return SiteConfig(
        id="module-iv-test",
        name="Module I-V Test",
        latitude=52.56,
        longitude=1.21,
        timezone="Europe/London",
        capacity_kwp=1.0,
        solcast_resource_id="test",
        module=module,
    )


def _jinko_site() -> SiteConfig:
    return _site(
        ModuleConfig(
            local_module_name="JKM570N-72HL4-BDV",
            technology="mono_si",
        )
    )


def _series(values: list[float]) -> pd.Series:
    index = pd.date_range(
        "2024-06-21 12:00",
        periods=len(values),
        freq="h",
        tz="Europe/London",
    )
    return pd.Series(values, index=index, dtype=float)


def test_long_form_contract_preserves_timestamp_order_and_fixed_shape() -> None:
    poa = _series([800.0, 1000.0])
    curves = calculate_module_iv_curves(
        _jinko_site(),
        poa,
        _series([35.0, 25.0]),
        voltage_points=11,
    )

    assert curves.columns.tolist() == IV_COLUMNS
    assert len(curves) == len(poa) * 11
    assert curves["timestamp"].drop_duplicates().tolist() == poa.index.tolist()
    for timestamp, curve in curves.groupby("timestamp", sort=False):
        assert timestamp in poa.index
        assert curve["curve_point"].tolist() == list(range(11))
    assert np.isfinite(curves[["voltage_v", "current_a", "power_w"]]).all().all()
    assert curves["power_w"].to_numpy() == pytest.approx(
        (curves["voltage_v"] * curves["current_a"]).to_numpy()
    )


def test_daylight_curve_has_physical_endpoints_and_shape() -> None:
    curve = calculate_module_iv_curves(
        _jinko_site(),
        _series([1000.0]),
        _series([25.0]),
    )

    first = curve.iloc[0]
    last = curve.iloc[-1]
    assert first["voltage_v"] == pytest.approx(0.0)
    assert first["current_a"] > 0.0
    assert first["power_w"] == pytest.approx(0.0)
    assert last["voltage_v"] > 0.0
    assert last["current_a"] == pytest.approx(0.0, abs=1e-7)
    assert last["power_w"] == pytest.approx(0.0, abs=1e-6)
    assert curve["voltage_v"].is_monotonic_increasing
    assert (curve[["voltage_v", "current_a", "power_w"]] >= 0.0).all().all()
    assert curve["power_w"].idxmax() not in (curve.index[0], curve.index[-1])


def test_sampled_mpp_matches_scalar_single_diode_operating_point() -> None:
    site = _jinko_site()
    poa = _series([850.0])
    temperature = _series([38.0])
    scalar = calculate_module_operating_point(site, poa, temperature).iloc[0]
    curve = calculate_module_iv_curves(site, poa, temperature)
    sampled = curve.loc[curve["power_w"].idxmax()]

    assert sampled["power_w"] == pytest.approx(scalar["p_mp_w"], rel=1e-3)
    assert sampled["voltage_v"] == pytest.approx(scalar["v_mp_v"], rel=0.01)
    assert sampled["current_a"] == pytest.approx(scalar["i_mp_a"], rel=0.01)


def test_tier1_cec_curve_is_physical_and_matches_scalar_mpp() -> None:
    import pvlib.pvsystem

    cec_name = pvlib.pvsystem.retrieve_sam("CECMod").columns[0]
    site = _site(ModuleConfig(cec_name=cec_name))
    poa = _series([1000.0])
    temperature = _series([25.0])
    curve = calculate_module_iv_curves(site, poa, temperature)
    scalar = calculate_module_operating_point(site, poa, temperature).iloc[0]

    assert curve["tier_used"].eq(1).all()
    assert curve["fit_quality"].eq("high").all()
    assert np.isfinite(curve[["voltage_v", "current_a", "power_w"]]).all().all()
    assert curve.iloc[0]["current_a"] > 0.0
    assert curve.iloc[-1]["current_a"] == pytest.approx(0.0, abs=1e-7)
    assert curve["power_w"].max() == pytest.approx(scalar["p_mp_w"], rel=1e-3)


def test_packaged_datasheet_module_generates_tier3_curve() -> None:
    curve = calculate_module_iv_curves(
        _jinko_site(),
        _series([1000.0]),
        _series([25.0]),
    )

    assert curve["tier_used"].eq(3).all()
    assert curve["fit_quality"].eq("low").all()
    assert curve["power_w"].max() == pytest.approx(570.0, rel=0.02)


def test_lower_irradiance_reduces_current_and_maximum_power() -> None:
    curves = calculate_module_iv_curves(
        _jinko_site(),
        _series([1000.0, 500.0]),
        _series([25.0, 25.0]),
    )
    high, low = (curve for _, curve in curves.groupby("timestamp", sort=False))

    assert low.iloc[0]["current_a"] < high.iloc[0]["current_a"] * 0.75
    assert low["power_w"].max() < high["power_w"].max()


def test_hotter_module_has_lower_open_circuit_voltage() -> None:
    curves = calculate_module_iv_curves(
        _jinko_site(),
        _series([1000.0, 1000.0]),
        _series([15.0, 55.0]),
    )
    cool, hot = (curve for _, curve in curves.groupby("timestamp", sort=False))

    assert hot["voltage_v"].iloc[-1] < cool["voltage_v"].iloc[-1]


@pytest.mark.parametrize("irradiance", [0.0, -25.0])
def test_non_positive_irradiance_returns_fixed_all_zero_curve(
    irradiance: float,
) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        curve = calculate_module_iv_curves(
            _jinko_site(),
            _series([irradiance]),
            _series([15.0]),
            voltage_points=7,
        )

    assert len(curve) == 7
    assert curve["curve_point"].tolist() == list(range(7))
    assert curve["effective_irradiance_wm2"].eq(0.0).all()
    assert curve[["voltage_v", "current_a", "power_w"]].eq(0.0).all().all()
    assert np.isfinite(curve[["voltage_v", "current_a", "power_w"]]).all().all()


def test_tier5_scalar_fallback_remains_available_but_iv_is_rejected() -> None:
    site = _site(ModuleConfig(pnom_wp=500.0, gamma_pmp=-0.3))
    poa = _series([1000.0])
    temperature = _series([25.0])

    scalar = calculate_module_operating_point(site, poa, temperature)
    assert scalar.iloc[0]["p_mp_w"] == pytest.approx(500.0)
    assert scalar.iloc[0]["tier_used"] == 5

    with pytest.raises(ValueError, match="Tier 5 PVWatts"):
        calculate_module_iv_curves(site, poa, temperature)


def test_non_physical_datasheet_fit_keeps_scalar_fallback_but_rejects_iv() -> None:
    site = _site(
        ModuleConfig(
            pnom_wp=570.0,
            v_mp=41.64,
            i_mp=13.69,
            v_oc=50.60,
            i_sc=13.48,
            alpha_sc=0.045,
            beta_voc=-0.25,
            gamma_pmp=-0.29,
        )
    )
    poa = _series([1000.0])
    temperature = _series([25.0])

    scalar = calculate_module_operating_point(site, poa, temperature)
    assert scalar.iloc[0]["p_mp_w"] == pytest.approx(570.0)
    assert scalar.iloc[0]["tier_used"] == 4

    with pytest.raises(ValueError, match="do not produce a physical"):
        calculate_module_iv_curves(site, poa, temperature)


@pytest.mark.parametrize("voltage_points", [0, 2])
def test_voltage_points_must_allow_endpoints_and_an_interior_point(
    voltage_points: int,
) -> None:
    with pytest.raises(ValueError, match="at least 3"):
        calculate_module_iv_curves(
            _jinko_site(),
            _series([1000.0]),
            _series([25.0]),
            voltage_points=voltage_points,
        )


def test_mismatched_environment_indexes_are_rejected() -> None:
    poa = _series([1000.0])
    temperature = pd.Series(
        [25.0],
        index=pd.date_range("2024-06-22", periods=1, tz="UTC"),
    )

    with pytest.raises(ValueError, match="align exactly"):
        calculate_module_iv_curves(_jinko_site(), poa, temperature)


@pytest.mark.parametrize("series_name", ["poa", "temperature"])
def test_duplicate_timestamp_indexes_are_rejected(series_name: str) -> None:
    duplicate_index = pd.DatetimeIndex(
        [pd.Timestamp("2024-06-21", tz="UTC")] * 2
    )
    duplicate = pd.Series([1000.0, 900.0], index=duplicate_index)
    unique = _series([25.0, 25.0])
    poa, temperature = (
        (duplicate, unique) if series_name == "poa" else (unique, duplicate)
    )

    with pytest.raises(ValueError, match="unique timestamps"):
        calculate_module_iv_curves(_jinko_site(), poa, temperature)


def test_optional_spectral_input_must_align_exactly() -> None:
    poa = _series([1000.0])
    misaligned = pd.Series(
        [40.0],
        index=pd.date_range("2024-06-22", periods=1, tz="UTC"),
    )

    with pytest.raises(ValueError, match="solar_zenith index must align exactly"):
        calculate_module_iv_curves(
            _jinko_site(),
            poa,
            _series([25.0]),
            solar_zenith=misaligned,
        )
