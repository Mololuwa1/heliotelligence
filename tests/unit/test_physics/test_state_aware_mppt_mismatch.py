"""Tests for canonical S8-2 state-aware common-voltage MPPT mismatch."""

from __future__ import annotations

import importlib
from dataclasses import replace
from typing import Any, cast

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

import heliotelligence.physics.electrical as electrical  # type: ignore[import-untyped]
from heliotelligence.config.site import (  # type: ignore[import-untyped]
    ElectricalTopologyConfig,
    InverterUnitConfig,
    MPPTConfig,
    StringConfig,
)
from heliotelligence.physics.electrical import (
    TOPOLOGY_MPPT_MISMATCH_CONTRACT_ID,
    TOPOLOGY_MPPT_MISMATCH_COVERAGE_SCOPE,
    TOPOLOGY_MPPT_MISMATCH_MODEL_ID,
    TOPOLOGY_MPPT_MISMATCH_SCOPE,
    TopologyMPPTMismatchResult,
    TopologyStringIVResult,
    calculate_topology_mppt_mismatch_from_string_iv,
    calculate_topology_string_iv_curves_from_receiver_module_iv,
)

s8_support: Any = importlib.import_module(
    "tests.unit.test_physics.test_receiver_string_module_iv_routing"
)


def _topology(
    mppts: list[tuple[str, list[tuple[str, int]]]],
    *,
    inverter_id: str = "inverter-1",
) -> ElectricalTopologyConfig:
    return ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id=inverter_id,
                mppts=[
                    MPPTConfig(
                        id=mppt_id,
                        strings=[
                            StringConfig(id=string_id, modules_per_string=count)
                            for string_id, count in strings
                        ],
                    )
                    for mppt_id, strings in mppts
                ],
            )
        ]
    )


def _real_s81(
    topology: ElectricalTopologyConfig | None = None,
    *,
    periods: int = 1,
    receiver_count: int = 1,
    zero: bool = False,
) -> tuple[ElectricalTopologyConfig, TopologyStringIVResult]:
    active = topology or _topology([("mppt-1", [("string-1", 24)])])
    receivers = s8_support._receivers(receiver_count)
    spectral = s8_support._spectral(
        receivers,
        periods=periods,
        front=0.0 if zero else 800.0,
        rear=0.0 if zero else 200.0,
    )
    handoff = s8_support._electrical(receivers, spectral=spectral)
    string_ids = [
        string.id
        for inverter in active.inverters
        for mppt in inverter.mppts
        for string in mppt.strings
    ]
    assignments = {
        string_id: receivers[position % receiver_count].id
        for position, string_id in enumerate(string_ids)
    }
    routed = s8_support._route(
        receivers,
        handoff,
        topology=active,
        assignments=assignments,
        policy="allow_unassigned_receivers",
        voltage_points=11,
    )
    return active, calculate_topology_string_iv_curves_from_receiver_module_iv(
        active, routed
    )


def _replace_curve(
    result: TopologyStringIVResult,
    string_id: str,
    curve: pd.DataFrame,
) -> TopologyStringIVResult:
    curves = {
        key: value.copy(deep=True)
        for key, value in result.string_iv_curves_by_string_id.items()
    }
    curves[string_id] = curve
    return replace(result, string_iv_curves_by_string_id=curves)


def _set_string_zero(
    result: TopologyStringIVResult,
    string_id: str,
) -> TopologyStringIVResult:
    states = result.states.copy(deep=True)
    mask = states.index.get_level_values("string_id") == string_id
    states.loc[mask, "receiver_module_electrical_state"] = (
        "resolved_zero_spectral_electrical_irradiance"
    )
    states.loc[mask, "spectral_electrical_equivalent_irradiance_wm2"] = 0.0
    states.loc[mask, "module_iv_state"] = "resolved_zero_module_iv"
    states.loc[mask, "string_iv_state"] = "resolved_zero_string_iv"
    curve = result.string_iv_curves_by_string_id[string_id].copy(deep=True)
    curve[["voltage_v", "current_a", "power_w", "effective_irradiance_wm2"]] = 0.0
    diagnostics = replace(
        result.diagnostics,
        zero_string_iv_state_count=result.diagnostics.zero_string_iv_state_count + 1,
        scaled_string_iv_state_count=result.diagnostics.scaled_string_iv_state_count - 1,
    )
    changed = replace(result, states=states, diagnostics=diagnostics)
    return _replace_curve(changed, string_id, curve)


def _set_string_unresolved(
    result: TopologyStringIVResult,
    string_id: str,
) -> TopologyStringIVResult:
    states = result.states.copy(deep=True)
    mask = states.index.get_level_values("string_id") == string_id
    states.loc[mask, "receiver_module_electrical_resolved"] = False
    states.loc[mask, "receiver_module_electrical_state"] = (
        "unresolved_spectral_electrical_equivalent_irradiance"
    )
    states.loc[mask, "spectral_electrical_equivalent_irradiance_wm2"] = np.nan
    states.loc[mask, "module_iv_resolved"] = False
    states.loc[mask, "module_iv_state"] = "unresolved_receiver_module_electrical"
    states.loc[mask, "string_iv_resolved"] = False
    states.loc[mask, "string_iv_state"] = "unresolved_receiver_module_electrical"
    removed = len(result.string_iv_curves_by_string_id[string_id])
    diagnostics = replace(
        result.diagnostics,
        resolved_string_iv_state_count=result.diagnostics.resolved_string_iv_state_count - 1,
        unresolved_string_iv_state_count=result.diagnostics.unresolved_string_iv_state_count + 1,
        scaled_string_iv_state_count=result.diagnostics.scaled_string_iv_state_count - 1,
        iv_curve_row_count=result.diagnostics.iv_curve_row_count - removed,
    )
    changed = replace(result, states=states, diagnostics=diagnostics)
    return _replace_curve(
        changed,
        string_id,
        result.string_iv_curves_by_string_id[string_id].iloc[0:0].copy(),
    )


def test_single_active_string_zero_mismatch_and_contract() -> None:
    topology, upstream = _real_s81()
    result = calculate_topology_mppt_mismatch_from_string_iv(topology, upstream)
    assert type(result) is TopologyMPPTMismatchResult
    row = result.operating_points.iloc[0]
    assert row["mppt_state"] == "resolved_common_voltage_mppt"
    assert row["p_mismatch_w"] == pytest.approx(0.0)
    assert row["mismatch_pct"] == pytest.approx(0.0)
    assert row["p_common_mppt_w"] == pytest.approx(
        row["v_common_mppt_v"] * row["i_common_mppt_a"]
    )
    assert row["topology_mppt_mismatch_contract"] == TOPOLOGY_MPPT_MISMATCH_CONTRACT_ID
    assert row["topology_mppt_mismatch_model"] == TOPOLOGY_MPPT_MISMATCH_MODEL_ID
    assert row["topology_mppt_mismatch_scope"] == TOPOLOGY_MPPT_MISMATCH_SCOPE
    assert row["topology_mppt_mismatch_coverage_scope"] == (
        TOPOLOGY_MPPT_MISMATCH_COVERAGE_SCOPE
    )


def test_identical_parallel_strings_have_zero_mismatch() -> None:
    topology = _topology([("mppt-1", [("a", 24), ("b", 24)])])
    _, upstream = _real_s81(topology)
    result = calculate_topology_mppt_mismatch_from_string_iv(topology, upstream)
    row = result.operating_points.iloc[0]
    assert row["p_mismatch_w"] == pytest.approx(0.0)
    independent = upstream.string_iv_curves_by_string_id["a"]["power_w"].max()
    assert row["p_common_mppt_w"] == pytest.approx(2 * independent)


def test_known_18_14_4_physical_mismatch() -> None:
    topology = _topology([("mppt-1", [("a", 1), ("b", 1)])])
    _, upstream = _real_s81(topology, receiver_count=2)
    timestamp = upstream.states.index.get_level_values("timestamp")[0]

    def curve(current: list[float]) -> pd.DataFrame:
        voltage = np.array([0.0, 1.0, 2.0, 4.0])
        amps = np.array(current)
        return pd.DataFrame(
            {
                "timestamp": [timestamp] * 4,
                "curve_point": range(4),
                "voltage_v": voltage,
                "current_a": amps,
                "power_w": voltage * amps,
                "effective_irradiance_wm2": [928.0] * 4,
                "tier_used": [3] * 4,
                "fit_quality": ["low"] * 4,
            }
        )

    forged = replace(
        upstream,
        string_iv_curves_by_string_id={
            "a": curve([10.0, 10.0, 2.0, 0.0]),
            "b": curve([4.0, 4.0, 4.0, 0.0]),
        },
        diagnostics=replace(upstream.diagnostics, voltage_points=4, iv_curve_row_count=8),
    )
    row = calculate_topology_mppt_mismatch_from_string_iv(
        topology, forged
    ).operating_points.iloc[0]
    assert row["p_independent_mp_w"] == pytest.approx(18.0)
    assert row["p_common_mppt_w"] == pytest.approx(14.0)
    assert row["p_mismatch_w"] == pytest.approx(4.0)


def test_all_zero_resolves_without_physics(monkeypatch: pytest.MonkeyPatch) -> None:
    topology = _topology([("mppt-1", [("a", 24), ("b", 30)])])
    _, upstream = _real_s81(topology, zero=True)

    def forbidden(*args: object, **kwargs: object) -> pd.DataFrame:
        raise AssertionError("physics called")

    monkeypatch.setattr(electrical, "calculate_physical_mismatch", forbidden)
    result = calculate_topology_mppt_mismatch_from_string_iv(topology, upstream)
    row = result.operating_points.iloc[0]
    assert row["mppt_state"] == "resolved_zero_common_voltage_mppt"
    numeric = [
        "v_common_mppt_v",
        "i_common_mppt_a",
        "p_common_mppt_w",
        "p_independent_mp_w",
        "p_mismatch_w",
        "mismatch_pct",
    ]
    assert row[numeric].eq(0.0).all()
    assert result.diagnostics.physics_call_count == 0


def test_mixed_active_zero_and_unresolved_member_are_not_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology([("mppt-1", [("a", 24), ("b", 24), ("c", 24)])])
    _, active = _real_s81(topology, receiver_count=3)
    calls = 0

    def forbidden(*args: object, **kwargs: object) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        raise AssertionError("physics called")

    monkeypatch.setattr(electrical, "calculate_physical_mismatch", forbidden)
    mixed = _set_string_zero(active, "c")
    mixed_result = calculate_topology_mppt_mismatch_from_string_iv(topology, mixed)
    assert mixed_result.operating_points.iloc[0]["mppt_state"] == (
        "unresolved_mixed_active_zero_requires_blocking_model"
    )
    assert mixed_result.operating_points.iloc[0]["active_string_count"] == 2
    unresolved = _set_string_unresolved(active, "c")
    unresolved_result = calculate_topology_mppt_mismatch_from_string_iv(topology, unresolved)
    row = unresolved_result.operating_points.iloc[0]
    assert row["mppt_state"] == "unresolved_member_string_iv"
    assert row["unresolved_string_ids"] == "c"
    assert row["unresolved_string_states"] == "unresolved_receiver_module_electrical"
    assert calls == 0


def test_multiple_active_timestamps_are_batched_once(monkeypatch: pytest.MonkeyPatch) -> None:
    topology = _topology([("mppt-1", [("a", 24), ("b", 24)])])
    _, upstream = _real_s81(topology, periods=3)
    original = electrical.calculate_physical_mismatch
    calls: list[int] = []

    def recording(curves: list[pd.DataFrame]) -> pd.DataFrame:
        calls.append(len(pd.unique(curves[0]["timestamp"])))
        return original(curves)

    monkeypatch.setattr(electrical, "calculate_physical_mismatch", recording)
    result = calculate_topology_mppt_mismatch_from_string_iv(topology, upstream)
    assert calls == [3]
    assert result.diagnostics.physics_call_count == 1
    assert result.diagnostics.physics_row_count == 3


def test_four_timestamp_active_zero_mixed_unresolved_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology([("mppt-1", [("a", 24), ("b", 24)])])
    _, upstream = _real_s81(topology, periods=4, receiver_count=2)
    timestamps = list(upstream.states.index.get_level_values("timestamp").unique())
    states = upstream.states.copy(deep=True)
    curves = {
        key: value.copy(deep=True)
        for key, value in upstream.string_iv_curves_by_string_id.items()
    }

    def zero_at(string_id: str, timestamp: pd.Timestamp) -> None:
        index = (timestamp, string_id)
        states.loc[index, "receiver_module_electrical_state"] = (
            "resolved_zero_spectral_electrical_irradiance"
        )
        states.loc[index, "spectral_electrical_equivalent_irradiance_wm2"] = 0.0
        states.loc[index, "module_iv_state"] = "resolved_zero_module_iv"
        states.loc[index, "string_iv_state"] = "resolved_zero_string_iv"
        mask = curves[string_id]["timestamp"].eq(timestamp)
        curves[string_id].loc[
            mask,
            ["voltage_v", "current_a", "power_w", "effective_irradiance_wm2"],
        ] = 0.0

    zero_at("a", timestamps[1])
    zero_at("b", timestamps[1])
    zero_at("b", timestamps[2])
    unresolved_index = (timestamps[3], "b")
    states.loc[unresolved_index, "receiver_module_electrical_resolved"] = False
    states.loc[unresolved_index, "receiver_module_electrical_state"] = (
        "unresolved_spectral_electrical_equivalent_irradiance"
    )
    states.loc[
        unresolved_index, "spectral_electrical_equivalent_irradiance_wm2"
    ] = np.nan
    states.loc[unresolved_index, "module_iv_resolved"] = False
    states.loc[unresolved_index, "module_iv_state"] = (
        "unresolved_receiver_module_electrical"
    )
    states.loc[unresolved_index, "string_iv_resolved"] = False
    states.loc[unresolved_index, "string_iv_state"] = (
        "unresolved_receiver_module_electrical"
    )
    curves["b"] = curves["b"].loc[
        ~curves["b"]["timestamp"].eq(timestamps[3])
    ].reset_index(drop=True)
    forged = replace(
        upstream,
        states=states,
        string_iv_curves_by_string_id=curves,
        diagnostics=replace(
            upstream.diagnostics,
            resolved_string_iv_state_count=7,
            unresolved_string_iv_state_count=1,
            zero_string_iv_state_count=3,
            scaled_string_iv_state_count=4,
            iv_curve_row_count=77,
        ),
    )
    original = electrical.calculate_physical_mismatch
    calls: list[list[pd.Timestamp]] = []

    def recording(values: list[pd.DataFrame]) -> pd.DataFrame:
        calls.append(list(pd.unique(values[0]["timestamp"])))
        return original(values)

    monkeypatch.setattr(electrical, "calculate_physical_mismatch", recording)
    result = calculate_topology_mppt_mismatch_from_string_iv(topology, forged)
    assert result.operating_points["mppt_state"].tolist() == [
        "resolved_common_voltage_mppt",
        "resolved_zero_common_voltage_mppt",
        "unresolved_mixed_active_zero_requires_blocking_model",
        "unresolved_member_string_iv",
    ]
    assert calls == [[timestamps[0]]]


def test_multiple_mppts_and_repeated_ids_remain_independent() -> None:
    topology = ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id="inv-a",
                mppts=[
                    MPPTConfig(id="mppt-1", strings=[StringConfig(id="a", modules_per_string=24)]),
                    MPPTConfig(id="mppt-2", strings=[StringConfig(id="b", modules_per_string=30)]),
                ],
            ),
            InverterUnitConfig(
                id="inv-b",
                mppts=[
                    MPPTConfig(
                        id="mppt-1",
                        strings=[StringConfig(id="c", modules_per_string=36)],
                    )
                ],
            ),
        ]
    )
    _, upstream = _real_s81(topology, receiver_count=3)
    result = calculate_topology_mppt_mismatch_from_string_iv(topology, upstream)
    assert list(result.operating_points.index.droplevel("timestamp")) == [
        ("inv-a", "mppt-1"),
        ("inv-a", "mppt-2"),
        ("inv-b", "mppt-1"),
    ]
    assert result.diagnostics.physics_call_count == 3


def test_stale_routing_and_series_length_rejected() -> None:
    topology, upstream = _real_s81()
    stale_count = _topology([("mppt-1", [("string-1", 30)])])
    with pytest.raises(ValueError, match="series length"):
        calculate_topology_mppt_mismatch_from_string_iv(stale_count, upstream)
    stale_route = _topology([("mppt-2", [("string-1", 24)])])
    with pytest.raises(ValueError, match="routing identity"):
        calculate_topology_mppt_mismatch_from_string_iv(stale_route, upstream)
    assert topology.string_count == 1


def test_zone_and_label_only_changes_are_non_authoritative() -> None:
    topology, upstream = _real_s81()
    changed = ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id="inverter-1",
                mppts=[
                    MPPTConfig(
                        id="mppt-1",
                        strings=[
                            StringConfig(
                                id="string-1",
                                modules_per_string=24,
                                zone_id="changed",
                                label="changed",
                            )
                        ],
                    )
                ],
            )
        ]
    )
    result = calculate_topology_mppt_mismatch_from_string_iv(changed, upstream)
    assert result.operating_points.iloc[0]["mppt_resolved"]


def test_invalid_authority_rejected_before_physics(monkeypatch: pytest.MonkeyPatch) -> None:
    topology, upstream = _real_s81()
    states = upstream.states.copy(deep=True)
    states.iloc[0, states.columns.get_loc("topology_string_iv_contract")] = "forged"
    calls = 0

    def forbidden(*args: object, **kwargs: object) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        raise AssertionError("physics called")

    monkeypatch.setattr(electrical, "calculate_physical_mismatch", forbidden)
    with pytest.raises(ValueError, match="provenance"):
        calculate_topology_mppt_mismatch_from_string_iv(
            topology, replace(upstream, states=states)
        )
    assert calls == 0


@pytest.mark.parametrize(
    "field",
    [
        "inverter_count",
        "mppt_count",
        "string_count",
        "timestamp_count",
        "state_row_count",
        "resolved_string_iv_state_count",
        "zero_string_iv_state_count",
        "iv_curve_row_count",
        "voltage_points",
    ],
)
def test_diagnostic_tamper_rejected(field: str) -> None:
    topology, upstream = _real_s81()
    forged = replace(
        upstream,
        diagnostics=replace(
            upstream.diagnostics,
            **{field: cast(Any, getattr(upstream.diagnostics, field) + 1)},
        ),
    )
    with pytest.raises(ValueError):
        calculate_topology_mppt_mismatch_from_string_iv(topology, forged)


def test_string_power_grid_and_active_shape_tamper_rejected() -> None:
    topology, upstream = _real_s81()
    base = upstream.string_iv_curves_by_string_id["string-1"]
    variants: list[pd.DataFrame] = []
    wrong_power = base.copy(deep=True)
    wrong_power.loc[1, "power_w"] += 1.0
    variants.append(wrong_power)
    variants.append(base.iloc[1:].copy())
    duplicate = pd.concat([base, base.iloc[[0]]], ignore_index=True)
    variants.append(duplicate)
    nonzero_start = base.copy(deep=True)
    nonzero_start.loc[0, "voltage_v"] = 1.0
    nonzero_start.loc[0, "power_w"] = nonzero_start.loc[0, "current_a"]
    variants.append(nonzero_start)
    for curve in variants:
        with pytest.raises(ValueError):
            calculate_topology_mppt_mismatch_from_string_iv(
                topology, _replace_curve(upstream, "string-1", curve)
            )


def test_shared_receiver_normalized_forgery_rejected() -> None:
    topology = _topology([("mppt-1", [("a", 24), ("b", 30)])])
    _, upstream = _real_s81(topology)
    curve = upstream.string_iv_curves_by_string_id["b"].copy(deep=True)
    curve["voltage_v"] *= 0.9
    curve["power_w"] *= 0.9
    with pytest.raises(ValueError, match="shared-receiver"):
        calculate_topology_mppt_mismatch_from_string_iv(
            topology, _replace_curve(upstream, "b", curve)
        )


def test_empty_time_topology_and_empty_mppt() -> None:
    topology, upstream = _real_s81(periods=0)
    empty_time = calculate_topology_mppt_mismatch_from_string_iv(topology, upstream)
    assert empty_time.operating_points.empty
    assert empty_time.operating_points.index.names == ["timestamp", "inverter_id", "mppt_id"]
    assert tuple(empty_time.operating_points.columns) == electrical._TOPOLOGY_MPPT_MISMATCH_COLUMNS

    empty_topology = ElectricalTopologyConfig(inverters=[])
    _, empty_upstream = _real_s81(empty_topology)
    empty = calculate_topology_mppt_mismatch_from_string_iv(empty_topology, empty_upstream)
    assert empty.operating_points.empty
    assert empty.diagnostics.mppt_count == 0

    empty_mppt_topology = _topology([("empty", []), ("live", [("string-1", 24)])])
    _, mixed_upstream = _real_s81(empty_mppt_topology)
    mixed = calculate_topology_mppt_mismatch_from_string_iv(
        empty_mppt_topology, mixed_upstream
    )
    assert mixed.diagnostics.empty_mppt_count == 1
    assert mixed.diagnostics.populated_mppt_count == 1
    assert set(mixed.operating_points.index.get_level_values("mppt_id")) == {"live"}


def test_reordering_determinism_immutability_and_exact_type() -> None:
    topology = _topology([("mppt-1", [("a", 24), ("b", 24)])])
    _, upstream = _real_s81(topology, periods=2)
    states_before = upstream.states.copy(deep=True)
    curves_before = {
        key: frame.copy(deep=True)
        for key, frame in upstream.string_iv_curves_by_string_id.items()
    }
    reordered = replace(
        upstream,
        states=upstream.states.iloc[::-1].copy(deep=True),
        string_iv_curves_by_string_id={
            key: frame.iloc[::-1].copy(deep=True)
            for key, frame in reversed(list(upstream.string_iv_curves_by_string_id.items()))
        },
    )
    normal = calculate_topology_mppt_mismatch_from_string_iv(topology, upstream)
    changed = calculate_topology_mppt_mismatch_from_string_iv(topology, reordered)
    pd.testing.assert_frame_equal(normal.operating_points, changed.operating_points)
    pd.testing.assert_frame_equal(upstream.states, states_before)
    for key, before in curves_before.items():
        pd.testing.assert_frame_equal(upstream.string_iv_curves_by_string_id[key], before)
    with pytest.raises(ValueError, match="exact TopologyStringIVResult"):
        calculate_topology_mppt_mismatch_from_string_iv(topology, cast(Any, {}))
