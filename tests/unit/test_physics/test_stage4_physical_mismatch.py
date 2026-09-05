"""Tests for IV-consistent physical mismatch at one shared MPPT."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from heliotelligence.config.site import ModuleConfig, SiteConfig
from heliotelligence.physics import electrical
from heliotelligence.physics.electrical import (
    calculate_common_voltage_mppt,
    calculate_module_iv_curves,
    calculate_physical_mismatch,
    scale_module_iv_to_string,
)

OUTPUT_COLUMNS = [
    "timestamp",
    "v_common_mppt_v",
    "i_common_mppt_a",
    "p_common_mppt_w",
    "p_independent_mp_w",
    "p_mismatch_w",
    "mismatch_pct",
    "string_count",
]


def _timestamp(hour: int = 12) -> pd.Timestamp:
    return pd.Timestamp(f"2024-06-21 {hour:02d}:00", tz="Europe/London")


def _curve(
    voltage: list[float],
    current: list[float],
    *,
    timestamp: pd.Timestamp | None = None,
) -> pd.DataFrame:
    voltage_values = np.asarray(voltage, dtype=float)
    current_values = np.asarray(current, dtype=float)
    return pd.DataFrame(
        {
            "timestamp": [timestamp or _timestamp()] * len(voltage),
            "curve_point": range(len(voltage)),
            "voltage_v": voltage_values,
            "current_a": current_values,
            "power_w": voltage_values * current_values,
        }
    )


def _night_curve(timestamp: pd.Timestamp | None = None) -> pd.DataFrame:
    return _curve([0.0, 0.0, 0.0], [0.0, 0.0, 0.0], timestamp=timestamp)


def _site() -> SiteConfig:
    return SiteConfig(
        id="physical-mismatch-test",
        name="Physical Mismatch Test",
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
    timestamp: pd.Timestamp | None = None,
    voltage_points: int = 51,
) -> pd.DataFrame:
    index = pd.DatetimeIndex([timestamp or _timestamp()])
    module_curve = calculate_module_iv_curves(
        _site(),
        pd.Series([irradiance], index=index, dtype=float),
        pd.Series([temperature], index=index, dtype=float),
        voltage_points=voltage_points,
    )
    return scale_module_iv_to_string(module_curve, 20)


def _assert_common_fields_match(strings: list[pd.DataFrame]) -> pd.DataFrame:
    mismatch = calculate_physical_mismatch(strings)
    common = calculate_common_voltage_mppt(strings)
    pd.testing.assert_frame_equal(
        mismatch[
            [
                "timestamp",
                "v_common_mppt_v",
                "i_common_mppt_a",
                "p_common_mppt_w",
                "string_count",
            ]
        ],
        common,
    )
    return mismatch


def test_empty_sequence_uses_common_mppt_validation() -> None:
    with pytest.raises(ValueError, match="must contain at least one string curve"):
        calculate_physical_mismatch([])


def test_single_active_string_has_zero_mismatch() -> None:
    result = _assert_common_fields_match([_physical_string_curve(900.0, 35.0)])

    assert result.columns.tolist() == OUTPUT_COLUMNS
    assert result.iloc[0]["p_independent_mp_w"] == pytest.approx(
        result.iloc[0]["p_common_mppt_w"]
    )
    assert result.iloc[0]["p_mismatch_w"] == 0.0
    assert result.iloc[0]["mismatch_pct"] == 0.0
    assert result.iloc[0]["string_count"] == 1


@pytest.mark.parametrize("string_count", [2, 4])
def test_identical_parallel_strings_have_zero_mismatch(string_count: int) -> None:
    curve = _physical_string_curve(900.0, 35.0)

    result = calculate_physical_mismatch([curve] * string_count).iloc[0]

    assert result["p_independent_mp_w"] == pytest.approx(
        result["p_common_mppt_w"]
    )
    assert result["p_mismatch_w"] == 0.0
    assert result["mismatch_pct"] == 0.0
    assert result["string_count"] == string_count


def test_known_positive_mismatch_matches_manual_algebra() -> None:
    low_voltage = _curve([0.0, 1.0, 2.0, 4.0], [10.0, 10.0, 2.0, 0.0])
    high_voltage = _curve([0.0, 1.0, 2.0, 4.0], [4.0, 4.0, 4.0, 0.0])

    result = calculate_physical_mismatch([low_voltage, high_voltage]).iloc[0]

    assert result["p_independent_mp_w"] == pytest.approx(18.0)
    assert result["p_common_mppt_w"] == pytest.approx(14.0)
    assert result["p_mismatch_w"] == pytest.approx(4.0)
    assert result["mismatch_pct"] == pytest.approx(100.0 * 4.0 / 18.0)


def test_master_union_enriches_each_independent_candidate_grid() -> None:
    sparse = _curve([0.0, 1.0, 3.0, 4.0], [10.0, 10.0, 4.0, 0.0])
    contributes_two_volts = _curve(
        [0.0, 2.0, 4.0],
        [0.0, 0.0, 0.0],
    )
    # Keep the second curve active while contributing no material power.
    contributes_two_volts.loc[0, "current_a"] = 1e-8
    contributes_two_volts.loc[0, "power_w"] = 0.0

    result = calculate_physical_mismatch([sparse, contributes_two_volts]).iloc[0]

    assert sparse["power_w"].max() == pytest.approx(12.0)
    assert result["p_independent_mp_w"] == pytest.approx(14.0)
    assert result["p_common_mppt_w"] <= result["p_independent_mp_w"]
    assert result["p_mismatch_w"] >= 0.0


@pytest.mark.parametrize(
    ("first_conditions", "second_conditions"),
    [
        ((1000.0, 25.0), (500.0, 25.0)),
        ((900.0, 15.0), (900.0, 55.0)),
    ],
)
def test_different_physical_conditions_preserve_mismatch_invariants(
    first_conditions: tuple[float, float],
    second_conditions: tuple[float, float],
) -> None:
    strings = [
        _physical_string_curve(*first_conditions),
        _physical_string_curve(*second_conditions),
    ]

    result = _assert_common_fields_match(strings).iloc[0]

    assert result["p_independent_mp_w"] >= result["p_common_mppt_w"]
    assert result["p_mismatch_w"] >= 0.0
    assert 0.0 <= result["mismatch_pct"] <= 100.0
    assert result["p_mismatch_w"] == pytest.approx(
        result["p_independent_mp_w"] - result["p_common_mppt_w"]
    )


def test_all_night_strings_return_zero_mismatch() -> None:
    result = calculate_physical_mismatch([_night_curve(), _night_curve()]).iloc[0]

    assert result[
        [
            "v_common_mppt_v",
            "i_common_mppt_a",
            "p_common_mppt_w",
            "p_independent_mp_w",
            "p_mismatch_w",
            "mismatch_pct",
        ]
    ].eq(0.0).all()
    assert result["string_count"] == 2


def test_multiple_all_night_timestamps_preserve_order_and_timezone() -> None:
    timestamps = [_timestamp(14), _timestamp(12)]
    first = pd.concat([_night_curve(value) for value in timestamps], ignore_index=True)
    second = first.copy(deep=True)

    result = calculate_physical_mismatch([first, second])

    assert result.columns.tolist() == OUTPUT_COLUMNS
    assert result.index.equals(pd.RangeIndex(2))
    assert result["timestamp"].tolist() == timestamps
    assert str(result["timestamp"].dt.tz) == "Europe/London"
    assert result[
        [
            "v_common_mppt_v",
            "i_common_mppt_a",
            "p_common_mppt_w",
            "p_independent_mp_w",
            "p_mismatch_w",
            "mismatch_pct",
        ]
    ].eq(0.0).all().all()
    assert result["string_count"].eq(2).all()


def test_mixed_active_and_night_strings_keep_common_validation() -> None:
    active = _curve([0.0, 1.0, 2.0], [2.0, 1.0, 0.0])

    with pytest.raises(ValueError, match="reverse-current or blocking-device model"):
        calculate_physical_mismatch([active, _night_curve()])


def test_inputs_are_not_mutated() -> None:
    strings = [
        _curve([0.0, 1.0, 2.0], [4.0, 3.0, 0.0]),
        _curve([0.0, 1.5, 2.5], [3.0, 2.0, 0.0]),
    ]
    originals = [curve.copy(deep=True) for curve in strings]

    calculate_physical_mismatch(strings)

    for curve, original in zip(strings, originals, strict=True):
        pd.testing.assert_frame_equal(curve, original)


def test_common_power_above_independent_power_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    curve = _curve([0.0, 1.0, 2.0], [2.0, 1.0, 0.0])
    impossible = pd.DataFrame(
        {
            "timestamp": [_timestamp()],
            "v_common_mppt_v": [1.0],
            "i_common_mppt_a": [3.0],
            "p_common_mppt_w": [3.0],
            "string_count": [1],
        }
    )
    monkeypatch.setattr(electrical, "calculate_common_voltage_mppt", lambda _: impossible)

    with pytest.raises(ValueError, match="exceeds the IV-consistent independent"):
        calculate_physical_mismatch([curve])


def test_pairwise_close_high_scale_violation_is_normalized_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    curve = _curve([0.0, 1.0, 2.0], [1_000_000.0, 1_000_000.0, 0.0])
    common_power = 1_000_000.0000005
    close_common = pd.DataFrame(
        {
            "timestamp": [_timestamp()],
            "v_common_mppt_v": [1.0],
            "i_common_mppt_a": [common_power],
            "p_common_mppt_w": [common_power],
            "string_count": [1],
        }
    )
    monkeypatch.setattr(electrical, "calculate_common_voltage_mppt", lambda _: close_common)

    result = calculate_physical_mismatch([curve]).iloc[0]

    assert np.isclose(
        result["p_common_mppt_w"],
        result["p_independent_mp_w"],
        rtol=1e-12,
        atol=1e-9,
    )
    assert result["p_mismatch_w"] == 0.0
    assert result["mismatch_pct"] == 0.0
    assert result["p_mismatch_w"] >= 0.0
    assert result["mismatch_pct"] >= 0.0
