"""Tests for S11C balanced radial LV AC operating solve."""

from __future__ import annotations

import importlib
import math
from dataclasses import replace
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics.inverter_ac_authority import (
    resolve_topology_inverter_ac_capability_authority,
)
from heliotelligence.physics.inverter_thermal_authority import (
    resolve_topology_inverter_thermal_derating_authority,
)
from heliotelligence.physics.lv_ac_collection_authority import (
    LvAcCollectionNetworkBasisAuthority,
    LvAcCollectionNodeAuthority,
    LvAcCollectionSegmentAuthority,
    LvAcInverterTerminalBindingAuthority,
    resolve_topology_lv_ac_collection_authority,
)
from heliotelligence.physics.lv_ac_collection_operating import (
    TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_CONTRACT_ID,
    TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_MODEL_ID,
    _solve_balanced_radial_tree,
    _validate_result,
    calculate_topology_lv_ac_collection_operating_solution,
)
from heliotelligence.physics.lv_ac_collection_voltage_authority import (
    LvAcCollectionExitVoltageState,
    resolve_topology_lv_ac_collection_exit_voltage_authority,
)

s10b: Any = importlib.import_module("tests.unit.test_physics.test_inverter_dispatch_feasibility")
s10c: Any = importlib.import_module("tests.unit.test_physics.test_inverter_dispatch_selection")
_PUBLIC_CACHE: dict[tuple[float | None, float | None, float | None], tuple[Any, ...]] = {}


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        inverter_lookup, "_load_cec_inverter_database", s10b.conversion_support._database
    )
    monkeypatch.setattr(
        inverter_envelope_lookup,
        "_load_cec_inverter_database",
        s10b.conversion_support._database,
    )


def _basis() -> LvAcCollectionNetworkBasisAuthority:
    return LvAcCollectionNetworkBasisAuthority(
        "balanced_three_phase", "line_to_line_rms", "per_phase_series", "drawing", "high"
    )


def _node(node_id: str, kind: str) -> LvAcCollectionNodeAuthority:
    return LvAcCollectionNodeAuthority(node_id, kind, "drawing", "high")  # type: ignore[arg-type]


def _segment(
    segment_id: str,
    source: str,
    destination: str,
    resistance: float = 0.0,
    reactance: float = 0.0,
) -> LvAcCollectionSegmentAuthority:
    return LvAcCollectionSegmentAuthority(
        segment_id, source, destination, resistance, reactance, "schedule", "high"
    )


def _binding(inverter_id: str, node_id: str) -> LvAcInverterTerminalBindingAuthority:
    return LvAcInverterTerminalBindingAuthority(
        inverter_id, node_id, "inverter_ac_output", "drawing", "high"
    )


def _voltage(value: float = 400.0) -> LvAcCollectionExitVoltageState:
    return LvAcCollectionExitVoltageState(
        value, "line_to_line_rms", "lv_ac_collection_exit", "meter", "high"
    )


def _single_tree(
    resistance: float = 0.0, reactance: float = 0.0
) -> tuple[
    dict[str, LvAcCollectionNodeAuthority],
    dict[str, LvAcCollectionSegmentAuthority],
]:
    nodes = {
        "terminal": _node("terminal", "inverter_terminal"),
        "exit": _node("exit", "collection_exit"),
    }
    segments = {"feeder": _segment("feeder", "terminal", "exit", resistance, reactance)}
    return nodes, segments


def test_pure_zero_impedance_preserves_voltage_and_has_zero_loss() -> None:
    nodes, segments = _single_tree()
    solved = _solve_balanced_radial_tree("exit", 400.0, nodes, segments, {"terminal": 9000 + 0j})
    assert solved.converged
    assert solved.node_voltages_phase_v["terminal"] == solved.node_voltages_phase_v["exit"]
    assert solved.segment_currents_phase_a["feeder"] == pytest.approx(
        complex(9000 / (math.sqrt(3) * 400), 0), abs=1e-12
    )


def test_pure_zero_dispatch_has_zero_current_and_flat_voltage() -> None:
    nodes, segments = _single_tree(0.1, 0.05)
    solved = _solve_balanced_radial_tree("exit", 400.0, nodes, segments, {"terminal": 0j})
    assert solved.converged
    assert solved.segment_currents_phase_a["feeder"] == 0j
    assert solved.node_voltages_phase_v["terminal"] == solved.node_voltages_phase_v["exit"]


def test_pure_resistive_export_voltage_rise_and_analytic_solution() -> None:
    resistance = 0.2
    power = 12000.0
    nodes, segments = _single_tree(resistance, 0.0)
    solved = _solve_balanced_radial_tree("exit", 400.0, nodes, segments, {"terminal": power + 0j})
    assert solved.converged
    exit_phase = 400.0 / math.sqrt(3.0)
    expected_current = (
        -3 * exit_phase + math.sqrt((3 * exit_phase) ** 2 + 12 * resistance * power)
    ) / (6 * resistance)
    assert solved.segment_currents_phase_a["feeder"].real == pytest.approx(
        expected_current, abs=1e-7
    )
    assert solved.node_voltages_phase_v["terminal"].real == pytest.approx(
        exit_phase + resistance * expected_current, abs=1e-7
    )
    assert abs(solved.node_voltages_phase_v["terminal"]) > abs(solved.node_voltages_phase_v["exit"])


@pytest.mark.parametrize("reactive", [4000.0, -4000.0])
def test_pure_complex_injection_and_absorption_close_equations(reactive: float) -> None:
    nodes, segments = _single_tree(0.1, 0.08)
    selected = 10000 + 1j * reactive
    solved = _solve_balanced_radial_tree("exit", 400.0, nodes, segments, {"terminal": selected})
    assert solved.converged
    voltage = solved.node_voltages_phase_v["terminal"]
    current = solved.segment_currents_phase_a["feeder"]
    assert 3 * voltage * current.conjugate() == pytest.approx(selected, abs=1e-5)
    assert voltage - solved.node_voltages_phase_v["exit"] == pytest.approx(
        complex(0.1, 0.08) * current, abs=1e-7
    )


def test_shared_segment_uses_aggregate_current_and_i_squared_loss() -> None:
    nodes = {
        "ta": _node("ta", "inverter_terminal"),
        "tb": _node("tb", "inverter_terminal"),
        "j": _node("j", "junction"),
        "exit": _node("exit", "collection_exit"),
    }
    segments = {
        "a": _segment("a", "ta", "j", 0.01),
        "b": _segment("b", "tb", "j", 0.01),
        "shared": _segment("shared", "j", "exit", 0.1),
    }
    solved = _solve_balanced_radial_tree(
        "exit", 400.0, nodes, segments, {"ta": 6000 + 0j, "tb": 9000 + 0j}
    )
    assert solved.converged
    ia = solved.segment_currents_phase_a["a"]
    ib = solved.segment_currents_phase_a["b"]
    shared = solved.segment_currents_phase_a["shared"]
    assert shared == pytest.approx(ia + ib, abs=1e-9)
    assert 3 * 0.1 * abs(shared) ** 2 > 3 * 0.1 * (abs(ia) ** 2 + abs(ib) ** 2)


def test_multilevel_and_passive_branch_solve_deterministically() -> None:
    nodes = {
        "t": _node("t", "inverter_terminal"),
        "passive": _node("passive", "junction"),
        "j1": _node("j1", "junction"),
        "j2": _node("j2", "junction"),
        "exit": _node("exit", "collection_exit"),
    }
    segments = {
        "s1": _segment("s1", "t", "j1", 0.02, 0.01),
        "passive": _segment("passive", "passive", "j1", 0.1, 0.1),
        "s2": _segment("s2", "j1", "j2", 0.02, 0.01),
        "s3": _segment("s3", "j2", "exit", 0.02, 0.01),
    }
    first = _solve_balanced_radial_tree("exit", 400.0, nodes, segments, {"t": 10000 + 2000j})
    second = _solve_balanced_radial_tree(
        "exit",
        400.0,
        dict(reversed(list(nodes.items()))),
        dict(reversed(list(segments.items()))),
        {"t": 10000 + 2000j},
    )
    assert first.converged and second.converged
    assert first.node_voltages_phase_v == second.node_voltages_phase_v
    assert first.segment_currents_phase_a == second.segment_currents_phase_a
    assert first.segment_currents_phase_a["passive"] == 0j


def test_two_independent_trees_use_independent_exit_references() -> None:
    nodes_a, segments_a = _single_tree(0.05, 0.01)
    nodes_b = {
        "terminal-b": _node("terminal-b", "inverter_terminal"),
        "exit-b": _node("exit-b", "collection_exit"),
    }
    segments_b = {"feeder-b": _segment("feeder-b", "terminal-b", "exit-b", 0.08, 0.03)}
    solved_a = _solve_balanced_radial_tree(
        "exit", 400.0, nodes_a, segments_a, {"terminal": 8000 + 1000j}
    )
    solved_b = _solve_balanced_radial_tree(
        "exit-b", 415.0, nodes_b, segments_b, {"terminal-b": 12000 - 2000j}
    )
    assert solved_a.converged and solved_b.converged
    assert solved_a.node_voltages_phase_v["exit"] == pytest.approx(400.0 / math.sqrt(3.0))
    assert solved_b.node_voltages_phase_v["exit-b"] == pytest.approx(415.0 / math.sqrt(3.0))


def test_zero_exit_voltage_zero_dispatch_is_resolved_zero() -> None:
    nodes, segments = _single_tree(0.1, 0.1)
    solved = _solve_balanced_radial_tree("exit", 0.0, nodes, segments, {"terminal": 0j})
    assert solved.converged
    assert set(solved.node_voltages_phase_v.values()) == {0j}
    assert set(solved.segment_currents_phase_a.values()) == {0j}


@pytest.mark.parametrize("power", [1000 + 0j, 0 + 1000j])
def test_zero_exit_voltage_nonzero_power_is_singular(power: complex) -> None:
    nodes, segments = _single_tree()
    solved = _solve_balanced_radial_tree("exit", 0.0, nodes, segments, {"terminal": power})
    assert not solved.converged
    assert solved.failure == "zero_voltage_nonzero_power"


def _public_setup(
    *, p: float | None = 100.0, q: float | None = 0.0, voltage_value: float | None = 400.0
) -> tuple[tuple[Any, ...], Any, Any, Any]:
    cache_key = (p, q, voltage_value)
    cached = _PUBLIC_CACHE.get(cache_key)
    if cached is not None:
        return cached
    setup = s10b._setup(p=p, q=q)
    dispatch = s10c._run(setup)
    context, parent, thermal_mapping, temperatures, p_requests, request_authority = setup
    topology, upstream, accounting, capabilities, q_requests, pqs = context
    (
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        names,
        inverter_authority,
        limits,
        envelope,
        inverter_ac,
        potential,
    ) = upstream
    ac_authority = resolve_topology_inverter_ac_capability_authority(topology, capabilities)
    thermal_authority = resolve_topology_inverter_thermal_derating_authority(
        topology, thermal_mapping
    )
    nodes, segments = _single_tree(0.05, 0.02)
    bindings = {topology.inverters[0].id: _binding(topology.inverters[0].id, "terminal")}
    network = resolve_topology_lv_ac_collection_authority(
        topology, _basis(), nodes, segments, bindings
    )
    timestamp = pd.Timestamp(dispatch.dispatch.index[0][0])
    voltage_mapping = (
        {} if voltage_value is None else {(timestamp, "exit"): _voltage(voltage_value)}
    )
    voltage = resolve_topology_lv_ac_collection_exit_voltage_authority(
        topology, _basis(), nodes, segments, bindings, network, voltage_mapping
    )
    arguments = (
        topology,
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        names,
        inverter_authority,
        limits,
        envelope,
        inverter_ac,
        potential,
        accounting,
        capabilities,
        ac_authority,
        q_requests,
        pqs,
        thermal_mapping,
        thermal_authority,
        temperatures,
        parent,
        p_requests,
        request_authority,
        s10b._run(setup),
        dispatch,
        _basis(),
        nodes,
        segments,
        bindings,
        network,
        voltage_mapping,
        voltage,
    )
    answer = (arguments, dispatch, network, voltage)
    _PUBLIC_CACHE[cache_key] = answer
    return answer


def _public(arguments: tuple[Any, ...]) -> Any:
    return calculate_topology_lv_ac_collection_operating_solution(*arguments)


def _replace_network_inputs(
    arguments: tuple[Any, ...],
    nodes: dict[str, LvAcCollectionNodeAuthority],
    segments: dict[str, LvAcCollectionSegmentAuthority],
    bindings: dict[str, LvAcInverterTerminalBindingAuthority],
    voltage_mapping: dict[tuple[pd.Timestamp, str], LvAcCollectionExitVoltageState],
) -> tuple[tuple[Any, ...], Any, Any]:
    values = list(arguments)
    topology = values[0]
    basis = values[24]
    network = resolve_topology_lv_ac_collection_authority(
        topology, basis, nodes, segments, bindings
    )
    voltage = resolve_topology_lv_ac_collection_exit_voltage_authority(
        topology, basis, nodes, segments, bindings, network, voltage_mapping
    )
    values[25:31] = [nodes, segments, bindings, network, voltage_mapping, voltage]
    return tuple(values), network, voltage


def test_public_full_solve_has_canonical_outputs_and_conservation() -> None:
    arguments, _, _, _ = _public_setup(p=100.0, q=20.0)
    result = _public(arguments)
    tree = result.collection_exit_states.iloc[0]
    assert tree["lv_ac_collection_operating_state"] == (
        "resolved_balanced_radial_lv_ac_operating_solution"
    )
    assert tree["lv_ac_operating_solution_resolved"]
    assert tree["active_power_conservation_residual_w"] == pytest.approx(0.0, abs=1e-6)
    assert tree["reactive_power_conservation_residual_var"] == pytest.approx(0.0, abs=1e-6)
    assert result.collection_exit_states.index.names == ["timestamp", "collection_exit_node_id"]
    assert result.node_states.index.names == ["timestamp", "node_id"]
    assert result.segment_states.index.names == ["timestamp", "segment_id"]
    assert tree["topology_lv_ac_collection_operating_solution_contract"] == (
        TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_CONTRACT_ID
    )
    assert result.diagnostics.model == TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_MODEL_ID


def test_public_missing_selected_dispatch_is_not_zero() -> None:
    arguments, _, _, _ = _public_setup(p=None)
    result = _public(arguments)
    tree = result.collection_exit_states.iloc[0]
    assert tree["lv_ac_collection_operating_state"] == (
        "unresolved_missing_selected_dispatch_for_collection_tree"
    )
    assert pd.isna(tree["p_delivered_at_collection_exit_w"])
    assert result.node_states["voltage_phase_real_v"].isna().all()


def test_public_missing_exit_voltage_is_unresolved_without_nearest_value() -> None:
    arguments, _, _, _ = _public_setup(voltage_value=None)
    result = _public(arguments)
    assert result.collection_exit_states.iloc[0]["lv_ac_collection_operating_state"] == (
        "unresolved_missing_collection_exit_voltage_authority"
    )


def test_s11b_extra_timestamp_does_not_create_s11c_rows() -> None:
    arguments, dispatch, _, _ = _public_setup()
    timestamp = pd.Timestamp(dispatch.dispatch.index[0][0])
    nodes = arguments[25]
    segments = arguments[26]
    bindings = arguments[27]
    voltage_mapping = {
        (timestamp, "exit"): _voltage(400.0),
        (timestamp + pd.Timedelta(hours=1), "exit"): _voltage(410.0),
    }
    changed, _, _ = _replace_network_inputs(arguments, nodes, segments, bindings, voltage_mapping)
    result = _public(changed)
    assert result.collection_exit_states.index.get_level_values("timestamp").unique().tolist() == [
        timestamp
    ]


def test_global_inverter_topology_membership_must_be_closed() -> None:
    arguments, dispatch, _, _ = _public_setup()
    timestamp = pd.Timestamp(dispatch.dispatch.index[0][0])
    nodes = {"exit": _node("exit", "collection_exit")}
    changed, _, _ = _replace_network_inputs(
        arguments,
        nodes,
        {},
        {},
        {(timestamp, "exit"): _voltage(400.0)},
    )
    result = _public(changed)
    assert result.collection_exit_states.iloc[0]["lv_ac_collection_operating_state"] == (
        "unresolved_incomplete_lv_ac_inverter_topology_authority"
    )
    assert result.node_states["voltage_phase_real_v"].isna().all()


def test_disconnected_passive_orphan_does_not_block_closed_tree() -> None:
    arguments, dispatch, _, _ = _public_setup()
    timestamp = pd.Timestamp(dispatch.dispatch.index[0][0])
    nodes, segments = _single_tree(0.05, 0.02)
    nodes["orphan-a"] = _node("orphan-a", "junction")
    nodes["orphan-b"] = _node("orphan-b", "junction")
    segments["orphan"] = _segment("orphan", "orphan-a", "orphan-b", 0.1, 0.1)
    inverter_id = arguments[0].inverters[0].id
    bindings = {inverter_id: _binding(inverter_id, "terminal")}
    changed, _, _ = _replace_network_inputs(
        arguments,
        nodes,
        segments,
        bindings,
        {(timestamp, "exit"): _voltage(400.0)},
    )
    result = _public(changed)
    assert result.collection_exit_states.iloc[0]["lv_ac_operating_solution_resolved"]
    assert result.node_states.loc[(timestamp, "orphan-a"), "node_operating_state"] == (
        "unresolved_node_not_connected_to_collection_exit"
    )
    assert pd.isna(result.segment_states.loc[(timestamp, "orphan"), "current_phase_real_a"])


@pytest.mark.parametrize("value", [0.0])
def test_public_zero_voltage_nonzero_dispatch_is_unresolved(value: float) -> None:
    arguments, _, _, _ = _public_setup(p=100.0, voltage_value=value)
    result = _public(arguments)
    assert result.collection_exit_states.iloc[0]["lv_ac_collection_operating_state"] == (
        "unresolved_zero_exit_voltage_with_nonzero_selected_power"
    )


@pytest.mark.parametrize("parent_index", [23, 28, 30])
def test_public_strong_parent_replay_rejects_tampering(parent_index: int) -> None:
    arguments, _, _, _ = _public_setup()
    values = list(arguments)
    parent = values[parent_index]
    if parent_index == 23:
        frame = parent.dispatch.copy(deep=True)
        frame.iloc[0, frame.columns.get_loc("p_selected_w")] += 1.0
        values[parent_index] = replace(parent, dispatch=frame)
    elif parent_index == 28:
        frame = parent.inverter_states.copy(deep=True)
        frame.iloc[0, frame.columns.get_loc("collection_exit_node_id")] = "bad"
        values[parent_index] = replace(parent, inverter_states=frame)
    else:
        values[parent_index] = replace(
            parent,
            diagnostics=replace(parent.diagnostics, voltage_state_present_count=0),
        )
    with pytest.raises(RuntimeError, match="S10C|S11A|S11B"):
        _public(tuple(values))


@pytest.mark.parametrize(
    ("frame_name", "column", "delta"),
    [
        ("node_states", "voltage_phase_real_v", 1.0),
        ("node_states", "collection_exit_node_id", "bad"),
        ("segment_states", "current_phase_real_a", 1.0),
        ("segment_states", "active_series_loss_w", 1.0),
        ("segment_states", "reactive_series_consumption_var", 1.0),
        ("segment_states", "p_from_w", 1.0),
        ("segment_states", "p_to_w", 1.0),
        ("segment_states", "phase_voltage_difference_from_to_real_v", 1.0),
        ("collection_exit_states", "p_delivered_at_collection_exit_w", 1.0),
        ("collection_exit_states", "q_delivered_at_collection_exit_var", 1.0),
        ("collection_exit_states", "total_active_series_loss_w", 1.0),
        ("collection_exit_states", "selected_p_total_w", 1.0),
        ("collection_exit_states", "lv_ac_collection_operating_state", "bad"),
        ("collection_exit_states", "network_solve_converged", False),
    ],
)
def test_private_validator_rejects_output_tampering(
    frame_name: str, column: str, delta: object
) -> None:
    arguments, dispatch, network, voltage = _public_setup()
    result = _public(arguments)
    frame = getattr(result, frame_name).copy(deep=True)
    location = frame.columns.get_loc(column)
    current = frame.iloc[0, location]
    frame.iloc[0, location] = current + delta if isinstance(delta, float) else delta
    tampered = replace(result, **{frame_name: frame})
    with pytest.raises(RuntimeError):
        _validate_result(arguments[0], dispatch, network, voltage, tampered)


@pytest.mark.parametrize(
    "field",
    [
        "solved_tree_count",
        "unresolved_tree_count",
        "resolved_node_row_count",
        "resolved_segment_row_count",
    ],
)
def test_private_validator_rejects_diagnostic_tampering(field: str) -> None:
    arguments, dispatch, network, voltage = _public_setup()
    result = _public(arguments)
    diagnostics = replace(result.diagnostics, **{field: getattr(result.diagnostics, field) + 1})
    with pytest.raises(RuntimeError, match="diagnostics"):
        _validate_result(
            arguments[0], dispatch, network, voltage, replace(result, diagnostics=diagnostics)
        )
