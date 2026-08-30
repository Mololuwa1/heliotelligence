"""Tests for the topology-ready Stage 4 electrical contracts."""

from __future__ import annotations

import pandas as pd
import pytest

from heliotelligence.config.site import InverterConfig, ModuleConfig, SiteConfig
from heliotelligence.physics.electrical import (
    calculate_dc_power,
    calculate_module_operating_point,
    scale_module_to_string,
)


def _series(value: float, n: int = 2) -> pd.Series:
    index = pd.date_range("2024-06-21 12:00", periods=n, freq="h", tz="UTC")
    return pd.Series(value, index=index)


def _site() -> SiteConfig:
    return SiteConfig(
        id="stage4-test",
        name="Stage 4 Test",
        latitude=52.56,
        longitude=1.21,
        timezone="Europe/London",
        capacity_kwp=28524.0,
        solcast_resource_id="test",
        module=ModuleConfig(
            local_module_name="JKM570N-72HL4-BDV",
            technology="mono_si",
            soiling_loss_pct=1.0,
            lid_loss_pct=0.6,
            mismatch_loss_pct=1.15,
            wiring_loss_dc_pct=0.48,
            modules_per_string=24,
            num_strings=10,
        ),
        inverter=InverterConfig(),
    )


def test_module_operating_point_exposes_stage4_contract() -> None:
    site = _site()
    module_point = calculate_module_operating_point(
        site,
        _series(1000.0),
        _series(25.0),
    )

    for column in (
        "p_mp_w",
        "v_mp_v",
        "i_mp_a",
        "effective_irradiance_wm2",
        "tier_used",
        "fit_quality",
    ):
        assert column in module_point.columns

    assert module_point["p_mp_w"].iloc[0] == pytest.approx(570.0, rel=0.02)
    assert module_point["v_mp_v"].iloc[0] > 0.0
    assert module_point["i_mp_a"].iloc[0] > 0.0


def test_module_to_string_scaling_uses_series_connection_rules() -> None:
    module_point = pd.DataFrame(
        {
            "p_mp_w": [500.0],
            "v_mp_v": [40.0],
            "i_mp_a": [12.5],
            "tier_used": [3],
            "fit_quality": ["high"],
        }
    )

    string_point = scale_module_to_string(module_point, modules_per_string=24)

    assert string_point["p_mp_w"].iloc[0] == pytest.approx(12000.0)
    assert string_point["v_mp_v"].iloc[0] == pytest.approx(960.0)
    assert string_point["i_mp_a"].iloc[0] == pytest.approx(12.5)


def test_aggregate_dc_result_is_preserved_by_module_refactor() -> None:
    site = _site()
    poa = _series(850.0)
    t_cell = _series(42.0)
    aoi = _series(12.0)

    module_point = calculate_module_operating_point(site, poa, t_cell)
    aggregate = calculate_dc_power(site, poa, t_cell, aoi)

    module_cfg = site.module
    n_modules = module_cfg.modules_per_string * module_cfg.num_strings
    legacy_factor = (
        (1.0 - module_cfg.soiling_loss_pct / 100.0)
        * (1.0 - module_cfg.lid_loss_pct / 100.0)
        * (1.0 - module_cfg.mismatch_loss_pct / 100.0)
        * (1.0 - module_cfg.wiring_loss_dc_pct / 100.0)
    )
    expected_kw = module_point["p_mp_w"] * n_modules * legacy_factor / 1000.0

    assert aggregate["p_dc_kw"].tolist() == pytest.approx(expected_kw.tolist())
    assert aggregate["v_mp"].tolist() == pytest.approx(module_point["v_mp_v"].tolist())
    assert aggregate["i_mp"].tolist() == pytest.approx(module_point["i_mp_a"].tolist())


def test_string_scaling_rejects_non_positive_module_count() -> None:
    module_point = pd.DataFrame(
        {"p_mp_w": [500.0], "v_mp_v": [40.0], "i_mp_a": [12.5]}
    )

    with pytest.raises(ValueError, match="greater than 0"):
        scale_module_to_string(module_point, modules_per_string=0)
