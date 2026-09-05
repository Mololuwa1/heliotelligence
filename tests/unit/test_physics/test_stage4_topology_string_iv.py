"""Tests for topology-aware physical string I-V construction."""

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
    calculate_topology_string_iv_curves,
    scale_module_iv_to_string,
)


def _timestamp(hour: int = 12) -> pd.Timestamp:
    return pd.Timestamp(f"2024-06-21 {hour:02d}:00", tz="Europe/London")


def _module_curve(
    voltage: list[float] | None = None,
    current: list[float] | None = None,
    *,
    timestamps: list[pd.Timestamp] | None = None,
) -> pd.DataFrame:
    voltage = voltage or [0.0, 1.0, 2.0]
    current = current or [3.0, 2.0, 0.0]
    timestamps = timestamps or [_timestamp()]
    frames: list[pd.DataFrame] = []
    for timestamp in timestamps:
        voltage_values = np.asarray(voltage, dtype=float)
        current_values = np.asarray(current, dtype=float)
        frames.append(
            pd.DataFrame(
                {
                    "timestamp": [timestamp] * len(voltage),
                    "curve_point": range(len(voltage)),
                    "voltage_v": voltage_values,
                    "current_a": current_values,
                    "power_w": voltage_values * current_values,
                    "condition": [f"condition-{timestamp.hour}"] * len(voltage),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _string(string_id: str, modules: int, *, zone: str | None = None) -> StringConfig:
    return StringConfig(
        id=string_id,
        modules_per_string=modules,
        zone_id=zone,
        label=f"label-{string_id}",
    )


def _topology(
    *inverters: tuple[str, list[tuple[str, list[StringConfig]]]],
) -> ElectricalTopologyConfig:
    return ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id=inverter_id,
                group_id=f"group-{inverter_id}",
                model_ref="arbitrary-model",
                mppts=[
                    MPPTConfig(id=mppt_id, strings=strings)
                    for mppt_id, strings in mppts
                ],
            )
            for inverter_id, mppts in inverters
        ]
    )


def test_empty_topology_returns_empty_dict_without_scaling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fail_if_called(_: pd.DataFrame, __: int) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        raise AssertionError("scaler must not run")

    monkeypatch.setattr(electrical, "scale_module_iv_to_string", fail_if_called)
    result = calculate_topology_string_iv_curves(
        ElectricalTopologyConfig(inverters=[]), {}
    )

    assert type(result) is dict
    assert result == {}
    assert calls == 0


def test_empty_topology_rejects_unexpected_module_curve() -> None:
    with pytest.raises(ValueError) as error:
        calculate_topology_string_iv_curves(
            ElectricalTopologyConfig(inverters=[]),
            {"string-x": _module_curve()},
        )

    assert str(error.value) == (
        "module_iv_curves_by_string_id does not match electrical topology: "
        "unexpected string ids: string-x"
    )


def test_one_string_matches_canonical_scaler() -> None:
    module_curve = _module_curve()
    topology = _topology(
        ("inverter-A", [("mppt-1", [_string("string-a", 12)])])
    )

    result = calculate_topology_string_iv_curves(
        topology, {"string-a": module_curve}
    )

    assert list(result) == ["string-a"]
    pd.testing.assert_frame_equal(
        result["string-a"], scale_module_iv_to_string(module_curve, 12)
    )


def test_different_strings_use_their_own_module_counts() -> None:
    module_a = _module_curve([0.0, 1.0, 3.0], [4.0, 3.0, 0.0])
    module_b = _module_curve([0.0, 2.0, 4.0], [5.0, 2.0, 0.0])
    topology = _topology(
        (
            "inverter-A",
            [
                (
                    "mppt-1",
                    [_string("string-a", 10), _string("string-b", 14)],
                )
            ],
        )
    )

    result = calculate_topology_string_iv_curves(
        topology, {"string-a": module_a, "string-b": module_b}
    )

    pd.testing.assert_frame_equal(
        result["string-a"], scale_module_iv_to_string(module_a, 10)
    )
    pd.testing.assert_frame_equal(
        result["string-b"], scale_module_iv_to_string(module_b, 14)
    )
    pd.testing.assert_series_equal(
        result["string-a"]["current_a"], module_a["current_a"]
    )
    pd.testing.assert_series_equal(
        result["string-b"]["current_a"], module_b["current_a"]
    )


def test_multiple_inverters_and_repeated_mppt_ids_preserve_topology_order() -> None:
    topology = _topology(
        (
            "inverter-A",
            [
                ("mppt-1", [_string("string-a", 2)]),
                ("mppt-2", [_string("string-b", 3)]),
            ],
        ),
        ("inverter-B", [("mppt-1", [_string("string-c", 4)])]),
    )
    curves = {
        string_id: _module_curve()
        for string_id in ["string-a", "string-b", "string-c"]
    }

    result = calculate_topology_string_iv_curves(topology, curves)

    assert list(result) == ["string-a", "string-b", "string-c"]


def test_mapping_order_does_not_control_scaling_or_output_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_a = _module_curve([0.0, 1.0], [1.0, 0.0])
    module_b = _module_curve([0.0, 2.0], [2.0, 0.0])
    topology = _topology(
        (
            "inverter-A",
            [("mppt-1", [_string("string-b", 7), _string("string-a", 5)])],
        )
    )
    calls: list[tuple[pd.DataFrame, int]] = []
    canonical = electrical.scale_module_iv_to_string

    def capture(curve: pd.DataFrame, modules: int) -> pd.DataFrame:
        calls.append((curve, modules))
        return canonical(curve, modules)

    monkeypatch.setattr(electrical, "scale_module_iv_to_string", capture)
    result = calculate_topology_string_iv_curves(
        topology, {"string-a": module_a, "string-b": module_b}
    )

    assert list(result) == ["string-b", "string-a"]
    assert calls == [(module_b, 7), (module_a, 5)]


def test_missing_configured_string_is_rejected() -> None:
    topology = _topology(
        (
            "inverter-A",
            [("mppt-1", [_string("string-a", 1), _string("string-b", 1)])],
        )
    )

    with pytest.raises(ValueError, match="missing string ids: string-b"):
        calculate_topology_string_iv_curves(
            topology, {"string-a": _module_curve()}
        )


def test_unexpected_string_is_rejected() -> None:
    topology = _topology(
        ("inverter-A", [("mppt-1", [_string("string-a", 1)])])
    )

    with pytest.raises(ValueError, match="unexpected string ids: string-extra"):
        calculate_topology_string_iv_curves(
            topology,
            {"string-a": _module_curve(), "string-extra": _module_curve()},
        )


def test_multiple_missing_and_unexpected_ids_are_sorted_deterministically() -> None:
    topology = _topology(
        (
            "inverter-A",
            [
                (
                    "mppt-1",
                    [
                        _string("string-z", 1),
                        _string("string-a", 1),
                        _string("string-b", 1),
                    ],
                )
            ],
        )
    )

    with pytest.raises(ValueError) as error:
        calculate_topology_string_iv_curves(
            topology,
            {
                "string-y": _module_curve(),
                "string-a": _module_curve(),
                "string-c": _module_curve(),
            },
        )

    assert str(error.value) == (
        "module_iv_curves_by_string_id does not match electrical topology: "
        "missing string ids: string-b, string-z; "
        "unexpected string ids: string-c, string-y"
    )


def test_invalid_global_id_contract_calls_no_scaler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(
        (
            "inverter-A",
            [("mppt-1", [_string("string-a", 1), _string("string-b", 1)])],
        )
    )
    calls = 0

    def fail_if_called(_: pd.DataFrame, __: int) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        raise AssertionError("scaler must not run for invalid IDs")

    monkeypatch.setattr(electrical, "scale_module_iv_to_string", fail_if_called)
    with pytest.raises(ValueError) as error:
        calculate_topology_string_iv_curves(
            topology,
            {"string-a": _module_curve(), "string-extra": _module_curve()},
        )

    assert "missing string ids: string-b" in str(error.value)
    assert "unexpected string ids: string-extra" in str(error.value)
    assert calls == 0


def test_one_scaler_call_per_configured_string_in_topology_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(
        (
            "inverter-A",
            [
                ("empty", []),
                ("first", [_string("string-b", 6), _string("string-a", 8)]),
            ],
        ),
        ("inverter-B", [("second", [_string("string-c", 11)])]),
    )
    curves = {string_id: _module_curve() for string_id in ("string-a", "string-b", "string-c")}
    calls: list[tuple[pd.DataFrame, int]] = []
    canonical = electrical.scale_module_iv_to_string

    def count(curve: pd.DataFrame, modules: int) -> pd.DataFrame:
        calls.append((curve, modules))
        return canonical(curve, modules)

    monkeypatch.setattr(electrical, "scale_module_iv_to_string", count)
    calculate_topology_string_iv_curves(topology, curves)

    assert calls == [
        (curves["string-b"], 6),
        (curves["string-a"], 8),
        (curves["string-c"], 11),
    ]


def test_scaler_error_includes_full_topology_context() -> None:
    topology = _topology(
        ("inverter-A", [("mppt-7", [_string("string-x", 9)])])
    )
    invalid = _module_curve().drop(columns="current_a")

    with pytest.raises(
        ValueError,
        match=(
            "inverter 'inverter-A' MPPT 'mppt-7' string 'string-x'.*"
            "module_iv_curves missing columns: current_a"
        ),
    ) as error:
        calculate_topology_string_iv_curves(topology, {"string-x": invalid})

    assert isinstance(error.value.__cause__, ValueError)


def test_only_empty_mppts_return_empty_dict_without_scaling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(
        ("inverter-A", [("empty-1", []), ("empty-2", [])]),
        ("inverter-B", []),
    )
    calls = 0

    def fail_if_called(_: pd.DataFrame, __: int) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        raise AssertionError("scaler must not run")

    monkeypatch.setattr(electrical, "scale_module_iv_to_string", fail_if_called)
    assert calculate_topology_string_iv_curves(topology, {}) == {}
    assert calls == 0


def test_valid_schema_empty_module_curve_is_scaled_without_fabricated_rows() -> None:
    empty = pd.DataFrame(
        columns=["timestamp", "curve_point", "voltage_v", "current_a", "power_w"]
    )
    topology = _topology(
        ("inverter-A", [("mppt-1", [_string("string-a", 12)])])
    )

    result = calculate_topology_string_iv_curves(topology, {"string-a": empty})

    assert list(result) == ["string-a"]
    pd.testing.assert_frame_equal(
        result["string-a"], scale_module_iv_to_string(empty, 12)
    )
    assert result["string-a"].empty


def test_different_string_timestamps_and_grids_are_scaled_independently() -> None:
    module_a = _module_curve(timestamps=[_timestamp(10), _timestamp(11)])
    module_b = _module_curve(
        [0.0, 0.5, 1.5, 2.5],
        [4.0, 3.0, 2.0, 0.0],
        timestamps=[_timestamp(14), _timestamp(13)],
    )
    topology = _topology(
        (
            "inverter-A",
            [("mppt-1", [_string("string-a", 2), _string("string-b", 3)])],
        )
    )

    result = calculate_topology_string_iv_curves(
        topology, {"string-a": module_a, "string-b": module_b}
    )

    assert result["string-a"]["timestamp"].drop_duplicates().tolist() == [
        _timestamp(10),
        _timestamp(11),
    ]
    assert result["string-b"]["timestamp"].drop_duplicates().tolist() == [
        _timestamp(14),
        _timestamp(13),
    ]


def test_inputs_are_not_mutated_and_outputs_do_not_alias_inputs() -> None:
    topology = _topology(
        (
            "inverter-A",
            [
                (
                    "mppt-1",
                    [
                        _string("string-a", 2, zone="zone-a"),
                        _string("string-b", 3, zone="zone-b"),
                    ],
                )
            ],
        )
    )
    curves = {"string-a": _module_curve(), "string-b": _module_curve()}
    topology_before = topology.model_dump(mode="python")
    mapping_items_before = list(curves.items())
    curves_before = {key: value.copy(deep=True) for key, value in curves.items()}

    result = calculate_topology_string_iv_curves(topology, curves)

    assert topology.model_dump(mode="python") == topology_before
    assert list(curves.items()) == mapping_items_before
    for string_id, curve in curves.items():
        pd.testing.assert_frame_equal(curve, curves_before[string_id])
    result["string-a"].loc[0, "voltage_v"] = -999.0
    pd.testing.assert_frame_equal(curves["string-a"], curves_before["string-a"])


def test_constructed_curves_feed_topology_mppt_router() -> None:
    module_a = _module_curve(
        [0.0, 1.0, 2.0, 4.0], [10.0, 10.0, 2.0, 0.0]
    )
    module_b = _module_curve(
        [0.0, 1.0, 2.0, 4.0], [4.0, 4.0, 4.0, 0.0]
    )
    topology = _topology(
        (
            "inverter-A",
            [("mppt-1", [_string("string-a", 2), _string("string-b", 3)])],
        )
    )

    string_curves = calculate_topology_string_iv_curves(
        topology, {"string-a": module_a, "string-b": module_b}
    )
    routed = calculate_topology_mppt_mismatch(topology, string_curves)
    direct = calculate_physical_mismatch(
        [
            scale_module_iv_to_string(module_a, 2),
            scale_module_iv_to_string(module_b, 3),
        ]
    )

    pd.testing.assert_frame_equal(
        routed.drop(columns=["inverter_id", "mppt_id"]), direct
    )
