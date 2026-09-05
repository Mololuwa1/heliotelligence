"""Tests for common-voltage aggregation of supplied string I-V curves."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from heliotelligence.config.site import ModuleConfig, SiteConfig
from heliotelligence.physics.electrical import (
    calculate_common_voltage_mppt,
    calculate_module_iv_curves,
    scale_module_iv_to_string,
)

OUTPUT_COLUMNS = [
    "timestamp",
    "v_common_mppt_v",
    "i_common_mppt_a",
    "p_common_mppt_w",
    "string_count",
]


def _timestamp(hour: int = 12) -> pd.Timestamp:
    return pd.Timestamp(f"2024-06-21 {hour:02d}:00", tz="Europe/London")


def _curve(
    voltage: list[float],
    current: list[float],
    *,
    timestamp: pd.Timestamp | None = None,
    curve_point: list[int] | None = None,
) -> pd.DataFrame:
    timestamp = timestamp or _timestamp()
    power = np.asarray(voltage, dtype=float) * np.asarray(current, dtype=float)
    return pd.DataFrame(
        {
            "timestamp": [timestamp] * len(voltage),
            "curve_point": curve_point or list(range(len(voltage))),
            "voltage_v": voltage,
            "current_a": current,
            "power_w": power,
        }
    )


def _night_curve(timestamp: pd.Timestamp | None = None) -> pd.DataFrame:
    return _curve([0.0, 0.0, 0.0], [0.0, 0.0, 0.0], timestamp=timestamp)


def _site() -> SiteConfig:
    return SiteConfig(
        id="common-mppt-test",
        name="Common MPPT Test",
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


def _physical_string_curve(
    irradiance: float,
    temperature: float,
    *,
    modules_per_string: int = 20,
    voltage_points: int = 51,
) -> pd.DataFrame:
    index = pd.DatetimeIndex([_timestamp()])
    module_curve = calculate_module_iv_curves(
        _site(),
        pd.Series([irradiance], index=index, dtype=float),
        pd.Series([temperature], index=index, dtype=float),
        voltage_points=voltage_points,
    )
    return scale_module_iv_to_string(module_curve, modules_per_string)


def test_empty_string_sequence_is_rejected() -> None:
    with pytest.raises(ValueError, match="must contain at least one string curve"):
        calculate_common_voltage_mppt([])


def test_missing_required_column_identifies_string_position() -> None:
    invalid = _curve([0.0, 1.0], [1.0, 0.0]).drop(columns="current_a")

    with pytest.raises(
        ValueError,
        match=r"string_iv_curves\[1\] missing columns: current_a",
    ):
        calculate_common_voltage_mppt([_curve([0.0, 1.0], [1.0, 0.0]), invalid])


def test_multiple_missing_columns_are_reported_in_sorted_order() -> None:
    invalid = _curve([0.0, 1.0], [1.0, 0.0]).drop(
        columns=["voltage_v", "curve_point"]
    )

    with pytest.raises(
        ValueError,
        match=r"string_iv_curves\[0\] missing columns: curve_point, voltage_v",
    ):
        calculate_common_voltage_mppt([invalid])


def test_mismatched_timestamp_set_is_rejected() -> None:
    first = _curve([0.0, 1.0], [1.0, 0.0], timestamp=_timestamp(12))
    second = _curve([0.0, 1.0], [1.0, 0.0], timestamp=_timestamp(13))

    with pytest.raises(ValueError, match="timestamps must exactly match"):
        calculate_common_voltage_mppt([first, second])


def test_mismatched_timestamp_order_is_rejected() -> None:
    first = pd.concat(
        [
            _curve([0.0, 1.0], [1.0, 0.0], timestamp=_timestamp(12)),
            _curve([0.0, 1.0], [1.0, 0.0], timestamp=_timestamp(13)),
        ],
        ignore_index=True,
    )
    second = pd.concat(
        [
            _curve([0.0, 1.0], [1.0, 0.0], timestamp=_timestamp(13)),
            _curve([0.0, 1.0], [1.0, 0.0], timestamp=_timestamp(12)),
        ],
        ignore_index=True,
    )

    with pytest.raises(ValueError, match="first-occurrence order"):
        calculate_common_voltage_mppt([first, second])


def test_duplicate_curve_point_within_timestamp_is_rejected() -> None:
    invalid = _curve(
        [0.0, 1.0, 2.0],
        [2.0, 1.0, 0.0],
        curve_point=[0, 1, 1],
    )

    with pytest.raises(ValueError, match="unique curve_point values"):
        calculate_common_voltage_mppt([invalid])


@pytest.mark.parametrize(
    ("voltage", "message"),
    [
        ([0.0, 2.0, 1.0], "strictly increasing"),
        ([0.0, 1.0, 1.0], "strictly increasing"),
        ([0.5, 1.0, 2.0], "must begin at 0 V"),
    ],
)
def test_malformed_active_voltage_order_is_rejected(
    voltage: list[float],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_common_voltage_mppt([_curve(voltage, [2.0, 1.0, 0.0])])


@pytest.mark.parametrize("column", ["voltage_v", "current_a", "power_w"])
def test_non_finite_electrical_values_are_rejected(column: str) -> None:
    invalid = _curve([0.0, 1.0, 2.0], [2.0, 1.0, 0.0])
    invalid.loc[1, column] = np.nan

    with pytest.raises(ValueError, match=rf"{column} must contain only finite"):
        calculate_common_voltage_mppt([invalid])


@pytest.mark.parametrize("column", ["voltage_v", "current_a", "power_w"])
def test_materially_negative_electrical_values_are_rejected(column: str) -> None:
    invalid = _curve([0.0, 1.0, 2.0], [2.0, 1.0, 0.0])
    invalid.loc[1, column] = -1.0

    with pytest.raises(ValueError, match=rf"{column} must be non-negative"):
        calculate_common_voltage_mppt([invalid])


def test_tiny_negative_solver_noise_is_clamped_without_mutating_input() -> None:
    curve = _curve([0.0, 1.0, 2.0], [2.0, 1.0, 0.0])
    curve.loc[2, "current_a"] = -1e-9
    curve.loc[2, "power_w"] = -2e-9
    original = curve.copy(deep=True)

    result = calculate_common_voltage_mppt([curve])

    assert result.iloc[0]["p_common_mppt_w"] == pytest.approx(1.0)
    pd.testing.assert_frame_equal(curve, original)


def test_single_string_selects_its_sampled_maximum_power_point() -> None:
    curve = _curve([0.0, 1.0, 2.0, 3.0], [4.0, 4.0, 3.0, 0.0])
    sampled_mpp = curve.loc[curve["power_w"].idxmax()]

    result = calculate_common_voltage_mppt([curve])

    assert result.columns.tolist() == OUTPUT_COLUMNS
    assert result.index.equals(pd.RangeIndex(1))
    assert result.iloc[0]["v_common_mppt_v"] == pytest.approx(
        sampled_mpp["voltage_v"]
    )
    assert result.iloc[0]["i_common_mppt_a"] == pytest.approx(
        sampled_mpp["current_a"]
    )
    assert result.iloc[0]["p_common_mppt_w"] == pytest.approx(sampled_mpp["power_w"])
    assert result.iloc[0]["string_count"] == 1


@pytest.mark.parametrize("string_count", [2, 4])
def test_identical_parallel_strings_scale_current_and_power(
    string_count: int,
) -> None:
    curve = _physical_string_curve(900.0, 35.0)
    sampled_mpp = curve.loc[curve["power_w"].idxmax()]

    result = calculate_common_voltage_mppt([curve] * string_count).iloc[0]

    assert result["v_common_mppt_v"] == pytest.approx(sampled_mpp["voltage_v"])
    assert result["i_common_mppt_a"] == pytest.approx(
        sampled_mpp["current_a"] * string_count
    )
    assert result["p_common_mppt_w"] == pytest.approx(
        sampled_mpp["power_w"] * string_count
    )
    assert result["string_count"] == string_count


@pytest.mark.parametrize(
    ("first_conditions", "second_conditions"),
    [
        ((1000.0, 25.0), (500.0, 25.0)),
        ((900.0, 15.0), (900.0, 55.0)),
    ],
)
def test_different_physical_strings_share_voltage_and_sum_current(
    first_conditions: tuple[float, float],
    second_conditions: tuple[float, float],
) -> None:
    strings = [
        _physical_string_curve(*first_conditions),
        _physical_string_curve(*second_conditions),
    ]

    result = calculate_common_voltage_mppt(strings).iloc[0]
    expected_current = sum(
        np.interp(result["v_common_mppt_v"], curve["voltage_v"], curve["current_a"])
        for curve in strings
    )
    independent_sampled_power = sum(curve["power_w"].max() for curve in strings)

    assert result["v_common_mppt_v"] > 0.0
    assert result["i_common_mppt_a"] == pytest.approx(expected_current)
    assert result["p_common_mppt_w"] == pytest.approx(
        result["v_common_mppt_v"] * expected_current
    )
    assert result["p_common_mppt_w"] <= independent_sampled_power * (1.0 + 1e-12)


def test_union_grid_uses_linear_current_interpolation() -> None:
    first = _curve([0.0, 2.0, 4.0], [4.0, 3.0, 0.0])
    second = _curve([0.0, 1.0, 3.0], [2.0, 2.0, 0.0])

    result = calculate_common_voltage_mppt([first, second]).iloc[0]

    assert result["v_common_mppt_v"] == pytest.approx(2.0)
    assert result["i_common_mppt_a"] == pytest.approx(4.0)
    assert result["p_common_mppt_w"] == pytest.approx(8.0)


def test_common_domain_stops_at_lowest_sampled_voc() -> None:
    first = _curve([0.0, 2.0, 4.0], [1.0, 1.0, 0.0])
    second = _curve([0.0, 3.0], [1.0, 1.0])

    result = calculate_common_voltage_mppt([first, second]).iloc[0]

    assert result["v_common_mppt_v"] == pytest.approx(3.0)
    assert result["v_common_mppt_v"] <= 3.0


def test_exact_power_tie_selects_lowest_voltage() -> None:
    curve = _curve([0.0, 1.0, 2.0], [2.0, 2.0, 1.0])

    result = calculate_common_voltage_mppt([curve]).iloc[0]

    assert result["v_common_mppt_v"] == pytest.approx(1.0)
    assert result["p_common_mppt_w"] == pytest.approx(2.0)


def test_all_night_strings_return_zero_operating_point() -> None:
    result = calculate_common_voltage_mppt([_night_curve(), _night_curve()]).iloc[0]

    assert result["v_common_mppt_v"] == pytest.approx(0.0)
    assert result["i_common_mppt_a"] == pytest.approx(0.0)
    assert result["p_common_mppt_w"] == pytest.approx(0.0)
    assert result["string_count"] == 2


def test_multiple_all_night_timestamps_preserve_order_and_zero_output() -> None:
    timestamps = pd.DatetimeIndex([_timestamp(14), _timestamp(12)])
    module_curves = calculate_module_iv_curves(
        _site(),
        pd.Series([0.0, -5.0], index=timestamps, dtype=float),
        pd.Series([20.0, 20.0], index=timestamps, dtype=float),
        voltage_points=5,
    )
    first_string = scale_module_iv_to_string(module_curves, 20)
    second_string = scale_module_iv_to_string(module_curves, 20)

    result = calculate_common_voltage_mppt([first_string, second_string])

    assert result.columns.tolist() == OUTPUT_COLUMNS
    assert result.index.equals(pd.RangeIndex(2))
    assert result["timestamp"].tolist() == timestamps.tolist()
    assert str(result["timestamp"].dt.tz) == "Europe/London"
    assert result[
        ["v_common_mppt_v", "i_common_mppt_a", "p_common_mppt_w"]
    ].eq(0.0).all().all()
    assert result["string_count"].eq(2).all()


def test_mixed_active_and_night_strings_are_rejected() -> None:
    active = _curve([0.0, 1.0, 2.0], [2.0, 1.0, 0.0])

    with pytest.raises(ValueError, match="reverse-current or blocking-device model"):
        calculate_common_voltage_mppt([active, _night_curve()])


def test_timestamp_order_timezone_and_one_row_per_timestamp_are_preserved() -> None:
    timestamps = [_timestamp(14), _timestamp(12), _timestamp(13)]
    curve = pd.concat(
        [_curve([0.0, 1.0], [1.0, 0.0], timestamp=value) for value in timestamps],
        ignore_index=True,
    )

    result = calculate_common_voltage_mppt([curve])

    assert result["timestamp"].tolist() == timestamps
    assert str(result["timestamp"].dt.tz) == "Europe/London"
    assert len(result) == 3


def test_common_power_is_shared_voltage_times_summed_current() -> None:
    first = _curve([0.0, 1.0, 2.0], [4.0, 3.0, 0.0])
    second = _curve([0.0, 1.5, 2.0], [2.0, 1.0, 0.0])

    result = calculate_common_voltage_mppt([first, second]).iloc[0]

    assert result["p_common_mppt_w"] == pytest.approx(
        result["v_common_mppt_v"] * result["i_common_mppt_a"]
    )


def test_input_frames_are_not_mutated() -> None:
    strings = [
        _curve([0.0, 1.0, 2.0], [3.0, 2.0, 0.0]),
        _curve([0.0, 1.5, 2.5], [2.0, 1.0, 0.0]),
    ]
    originals = [curve.copy(deep=True) for curve in strings]

    calculate_common_voltage_mppt(strings)

    for curve, original in zip(strings, originals, strict=True):
        pd.testing.assert_frame_equal(curve, original)
