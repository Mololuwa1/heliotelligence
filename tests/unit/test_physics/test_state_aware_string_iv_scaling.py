"""Tests for canonical S8-1 state-aware physical string-I-V scaling."""

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
    TOPOLOGY_STRING_IV_CONTRACT_ID,
    TOPOLOGY_STRING_IV_COVERAGE_SCOPE,
    TOPOLOGY_STRING_IV_MODEL_ID,
    TOPOLOGY_STRING_IV_SCOPE,
    ReceiverStringModuleIVResult,
    TopologyStringIVResult,
    calculate_topology_string_iv_curves_from_receiver_module_iv,
)

s8_support: Any = importlib.import_module(
    "tests.unit.test_physics.test_receiver_string_module_iv_routing"
)


def _topology(specs: list[tuple[str, str | None, int]]) -> ElectricalTopologyConfig:
    return cast(ElectricalTopologyConfig, s8_support._topology(specs))


def _real_s8(
    topology: ElectricalTopologyConfig | None = None,
    *,
    periods: int = 1,
) -> tuple[ElectricalTopologyConfig, ReceiverStringModuleIVResult]:
    receivers = s8_support._receivers()
    spectral = s8_support._spectral(receivers, periods=periods)
    handoff = s8_support._electrical(receivers, spectral=spectral)
    active = topology or _topology([("string-1", "unused", 24)])
    assignments = {
        string.id: receivers[0].id
        for inverter in active.inverters
        for mppt in inverter.mppts
        for string in mppt.strings
    }
    result = s8_support._route(
        receivers,
        handoff,
        topology=active,
        assignments=assignments,
        voltage_points=11,
    )
    return active, cast(ReceiverStringModuleIVResult, result)


def _replace_curve(
    result: ReceiverStringModuleIVResult,
    string_id: str,
    frame: pd.DataFrame,
) -> ReceiverStringModuleIVResult:
    curves = {
        key: value.copy(deep=True)
        for key, value in result.module_iv_curves_by_string_id.items()
    }
    curves[string_id] = frame
    return replace(result, module_iv_curves_by_string_id=curves)


def test_real_series_physics_and_contract() -> None:
    topology, upstream = _real_s8()
    result = calculate_topology_string_iv_curves_from_receiver_module_iv(topology, upstream)
    assert type(result) is TopologyStringIVResult
    module = upstream.module_iv_curves_by_string_id["string-1"]
    string = result.string_iv_curves_by_string_id["string-1"]
    np.testing.assert_allclose(string["voltage_v"], module["voltage_v"] * 24)
    np.testing.assert_allclose(string["current_a"], module["current_a"])
    np.testing.assert_allclose(string["power_w"], module["power_w"] * 24)
    np.testing.assert_allclose(string["power_w"], string["voltage_v"] * string["current_a"])
    row = result.states.iloc[0]
    assert row["modules_per_string"] == 24
    assert row["string_iv_state"] == "resolved_string_iv"
    assert row["topology_string_iv_contract"] == TOPOLOGY_STRING_IV_CONTRACT_ID
    assert row["topology_string_iv_model"] == TOPOLOGY_STRING_IV_MODEL_ID
    assert row["topology_string_iv_scope"] == TOPOLOGY_STRING_IV_SCOPE
    assert row["topology_string_iv_coverage_scope"] == TOPOLOGY_STRING_IV_COVERAGE_SCOPE


def test_shared_receiver_24_30_36_current_invariant_and_one_scaler_each(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology([("a", None, 24), ("b", None, 30), ("c", None, 36)])
    _, upstream = _real_s8(topology)
    original = electrical.scale_module_iv_to_string
    calls: list[int] = []

    def recording(frame: pd.DataFrame, count: int) -> pd.DataFrame:
        calls.append(count)
        return original(frame, count)

    monkeypatch.setattr(electrical, "scale_module_iv_to_string", recording)
    result = calculate_topology_string_iv_curves_from_receiver_module_iv(topology, upstream)
    a, b, c = (result.string_iv_curves_by_string_id[key] for key in ("a", "b", "c"))
    np.testing.assert_allclose(a["current_a"], b["current_a"])
    np.testing.assert_allclose(a["current_a"], c["current_a"])
    nonzero = (a["voltage_v"] > 0) & (a["power_w"] > 0)
    np.testing.assert_allclose(b.loc[nonzero, "voltage_v"] / a.loc[nonzero, "voltage_v"], 30 / 24)
    np.testing.assert_allclose(c.loc[nonzero, "power_w"] / a.loc[nonzero, "power_w"], 36 / 24)
    assert calls == [24, 30, 36]


def test_current_topology_module_count_is_authority() -> None:
    original, upstream = _real_s8()
    current = _topology([("string-1", "different-zone", 31)])
    result = calculate_topology_string_iv_curves_from_receiver_module_iv(current, upstream)
    module = upstream.module_iv_curves_by_string_id["string-1"]
    np.testing.assert_allclose(
        result.string_iv_curves_by_string_id["string-1"]["voltage_v"],
        module["voltage_v"] * 31,
    )
    assert original.inverter_count == current.inverter_count


def test_topology_move_is_rejected() -> None:
    topology, upstream = _real_s8()
    moved = ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id="inverter-2",
                mppts=[
                    MPPTConfig(
                        id="mppt-2",
                        strings=[StringConfig(id="string-1", modules_per_string=24)],
                    )
                ],
            )
        ]
    )
    with pytest.raises(ValueError, match="topology identity"):
        calculate_topology_string_iv_curves_from_receiver_module_iv(moved, upstream)
    assert topology.string_count == 1


def test_shared_receiver_coherent_curve_forgery_is_rejected() -> None:
    topology = _topology([("a", None, 24), ("b", None, 30)])
    _, upstream = _real_s8(topology)
    forged = upstream.module_iv_curves_by_string_id["b"].copy(deep=True)
    forged["voltage_v"] *= 0.9
    forged["power_w"] *= 0.9
    with pytest.raises(ValueError, match="sharing a receiver"):
        calculate_topology_string_iv_curves_from_receiver_module_iv(
            topology, _replace_curve(upstream, "b", forged)
        )


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("power_w", 123.0, "power"),
        ("effective_irradiance_wm2", 777.0, "irradiance"),
        ("voltage_v", np.nan, "finite"),
        ("current_a", np.inf, "finite"),
        ("voltage_v", -1.0, "non-negative"),
    ],
)
def test_curve_value_tampering_is_rejected(column: str, value: float, message: str) -> None:
    topology, upstream = _real_s8()
    forged = upstream.module_iv_curves_by_string_id["string-1"].copy(deep=True)
    forged.loc[0, column] = value
    with pytest.raises(ValueError, match=message):
        calculate_topology_string_iv_curves_from_receiver_module_iv(
            topology, _replace_curve(upstream, "string-1", forged)
        )


@pytest.mark.parametrize("mode", ["missing", "duplicate", "extra", "wrong_timestamp"])
def test_curve_grid_tampering_is_rejected(mode: str) -> None:
    topology, upstream = _real_s8()
    curve = upstream.module_iv_curves_by_string_id["string-1"].copy(deep=True)
    if mode == "missing":
        curve = curve.iloc[1:].copy()
    elif mode == "duplicate":
        curve = pd.concat([curve, curve.iloc[[0]]], ignore_index=True)
    elif mode == "extra":
        extra = curve.iloc[[0]].copy()
        extra["curve_point"] = 99
        curve = pd.concat([curve, extra], ignore_index=True)
    else:
        curve.loc[0, "timestamp"] += pd.Timedelta(hours=1)
    with pytest.raises(ValueError):
        calculate_topology_string_iv_curves_from_receiver_module_iv(
            topology, _replace_curve(upstream, "string-1", curve)
        )


def test_invalid_authority_rejected_before_scaling(monkeypatch: pytest.MonkeyPatch) -> None:
    topology, upstream = _real_s8()
    states = upstream.states.copy(deep=True)
    states.iloc[0, states.columns.get_loc("receiver_string_module_iv_contract")] = "forged"
    forged = replace(upstream, states=states)
    calls = 0

    def forbidden(*args: object, **kwargs: object) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        raise AssertionError("scaler called")

    monkeypatch.setattr(electrical, "scale_module_iv_to_string", forbidden)
    with pytest.raises(ValueError, match="provenance"):
        calculate_topology_string_iv_curves_from_receiver_module_iv(topology, forged)
    assert calls == 0


def test_exact_type_and_diagnostic_tamper_rejected() -> None:
    topology, upstream = _real_s8()
    with pytest.raises(ValueError, match="exact result"):
        calculate_topology_string_iv_curves_from_receiver_module_iv(topology, cast(Any, {}))
    stale = replace(
        upstream,
        diagnostics=replace(upstream.diagnostics, solved_iv_state_count=99),
    )
    with pytest.raises(ValueError, match="diagnostics"):
        calculate_topology_string_iv_curves_from_receiver_module_iv(topology, stale)


def test_input_reordering_immutability_and_output_isolation() -> None:
    topology = _topology([("a", None, 24), ("b", None, 30)])
    _, upstream = _real_s8(topology, periods=2)
    states_before = upstream.states.copy(deep=True)
    curves_before = {
        key: frame.copy(deep=True)
        for key, frame in upstream.module_iv_curves_by_string_id.items()
    }
    reordered = replace(
        upstream,
        states=upstream.states.iloc[::-1].copy(deep=True),
        module_iv_curves_by_string_id={
            key: frame.iloc[::-1].copy(deep=True)
            for key, frame in reversed(list(upstream.module_iv_curves_by_string_id.items()))
        },
    )
    normal = calculate_topology_string_iv_curves_from_receiver_module_iv(topology, upstream)
    changed = calculate_topology_string_iv_curves_from_receiver_module_iv(topology, reordered)
    pd.testing.assert_frame_equal(normal.states, changed.states)
    for key in ("a", "b"):
        pd.testing.assert_frame_equal(
            normal.string_iv_curves_by_string_id[key],
            changed.string_iv_curves_by_string_id[key],
        )
    pd.testing.assert_frame_equal(upstream.states, states_before)
    for key, before in curves_before.items():
        pd.testing.assert_frame_equal(upstream.module_iv_curves_by_string_id[key], before)
    normal.string_iv_curves_by_string_id["a"].iloc[0, 2] = -99.0
    assert upstream.module_iv_curves_by_string_id["a"].iloc[0, 2] >= 0
    assert normal.string_iv_curves_by_string_id["b"].iloc[0, 2] >= 0


def test_empty_time_and_empty_topology() -> None:
    topology, upstream = _real_s8(periods=0)
    result = calculate_topology_string_iv_curves_from_receiver_module_iv(topology, upstream)
    assert result.states.empty
    assert tuple(result.states.columns) == electrical._TOPOLOGY_STRING_IV_STATE_COLUMNS
    assert result.string_iv_curves_by_string_id["string-1"].empty
    assert result.diagnostics.state_row_count == 0

    receivers = s8_support._receivers()
    handoff = s8_support._electrical(receivers)
    empty_topology = ElectricalTopologyConfig(inverters=[])
    empty_upstream = s8_support._route(
        receivers,
        handoff,
        topology=empty_topology,
        assignments={},
        policy="allow_unassigned_receivers",
    )
    empty = calculate_topology_string_iv_curves_from_receiver_module_iv(
        empty_topology, empty_upstream
    )
    assert empty.string_iv_curves_by_string_id == {}
    assert empty.states.empty
    assert empty.diagnostics.string_count == 0


def test_zero_and_tier5_root_causes_are_preserved() -> None:
    receivers = s8_support._receivers()
    topology = _topology([("string-1", None, 24)])
    site = s8_support._site(tier5=True)
    positive = s8_support._electrical(receivers, site=site)
    positive_upstream = s8_support._route(
        receivers, positive, topology=topology, site=site, voltage_points=7
    )
    positive_result = calculate_topology_string_iv_curves_from_receiver_module_iv(
        topology, positive_upstream
    )
    assert positive_result.string_iv_curves_by_string_id["string-1"].empty
    assert positive_result.states.iloc[0]["string_iv_state"] == (
        "unresolved_tier5_voltage_dependent_iv_unavailable"
    )

    zero_spectral = s8_support._spectral(receivers, front=0.0, rear=0.0)
    zero = s8_support._electrical(receivers, site=site, spectral=zero_spectral)
    zero_upstream = s8_support._route(
        receivers, zero, topology=topology, site=site, voltage_points=7
    )
    zero_result = calculate_topology_string_iv_curves_from_receiver_module_iv(
        topology, zero_upstream
    )
    curve = zero_result.string_iv_curves_by_string_id["string-1"]
    assert curve[["voltage_v", "current_a", "power_w"]].eq(0.0).all().all()
    assert zero_result.states.iloc[0]["string_iv_state"] == "resolved_zero_string_iv"


def test_mixed_positive_zero_unresolved_handoff() -> None:
    receivers = s8_support._receivers()
    topology = _topology([("string-1", None, 24)])
    spectral = s8_support._spectral(receivers, periods=3)
    handoff = s8_support._electrical(receivers, spectral=spectral)
    frame = handoff.operating_points.copy(deep=True)
    zero_index, unresolved_index = frame.index[1], frame.index[2]
    frame.loc[zero_index, "spectral_electrical_equivalent_irradiance_wm2"] = 0.0
    frame.loc[zero_index, ["p_mp_w", "v_mp_v", "i_mp_a"]] = 0.0
    frame.loc[zero_index, "module_electrical_state"] = (
        "resolved_zero_spectral_electrical_irradiance"
    )
    frame.loc[unresolved_index, "spectral_electrical_equivalent_irradiance_wm2"] = np.nan
    frame.loc[unresolved_index, "spectral_electrical_equivalent_resolved"] = False
    frame.loc[unresolved_index, "spectral_electrical_equivalent_state"] = (
        "unresolved_front_spectral_response"
    )
    frame.loc[unresolved_index, ["p_mp_w", "v_mp_v", "i_mp_a"]] = np.nan
    frame.loc[unresolved_index, "module_electrical_resolved"] = False
    frame.loc[unresolved_index, "module_electrical_state"] = (
        "unresolved_spectral_electrical_equivalent_irradiance"
    )
    mixed = replace(
        handoff,
        operating_points=frame,
        diagnostics=replace(
            handoff.diagnostics,
            resolved_row_count=2,
            unresolved_row_count=1,
            zero_irradiance_row_count=1,
            solver_row_count=1,
        ),
    )
    upstream = s8_support._route(
        receivers, mixed, topology=topology, voltage_points=7
    )
    result = calculate_topology_string_iv_curves_from_receiver_module_iv(topology, upstream)
    assert result.states["string_iv_state"].tolist() == [
        "resolved_string_iv",
        "resolved_zero_string_iv",
        "unresolved_receiver_module_electrical",
    ]
    assert len(result.string_iv_curves_by_string_id["string-1"]) == 14


def test_downstream_mppt_compatibility_with_stage4_scaler() -> None:
    topology = _topology([("a", None, 24), ("b", None, 30)])
    _, upstream = _real_s8(topology)
    canonical = calculate_topology_string_iv_curves_from_receiver_module_iv(
        topology, upstream
    )
    legacy_scaled = electrical.calculate_topology_string_iv_curves(
        topology, upstream.module_iv_curves_by_string_id
    )
    canonical_mppt = electrical.calculate_topology_mppt_mismatch(
        topology, canonical.string_iv_curves_by_string_id
    )
    legacy_mppt = electrical.calculate_topology_mppt_mismatch(topology, legacy_scaled)
    pd.testing.assert_frame_equal(canonical_mppt, legacy_mppt)
