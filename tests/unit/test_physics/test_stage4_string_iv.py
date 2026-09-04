"""Tests for ideal homogeneous module-to-string I-V scaling."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from heliotelligence.config.site import ModuleConfig, SiteConfig
from heliotelligence.physics.electrical import (
    calculate_module_iv_curves,
    scale_module_iv_to_string,
)


def _site() -> SiteConfig:
    return SiteConfig(
        id="homogeneous-string-iv-test",
        name="Homogeneous String I-V Test",
        latitude=52.56,
        longitude=1.21,
        timezone="Europe/London",
        capacity_kwp=1.0,
        solcast_resource_id="test",
        module=ModuleConfig(
            local_module_name="JKM570N-72HL4-BDV",
            technology="mono_si",
        ),
    )


def _series(values: list[float]) -> pd.Series:
    index = pd.date_range(
        "2024-06-21 12:00",
        periods=len(values),
        freq="h",
        tz="Europe/London",
    )
    return pd.Series(values, index=index, dtype=float)


def _physical_curves(
    irradiance: list[float] | None = None,
    temperature: list[float] | None = None,
    *,
    voltage_points: int = 21,
) -> pd.DataFrame:
    irradiance = irradiance or [1000.0]
    temperature = temperature or [25.0] * len(irradiance)
    return calculate_module_iv_curves(
        _site(),
        _series(irradiance),
        _series(temperature),
        voltage_points=voltage_points,
    )


def test_homogeneous_series_law_scales_voltage_and_power_not_current() -> None:
    module_curves = _physical_curves()
    string_curves = scale_module_iv_to_string(module_curves, 24)

    assert string_curves["voltage_v"].to_numpy() == pytest.approx(
        module_curves["voltage_v"].to_numpy() * 24
    )
    assert string_curves["current_a"].equals(module_curves["current_a"])
    assert string_curves["power_w"].to_numpy() == pytest.approx(
        module_curves["power_w"].to_numpy() * 24
    )


def test_one_module_is_electrical_identity_and_returns_independent_frame() -> None:
    module_curves = _physical_curves()
    string_curves = scale_module_iv_to_string(module_curves, 1)

    assert string_curves is not module_curves
    pd.testing.assert_frame_equal(string_curves, module_curves)
    string_curves.loc[0, "voltage_v"] = -1.0
    assert module_curves.loc[0, "voltage_v"] == pytest.approx(0.0)


def test_physical_curve_endpoints_follow_series_law() -> None:
    module_curves = _physical_curves()
    string_curves = scale_module_iv_to_string(module_curves, 18)

    assert string_curves.iloc[0]["voltage_v"] == pytest.approx(0.0)
    assert string_curves.iloc[0]["power_w"] == pytest.approx(0.0)
    assert string_curves.iloc[-1]["voltage_v"] == pytest.approx(
        module_curves.iloc[-1]["voltage_v"] * 18
    )
    assert string_curves.iloc[-1]["current_a"] == pytest.approx(0.0, abs=1e-7)
    assert string_curves.iloc[-1]["power_w"] == pytest.approx(0.0, abs=1e-6)


def test_sampled_string_mpp_is_scaled_module_sampled_mpp() -> None:
    module_curves = _physical_curves(voltage_points=201)
    string_curves = scale_module_iv_to_string(module_curves, 24)
    module_mpp = module_curves.loc[module_curves["power_w"].idxmax()]
    string_mpp = string_curves.loc[string_curves["power_w"].idxmax()]

    assert string_mpp["power_w"] == pytest.approx(module_mpp["power_w"] * 24)
    assert string_mpp["voltage_v"] == pytest.approx(module_mpp["voltage_v"] * 24)
    assert string_mpp["current_a"] == pytest.approx(module_mpp["current_a"])
    assert string_mpp["curve_point"] == module_mpp["curve_point"]


def test_multiple_timestamp_and_curve_point_order_is_preserved() -> None:
    module_curves = _physical_curves(
        irradiance=[500.0, 1000.0, 800.0],
        temperature=[25.0, 30.0, 35.0],
        voltage_points=5,
    )
    module_curves = module_curves.iloc[[4, 0, 2, 9, 5, 7, 14, 10, 12]].copy()

    string_curves = scale_module_iv_to_string(module_curves, 20)

    assert string_curves["timestamp"].tolist() == module_curves["timestamp"].tolist()
    assert string_curves["curve_point"].tolist() == module_curves[
        "curve_point"
    ].tolist()
    assert string_curves.index.tolist() == module_curves.index.tolist()


def test_duplicate_index_labels_are_preserved_exactly() -> None:
    timestamps = pd.date_range("2024-06-21 12:00", periods=3, freq="h", tz="UTC")
    module_curves = pd.DataFrame(
        {
            "timestamp": timestamps,
            "curve_point": [0, 1, 2],
            "voltage_v": [0.0, 20.0, 40.0],
            "current_a": [10.0, 9.0, 0.0],
            "power_w": [0.0, 180.0, 0.0],
        },
        index=[7, 7, 9],
    )
    original_index = module_curves.index.copy()

    string_curves = scale_module_iv_to_string(module_curves, 3)

    assert string_curves.index.equals(module_curves.index)
    assert string_curves.index.tolist() == [7, 7, 9]
    assert string_curves["curve_point"].tolist() == [0, 1, 2]
    assert string_curves["voltage_v"].tolist() == [0.0, 60.0, 120.0]
    assert string_curves["current_a"].tolist() == [10.0, 9.0, 0.0]
    assert string_curves["power_w"].tolist() == [0.0, 540.0, 0.0]
    assert module_curves.index.equals(original_index)


def test_all_metadata_and_column_order_are_preserved() -> None:
    module_curves = _physical_curves()
    module_curves["source_note"] = "module-curve"

    string_curves = scale_module_iv_to_string(module_curves, 24)

    assert string_curves.columns.tolist() == module_curves.columns.tolist()
    for column in (
        "timestamp",
        "curve_point",
        "current_a",
        "effective_irradiance_wm2",
        "tier_used",
        "fit_quality",
        "source_note",
    ):
        assert string_curves[column].equals(module_curves[column])


def test_night_curve_remains_all_zero() -> None:
    module_curves = _physical_curves(irradiance=[0.0], voltage_points=7)
    string_curves = scale_module_iv_to_string(module_curves, 24)

    assert len(string_curves) == 7
    assert string_curves[["voltage_v", "current_a", "power_w"]].eq(0.0).all().all()
    assert np.isfinite(
        string_curves[["voltage_v", "current_a", "power_w"]]
    ).all().all()


@pytest.mark.parametrize("modules_per_string", [0, -1])
def test_non_positive_modules_per_string_is_rejected(
    modules_per_string: int,
) -> None:
    with pytest.raises(ValueError, match="must be greater than 0"):
        scale_module_iv_to_string(_physical_curves(), modules_per_string)


@pytest.mark.parametrize(
    "missing_column",
    ["timestamp", "curve_point", "voltage_v", "current_a", "power_w"],
)
def test_required_curve_columns_are_validated(missing_column: str) -> None:
    module_curves = _physical_curves().drop(columns=missing_column)

    with pytest.raises(
        ValueError,
        match=rf"module_iv_curves missing columns: {missing_column}",
    ):
        scale_module_iv_to_string(module_curves, 24)


def test_missing_columns_are_reported_in_deterministic_sorted_order() -> None:
    module_curves = _physical_curves().drop(columns=["voltage_v", "curve_point"])

    with pytest.raises(
        ValueError,
        match="module_iv_curves missing columns: curve_point, voltage_v",
    ):
        scale_module_iv_to_string(module_curves, 24)


def test_input_frame_is_not_mutated() -> None:
    module_curves = _physical_curves(irradiance=[700.0, 900.0])
    original = module_curves.copy(deep=True)

    scale_module_iv_to_string(module_curves, 24)

    pd.testing.assert_frame_equal(module_curves, original)


def test_string_power_remains_voltage_times_current() -> None:
    string_curves = scale_module_iv_to_string(_physical_curves(), 24)

    assert string_curves["power_w"].to_numpy() == pytest.approx(
        (string_curves["voltage_v"] * string_curves["current_a"]).to_numpy()
    )
