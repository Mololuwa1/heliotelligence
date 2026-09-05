"""Tests for explicit topology routing into physical MPPT mismatch."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from heliotelligence.config.site import (
    ElectricalTopologyConfig,
    InverterUnitConfig,
    MPPTConfig,
    StringConfig,
)
from heliotelligence.physics import electrical
from heliotelligence.physics.electrical import (
    calculate_physical_mismatch,
    calculate_topology_mppt_mismatch,
)

OUTPUT_COLUMNS = [
    "timestamp",
    "inverter_id",
    "mppt_id",
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
    return _curve([0.0, 0.0], [0.0, 0.0], timestamp=timestamp)


def _string(string_id: str) -> StringConfig:
    return StringConfig(id=string_id, modules_per_string=1)


def _topology(
    *inverters: tuple[str, list[tuple[str, list[str]]]],
) -> ElectricalTopologyConfig:
    return ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id=inverter_id,
                mppts=[
                    MPPTConfig(
                        id=mppt_id,
                        strings=[_string(string_id) for string_id in string_ids],
                    )
                    for mppt_id, string_ids in mppts
                ],
            )
            for inverter_id, mppts in inverters
        ]
    )


def _positive_mismatch_curves() -> tuple[pd.DataFrame, pd.DataFrame]:
    return (
        _curve([0.0, 1.0, 2.0, 4.0], [10.0, 10.0, 2.0, 0.0]),
        _curve([0.0, 1.0, 2.0, 4.0], [4.0, 4.0, 4.0, 0.0]),
    )


def _without_topology_ids(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.drop(columns=["inverter_id", "mppt_id"])


def test_empty_topology_returns_declared_empty_schema() -> None:
    result = calculate_topology_mppt_mismatch(
        ElectricalTopologyConfig(inverters=[]),
        {},
    )

    assert result.columns.tolist() == OUTPUT_COLUMNS
    assert result.index.equals(pd.RangeIndex(0))
    assert result.empty


def test_empty_topology_rejects_unexpected_curve() -> None:
    with pytest.raises(ValueError, match="unexpected string ids: string-x"):
        calculate_topology_mppt_mismatch(
            ElectricalTopologyConfig(inverters=[]),
            {"string-x": _curve([0.0, 1.0], [1.0, 0.0])},
        )


def test_one_string_one_mppt_matches_canonical_result() -> None:
    curve = _curve([0.0, 1.0, 2.0], [3.0, 2.0, 0.0])
    topology = _topology(("inverter-A", [("mppt-1", ["string-1"])]))

    result = calculate_topology_mppt_mismatch(topology, {"string-1": curve})
    direct = calculate_physical_mismatch([curve])

    assert result["inverter_id"].eq("inverter-A").all()
    assert result["mppt_id"].eq("mppt-1").all()
    assert result["string_count"].eq(1).all()
    assert result["p_mismatch_w"].eq(0.0).all()
    assert result["mismatch_pct"].eq(0.0).all()
    pd.testing.assert_frame_equal(_without_topology_ids(result), direct)


def test_multiple_strings_positive_mismatch_matches_canonical_result() -> None:
    first, second = _positive_mismatch_curves()
    topology = _topology(
        ("inverter-A", [("mppt-1", ["string-a", "string-b"])])
    )

    result = calculate_topology_mppt_mismatch(
        topology,
        {"string-a": first, "string-b": second},
    )
    direct = calculate_physical_mismatch([first, second])

    pd.testing.assert_frame_equal(_without_topology_ids(result), direct)
    assert result.iloc[0]["p_independent_mp_w"] == pytest.approx(18.0)
    assert result.iloc[0]["p_common_mppt_w"] == pytest.approx(14.0)
    assert result.iloc[0]["p_mismatch_w"] == pytest.approx(4.0)


def test_two_mppts_are_evaluated_independently_in_topology_order() -> None:
    first, second = _positive_mismatch_curves()
    solo = _curve([0.0, 2.0, 3.0], [3.0, 2.0, 0.0])
    topology = _topology(
        (
            "inverter-A",
            [
                ("mppt-1", ["string-a", "string-b"]),
                ("mppt-2", ["string-c"]),
            ],
        )
    )

    result = calculate_topology_mppt_mismatch(
        topology,
        {"string-a": first, "string-b": second, "string-c": solo},
    )

    assert result["mppt_id"].tolist() == ["mppt-1", "mppt-2"]
    assert result["string_count"].tolist() == [2, 1]
    assert result["p_mismatch_w"].tolist() == pytest.approx([4.0, 0.0])


def test_repeated_mppt_id_across_inverters_remains_separate() -> None:
    first = _curve([0.0, 1.0, 2.0], [3.0, 2.0, 0.0])
    second = _curve([0.0, 2.0, 4.0], [5.0, 4.0, 0.0])
    topology = _topology(
        ("inverter-A", [("mppt-1", ["string-a"])]),
        ("inverter-B", [("mppt-1", ["string-b"])]),
    )

    result = calculate_topology_mppt_mismatch(
        topology,
        {"string-a": first, "string-b": second},
    )

    assert result[["inverter_id", "mppt_id"]].values.tolist() == [
        ["inverter-A", "mppt-1"],
        ["inverter-B", "mppt-1"],
    ]
    assert result["p_common_mppt_w"].tolist() == pytest.approx([2.0, 8.0])


def test_missing_configured_string_is_rejected() -> None:
    topology = _topology(
        ("inverter-A", [("mppt-1", ["string-a", "string-b"])])
    )

    with pytest.raises(ValueError, match="missing string ids: string-b"):
        calculate_topology_mppt_mismatch(
            topology,
            {"string-a": _curve([0.0, 1.0], [1.0, 0.0])},
        )


def test_unexpected_string_is_rejected() -> None:
    topology = _topology(("inverter-A", [("mppt-1", ["string-a"])]))

    with pytest.raises(ValueError, match="unexpected string ids: string-extra"):
        calculate_topology_mppt_mismatch(
            topology,
            {
                "string-a": _curve([0.0, 1.0], [1.0, 0.0]),
                "string-extra": _curve([0.0, 1.0], [1.0, 0.0]),
            },
        )


def test_missing_and_unexpected_strings_are_reported_together() -> None:
    topology = _topology(
        ("inverter-A", [("mppt-1", ["string-a", "string-b"])])
    )

    with pytest.raises(
        ValueError,
        match="missing string ids: string-b; unexpected string ids: string-c",
    ):
        calculate_topology_mppt_mismatch(
            topology,
            {
                "string-a": _curve([0.0, 1.0], [1.0, 0.0]),
                "string-c": _curve([0.0, 1.0], [1.0, 0.0]),
            },
        )


def test_invalid_global_id_contract_calls_no_physics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(
        ("inverter-A", [("mppt-1", ["string-a", "string-b"])])
    )
    calls = 0

    def fail_if_called(_: list[pd.DataFrame]) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        raise AssertionError("physical mismatch must not run for invalid IDs")

    monkeypatch.setattr(electrical, "calculate_physical_mismatch", fail_if_called)

    with pytest.raises(ValueError) as error:
        calculate_topology_mppt_mismatch(
            topology,
            {
                "string-a": _curve([0.0, 1.0], [1.0, 0.0]),
                "string-extra": _curve([0.0, 1.0], [1.0, 0.0]),
            },
        )

    assert str(error.value) == (
        "string_iv_curves_by_id does not match electrical topology: "
        "missing string ids: string-b; unexpected string ids: string-extra"
    )
    assert calls == 0


def test_multiple_missing_and_unexpected_ids_are_sorted_deterministically() -> None:
    topology = _topology(
        (
            "inverter-A",
            [("mppt-1", ["string-z", "string-a", "string-b"])],
        )
    )

    with pytest.raises(ValueError) as error:
        calculate_topology_mppt_mismatch(
            topology,
            {
                "string-y": _curve([0.0, 1.0], [1.0, 0.0]),
                "string-a": _curve([0.0, 1.0], [1.0, 0.0]),
                "string-c": _curve([0.0, 1.0], [1.0, 0.0]),
            },
        )

    assert str(error.value) == (
        "string_iv_curves_by_id does not match electrical topology: "
        "missing string ids: string-b, string-z; "
        "unexpected string ids: string-c, string-y"
    )


def test_empty_mppt_produces_no_rows_but_live_mppt_does() -> None:
    topology = _topology(
        (
            "inverter-A",
            [("mppt-empty", []), ("mppt-live", ["string-a"])],
        )
    )

    result = calculate_topology_mppt_mismatch(
        topology,
        {"string-a": _curve([0.0, 1.0], [1.0, 0.0])},
    )

    assert result["mppt_id"].tolist() == ["mppt-live"]


def test_only_empty_mppts_return_declared_empty_schema() -> None:
    topology = _topology(
        ("inverter-A", [("mppt-1", []), ("mppt-2", [])]),
        ("inverter-B", []),
    )

    result = calculate_topology_mppt_mismatch(topology, {})

    assert result.columns.tolist() == OUTPUT_COLUMNS
    assert result.index.equals(pd.RangeIndex(0))


def test_topology_string_order_overrides_mapping_insertion_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    curve_a = _curve([0.0, 1.0], [1.0, 0.0])
    curve_b = _curve([0.0, 2.0], [2.0, 0.0])
    topology = _topology(
        ("inverter-A", [("mppt-1", ["string-b", "string-a"])])
    )
    captured: list[list[pd.DataFrame]] = []
    canonical = electrical.calculate_physical_mismatch

    def capture(curves: list[pd.DataFrame]) -> pd.DataFrame:
        captured.append(curves)
        return canonical(curves)

    monkeypatch.setattr(electrical, "calculate_physical_mismatch", capture)

    calculate_topology_mppt_mismatch(
        topology,
        {"string-a": curve_a, "string-b": curve_b},
    )

    assert captured == [[curve_b, curve_a]]


def test_one_physics_call_per_populated_mppt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(
        (
            "inverter-A",
            [
                ("empty", []),
                ("first", ["string-a"]),
                ("second", ["string-b"]),
            ],
        )
    )
    calls: list[list[pd.DataFrame]] = []
    canonical = electrical.calculate_physical_mismatch

    def count(curves: list[pd.DataFrame]) -> pd.DataFrame:
        calls.append(curves)
        return canonical(curves)

    monkeypatch.setattr(electrical, "calculate_physical_mismatch", count)
    curves = {
        "string-a": _curve([0.0, 1.0], [1.0, 0.0]),
        "string-b": _curve([0.0, 2.0], [2.0, 0.0]),
    }

    calculate_topology_mppt_mismatch(topology, curves)

    assert calls == [[curves["string-a"]], [curves["string-b"]]]


def test_physical_validation_error_includes_inverter_and_mppt_context() -> None:
    topology = _topology(
        ("inverter-A", [("mppt-1", ["active", "night"])])
    )

    with pytest.raises(
        ValueError,
        match=(
            "inverter 'inverter-A' MPPT 'mppt-1'.*"
            "reverse-current or blocking-device model"
        ),
    ) as error:
        calculate_topology_mppt_mismatch(
            topology,
            {
                "active": _curve([0.0, 1.0], [1.0, 0.0]),
                "night": _night_curve(),
            },
        )

    assert isinstance(error.value.__cause__, ValueError)


def test_timestamp_order_timezone_and_topology_group_order_are_preserved() -> None:
    first_timestamps = [_timestamp(14), _timestamp(12)]
    second_timestamps = [_timestamp(13), _timestamp(11)]
    first_curve = pd.concat(
        [_curve([0.0, 1.0], [1.0, 0.0], timestamp=value) for value in first_timestamps],
        ignore_index=True,
    )
    second_curve = pd.concat(
        [_curve([0.0, 2.0], [2.0, 0.0], timestamp=value) for value in second_timestamps],
        ignore_index=True,
    )
    topology = _topology(
        (
            "inverter-A",
            [("mppt-1", ["string-a"]), ("mppt-2", ["string-b"])],
        )
    )

    result = calculate_topology_mppt_mismatch(
        topology,
        {"string-a": first_curve, "string-b": second_curve},
    )

    assert result["mppt_id"].tolist() == ["mppt-1", "mppt-1", "mppt-2", "mppt-2"]
    assert result["timestamp"].tolist() == first_timestamps + second_timestamps
    assert str(result["timestamp"].dt.tz) == "Europe/London"


def test_inputs_and_topology_are_not_mutated() -> None:
    topology = _topology(
        ("inverter-A", [("mppt-1", ["string-a", "string-b"])])
    )
    curves = {
        "string-a": _curve([0.0, 1.0], [1.0, 0.0]),
        "string-b": _curve([0.0, 2.0], [2.0, 0.0]),
    }
    topology_before = topology.model_dump(mode="python")
    curves_before = {key: curve.copy(deep=True) for key, curve in curves.items()}
    mapping_items_before = list(curves.items())

    calculate_topology_mppt_mismatch(topology, curves)

    assert topology.model_dump(mode="python") == topology_before
    assert list(curves.items()) == mapping_items_before
    for string_id, curve in curves.items():
        pd.testing.assert_frame_equal(curve, curves_before[string_id])


def test_valid_schema_empty_curve_produces_no_rows() -> None:
    topology = _topology(("inverter-A", [("mppt-1", ["string-a"])]))
    empty_curve = pd.DataFrame(
        columns=["timestamp", "curve_point", "voltage_v", "current_a", "power_w"]
    )

    result = calculate_topology_mppt_mismatch(topology, {"string-a": empty_curve})

    assert result.columns.tolist() == OUTPUT_COLUMNS
    assert result.index.equals(pd.RangeIndex(0))
    assert result.empty
