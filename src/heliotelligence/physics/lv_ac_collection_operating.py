"""Balanced radial LV AC collection operating-network solve.

S11C treats canonical S10C selected P/Q as modeled constant-PQ injections,
uses explicit S11A per-phase series impedance and topology, and fixes each
S11B collection-exit voltage magnitude at a zero-degree mathematical phase
reference. It does not redispatch, infer loads, model shunts or transformers,
or claim that solved quantities are measurements.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import dc_collection, electrical
from heliotelligence.physics.inverter_ac_authority import (
    InverterAcCapabilityAuthority,
    TopologyInverterAcCapabilityAuthorityResult,
)
from heliotelligence.physics.inverter_accounting import TopologySandiaInverterPowerAccountingResult
from heliotelligence.physics.inverter_authority import TopologyInverterAuthorityResult
from heliotelligence.physics.inverter_conversion import TopologySandiaInverterAcResult
from heliotelligence.physics.inverter_dispatch_feasibility import (
    TopologyInverterDispatchFeasibilityResult,
)
from heliotelligence.physics.inverter_dispatch_request_authority import (
    InverterActivePowerDispatchRequest,
    TopologyInverterActivePowerDispatchRequestAuthorityResult,
)
from heliotelligence.physics.inverter_dispatch_selection import (
    TopologyInverterDispatchSelectionResult,
    calculate_topology_inverter_dispatch_selection,
)
from heliotelligence.physics.inverter_potential import TopologySandiaPreLimitAcResult
from heliotelligence.physics.inverter_pqs_capability import (
    InverterReactivePowerRequest,
    TopologyInverterPqsCapabilityResult,
)
from heliotelligence.physics.inverter_temperature_capability import (
    InverterTemperatureState,
    TopologyInverterTemperatureCapabilityResult,
)
from heliotelligence.physics.inverter_thermal_authority import (
    InverterThermalDeratingAuthority,
    TopologyInverterThermalDeratingAuthorityResult,
)
from heliotelligence.physics.inverter_topology import (
    MpptDcCurrentLimitAuthority,
    TopologyInverterDcEnvelopeResult,
)
from heliotelligence.physics.lv_ac_collection_authority import (
    LvAcCollectionNetworkBasisAuthority,
    LvAcCollectionNodeAuthority,
    LvAcCollectionSegmentAuthority,
    LvAcInverterTerminalBindingAuthority,
    TopologyLvAcCollectionAuthorityResult,
    resolve_topology_lv_ac_collection_authority,
)
from heliotelligence.physics.lv_ac_collection_voltage_authority import (
    LvAcCollectionExitVoltageState,
    TopologyLvAcCollectionExitVoltageAuthorityResult,
    resolve_topology_lv_ac_collection_exit_voltage_authority,
)

TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_CONTRACT_ID = (
    "admitted_selected_dispatch_lv_topology_and_exit_voltage_to_"
    "balanced_radial_operating_solution_v1"
)
TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_MODEL_ID = (
    "balanced_three_phase_radial_constant_pq_backward_forward_sweep_v1"
)
TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_SCOPE = (
    "lv_ac_collection_operating_solve_from_inverter_ac_output_to_collection_exit_before_transformer"
)
TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_COVERAGE_SCOPE = (
    "complete_radial_lv_collection_trees_with_selected_inverter_pq_"
    "and_explicit_collection_exit_voltage"
)

_MAX_ITERATIONS = 200
_VOLTAGE_ABS_TOL_V = 1e-7
_VOLTAGE_REL_TOL = 1e-10
_EQUATION_ABS_TOL = 1e-6
_EQUATION_REL_TOL = 1e-9

_EXIT_COLUMNS = (
    "topology_membership_closed",
    "exit_voltage_boundary_resolved",
    "tree_inverter_count",
    "selected_dispatch_inverter_count",
    "missing_selected_dispatch_inverter_count",
    "missing_selected_dispatch_inverter_ids",
    "network_solve_attempted",
    "network_solve_converged",
    "lv_ac_operating_solution_resolved",
    "exit_voltage_line_to_line_rms_v",
    "selected_p_total_w",
    "selected_q_total_var",
    "selected_apparent_power_vector_magnitude_va",
    "p_delivered_at_collection_exit_w",
    "q_delivered_at_collection_exit_var",
    "s_delivered_vector_magnitude_va",
    "total_active_series_loss_w",
    "total_reactive_series_consumption_var",
    "active_power_conservation_residual_w",
    "reactive_power_conservation_residual_var",
    "solver_iteration_count",
    "solver_max_voltage_delta_v",
    "lv_ac_collection_operating_state",
    "topology_lv_ac_collection_operating_solution_contract",
    "topology_lv_ac_collection_operating_solution_model",
    "topology_lv_ac_collection_operating_solution_scope",
    "topology_lv_ac_collection_operating_solution_coverage_scope",
)
_NODE_COLUMNS = (
    "node_kind",
    "collection_exit_node_id",
    "node_connected_to_collection_exit",
    "lv_ac_operating_solution_resolved",
    "voltage_phase_real_v",
    "voltage_phase_imag_v",
    "voltage_phase_magnitude_v",
    "voltage_line_to_line_rms_v",
    "voltage_phase_angle_deg_relative_to_exit_reference",
    "node_operating_state",
    "topology_lv_ac_collection_operating_solution_contract",
    "topology_lv_ac_collection_operating_solution_model",
)
_SEGMENT_COLUMNS = (
    "from_node_id",
    "to_node_id",
    "collection_exit_node_id",
    "segment_connected_to_collection_exit",
    "lv_ac_operating_solution_resolved",
    "series_resistance_ohm_per_phase",
    "series_reactance_ohm_per_phase",
    "current_phase_real_a",
    "current_phase_imag_a",
    "current_phase_magnitude_a",
    "current_phase_angle_deg_relative_to_exit_reference",
    "phase_voltage_difference_from_to_real_v",
    "phase_voltage_difference_from_to_imag_v",
    "phase_voltage_difference_from_to_magnitude_v",
    "line_to_line_voltage_magnitude_delta_from_to_v",
    "p_from_w",
    "q_from_var",
    "p_to_w",
    "q_to_var",
    "active_series_loss_w",
    "reactive_series_consumption_var",
    "segment_operating_state",
    "topology_lv_ac_collection_operating_solution_contract",
    "topology_lv_ac_collection_operating_solution_model",
)

_EXIT_BOOL = {
    "topology_membership_closed",
    "exit_voltage_boundary_resolved",
    "network_solve_attempted",
    "network_solve_converged",
    "lv_ac_operating_solution_resolved",
}
_EXIT_INT = {
    "tree_inverter_count",
    "selected_dispatch_inverter_count",
    "missing_selected_dispatch_inverter_count",
    "solver_iteration_count",
}
_EXIT_FLOAT = (
    set(_EXIT_COLUMNS)
    - _EXIT_BOOL
    - _EXIT_INT
    - {
        "missing_selected_dispatch_inverter_ids",
        "lv_ac_collection_operating_state",
        "topology_lv_ac_collection_operating_solution_contract",
        "topology_lv_ac_collection_operating_solution_model",
        "topology_lv_ac_collection_operating_solution_scope",
        "topology_lv_ac_collection_operating_solution_coverage_scope",
    }
)
_NODE_BOOL = {"node_connected_to_collection_exit", "lv_ac_operating_solution_resolved"}
_NODE_FLOAT = {
    "voltage_phase_real_v",
    "voltage_phase_imag_v",
    "voltage_phase_magnitude_v",
    "voltage_line_to_line_rms_v",
    "voltage_phase_angle_deg_relative_to_exit_reference",
}
_SEGMENT_BOOL = {"segment_connected_to_collection_exit", "lv_ac_operating_solution_resolved"}
_SEGMENT_FLOAT = {
    "series_resistance_ohm_per_phase",
    "series_reactance_ohm_per_phase",
    "current_phase_real_a",
    "current_phase_imag_a",
    "current_phase_magnitude_a",
    "current_phase_angle_deg_relative_to_exit_reference",
    "phase_voltage_difference_from_to_real_v",
    "phase_voltage_difference_from_to_imag_v",
    "phase_voltage_difference_from_to_magnitude_v",
    "line_to_line_voltage_magnitude_delta_from_to_v",
    "p_from_w",
    "q_from_var",
    "p_to_w",
    "q_to_var",
    "active_series_loss_w",
    "reactive_series_consumption_var",
}


@dataclass(frozen=True)
class _RadialTreeSolution:
    converged: bool
    failure: str
    iteration_count: int
    max_voltage_delta_v: float
    node_voltages_phase_v: Mapping[str, complex]
    segment_currents_phase_a: Mapping[str, complex]


@dataclass(frozen=True)
class TopologyLvAcCollectionOperatingSolutionDiagnostics:
    inverter_count: int
    timestamp_count: int
    collection_exit_count: int
    tree_row_count: int
    solved_tree_count: int
    unresolved_tree_count: int
    missing_network_basis_tree_count: int
    incomplete_topology_tree_count: int
    missing_selected_dispatch_tree_count: int
    missing_exit_voltage_tree_count: int
    zero_voltage_nonzero_power_tree_count: int
    nonfinite_numerical_tree_count: int
    nonconverged_tree_count: int
    node_row_count: int
    resolved_node_row_count: int
    unresolved_node_row_count: int
    segment_row_count: int
    resolved_segment_row_count: int
    unresolved_segment_row_count: int
    model: str


@dataclass(frozen=True)
class TopologyLvAcCollectionOperatingSolutionResult:
    collection_exit_states: pd.DataFrame
    node_states: pd.DataFrame
    segment_states: pd.DataFrame
    diagnostics: TopologyLvAcCollectionOperatingSolutionDiagnostics


def calculate_topology_lv_ac_collection_operating_solution(
    topology: ElectricalTopologyConfig,
    topology_string_iv: electrical.TopologyStringIVResult,
    branch_authority: dc_collection.DcBranchPathAuthorityResult,
    mppt_input_string_iv: dc_collection.TopologyMpptInputStringIVResult,
    mppt_input_operating_points: dc_collection.TopologyMpptInputOperatingPointResult,
    cec_sam_name_by_inverter_id: Mapping[str, str],
    inverter_authority: TopologyInverterAuthorityResult,
    mppt_current_limit_by_key: Mapping[tuple[str, str], MpptDcCurrentLimitAuthority],
    inverter_dc_envelope: TopologyInverterDcEnvelopeResult,
    inverter_ac: TopologySandiaInverterAcResult,
    pre_limit_ac: TopologySandiaPreLimitAcResult,
    inverter_power_accounting: TopologySandiaInverterPowerAccountingResult,
    ac_capability_by_inverter_id: Mapping[str, InverterAcCapabilityAuthority],
    ac_capability_authority: TopologyInverterAcCapabilityAuthorityResult,
    reactive_power_request_by_key: Mapping[tuple[pd.Timestamp, str], InverterReactivePowerRequest],
    pqs_capability: TopologyInverterPqsCapabilityResult,
    thermal_derating_by_inverter_id: Mapping[str, InverterThermalDeratingAuthority],
    thermal_derating_authority: TopologyInverterThermalDeratingAuthorityResult,
    inverter_temperature_by_key: Mapping[tuple[pd.Timestamp, str], InverterTemperatureState],
    temperature_capability: TopologyInverterTemperatureCapabilityResult,
    active_power_dispatch_request_by_key: Mapping[
        tuple[pd.Timestamp, str], InverterActivePowerDispatchRequest
    ],
    dispatch_request_authority: TopologyInverterActivePowerDispatchRequestAuthorityResult,
    dispatch_feasibility: TopologyInverterDispatchFeasibilityResult,
    dispatch_selection: TopologyInverterDispatchSelectionResult,
    network_basis: LvAcCollectionNetworkBasisAuthority | None,
    node_authority_by_id: Mapping[str, LvAcCollectionNodeAuthority],
    segment_authority_by_id: Mapping[str, LvAcCollectionSegmentAuthority],
    inverter_terminal_binding_by_inverter_id: Mapping[str, LvAcInverterTerminalBindingAuthority],
    lv_ac_collection_authority: TopologyLvAcCollectionAuthorityResult,
    collection_exit_voltage_by_key: Mapping[
        tuple[pd.Timestamp, str], LvAcCollectionExitVoltageState
    ],
    collection_exit_voltage_authority: TopologyLvAcCollectionExitVoltageAuthorityResult,
) -> TopologyLvAcCollectionOperatingSolutionResult:
    """Solve modeled balanced radial LV operating states without redispatch."""

    canonical_dispatch = calculate_topology_inverter_dispatch_selection(
        topology,
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        cec_sam_name_by_inverter_id,
        inverter_authority,
        mppt_current_limit_by_key,
        inverter_dc_envelope,
        inverter_ac,
        pre_limit_ac,
        inverter_power_accounting,
        ac_capability_by_inverter_id,
        ac_capability_authority,
        reactive_power_request_by_key,
        pqs_capability,
        thermal_derating_by_inverter_id,
        thermal_derating_authority,
        inverter_temperature_by_key,
        temperature_capability,
        active_power_dispatch_request_by_key,
        dispatch_request_authority,
        dispatch_feasibility,
    )
    _replay_dispatch(dispatch_selection, canonical_dispatch)
    canonical_network = resolve_topology_lv_ac_collection_authority(
        topology,
        network_basis,
        node_authority_by_id,
        segment_authority_by_id,
        inverter_terminal_binding_by_inverter_id,
    )
    _replay_network(lv_ac_collection_authority, canonical_network)
    canonical_voltage = resolve_topology_lv_ac_collection_exit_voltage_authority(
        topology,
        network_basis,
        node_authority_by_id,
        segment_authority_by_id,
        inverter_terminal_binding_by_inverter_id,
        canonical_network,
        collection_exit_voltage_by_key,
    )
    _replay_voltage(collection_exit_voltage_authority, canonical_voltage)
    result = _build_result(topology, canonical_dispatch, canonical_network, canonical_voltage)
    _validate_result(topology, canonical_dispatch, canonical_network, canonical_voltage, result)
    return result


def _replay_dispatch(supplied: object, canonical: TopologyInverterDispatchSelectionResult) -> None:
    if type(supplied) is not TopologyInverterDispatchSelectionResult:
        raise RuntimeError("supplied S10C result type is invalid")
    try:
        pd.testing.assert_frame_equal(supplied.dispatch, canonical.dispatch, check_exact=True)
    except AssertionError as exc:
        raise RuntimeError("supplied S10C dispatch failed exact replay") from exc
    if supplied.diagnostics != canonical.diagnostics:
        raise RuntimeError("supplied S10C diagnostics failed exact replay")


def _replay_network(supplied: object, canonical: TopologyLvAcCollectionAuthorityResult) -> None:
    if type(supplied) is not TopologyLvAcCollectionAuthorityResult:
        raise RuntimeError("supplied S11A result type is invalid")
    if any(
        type(mapping).__name__ != "mappingproxy"
        for mapping in (
            supplied.nodes_by_id,
            supplied.segments_by_id,
            supplied.inverter_terminal_binding_by_inverter_id,
        )
    ):
        raise RuntimeError("supplied S11A mappings must be immutable")
    if (
        supplied.network_basis != canonical.network_basis
        or dict(supplied.nodes_by_id) != dict(canonical.nodes_by_id)
        or dict(supplied.segments_by_id) != dict(canonical.segments_by_id)
        or dict(supplied.inverter_terminal_binding_by_inverter_id)
        != dict(canonical.inverter_terminal_binding_by_inverter_id)
    ):
        raise RuntimeError("supplied S11A mappings failed exact replay")
    try:
        pd.testing.assert_frame_equal(
            supplied.inverter_states, canonical.inverter_states, check_exact=True
        )
    except AssertionError as exc:
        raise RuntimeError("supplied S11A states failed exact replay") from exc
    if supplied.diagnostics != canonical.diagnostics:
        raise RuntimeError("supplied S11A diagnostics failed exact replay")


def _replay_voltage(
    supplied: object, canonical: TopologyLvAcCollectionExitVoltageAuthorityResult
) -> None:
    if type(supplied) is not TopologyLvAcCollectionExitVoltageAuthorityResult:
        raise RuntimeError("supplied S11B result type is invalid")
    if type(supplied.voltage_states_by_key).__name__ != "mappingproxy":
        raise RuntimeError("supplied S11B voltage mapping must be immutable")
    if dict(supplied.voltage_states_by_key) != dict(canonical.voltage_states_by_key):
        raise RuntimeError("supplied S11B voltage mapping failed exact replay")
    try:
        pd.testing.assert_frame_equal(supplied.states, canonical.states, check_exact=True)
    except AssertionError as exc:
        raise RuntimeError("supplied S11B states failed exact replay") from exc
    if supplied.diagnostics != canonical.diagnostics:
        raise RuntimeError("supplied S11B diagnostics failed exact replay")


def _close_complex(left: complex, right: complex) -> bool:
    return abs(left - right) <= _EQUATION_ABS_TOL + _EQUATION_REL_TOL * max(
        1.0, abs(left), abs(right)
    )


def _voltage_close(left: complex, right: complex) -> bool:
    return abs(left - right) <= _VOLTAGE_ABS_TOL_V + _VOLTAGE_REL_TOL * max(1.0, abs(right))


def _finite_complex(value: complex) -> bool:
    return math.isfinite(value.real) and math.isfinite(value.imag)


def _tree_membership(
    nodes: Mapping[str, LvAcCollectionNodeAuthority],
    segments: Mapping[str, LvAcCollectionSegmentAuthority],
) -> tuple[dict[str, str | None], dict[str, str | None]]:
    outgoing = {segment.from_node_id: segment for segment in segments.values()}
    node_exit: dict[str, str | None] = {}
    for start in nodes:
        current = start
        while nodes[current].node_kind != "collection_exit":
            segment = outgoing.get(current)
            if segment is None:
                current = ""
                break
            current = segment.to_node_id
        node_exit[start] = current or None
    segment_exit = {
        segment_id: node_exit[segment.from_node_id] for segment_id, segment in segments.items()
    }
    return node_exit, segment_exit


def _validator_tree_membership(
    nodes: Mapping[str, LvAcCollectionNodeAuthority],
    segments: Mapping[str, LvAcCollectionSegmentAuthority],
) -> tuple[dict[str, str | None], dict[str, str | None]]:
    """Independently reconstruct validator-only node and segment tree membership."""

    validator_outgoing = {segment.from_node_id: segment.to_node_id for segment in segments.values()}
    validator_node_exit: dict[str, str | None] = {}
    for start_node_id in nodes:
        current_node_id = start_node_id
        while True:
            current_node = nodes[current_node_id]
            if current_node.node_kind == "collection_exit":
                validator_node_exit[start_node_id] = current_node_id
                break
            next_node_id = validator_outgoing.get(current_node_id)
            if next_node_id is None:
                validator_node_exit[start_node_id] = None
                break
            current_node_id = next_node_id
    validator_segment_exit = {
        segment_id: validator_node_exit[segment.from_node_id]
        for segment_id, segment in segments.items()
    }
    return validator_node_exit, validator_segment_exit


def _sweep_currents(
    nodes: Mapping[str, LvAcCollectionNodeAuthority],
    segments: Mapping[str, LvAcCollectionSegmentAuthority],
    selected_power_by_terminal: Mapping[str, complex],
    voltages: Mapping[str, complex],
) -> tuple[dict[str, complex], bool]:
    incoming: dict[str, list[LvAcCollectionSegmentAuthority]] = {node_id: [] for node_id in nodes}
    for segment in segments.values():
        incoming[segment.to_node_id].append(segment)
    local: dict[str, complex] = {}
    try:
        for node_id in nodes:
            power = selected_power_by_terminal.get(node_id, 0j)
            voltage = voltages[node_id]
            if power == 0j:
                local[node_id] = 0j
            elif voltage == 0j:
                return {}, False
            else:
                local[node_id] = (power / (3.0 * voltage)).conjugate()
                if not _finite_complex(local[node_id]):
                    return {}, False
    except (OverflowError, ZeroDivisionError):
        return {}, False
    node_current: dict[str, complex] = {}

    def aggregate(node_id: str) -> complex:
        if node_id in node_current:
            return node_current[node_id]
        value = local[node_id]
        for child_segment in incoming[node_id]:
            value += aggregate(child_segment.from_node_id)
        node_current[node_id] = value
        return value

    currents: dict[str, complex] = {}
    for segment_id, segment in segments.items():
        current = aggregate(segment.from_node_id)
        if not _finite_complex(current):
            return {}, False
        currents[segment_id] = current
    return currents, True


def _forward_voltages(
    exit_node_id: str,
    exit_voltage_phase_v: complex,
    nodes: Mapping[str, LvAcCollectionNodeAuthority],
    segments: Mapping[str, LvAcCollectionSegmentAuthority],
    currents: Mapping[str, complex],
) -> tuple[dict[str, complex], bool]:
    incoming: dict[str, list[LvAcCollectionSegmentAuthority]] = {node_id: [] for node_id in nodes}
    for segment in segments.values():
        incoming[segment.to_node_id].append(segment)
    voltages = {exit_node_id: exit_voltage_phase_v}

    def visit(to_node_id: str) -> bool:
        for segment in incoming[to_node_id]:
            impedance = complex(
                segment.series_resistance_ohm_per_phase,
                segment.series_reactance_ohm_per_phase,
            )
            voltage = voltages[to_node_id] + impedance * currents[segment.segment_id]
            if not _finite_complex(voltage):
                return False
            voltages[segment.from_node_id] = voltage
            if not visit(segment.from_node_id):
                return False
        return True

    return voltages, visit(exit_node_id)


def _solve_balanced_radial_tree(
    exit_node_id: str,
    exit_voltage_line_to_line_rms_v: float,
    nodes: Mapping[str, LvAcCollectionNodeAuthority],
    segments: Mapping[str, LvAcCollectionSegmentAuthority],
    selected_power_by_terminal: Mapping[str, complex],
) -> _RadialTreeSolution:
    """Solve one admitted radial tree with deterministic backward/forward sweeps."""

    exit_phase = complex(exit_voltage_line_to_line_rms_v / math.sqrt(3.0), 0.0)
    nonzero_power = any(power != 0j for power in selected_power_by_terminal.values())
    if exit_voltage_line_to_line_rms_v == 0.0:
        if nonzero_power:
            return _RadialTreeSolution(False, "zero_voltage_nonzero_power", 0, math.nan, {}, {})
        return _RadialTreeSolution(
            True,
            "",
            0,
            0.0,
            {node_id: 0j for node_id in nodes},
            {segment_id: 0j for segment_id in segments},
        )
    voltages = {node_id: exit_phase for node_id in nodes}
    last_delta = math.nan
    for iteration in range(1, _MAX_ITERATIONS + 1):
        currents, finite = _sweep_currents(nodes, segments, selected_power_by_terminal, voltages)
        if not finite:
            return _RadialTreeSolution(False, "nonfinite", iteration, math.nan, {}, {})
        candidate, finite = _forward_voltages(exit_node_id, exit_phase, nodes, segments, currents)
        if not finite or set(candidate) != set(nodes):
            return _RadialTreeSolution(False, "nonfinite", iteration, math.nan, {}, {})
        last_delta = max(abs(candidate[node] - voltages[node]) for node in nodes)
        update_closed = all(_voltage_close(candidate[node], voltages[node]) for node in nodes)
        voltages = candidate
        if update_closed:
            final_currents, finite = _sweep_currents(
                nodes, segments, selected_power_by_terminal, voltages
            )
            implied, implied_finite = _forward_voltages(
                exit_node_id, exit_phase, nodes, segments, final_currents
            )
            if not finite or not implied_finite:
                return _RadialTreeSolution(False, "nonfinite", iteration, math.nan, {}, {})
            residual = max(abs(implied[node] - voltages[node]) for node in nodes)
            if all(_voltage_close(implied[node], voltages[node]) for node in nodes):
                return _RadialTreeSolution(
                    True, "", iteration, max(last_delta, residual), voltages, final_currents
                )
    return _RadialTreeSolution(False, "nonconvergence", _MAX_ITERATIONS, last_delta, {}, {})


def _timestamps(dispatch: pd.DataFrame) -> tuple[pd.Timestamp, ...]:
    if not isinstance(dispatch.index, pd.MultiIndex):
        return ()
    return tuple(dict.fromkeys(pd.Timestamp(value) for value in dispatch.index.get_level_values(0)))


def _provenance() -> dict[str, str]:
    return {
        "topology_lv_ac_collection_operating_solution_contract": (
            TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_CONTRACT_ID
        ),
        "topology_lv_ac_collection_operating_solution_model": (
            TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_MODEL_ID
        ),
    }


def _build_result(
    topology: ElectricalTopologyConfig,
    dispatch: TopologyInverterDispatchSelectionResult,
    network: TopologyLvAcCollectionAuthorityResult,
    voltage: TopologyLvAcCollectionExitVoltageAuthorityResult,
) -> TopologyLvAcCollectionOperatingSolutionResult:
    timestamps = _timestamps(dispatch.dispatch)
    exit_ids = tuple(
        node_id
        for node_id, node in network.nodes_by_id.items()
        if node.node_kind == "collection_exit"
    )
    node_exit, segment_exit = _tree_membership(network.nodes_by_id, network.segments_by_id)
    topology_closed = network.network_basis is not None and bool(
        network.inverter_states["lv_ac_collection_authority_resolved"].all()
    )
    inverters_by_exit: dict[str, list[str]] = {exit_id: [] for exit_id in exit_ids}
    terminal_by_inverter: dict[str, str] = {}
    for inverter in topology.inverters:
        binding = network.inverter_terminal_binding_by_inverter_id.get(inverter.id)
        if binding is not None:
            terminal_by_inverter[inverter.id] = binding.node_id
            exit_id = node_exit[binding.node_id]
            if exit_id is not None:
                inverters_by_exit[exit_id].append(inverter.id)

    solves: dict[tuple[pd.Timestamp, str], tuple[str, _RadialTreeSolution | None]] = {}
    exit_records: list[dict[str, object]] = []
    for timestamp in timestamps:
        for exit_id in exit_ids:
            inverter_ids = inverters_by_exit[exit_id]
            selected: dict[str, complex] = {}
            missing: list[str] = []
            for inverter_id in inverter_ids:
                row = dispatch.dispatch.loc[(timestamp, inverter_id)]
                if bool(row["selected_dispatch_present"]):
                    selected[terminal_by_inverter[inverter_id]] = complex(
                        float(row["p_selected_w"]), float(row["q_selected_var"])
                    )
                else:
                    missing.append(inverter_id)
            voltage_state = voltage.voltage_states_by_key.get((timestamp, exit_id))
            voltage_resolved = network.network_basis is not None and voltage_state is not None
            tree_nodes = {
                node_id: node
                for node_id, node in network.nodes_by_id.items()
                if node_exit[node_id] == exit_id
            }
            tree_segments = {
                segment_id: segment
                for segment_id, segment in network.segments_by_id.items()
                if segment_exit[segment_id] == exit_id
            }
            attempted = False
            solution: _RadialTreeSolution | None = None
            state = ""
            if network.network_basis is None:
                state = "unresolved_no_lv_ac_network_basis_authority"
            elif not topology_closed:
                state = "unresolved_incomplete_lv_ac_inverter_topology_authority"
            elif missing:
                state = "unresolved_missing_selected_dispatch_for_collection_tree"
            elif not voltage_resolved:
                state = "unresolved_missing_collection_exit_voltage_authority"
            else:
                assert voltage_state is not None
                attempted = voltage_state.voltage_line_to_line_rms_v != 0.0
                solution = _solve_balanced_radial_tree(
                    exit_id,
                    voltage_state.voltage_line_to_line_rms_v,
                    tree_nodes,
                    tree_segments,
                    selected,
                )
                if solution.failure == "zero_voltage_nonzero_power":
                    state = "unresolved_zero_exit_voltage_with_nonzero_selected_power"
                elif solution.failure == "nonfinite":
                    state = "unresolved_nonfinite_numerical_state"
                elif solution.failure == "nonconvergence":
                    state = "unresolved_network_solver_nonconvergence"
                elif voltage_state.voltage_line_to_line_rms_v == 0.0:
                    state = "resolved_zero_voltage_zero_dispatch_solution"
                else:
                    state = "resolved_balanced_radial_lv_ac_operating_solution"
            solves[(timestamp, exit_id)] = (state, solution)
            resolved = solution is not None and solution.converged
            selected_total = sum(selected.values(), 0j)
            numeric = (
                _tree_numeric(exit_id, tree_segments, solution)
                if resolved and solution is not None
                else None
            )
            exit_records.append(
                {
                    "topology_membership_closed": topology_closed,
                    "exit_voltage_boundary_resolved": voltage_resolved,
                    "tree_inverter_count": len(inverter_ids),
                    "selected_dispatch_inverter_count": len(selected),
                    "missing_selected_dispatch_inverter_count": len(missing),
                    "missing_selected_dispatch_inverter_ids": tuple(missing),
                    "network_solve_attempted": attempted,
                    "network_solve_converged": resolved,
                    "lv_ac_operating_solution_resolved": resolved,
                    "exit_voltage_line_to_line_rms_v": (
                        voltage_state.voltage_line_to_line_rms_v
                        if voltage_state is not None
                        else math.nan
                    ),
                    "selected_p_total_w": selected_total.real if not missing else math.nan,
                    "selected_q_total_var": selected_total.imag if not missing else math.nan,
                    "selected_apparent_power_vector_magnitude_va": (
                        abs(selected_total) if not missing else math.nan
                    ),
                    "p_delivered_at_collection_exit_w": numeric[0].real if numeric else math.nan,
                    "q_delivered_at_collection_exit_var": numeric[0].imag if numeric else math.nan,
                    "s_delivered_vector_magnitude_va": abs(numeric[0]) if numeric else math.nan,
                    "total_active_series_loss_w": numeric[1].real if numeric else math.nan,
                    "total_reactive_series_consumption_var": (
                        numeric[1].imag if numeric else math.nan
                    ),
                    "active_power_conservation_residual_w": (
                        selected_total.real - numeric[1].real - numeric[0].real
                        if numeric
                        else math.nan
                    ),
                    "reactive_power_conservation_residual_var": (
                        selected_total.imag - numeric[1].imag - numeric[0].imag
                        if numeric
                        else math.nan
                    ),
                    "solver_iteration_count": solution.iteration_count if solution else 0,
                    "solver_max_voltage_delta_v": (
                        solution.max_voltage_delta_v if solution else math.nan
                    ),
                    "lv_ac_collection_operating_state": state,
                    **_provenance(),
                    "topology_lv_ac_collection_operating_solution_scope": (
                        TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_SCOPE
                    ),
                    "topology_lv_ac_collection_operating_solution_coverage_scope": (
                        TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_COVERAGE_SCOPE
                    ),
                }
            )

    exit_index = pd.MultiIndex.from_product(
        [timestamps, exit_ids], names=["timestamp", "collection_exit_node_id"]
    )
    exit_frame = pd.DataFrame.from_records(exit_records, columns=_EXIT_COLUMNS, index=exit_index)
    exit_frame.index = exit_index
    _cast(exit_frame, _EXIT_BOOL, _EXIT_FLOAT, _EXIT_INT)
    node_frame = _build_node_frame(timestamps, network, node_exit, solves)
    segment_frame = _build_segment_frame(timestamps, network, segment_exit, solves)
    diagnostics = _operating_diagnostics(
        topology, timestamps, len(exit_ids), exit_frame, node_frame, segment_frame
    )
    return TopologyLvAcCollectionOperatingSolutionResult(
        exit_frame.copy(deep=True),
        node_frame.copy(deep=True),
        segment_frame.copy(deep=True),
        diagnostics,
    )


def _tree_numeric(
    exit_id: str,
    segments: Mapping[str, LvAcCollectionSegmentAuthority],
    solution: _RadialTreeSolution,
) -> tuple[complex, complex]:
    delivered = 0j
    losses = 0j
    voltages = solution.node_voltages_phase_v
    for segment_id, segment in segments.items():
        current = solution.segment_currents_phase_a[segment_id]
        impedance = complex(
            segment.series_resistance_ohm_per_phase,
            segment.series_reactance_ohm_per_phase,
        )
        losses += 3.0 * impedance * abs(current) ** 2
        if segment.to_node_id == exit_id:
            delivered += 3.0 * voltages[exit_id] * current.conjugate()
    return delivered, losses


def _build_node_frame(
    timestamps: tuple[pd.Timestamp, ...],
    network: TopologyLvAcCollectionAuthorityResult,
    node_exit: Mapping[str, str | None],
    solves: Mapping[tuple[pd.Timestamp, str], tuple[str, _RadialTreeSolution | None]],
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for timestamp in timestamps:
        for node_id, node in network.nodes_by_id.items():
            exit_id = node_exit[node_id]
            state, solution = (
                solves[(timestamp, exit_id)]
                if exit_id is not None
                else ("unresolved_node_not_connected_to_collection_exit", None)
            )
            resolved = solution is not None and solution.converged
            if resolved:
                assert solution is not None
                node_voltage = solution.node_voltages_phase_v[node_id]
            else:
                node_voltage = complex(math.nan, math.nan)
            records.append(
                {
                    "node_kind": node.node_kind,
                    "collection_exit_node_id": exit_id or "",
                    "node_connected_to_collection_exit": exit_id is not None,
                    "lv_ac_operating_solution_resolved": resolved,
                    "voltage_phase_real_v": node_voltage.real,
                    "voltage_phase_imag_v": node_voltage.imag,
                    "voltage_phase_magnitude_v": abs(node_voltage) if resolved else math.nan,
                    "voltage_line_to_line_rms_v": (
                        abs(node_voltage) * math.sqrt(3.0) if resolved else math.nan
                    ),
                    "voltage_phase_angle_deg_relative_to_exit_reference": (
                        math.degrees(math.atan2(node_voltage.imag, node_voltage.real))
                        if resolved
                        else math.nan
                    ),
                    "node_operating_state": state,
                    **_provenance(),
                }
            )
    index = pd.MultiIndex.from_product(
        [timestamps, tuple(network.nodes_by_id)], names=["timestamp", "node_id"]
    )
    frame = pd.DataFrame.from_records(records, columns=_NODE_COLUMNS, index=index)
    frame.index = index
    _cast(frame, _NODE_BOOL, _NODE_FLOAT, set())
    return frame


def _build_segment_frame(
    timestamps: tuple[pd.Timestamp, ...],
    network: TopologyLvAcCollectionAuthorityResult,
    segment_exit: Mapping[str, str | None],
    solves: Mapping[tuple[pd.Timestamp, str], tuple[str, _RadialTreeSolution | None]],
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for timestamp in timestamps:
        for segment_id, segment in network.segments_by_id.items():
            exit_id = segment_exit[segment_id]
            state, solution = (
                solves[(timestamp, exit_id)]
                if exit_id is not None
                else ("unresolved_segment_not_connected_to_collection_exit", None)
            )
            resolved = solution is not None and solution.converged
            if resolved:
                assert solution is not None
                current = solution.segment_currents_phase_a[segment_id]
                v_from = solution.node_voltages_phase_v[segment.from_node_id]
                v_to = solution.node_voltages_phase_v[segment.to_node_id]
            else:
                current = complex(math.nan, math.nan)
                v_from = complex(math.nan, math.nan)
                v_to = complex(math.nan, math.nan)
            difference = v_from - v_to
            s_from = 3.0 * v_from * current.conjugate() if resolved else complex(math.nan, math.nan)
            s_to = 3.0 * v_to * current.conjugate() if resolved else complex(math.nan, math.nan)
            loss = s_from - s_to
            records.append(
                {
                    "from_node_id": segment.from_node_id,
                    "to_node_id": segment.to_node_id,
                    "collection_exit_node_id": exit_id or "",
                    "segment_connected_to_collection_exit": exit_id is not None,
                    "lv_ac_operating_solution_resolved": resolved,
                    "series_resistance_ohm_per_phase": segment.series_resistance_ohm_per_phase,
                    "series_reactance_ohm_per_phase": segment.series_reactance_ohm_per_phase,
                    "current_phase_real_a": current.real,
                    "current_phase_imag_a": current.imag,
                    "current_phase_magnitude_a": abs(current) if resolved else math.nan,
                    "current_phase_angle_deg_relative_to_exit_reference": (
                        math.degrees(math.atan2(current.imag, current.real))
                        if resolved
                        else math.nan
                    ),
                    "phase_voltage_difference_from_to_real_v": difference.real,
                    "phase_voltage_difference_from_to_imag_v": difference.imag,
                    "phase_voltage_difference_from_to_magnitude_v": (
                        abs(difference) if resolved else math.nan
                    ),
                    "line_to_line_voltage_magnitude_delta_from_to_v": (
                        math.sqrt(3.0) * (abs(v_from) - abs(v_to)) if resolved else math.nan
                    ),
                    "p_from_w": s_from.real,
                    "q_from_var": s_from.imag,
                    "p_to_w": s_to.real,
                    "q_to_var": s_to.imag,
                    "active_series_loss_w": loss.real,
                    "reactive_series_consumption_var": loss.imag,
                    "segment_operating_state": state,
                    **_provenance(),
                }
            )
    index = pd.MultiIndex.from_product(
        [timestamps, tuple(network.segments_by_id)], names=["timestamp", "segment_id"]
    )
    frame = pd.DataFrame.from_records(records, columns=_SEGMENT_COLUMNS, index=index)
    frame.index = index
    _cast(frame, _SEGMENT_BOOL, _SEGMENT_FLOAT, set())
    return frame


def _cast(
    frame: pd.DataFrame,
    bool_columns: set[str],
    float_columns: set[str],
    int_columns: set[str],
) -> None:
    for column in bool_columns:
        frame[column] = frame[column].astype("bool")
    for column in float_columns:
        frame[column] = frame[column].astype("float64")
    for column in int_columns:
        frame[column] = frame[column].astype("int64")
    for column in set(frame.columns) - bool_columns - float_columns - int_columns:
        frame[column] = frame[column].astype("object")


def _operating_diagnostics(
    topology: ElectricalTopologyConfig,
    timestamps: tuple[pd.Timestamp, ...],
    collection_exit_count: int,
    exits: pd.DataFrame,
    nodes: pd.DataFrame,
    segments: pd.DataFrame,
) -> TopologyLvAcCollectionOperatingSolutionDiagnostics:
    state = exits["lv_ac_collection_operating_state"]
    solved = int(exits["lv_ac_operating_solution_resolved"].sum())
    return TopologyLvAcCollectionOperatingSolutionDiagnostics(
        inverter_count=topology.inverter_count,
        timestamp_count=len(timestamps),
        collection_exit_count=collection_exit_count,
        tree_row_count=len(exits),
        solved_tree_count=solved,
        unresolved_tree_count=len(exits) - solved,
        missing_network_basis_tree_count=int(
            (state == "unresolved_no_lv_ac_network_basis_authority").sum()
        ),
        incomplete_topology_tree_count=int(
            (state == "unresolved_incomplete_lv_ac_inverter_topology_authority").sum()
        ),
        missing_selected_dispatch_tree_count=int(
            (state == "unresolved_missing_selected_dispatch_for_collection_tree").sum()
        ),
        missing_exit_voltage_tree_count=int(
            (state == "unresolved_missing_collection_exit_voltage_authority").sum()
        ),
        zero_voltage_nonzero_power_tree_count=int(
            (state == "unresolved_zero_exit_voltage_with_nonzero_selected_power").sum()
        ),
        nonfinite_numerical_tree_count=int((state == "unresolved_nonfinite_numerical_state").sum()),
        nonconverged_tree_count=int((state == "unresolved_network_solver_nonconvergence").sum()),
        node_row_count=len(nodes),
        resolved_node_row_count=int(nodes["lv_ac_operating_solution_resolved"].sum()),
        unresolved_node_row_count=len(nodes)
        - int(nodes["lv_ac_operating_solution_resolved"].sum()),
        segment_row_count=len(segments),
        resolved_segment_row_count=int(segments["lv_ac_operating_solution_resolved"].sum()),
        unresolved_segment_row_count=len(segments)
        - int(segments["lv_ac_operating_solution_resolved"].sum()),
        model=TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_MODEL_ID,
    )


def _validate_result(
    topology: ElectricalTopologyConfig,
    dispatch: TopologyInverterDispatchSelectionResult,
    network: TopologyLvAcCollectionAuthorityResult,
    voltage: TopologyLvAcCollectionExitVoltageAuthorityResult,
    result: TopologyLvAcCollectionOperatingSolutionResult,
) -> None:
    """Independently validate schemas, state closure, and solved network equations."""

    if type(result) is not TopologyLvAcCollectionOperatingSolutionResult:
        raise RuntimeError("S11C result type is invalid")
    timestamps = _timestamps(dispatch.dispatch)
    exit_ids = tuple(
        node_id
        for node_id, node in network.nodes_by_id.items()
        if node.node_kind == "collection_exit"
    )
    _validate_frame(
        result.collection_exit_states,
        _EXIT_COLUMNS,
        _EXIT_BOOL,
        _EXIT_FLOAT,
        _EXIT_INT,
        ["timestamp", "collection_exit_node_id"],
        tuple((timestamp, exit_id) for timestamp in timestamps for exit_id in exit_ids),
    )
    _validate_frame(
        result.node_states,
        _NODE_COLUMNS,
        _NODE_BOOL,
        _NODE_FLOAT,
        set(),
        ["timestamp", "node_id"],
        tuple((timestamp, node_id) for timestamp in timestamps for node_id in network.nodes_by_id),
    )
    _validate_frame(
        result.segment_states,
        _SEGMENT_COLUMNS,
        _SEGMENT_BOOL,
        _SEGMENT_FLOAT,
        set(),
        ["timestamp", "segment_id"],
        tuple(
            (timestamp, segment_id)
            for timestamp in timestamps
            for segment_id in network.segments_by_id
        ),
    )
    node_exit, segment_exit = _validator_tree_membership(
        network.nodes_by_id, network.segments_by_id
    )
    for (_timestamp, node_id), row in result.node_states.iterrows():
        exit_id = node_exit[node_id]
        if row["node_kind"] != network.nodes_by_id[node_id].node_kind or row[
            "collection_exit_node_id"
        ] != (exit_id or ""):
            raise RuntimeError("S11C node structural replay failed")
        if bool(row["node_connected_to_collection_exit"]) != (exit_id is not None):
            raise RuntimeError("S11C node membership flag failed")
        _validate_provenance(row)
        expected_node_state = (
            result.collection_exit_states.loc[(_timestamp, exit_id)][
                "lv_ac_collection_operating_state"
            ]
            if exit_id is not None
            else "unresolved_node_not_connected_to_collection_exit"
        )
        if row["node_operating_state"] != expected_node_state:
            raise RuntimeError("S11C node operating state failed closure")
        if bool(row["lv_ac_operating_solution_resolved"]):
            voltage_phase = complex(row["voltage_phase_real_v"], row["voltage_phase_imag_v"])
            if not _finite_complex(voltage_phase):
                raise RuntimeError("S11C resolved node voltage is nonfinite")
            if not math.isclose(
                row["voltage_phase_magnitude_v"],
                abs(voltage_phase),
                rel_tol=_EQUATION_REL_TOL,
                abs_tol=_EQUATION_ABS_TOL,
            ):
                raise RuntimeError("S11C node phase magnitude failed closure")
            if not math.isclose(
                row["voltage_line_to_line_rms_v"],
                math.sqrt(3.0) * abs(voltage_phase),
                rel_tol=_EQUATION_REL_TOL,
                abs_tol=_EQUATION_ABS_TOL,
            ):
                raise RuntimeError("S11C balanced node voltage failed closure")
            if network.nodes_by_id[node_id].node_kind == "collection_exit" and not math.isclose(
                row["voltage_phase_angle_deg_relative_to_exit_reference"],
                0.0,
                abs_tol=_EQUATION_ABS_TOL,
            ):
                raise RuntimeError("S11C exit angle reference failed closure")
        else:
            for column in _NODE_FLOAT:
                if not pd.isna(row[column]):
                    raise RuntimeError("S11C unresolved node physical values must be NaN")
    for (timestamp, segment_id), row in result.segment_states.iterrows():
        segment = network.segments_by_id[segment_id]
        if (
            row["from_node_id"] != segment.from_node_id
            or row["to_node_id"] != segment.to_node_id
            or row["collection_exit_node_id"] != (segment_exit[segment_id] or "")
        ):
            raise RuntimeError("S11C segment structural replay failed")
        if (
            row["series_resistance_ohm_per_phase"] != segment.series_resistance_ohm_per_phase
            or row["series_reactance_ohm_per_phase"] != segment.series_reactance_ohm_per_phase
        ):
            raise RuntimeError("S11C segment impedance replay failed")
        member_exit = segment_exit[segment_id]
        expected_segment_state = (
            result.collection_exit_states.loc[(timestamp, member_exit)][
                "lv_ac_collection_operating_state"
            ]
            if member_exit is not None
            else "unresolved_segment_not_connected_to_collection_exit"
        )
        if row["segment_operating_state"] != expected_segment_state:
            raise RuntimeError("S11C segment operating state failed closure")
        _validate_provenance(row)
        if bool(row["lv_ac_operating_solution_resolved"]):
            current = complex(row["current_phase_real_a"], row["current_phase_imag_a"])
            v_from_row = result.node_states.loc[(timestamp, segment.from_node_id)]
            v_to_row = result.node_states.loc[(timestamp, segment.to_node_id)]
            v_from = complex(v_from_row["voltage_phase_real_v"], v_from_row["voltage_phase_imag_v"])
            v_to = complex(v_to_row["voltage_phase_real_v"], v_to_row["voltage_phase_imag_v"])
            impedance = complex(
                segment.series_resistance_ohm_per_phase, segment.series_reactance_ohm_per_phase
            )
            if not math.isclose(
                row["current_phase_magnitude_a"],
                abs(current),
                rel_tol=_EQUATION_REL_TOL,
                abs_tol=_EQUATION_ABS_TOL,
            ):
                raise RuntimeError("S11C segment current magnitude failed closure")
            if not _close_complex(v_from - v_to, impedance * current):
                raise RuntimeError("S11C segment V=ZI equation failed")
            reported_difference = complex(
                row["phase_voltage_difference_from_to_real_v"],
                row["phase_voltage_difference_from_to_imag_v"],
            )
            if not _close_complex(reported_difference, v_from - v_to):
                raise RuntimeError("S11C segment voltage-difference fields failed closure")
            if not math.isclose(
                row["phase_voltage_difference_from_to_magnitude_v"],
                abs(v_from - v_to),
                rel_tol=_EQUATION_REL_TOL,
                abs_tol=_EQUATION_ABS_TOL,
            ):
                raise RuntimeError("S11C segment voltage-difference magnitude failed closure")
            expected_ll_delta = math.sqrt(3.0) * (abs(v_from) - abs(v_to))
            if not math.isclose(
                row["line_to_line_voltage_magnitude_delta_from_to_v"],
                expected_ll_delta,
                rel_tol=_EQUATION_REL_TOL,
                abs_tol=_EQUATION_ABS_TOL,
            ):
                raise RuntimeError("S11C segment line-voltage delta failed closure")
            s_from = complex(row["p_from_w"], row["q_from_var"])
            s_to = complex(row["p_to_w"], row["q_to_var"])
            if not _close_complex(s_from, 3.0 * v_from * current.conjugate()) or not _close_complex(
                s_to, 3.0 * v_to * current.conjugate()
            ):
                raise RuntimeError("S11C segment complex power failed closure")
            expected_loss = 3.0 * impedance * abs(current) ** 2
            if not _close_complex(s_from - s_to, expected_loss):
                raise RuntimeError("S11C segment loss equation failed closure")
            if not math.isclose(
                row["active_series_loss_w"],
                expected_loss.real,
                rel_tol=_EQUATION_REL_TOL,
                abs_tol=_EQUATION_ABS_TOL,
            ) or not math.isclose(
                row["reactive_series_consumption_var"],
                expected_loss.imag,
                rel_tol=_EQUATION_REL_TOL,
                abs_tol=_EQUATION_ABS_TOL,
            ):
                raise RuntimeError("S11C segment loss fields failed closure")
        else:
            for column in _SEGMENT_FLOAT - {
                "series_resistance_ohm_per_phase",
                "series_reactance_ohm_per_phase",
            }:
                if not pd.isna(row[column]):
                    raise RuntimeError("S11C unresolved segment physical values must be NaN")
    _validate_tree_equations(topology, dispatch, network, voltage, result, node_exit, segment_exit)
    validator_tree_states = result.collection_exit_states["lv_ac_collection_operating_state"]
    validator_solved_tree_count = int(
        result.collection_exit_states["lv_ac_operating_solution_resolved"].sum()
    )
    validator_resolved_node_count = int(
        result.node_states["lv_ac_operating_solution_resolved"].sum()
    )
    validator_resolved_segment_count = int(
        result.segment_states["lv_ac_operating_solution_resolved"].sum()
    )
    expected_diagnostics = TopologyLvAcCollectionOperatingSolutionDiagnostics(
        inverter_count=topology.inverter_count,
        timestamp_count=len(timestamps),
        collection_exit_count=len(exit_ids),
        tree_row_count=len(result.collection_exit_states),
        solved_tree_count=validator_solved_tree_count,
        unresolved_tree_count=(len(result.collection_exit_states) - validator_solved_tree_count),
        missing_network_basis_tree_count=int(
            (validator_tree_states == "unresolved_no_lv_ac_network_basis_authority").sum()
        ),
        incomplete_topology_tree_count=int(
            (
                validator_tree_states == "unresolved_incomplete_lv_ac_inverter_topology_authority"
            ).sum()
        ),
        missing_selected_dispatch_tree_count=int(
            (
                validator_tree_states == "unresolved_missing_selected_dispatch_for_collection_tree"
            ).sum()
        ),
        missing_exit_voltage_tree_count=int(
            (validator_tree_states == "unresolved_missing_collection_exit_voltage_authority").sum()
        ),
        zero_voltage_nonzero_power_tree_count=int(
            (
                validator_tree_states == "unresolved_zero_exit_voltage_with_nonzero_selected_power"
            ).sum()
        ),
        nonfinite_numerical_tree_count=int(
            (validator_tree_states == "unresolved_nonfinite_numerical_state").sum()
        ),
        nonconverged_tree_count=int(
            (validator_tree_states == "unresolved_network_solver_nonconvergence").sum()
        ),
        node_row_count=len(result.node_states),
        resolved_node_row_count=validator_resolved_node_count,
        unresolved_node_row_count=(len(result.node_states) - validator_resolved_node_count),
        segment_row_count=len(result.segment_states),
        resolved_segment_row_count=validator_resolved_segment_count,
        unresolved_segment_row_count=(
            len(result.segment_states) - validator_resolved_segment_count
        ),
        model=TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_MODEL_ID,
    )
    if result.diagnostics != expected_diagnostics:
        raise RuntimeError("S11C diagnostics failed exact closure")
    diagnostics = result.diagnostics
    if (
        diagnostics.solved_tree_count + diagnostics.unresolved_tree_count
        != diagnostics.tree_row_count
        or diagnostics.tree_row_count != len(timestamps) * len(exit_ids)
    ):
        raise RuntimeError("S11C tree diagnostics do not close")
    if (
        diagnostics.resolved_node_row_count + diagnostics.unresolved_node_row_count
        != diagnostics.node_row_count
        or diagnostics.node_row_count != len(timestamps) * len(network.nodes_by_id)
    ):
        raise RuntimeError("S11C node diagnostics do not close")
    if (
        diagnostics.resolved_segment_row_count + diagnostics.unresolved_segment_row_count
        != diagnostics.segment_row_count
        or diagnostics.segment_row_count != len(timestamps) * len(network.segments_by_id)
    ):
        raise RuntimeError("S11C segment diagnostics do not close")
    mutually_exclusive_states = (
        diagnostics.solved_tree_count
        + diagnostics.missing_network_basis_tree_count
        + diagnostics.incomplete_topology_tree_count
        + diagnostics.missing_selected_dispatch_tree_count
        + diagnostics.missing_exit_voltage_tree_count
        + diagnostics.zero_voltage_nonzero_power_tree_count
        + diagnostics.nonfinite_numerical_tree_count
        + diagnostics.nonconverged_tree_count
    )
    if mutually_exclusive_states != diagnostics.tree_row_count:
        raise RuntimeError("S11C primary-state diagnostics do not close")


def _validate_frame(
    frame: pd.DataFrame,
    columns: tuple[str, ...],
    bool_columns: set[str],
    float_columns: set[str],
    int_columns: set[str],
    index_names: list[str],
    expected_index: tuple[tuple[object, object], ...],
) -> None:
    if tuple(frame.columns) != columns or not isinstance(frame.index, pd.MultiIndex):
        raise RuntimeError("S11C frame schema is invalid")
    if (
        list(frame.index.names) != index_names
        or frame.index.has_duplicates
        or tuple(frame.index) != expected_index
    ):
        raise RuntimeError("S11C frame canonical index is invalid")
    for column in columns:
        expected = (
            "bool"
            if column in bool_columns
            else "float64"
            if column in float_columns
            else "int64"
            if column in int_columns
            else "object"
        )
        if str(frame[column].dtype) != expected:
            raise RuntimeError(f"S11C dtype is invalid for {column}")


def _validate_provenance(row: pd.Series) -> None:
    if (
        row["topology_lv_ac_collection_operating_solution_contract"]
        != TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_CONTRACT_ID
        or row["topology_lv_ac_collection_operating_solution_model"]
        != TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_MODEL_ID
    ):
        raise RuntimeError("S11C provenance failed exact closure")


def _validate_solver_diagnostics(row: pd.Series, state: str, resolved: bool) -> None:
    attempted = bool(row["network_solve_attempted"])
    converged = bool(row["network_solve_converged"])
    iterations = int(row["solver_iteration_count"])
    delta = float(row["solver_max_voltage_delta_v"])
    if bool(row["lv_ac_operating_solution_resolved"]) != resolved:
        raise RuntimeError("S11C solution-resolution flag failed closure")
    no_attempt_states = {
        "unresolved_no_lv_ac_network_basis_authority",
        "unresolved_incomplete_lv_ac_inverter_topology_authority",
        "unresolved_missing_selected_dispatch_for_collection_tree",
        "unresolved_missing_collection_exit_voltage_authority",
        "unresolved_zero_exit_voltage_with_nonzero_selected_power",
    }
    if state in no_attempt_states:
        if attempted or converged or resolved or iterations != 0 or not math.isnan(delta):
            raise RuntimeError("S11C unattempted solver diagnostics failed closure")
    elif state == "unresolved_network_solver_nonconvergence":
        if (
            not attempted
            or converged
            or resolved
            or iterations != _MAX_ITERATIONS
            or not math.isfinite(delta)
            or delta < 0.0
        ):
            raise RuntimeError("S11C nonconvergence diagnostics failed closure")
    elif state == "unresolved_nonfinite_numerical_state":
        if not attempted or converged or resolved or iterations < 1:
            raise RuntimeError("S11C nonfinite solver diagnostics failed closure")
        if not math.isnan(delta) and (not math.isfinite(delta) or delta < 0.0):
            raise RuntimeError("S11C nonfinite solver delta is invalid")
    elif state == "resolved_zero_voltage_zero_dispatch_solution":
        if attempted or not converged or not resolved or iterations != 0 or delta != 0.0:
            raise RuntimeError("S11C resolved zero solver diagnostics failed closure")
    elif state == "resolved_balanced_radial_lv_ac_operating_solution":
        if (
            not attempted
            or not converged
            or not resolved
            or iterations < 1
            or iterations > _MAX_ITERATIONS
            or not math.isfinite(delta)
            or delta < 0.0
        ):
            raise RuntimeError("S11C converged solver diagnostics failed closure")
    else:
        raise RuntimeError("S11C solver diagnostics use an unsupported primary state")


def _validate_tree_equations(
    topology: ElectricalTopologyConfig,
    dispatch: TopologyInverterDispatchSelectionResult,
    network: TopologyLvAcCollectionAuthorityResult,
    voltage: TopologyLvAcCollectionExitVoltageAuthorityResult,
    result: TopologyLvAcCollectionOperatingSolutionResult,
    node_exit: Mapping[str, str | None],
    segment_exit: Mapping[str, str | None],
) -> None:
    incoming: dict[str, list[str]] = {node_id: [] for node_id in network.nodes_by_id}
    outgoing: dict[str, str] = {}
    for segment_id, segment in network.segments_by_id.items():
        incoming[segment.to_node_id].append(segment_id)
        outgoing[segment.from_node_id] = segment_id
    terminal_to_inverter = {
        binding.node_id: inverter_id
        for inverter_id, binding in network.inverter_terminal_binding_by_inverter_id.items()
    }
    for key, tree_row in result.collection_exit_states.iterrows():
        timestamp, exit_id = key
        _validate_provenance(tree_row)
        if (
            tree_row["topology_lv_ac_collection_operating_solution_scope"]
            != TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_SCOPE
            or tree_row["topology_lv_ac_collection_operating_solution_coverage_scope"]
            != TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_COVERAGE_SCOPE
        ):
            raise RuntimeError("S11C tree provenance failed exact closure")
        member_inverters = [
            inverter_id
            for node_id, inverter_id in terminal_to_inverter.items()
            if node_exit[node_id] == exit_id
        ]
        missing_inverters = [
            inverter_id
            for inverter_id in member_inverters
            if not bool(
                dispatch.dispatch.loc[(timestamp, inverter_id)]["selected_dispatch_present"]
            )
        ]
        topology_closed = network.network_basis is not None and bool(
            network.inverter_states["lv_ac_collection_authority_resolved"].all()
        )
        boundary = voltage.voltage_states_by_key.get((timestamp, exit_id))
        boundary_resolved = network.network_basis is not None and boundary is not None
        if (
            bool(tree_row["topology_membership_closed"]) != topology_closed
            or bool(tree_row["exit_voltage_boundary_resolved"]) != boundary_resolved
            or tree_row["tree_inverter_count"] != len(member_inverters)
            or tree_row["selected_dispatch_inverter_count"]
            != len(member_inverters) - len(missing_inverters)
            or tree_row["missing_selected_dispatch_inverter_count"] != len(missing_inverters)
            or tree_row["missing_selected_dispatch_inverter_ids"] != tuple(missing_inverters)
        ):
            raise RuntimeError("S11C tree structural/count fields failed closure")
        selected_total = sum(
            (
                complex(
                    dispatch.dispatch.loc[(timestamp, inverter_id)]["p_selected_w"],
                    dispatch.dispatch.loc[(timestamp, inverter_id)]["q_selected_var"],
                )
                for inverter_id in member_inverters
                if inverter_id not in missing_inverters
            ),
            0j,
        )
        if missing_inverters:
            for column in (
                "selected_p_total_w",
                "selected_q_total_var",
                "selected_apparent_power_vector_magnitude_va",
            ):
                if not pd.isna(tree_row[column]):
                    raise RuntimeError("S11C incomplete selected totals must be NaN")
        elif (
            tree_row["selected_p_total_w"] != selected_total.real
            or tree_row["selected_q_total_var"] != selected_total.imag
            or tree_row["selected_apparent_power_vector_magnitude_va"] != abs(selected_total)
        ):
            raise RuntimeError("S11C selected total fields failed exact closure")
        resolved = bool(tree_row["lv_ac_operating_solution_resolved"])
        state = tree_row["lv_ac_collection_operating_state"]
        structural_state = (
            "unresolved_no_lv_ac_network_basis_authority"
            if network.network_basis is None
            else "unresolved_incomplete_lv_ac_inverter_topology_authority"
            if not topology_closed
            else "unresolved_missing_selected_dispatch_for_collection_tree"
            if missing_inverters
            else "unresolved_missing_collection_exit_voltage_authority"
            if not boundary_resolved
            else ""
        )
        if structural_state and state != structural_state:
            raise RuntimeError("S11C primary-state precedence failed closure")
        if resolved:
            expected_resolved_state = (
                "resolved_zero_voltage_zero_dispatch_solution"
                if boundary is not None and boundary.voltage_line_to_line_rms_v == 0.0
                else "resolved_balanced_radial_lv_ac_operating_solution"
            )
            if state != expected_resolved_state or not bool(tree_row["network_solve_converged"]):
                raise RuntimeError("S11C resolved tree state/flags failed closure")
        elif bool(tree_row["network_solve_converged"]):
            raise RuntimeError("S11C unresolved tree cannot be converged")
        _validate_solver_diagnostics(tree_row, state, resolved)
        physical = _EXIT_FLOAT - {
            "exit_voltage_line_to_line_rms_v",
            "selected_p_total_w",
            "selected_q_total_var",
            "selected_apparent_power_vector_magnitude_va",
            "solver_max_voltage_delta_v",
        }
        if not resolved:
            for column in physical:
                if not pd.isna(tree_row[column]):
                    raise RuntimeError("S11C unresolved tree physical values must be NaN")
            continue
        if (
            boundary is None
            or tree_row["exit_voltage_line_to_line_rms_v"] != boundary.voltage_line_to_line_rms_v
        ):
            raise RuntimeError("S11C exit boundary failed exact replay")
        selected_total = 0j
        for node_id, inverter_id in terminal_to_inverter.items():
            if node_exit[node_id] != exit_id:
                continue
            selection = dispatch.dispatch.loc[(timestamp, inverter_id)]
            selected = complex(selection["p_selected_w"], selection["q_selected_var"])
            selected_total += selected
            voltage_row = result.node_states.loc[(timestamp, node_id)]
            terminal_voltage = complex(
                voltage_row["voltage_phase_real_v"], voltage_row["voltage_phase_imag_v"]
            )
            current_row = result.segment_states.loc[(timestamp, outgoing[node_id])]
            terminal_current = complex(
                current_row["current_phase_real_a"], current_row["current_phase_imag_a"]
            )
            if not _close_complex(selected, 3.0 * terminal_voltage * terminal_current.conjugate()):
                raise RuntimeError("S11C terminal constant-PQ equation failed")
        for node_id, node in network.nodes_by_id.items():
            if node_exit[node_id] != exit_id or node.node_kind == "collection_exit":
                continue
            outgoing_id = outgoing.get(node_id)
            if outgoing_id is None:
                continue
            outgoing_row = result.segment_states.loc[(timestamp, outgoing_id)]
            outgoing_current = complex(
                outgoing_row["current_phase_real_a"], outgoing_row["current_phase_imag_a"]
            )
            child_current = sum(
                (
                    complex(
                        result.segment_states.loc[(timestamp, child)]["current_phase_real_a"],
                        result.segment_states.loc[(timestamp, child)]["current_phase_imag_a"],
                    )
                    for child in incoming[node_id]
                ),
                0j,
            )
            local = 0j
            local_inverter_id = terminal_to_inverter.get(node_id)
            if local_inverter_id is not None:
                selection = dispatch.dispatch.loc[(timestamp, local_inverter_id)]
                node_row = result.node_states.loc[(timestamp, node_id)]
                node_voltage = complex(
                    node_row["voltage_phase_real_v"], node_row["voltage_phase_imag_v"]
                )
                local = (
                    (
                        complex(selection["p_selected_w"], selection["q_selected_var"])
                        / (3.0 * node_voltage)
                    ).conjugate()
                    if node_voltage != 0j
                    else 0j
                )
            if not _close_complex(outgoing_current, child_current + local):
                raise RuntimeError("S11C junction/terminal KCL failed")
        segment_rows = [
            result.segment_states.loc[(timestamp, segment_id)]
            for segment_id, member_exit in segment_exit.items()
            if member_exit == exit_id
        ]
        losses = sum(
            (
                complex(row["active_series_loss_w"], row["reactive_series_consumption_var"])
                for row in segment_rows
            ),
            0j,
        )
        exit_voltage_row = result.node_states.loc[(timestamp, exit_id)]
        exit_phase = complex(
            exit_voltage_row["voltage_phase_real_v"], exit_voltage_row["voltage_phase_imag_v"]
        )
        delivered = sum(
            (
                3.0
                * exit_phase
                * complex(row["current_phase_real_a"], row["current_phase_imag_a"]).conjugate()
                for row in segment_rows
                if row["to_node_id"] == exit_id
            ),
            0j,
        )
        if not _close_complex(selected_total - losses, delivered):
            raise RuntimeError("S11C whole-tree conservation failed")
        if not _close_complex(
            complex(
                tree_row["p_delivered_at_collection_exit_w"],
                tree_row["q_delivered_at_collection_exit_var"],
            ),
            delivered,
        ):
            raise RuntimeError("S11C delivered power fields failed closure")
        if not _close_complex(
            complex(
                tree_row["total_active_series_loss_w"],
                tree_row["total_reactive_series_consumption_var"],
            ),
            losses,
        ):
            raise RuntimeError("S11C tree loss fields failed closure")
        if not math.isclose(
            tree_row["s_delivered_vector_magnitude_va"],
            abs(delivered),
            rel_tol=_EQUATION_REL_TOL,
            abs_tol=_EQUATION_ABS_TOL,
        ):
            raise RuntimeError("S11C delivered apparent-power magnitude failed closure")
        expected_residual = selected_total - losses - delivered
        if not _close_complex(
            complex(
                tree_row["active_power_conservation_residual_w"],
                tree_row["reactive_power_conservation_residual_var"],
            ),
            expected_residual,
        ):
            raise RuntimeError("S11C conservation residual fields failed closure")
