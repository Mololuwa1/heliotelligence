"""Balanced radial nominal-pi MV/HV operating solution (S13C).

S12M terminal P/Q is injected at S13A transformer-terminal nodes.  S13B fixes
each grid-boundary voltage magnitude; its zero phase angle is only a
mathematical coordinate.  Transformer losses are already owned by S12M and
are never reapplied here.  S13C owns only admitted S13 series and shunt
physics and produces modeled, not measured, revenue-meter boundary power.
"""

from __future__ import annotations

import cmath
import inspect
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, TypeVar, cast

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.physics.mv_hv_grid_boundary_voltage_authority import (
    MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_CONTRACT_ID,
    resolve_topology_mv_hv_grid_boundary_voltage_authority,
)
from heliotelligence.physics.mv_hv_network_authority import (
    MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
    MvHvNetworkNodeAuthority,
    MvHvNetworkSegmentAuthority,
    TopologyMvHvNetworkAuthorityResult,
    resolve_topology_mv_hv_network_authority,
)
from heliotelligence.physics.transformer_advanced_operating_solution import (
    TRANSFORMER_ADVANCED_OPERATING_SOLUTION_CONTRACT_ID,
    calculate_topology_transformer_advanced_operating_solution,
)

MV_HV_OPERATING_SOLUTION_CONTRACT_ID = (
    "admitted_s12m_s13a_s13b_to_balanced_radial_nominal_pi_mv_hv_operating_solution_v1"
)
MV_HV_OPERATING_SOLUTION_MODEL_ID = (
    "balanced_three_phase_radial_constant_pq_transformer_injection_"
    "nominal_pi_backward_forward_sweep_v1"
)
MV_HV_OPERATING_SOLUTION_SCOPE = (
    "timestamped_mv_hv_network_operating_solve_from_transformer_"
    "network_terminals_to_grid_and_revenue_meter_boundaries"
)
MV_HV_OPERATING_SOLUTION_COVERAGE_SCOPE = (
    "admitted_same_voltage_level_radial_s13_networks_with_s12m_"
    "transformer_terminal_pq_and_explicit_grid_boundary_voltage"
)

MAX_ITERATIONS = 200
VOLTAGE_ABS_TOL_V = 1e-7
VOLTAGE_REL_TOL = 1e-10
EQUATION_ABS_TOL = 1e-6
EQUATION_REL_TOL = 1e-9
TERMINAL_VOLTAGE_ABS_TOL_V = 1e-6
TERMINAL_VOLTAGE_REL_TOL = 1e-9

GRID_ANGLE_TREATMENT = "grid_boundary_zero_angle_is_mathematical_reference_not_measurement"
TERMINAL_COUPLING = "s12m_s13_same_plane_line_to_line_rms_voltage_magnitude_closure"
SHUNT_SEMANTICS = "positive_susceptance_is_capacitive_reactive_injection_with_half_at_each_end"
METER_CUT = "gridward_directed_node_cut_outgoing_branch_terminal_power_v1"
TRANSFORMER_LOSS_TREATMENT = "transformer_losses_owned_by_s12m_not_reapplied_in_s13c"
SERIES_LOSS_TREATMENT = "s13_series_losses_owned_by_s13c"
SHUNT_ACTIVE_TREATMENT = "s13_shunt_active_consumption_owned_by_s13c"
SHUNT_REACTIVE_TREATMENT = "s13_capacitive_reactive_injection_owned_by_s13c"
METER_TREATMENT = "revenue_meter_expected_power_is_boundary_flow_not_additional_loss"

_TREE_STATES = (
    "unresolved_no_mv_hv_network_basis_authority",
    "unresolved_network_exit_without_grid_boundary",
    "unresolved_missing_grid_boundary_voltage_authority",
    "unresolved_missing_s12m_transformer_operating_state",
    "unresolved_upstream_s12m_transformer_operating_solution",
    "unresolved_zero_grid_voltage_with_nonzero_transformer_injection",
    "unresolved_nonfinite_mv_hv_numerical_state",
    "unresolved_mv_hv_network_solver_nonconvergence",
    "unresolved_s12m_s13_transformer_terminal_voltage_mismatch",
    "resolved_zero_grid_voltage_zero_injection_mv_hv_solution",
    "resolved_balanced_radial_nominal_pi_mv_hv_operating_solution",
)

_TREE_COLUMNS = (
    "grid_boundary_id",
    "network_basis_resolved",
    "grid_boundary_present",
    "grid_boundary_voltage_resolved",
    "tree_transformer_count",
    "s12m_ready_transformer_count",
    "missing_s12m_transformer_count",
    "unresolved_s12m_transformer_count",
    "missing_s12m_transformer_ids",
    "unresolved_s12m_transformer_ids",
    "network_solve_attempted",
    "network_solve_converged",
    "transformer_terminal_voltage_consistency_checked",
    "transformer_terminal_voltage_consistency_satisfied",
    "mismatched_transformer_count",
    "mismatched_transformer_ids",
    "maximum_transformer_terminal_voltage_magnitude_residual_v",
    "mv_hv_operating_solution_resolved",
    "grid_boundary_voltage_line_to_line_rms_v",
    "transformer_injected_p_total_w",
    "transformer_injected_q_total_var",
    "transformer_injected_s_vector_magnitude_va",
    "p_export_at_grid_boundary_w",
    "q_export_at_grid_boundary_var",
    "s_export_at_grid_boundary_magnitude_va",
    "total_series_active_loss_w",
    "total_series_reactive_consumption_var",
    "total_shunt_active_consumption_w",
    "total_shunt_capacitive_reactive_injection_var",
    "net_network_active_consumption_w",
    "net_network_reactive_consumption_var",
    "active_power_conservation_residual_w",
    "reactive_power_conservation_residual_var",
    "solver_iteration_count",
    "solver_max_voltage_delta_v",
    "grid_boundary_phase_angle_treatment",
    "transformer_terminal_voltage_coupling_treatment",
    "transformer_terminal_phase_angle_coupling_applied",
    "shunt_susceptance_semantics",
    "transformer_loss_treatment",
    "s13_series_loss_treatment",
    "s13_shunt_active_treatment",
    "s13_shunt_reactive_treatment",
    "revenue_meter_expected_power_treatment",
    "mv_hv_operating_state",
    "transformer_advanced_operating_solution_contract",
    "mv_hv_network_authority_contract",
    "mv_hv_grid_boundary_voltage_authority_contract",
    "mv_hv_operating_solution_contract",
    "mv_hv_operating_solution_model",
    "mv_hv_operating_solution_scope",
    "mv_hv_operating_solution_coverage_scope",
)
_TX_COLUMNS = (
    "transformer_terminal_node_id",
    "network_exit_node_id",
    "transformer_connected_to_network_exit",
    "s12m_row_present",
    "s12m_operating_state",
    "s12m_injection_ready",
    "transformer_energised",
    "p_network_terminal_injection_w",
    "q_network_terminal_injection_var",
    "s_network_terminal_injection_magnitude_va",
    "s12m_network_terminal_voltage_line_to_line_rms_v",
    "solved_s13_terminal_voltage_line_to_line_rms_v",
    "terminal_voltage_consistency_applicable",
    "terminal_voltage_magnitude_residual_v",
    "terminal_voltage_magnitude_consistency_satisfied",
    "mv_hv_operating_solution_resolved",
    "transformer_terminal_operating_state",
    "mv_hv_operating_solution_contract",
    "mv_hv_operating_solution_model",
)
_NODE_COLUMNS = (
    "node_kind",
    "voltage_level_id",
    "network_exit_node_id",
    "node_connected_to_network_exit",
    "mv_hv_operating_solution_resolved",
    "local_transformer_p_injection_w",
    "local_transformer_q_injection_var",
    "total_incident_half_shunt_conductance_siemens_per_phase",
    "total_incident_half_shunt_susceptance_siemens_per_phase",
    "voltage_phase_real_v",
    "voltage_phase_imag_v",
    "voltage_phase_magnitude_v",
    "voltage_line_to_line_rms_v",
    "voltage_phase_angle_deg_relative_to_grid_boundary_reference",
    "node_operating_state",
    "mv_hv_operating_solution_contract",
    "mv_hv_operating_solution_model",
)
_SEG_COLUMNS = (
    "from_node_id",
    "to_node_id",
    "network_exit_node_id",
    "segment_connected_to_network_exit",
    "mv_hv_operating_solution_resolved",
    "series_resistance_ohm_per_phase",
    "series_reactance_ohm_per_phase",
    "total_shunt_conductance_siemens_per_phase",
    "total_shunt_susceptance_siemens_per_phase",
    "series_current_real_a",
    "series_current_imag_a",
    "series_current_magnitude_a",
    "series_current_angle_deg_relative_to_grid_reference",
    "from_terminal_current_real_a",
    "from_terminal_current_imag_a",
    "to_terminal_current_real_a",
    "to_terminal_current_imag_a",
    "phase_voltage_difference_from_to_real_v",
    "phase_voltage_difference_from_to_imag_v",
    "phase_voltage_difference_from_to_magnitude_v",
    "line_to_line_voltage_magnitude_delta_from_to_v",
    "p_from_terminal_into_segment_w",
    "q_from_terminal_into_segment_var",
    "p_to_terminal_into_segment_w",
    "q_to_terminal_into_segment_var",
    "active_series_loss_w",
    "reactive_series_consumption_var",
    "active_shunt_consumption_w",
    "capacitive_shunt_reactive_injection_var",
    "net_active_consumption_w",
    "net_reactive_consumption_var",
    "segment_operating_state",
    "mv_hv_operating_solution_contract",
    "mv_hv_operating_solution_model",
)
_METER_COLUMNS = (
    "revenue_meter_node_id",
    "revenue_meter_node_kind",
    "network_exit_node_id",
    "grid_boundary_id",
    "meter_connected_to_network_exit",
    "mv_hv_operating_solution_resolved",
    "expected_meter_voltage_line_to_line_rms_v",
    "expected_p_at_revenue_meter_w",
    "expected_q_at_revenue_meter_var",
    "expected_s_at_revenue_meter_magnitude_va",
    "active_power_sign_convention",
    "reactive_power_sign_convention",
    "power_basis",
    "meter_boundary_cut_semantics",
    "revenue_meter_expected_state",
    "mv_hv_operating_solution_contract",
    "mv_hv_operating_solution_model",
)

_TREE_BOOL = frozenset(
    {
        "network_basis_resolved",
        "grid_boundary_present",
        "grid_boundary_voltage_resolved",
        "network_solve_attempted",
        "network_solve_converged",
        "transformer_terminal_voltage_consistency_checked",
        "transformer_terminal_voltage_consistency_satisfied",
        "mv_hv_operating_solution_resolved",
        "transformer_terminal_phase_angle_coupling_applied",
    }
)
_TREE_INT = frozenset(
    {
        "tree_transformer_count",
        "s12m_ready_transformer_count",
        "missing_s12m_transformer_count",
        "unresolved_s12m_transformer_count",
        "mismatched_transformer_count",
        "solver_iteration_count",
    }
)
_TREE_FLOAT = (
    frozenset(_TREE_COLUMNS)
    - _TREE_BOOL
    - _TREE_INT
    - frozenset(
        {
            "grid_boundary_id",
            "missing_s12m_transformer_ids",
            "unresolved_s12m_transformer_ids",
            "mismatched_transformer_ids",
            "grid_boundary_phase_angle_treatment",
            "transformer_terminal_voltage_coupling_treatment",
            "shunt_susceptance_semantics",
            "transformer_loss_treatment",
            "s13_series_loss_treatment",
            "s13_shunt_active_treatment",
            "s13_shunt_reactive_treatment",
            "revenue_meter_expected_power_treatment",
            "mv_hv_operating_state",
            "transformer_advanced_operating_solution_contract",
            "mv_hv_network_authority_contract",
            "mv_hv_grid_boundary_voltage_authority_contract",
            "mv_hv_operating_solution_contract",
            "mv_hv_operating_solution_model",
            "mv_hv_operating_solution_scope",
            "mv_hv_operating_solution_coverage_scope",
        }
    )
)
_TX_BOOL = frozenset(
    {
        "transformer_connected_to_network_exit",
        "s12m_row_present",
        "s12m_injection_ready",
        "terminal_voltage_consistency_applicable",
        "terminal_voltage_magnitude_consistency_satisfied",
        "mv_hv_operating_solution_resolved",
    }
)
_TX_NULLABLE_BOOL = frozenset({"transformer_energised"})
_TX_FLOAT = frozenset(
    {
        "p_network_terminal_injection_w",
        "q_network_terminal_injection_var",
        "s_network_terminal_injection_magnitude_va",
        "s12m_network_terminal_voltage_line_to_line_rms_v",
        "solved_s13_terminal_voltage_line_to_line_rms_v",
        "terminal_voltage_magnitude_residual_v",
    }
)
_NODE_BOOL = frozenset({"node_connected_to_network_exit", "mv_hv_operating_solution_resolved"})
_NODE_FLOAT = (
    frozenset(_NODE_COLUMNS)
    - _NODE_BOOL
    - frozenset(
        {
            "node_kind",
            "voltage_level_id",
            "network_exit_node_id",
            "node_operating_state",
            "mv_hv_operating_solution_contract",
            "mv_hv_operating_solution_model",
        }
    )
)
_SEG_BOOL = frozenset({"segment_connected_to_network_exit", "mv_hv_operating_solution_resolved"})
_SEG_FLOAT = (
    frozenset(_SEG_COLUMNS)
    - _SEG_BOOL
    - frozenset(
        {
            "from_node_id",
            "to_node_id",
            "network_exit_node_id",
            "segment_operating_state",
            "mv_hv_operating_solution_contract",
            "mv_hv_operating_solution_model",
        }
    )
)
_METER_BOOL = frozenset({"meter_connected_to_network_exit", "mv_hv_operating_solution_resolved"})
_METER_FLOAT = frozenset(
    {
        "expected_meter_voltage_line_to_line_rms_v",
        "expected_p_at_revenue_meter_w",
        "expected_q_at_revenue_meter_var",
        "expected_s_at_revenue_meter_magnitude_va",
    }
)


@dataclass(frozen=True)
class _Solution:
    converged: bool
    failure: str
    iterations: int
    delta: float
    voltages: Mapping[str, complex]
    currents: Mapping[str, complex]


@dataclass(frozen=True)
class TopologyMvHvOperatingSolutionDiagnostics:
    timestamp_count: int
    network_exit_count: int
    tree_row_count: int
    resolved_tree_count: int
    unresolved_tree_count: int
    transformer_terminal_row_count: int
    node_row_count: int
    segment_row_count: int
    revenue_meter_row_count: int
    state_counts: tuple[tuple[str, int], ...]
    model: str


@dataclass(frozen=True)
class TopologyMvHvOperatingSolutionResult:
    network_exit_states: pd.DataFrame
    transformer_terminal_states: pd.DataFrame
    node_states: pd.DataFrame
    segment_states: pd.DataFrame
    revenue_meter_states: pd.DataFrame
    diagnostics: TopologyMvHvOperatingSolutionDiagnostics


F = TypeVar("F", bound=Callable[..., Any])


def _call(function: F, values: Mapping[str, Any]) -> Any:
    parameters = inspect.signature(function).parameters
    if any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()):
        return function(**values)
    return function(**{name: values[name] for name in parameters})


def _exact_replay(label: str, supplied: object, canonical: object) -> None:
    if type(supplied) is not type(canonical):
        raise ValueError(f"supplied {label} result type is invalid")
    for name, expected in vars(canonical).items():
        actual = getattr(supplied, name)
        if isinstance(expected, pd.DataFrame):
            try:
                pd.testing.assert_frame_equal(actual, expected, check_exact=True)
            except AssertionError as error:
                raise ValueError(f"supplied {label} frame failed canonical replay") from error
        elif isinstance(expected, Mapping):
            if type(actual) is not MappingProxyType or tuple(actual.items()) != tuple(
                expected.items()
            ):
                raise ValueError(f"supplied {label} mapping failed immutable canonical replay")
        elif actual != expected:
            raise ValueError(f"supplied {label} diagnostics failed canonical replay")


def _parents(values: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    s12m = _call(calculate_topology_transformer_advanced_operating_solution, values)
    _exact_replay("S12M", values["transformer_advanced_operating_solution"], s12m)
    s13a = _call(resolve_topology_mv_hv_network_authority, values)
    _exact_replay("S13A", values["mv_hv_network_authority"], s13a)
    canonical_values = dict(values)
    canonical_values["mv_hv_network_authority"] = s13a
    s13b = _call(resolve_topology_mv_hv_grid_boundary_voltage_authority, canonical_values)
    _exact_replay("S13B", values["mv_hv_grid_boundary_voltage_authority"], s13b)
    return s12m, s13a, s13b


def _finite(value: complex | float) -> bool:
    if isinstance(value, complex):
        return math.isfinite(value.real) and math.isfinite(value.imag)
    return math.isfinite(value)


def _close(a: float, b: float, *, terminal: bool = False) -> bool:
    return math.isclose(
        a,
        b,
        rel_tol=TERMINAL_VOLTAGE_REL_TOL if terminal else EQUATION_REL_TOL,
        abs_tol=TERMINAL_VOLTAGE_ABS_TOL_V if terminal else EQUATION_ABS_TOL,
    )


def _membership(
    network: TopologyMvHvNetworkAuthorityResult,
) -> tuple[dict[str, str | None], dict[str, str | None]]:
    outgoing = {s.from_node_id: s.to_node_id for s in network.segments_by_id.values()}
    node_exit: dict[str, str | None] = {}
    for start in network.nodes_by_id:
        current = start
        while current in outgoing:
            current = outgoing[current]
        node_exit[start] = (
            current if network.nodes_by_id[current].node_kind == "network_exit" else None
        )
    segment_exit = {sid: node_exit[s.from_node_id] for sid, s in network.segments_by_id.items()}
    return node_exit, segment_exit


def _node_shunts(
    nodes: Mapping[str, MvHvNetworkNodeAuthority],
    segments: Mapping[str, MvHvNetworkSegmentAuthority],
) -> dict[str, complex]:
    result = {identifier: 0j for identifier in nodes}
    for segment in segments.values():
        half = 0.5 * complex(
            segment.total_shunt_conductance_siemens_per_phase,
            segment.total_shunt_susceptance_siemens_per_phase,
        )
        result[segment.from_node_id] += half
        result[segment.to_node_id] += half
    return result


def _sweep_currents(
    nodes: Mapping[str, MvHvNetworkNodeAuthority],
    segments: Mapping[str, MvHvNetworkSegmentAuthority],
    injections: Mapping[str, complex],
    voltages: Mapping[str, complex],
) -> tuple[dict[str, complex], complex, bool]:
    incoming: dict[str, list[MvHvNetworkSegmentAuthority]] = {node: [] for node in nodes}
    outgoing: dict[str, MvHvNetworkSegmentAuthority] = {}
    for segment in segments.values():
        incoming[segment.to_node_id].append(segment)
        outgoing[segment.from_node_id] = segment
    shunts = _node_shunts(nodes, segments)
    aggregate: dict[str, complex] = {}

    def visit(node: str) -> complex:
        power, voltage = injections.get(node, 0j), voltages[node]
        if power == 0j:
            value = -shunts[node] * voltage
        elif voltage == 0j:
            raise ZeroDivisionError
        else:
            value = (power / (3.0 * voltage)).conjugate() - shunts[node] * voltage
        for child in incoming[node]:
            value += visit(child.from_node_id)
        aggregate[node] = value
        return value

    exits = [node for node in nodes if node not in outgoing]
    try:
        grid = visit(exits[0])
    except (OverflowError, ZeroDivisionError):
        return {}, complex(math.nan, math.nan), False
    currents = {sid: aggregate[s.from_node_id] for sid, s in segments.items()}
    finite = _finite(grid) and all(_finite(value) for value in currents.values())
    return currents, grid, finite


def _forward_voltages(
    exit_id: str,
    grid_phase: complex,
    nodes: Mapping[str, MvHvNetworkNodeAuthority],
    segments: Mapping[str, MvHvNetworkSegmentAuthority],
    currents: Mapping[str, complex],
) -> tuple[dict[str, complex], bool]:
    incoming: dict[str, list[MvHvNetworkSegmentAuthority]] = {node: [] for node in nodes}
    for segment in segments.values():
        incoming[segment.to_node_id].append(segment)
    result = {exit_id: grid_phase}

    def visit(node: str) -> bool:
        for segment in incoming[node]:
            impedance = complex(
                segment.series_resistance_ohm_per_phase,
                segment.series_reactance_ohm_per_phase,
            )
            voltage = result[node] + impedance * currents[segment.segment_id]
            if not _finite(voltage):
                return False
            result[segment.from_node_id] = voltage
            if not visit(segment.from_node_id):
                return False
        return True

    return result, visit(exit_id)


def _solve_tree(
    exit_id: str,
    voltage_ll: float,
    nodes: Mapping[str, MvHvNetworkNodeAuthority],
    segments: Mapping[str, MvHvNetworkSegmentAuthority],
    injections: Mapping[str, complex],
) -> _Solution:
    nonzero = any(value != 0j for value in injections.values())
    if voltage_ll == 0.0:
        if nonzero:
            return _Solution(False, "zero_nonzero", 0, math.nan, {}, {})
        return _Solution(
            True, "zero", 0, 0.0, {key: 0j for key in nodes}, {key: 0j for key in segments}
        )
    grid = complex(voltage_ll / math.sqrt(3.0), 0.0)
    voltages = {node: grid for node in nodes}
    delta = math.nan
    for iteration in range(1, MAX_ITERATIONS + 1):
        currents, _, finite = _sweep_currents(nodes, segments, injections, voltages)
        if not finite:
            return _Solution(False, "nonfinite", iteration, math.nan, {}, {})
        candidate, finite = _forward_voltages(exit_id, grid, nodes, segments, currents)
        if not finite or set(candidate) != set(nodes):
            return _Solution(False, "nonfinite", iteration, math.nan, {}, {})
        delta = max(abs(candidate[node] - voltages[node]) for node in nodes)
        converged = all(
            math.isclose(
                abs(candidate[node] - voltages[node]),
                0.0,
                rel_tol=VOLTAGE_REL_TOL,
                abs_tol=VOLTAGE_ABS_TOL_V,
            )
            for node in nodes
        )
        voltages = candidate
        if converged:
            final_currents, _, finite = _sweep_currents(nodes, segments, injections, voltages)
            implied, implied_finite = _forward_voltages(
                exit_id, grid, nodes, segments, final_currents
            )
            if not finite or not implied_finite:
                return _Solution(False, "nonfinite", iteration, math.nan, {}, {})
            residual = max(abs(implied[node] - voltages[node]) for node in nodes)
            if all(
                math.isclose(
                    abs(implied[node] - voltages[node]),
                    0.0,
                    rel_tol=VOLTAGE_REL_TOL,
                    abs_tol=VOLTAGE_ABS_TOL_V,
                )
                for node in nodes
            ):
                return _Solution(
                    True, "", iteration, max(delta, residual), voltages, final_currents
                )
    return _Solution(False, "nonconvergence", MAX_ITERATIONS, delta, {}, {})


def _branch(
    segment: MvHvNetworkSegmentAuthority, vf: complex, vt: complex, current: complex
) -> dict[str, float | complex]:
    z = complex(segment.series_resistance_ohm_per_phase, segment.series_reactance_ohm_per_phase)
    y = complex(
        segment.total_shunt_conductance_siemens_per_phase,
        segment.total_shunt_susceptance_siemens_per_phase,
    )
    i_from = current + 0.5 * y * vf
    i_to = -current + 0.5 * y * vt
    s_from = 3.0 * vf * i_from.conjugate()
    s_to = 3.0 * vt * i_to.conjugate()
    v2 = abs(vf) ** 2 + abs(vt) ** 2
    p_series = 3.0 * z.real * abs(current) ** 2
    q_series = 3.0 * z.imag * abs(current) ** 2
    p_shunt = 1.5 * y.real * v2
    q_cap = 1.5 * y.imag * v2
    return {
        "i_from": i_from,
        "i_to": i_to,
        "s_from": s_from,
        "s_to": s_to,
        "p_series": p_series,
        "q_series": q_series,
        "p_shunt": p_shunt,
        "q_cap": q_cap,
    }


def _nan_tree() -> dict[str, object]:
    row: dict[str, object] = {column: None for column in _TREE_COLUMNS}
    for column in _TREE_COLUMNS:
        if any(token in column for token in ("_w", "_var", "_va", "_v")):
            row[column] = math.nan
    for column in (
        "network_basis_resolved",
        "grid_boundary_present",
        "grid_boundary_voltage_resolved",
        "network_solve_attempted",
        "network_solve_converged",
        "transformer_terminal_voltage_consistency_checked",
        "transformer_terminal_voltage_consistency_satisfied",
        "mv_hv_operating_solution_resolved",
        "transformer_terminal_phase_angle_coupling_applied",
    ):
        row[column] = False
    for column in (
        "tree_transformer_count",
        "s12m_ready_transformer_count",
        "missing_s12m_transformer_count",
        "unresolved_s12m_transformer_count",
        "mismatched_transformer_count",
        "solver_iteration_count",
    ):
        row[column] = 0
    row.update(
        {
            "missing_s12m_transformer_ids": (),
            "unresolved_s12m_transformer_ids": (),
            "mismatched_transformer_ids": (),
            "grid_boundary_phase_angle_treatment": GRID_ANGLE_TREATMENT,
            "transformer_terminal_voltage_coupling_treatment": TERMINAL_COUPLING,
            "shunt_susceptance_semantics": SHUNT_SEMANTICS,
            "transformer_loss_treatment": TRANSFORMER_LOSS_TREATMENT,
            "s13_series_loss_treatment": SERIES_LOSS_TREATMENT,
            "s13_shunt_active_treatment": SHUNT_ACTIVE_TREATMENT,
            "s13_shunt_reactive_treatment": SHUNT_REACTIVE_TREATMENT,
            "revenue_meter_expected_power_treatment": METER_TREATMENT,
            "transformer_advanced_operating_solution_contract": (
                TRANSFORMER_ADVANCED_OPERATING_SOLUTION_CONTRACT_ID
            ),
            "mv_hv_network_authority_contract": MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
            "mv_hv_grid_boundary_voltage_authority_contract": (
                MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_CONTRACT_ID
            ),
            "mv_hv_operating_solution_contract": MV_HV_OPERATING_SOLUTION_CONTRACT_ID,
            "mv_hv_operating_solution_model": MV_HV_OPERATING_SOLUTION_MODEL_ID,
            "mv_hv_operating_solution_scope": MV_HV_OPERATING_SOLUTION_SCOPE,
            "mv_hv_operating_solution_coverage_scope": MV_HV_OPERATING_SOLUTION_COVERAGE_SCOPE,
        }
    )
    return row


def _timestamps(s12m: Any, s13b: Any) -> tuple[pd.Timestamp, ...]:
    groups = []
    for frame in (s12m.states, s13b.states):
        groups.append(set(frame.index.get_level_values("timestamp")) if len(frame) else set())
    try:
        return tuple(sorted(set().union(*groups)))
    except TypeError as error:
        raise ValueError("S13C timestamps have incompatible timezone semantics") from error


def _build_result(parents: tuple[Any, Any, Any]) -> TopologyMvHvOperatingSolutionResult:
    s12m, network, voltage = parents
    times = _timestamps(s12m, voltage)
    exits = tuple(
        key for key, node in network.nodes_by_id.items() if node.node_kind == "network_exit"
    )
    node_exit, segment_exit = _membership(network)
    grid_by_exit = {grid.node_id: grid for grid in network.grid_boundary_by_id.values()}
    binding_by_node = {
        binding.node_id: tx
        for tx, binding in network.transformer_terminal_binding_by_transformer_id.items()
    }
    tree_records: list[dict[str, object]] = []
    tree_data: dict[tuple[pd.Timestamp, str], dict[str, Any]] = {}
    for timestamp in times:
        for exit_id in exits:
            row = _nan_tree()
            tree_nodes = {
                key: value
                for key, value in network.nodes_by_id.items()
                if node_exit[key] == exit_id
            }
            tree_segments = {
                key: value
                for key, value in network.segments_by_id.items()
                if segment_exit[key] == exit_id
            }
            txs = tuple(binding_by_node[node] for node in tree_nodes if node in binding_by_node)
            grid = grid_by_exit.get(exit_id)
            row.update(
                {
                    "grid_boundary_id": grid.grid_boundary_id if grid else None,
                    "network_basis_resolved": network.network_basis is not None,
                    "grid_boundary_present": grid is not None,
                    "tree_transformer_count": len(txs),
                }
            )
            missing: list[str] = []
            unresolved: list[str] = []
            injections: dict[str, complex] = {}
            tx_rows: dict[str, pd.Series] = {}
            for tx in txs:
                key = (timestamp, tx)
                if key not in s12m.states.index:
                    missing.append(tx)
                    continue
                upstream = s12m.states.loc[key]
                tx_rows[tx] = upstream
                state = upstream["transformer_advanced_operating_solution_state"]
                node = network.transformer_terminal_binding_by_transformer_id[tx].node_id
                if state == "resolved_coupled_advanced_transformer_terminal_solution":
                    injections[node] = complex(
                        upstream["p_network_terminal_w"], upstream["q_network_terminal_var"]
                    )
                elif state == "resolved_deenergised_transformer_zero_advanced_transfer":
                    injections[node] = 0j
                else:
                    unresolved.append(tx)
            row.update(
                {
                    "s12m_ready_transformer_count": len(injections),
                    "missing_s12m_transformer_count": len(missing),
                    "unresolved_s12m_transformer_count": len(unresolved),
                    "missing_s12m_transformer_ids": tuple(missing),
                    "unresolved_s12m_transformer_ids": tuple(unresolved),
                }
            )
            boundary_row = None
            if grid is not None and (timestamp, grid.grid_boundary_id) in voltage.states.index:
                boundary_row = voltage.states.loc[(timestamp, grid.grid_boundary_id)]
            boundary_resolved = boundary_row is not None and bool(
                boundary_row["grid_boundary_voltage_authority_resolved"]
            )
            if boundary_resolved:
                assert boundary_row is not None
                boundary_v = float(boundary_row["voltage_line_to_line_rms_v"])
            else:
                boundary_v = math.nan
            row["grid_boundary_voltage_resolved"] = boundary_resolved
            row["grid_boundary_voltage_line_to_line_rms_v"] = boundary_v
            if network.network_basis is None:
                state = _TREE_STATES[0]
            elif grid is None:
                state = _TREE_STATES[1]
            elif not boundary_resolved:
                state = _TREE_STATES[2]
            elif missing:
                state = _TREE_STATES[3]
            elif unresolved:
                state = _TREE_STATES[4]
            else:
                p_total = math.fsum(value.real for value in injections.values())
                q_total = math.fsum(value.imag for value in injections.values())
                row.update(
                    {
                        "transformer_injected_p_total_w": p_total,
                        "transformer_injected_q_total_var": q_total,
                        "transformer_injected_s_vector_magnitude_va": abs(
                            complex(p_total, q_total)
                        ),
                    }
                )
                solution = _solve_tree(exit_id, boundary_v, tree_nodes, tree_segments, injections)
                row.update(
                    {
                        "network_solve_attempted": boundary_v != 0.0,
                        "network_solve_converged": solution.converged,
                        "solver_iteration_count": solution.iterations,
                        "solver_max_voltage_delta_v": solution.delta,
                    }
                )
                if solution.failure == "zero_nonzero":
                    state = _TREE_STATES[5]
                elif solution.failure == "nonfinite":
                    state = _TREE_STATES[6]
                elif solution.failure == "nonconvergence":
                    state = _TREE_STATES[7]
                else:
                    mismatched: list[str] = []
                    residuals: dict[str, float] = {}
                    applicable = 0
                    for tx, upstream in tx_rows.items():
                        if (
                            upstream["transformer_advanced_operating_solution_state"]
                            != "resolved_coupled_advanced_transformer_terminal_solution"
                        ):
                            continue
                        applicable += 1
                        node = network.transformer_terminal_binding_by_transformer_id[tx].node_id
                        solved = math.sqrt(3.0) * abs(solution.voltages[node])
                        expected = float(upstream["network_terminal_voltage_line_to_line_rms_v"])
                        residuals[tx] = solved - expected
                        if not _close(solved, expected, terminal=True):
                            mismatched.append(tx)
                    row.update(
                        {
                            "transformer_terminal_voltage_consistency_checked": applicable > 0,
                            "transformer_terminal_voltage_consistency_satisfied": not mismatched,
                            "mismatched_transformer_count": len(mismatched),
                            "mismatched_transformer_ids": tuple(mismatched),
                            "maximum_transformer_terminal_voltage_magnitude_residual_v": max(
                                (abs(v) for v in residuals.values()), default=0.0
                            ),
                        }
                    )
                    if mismatched:
                        # Retain the converged candidate only for boundary-mismatch
                        # diagnostics.  Downstream physical frames continue to gate
                        # publication on the tree's final resolved flag.
                        tree_data[(timestamp, exit_id)] = {
                            "solution": solution,
                            "injections": injections,
                            "residuals": residuals,
                        }
                        state = _TREE_STATES[8]
                    else:
                        currents, grid_current, finite = _sweep_currents(
                            tree_nodes, tree_segments, injections, solution.voltages
                        )
                        branches = {
                            sid: _branch(
                                seg,
                                solution.voltages[seg.from_node_id],
                                solution.voltages[seg.to_node_id],
                                currents[sid],
                            )
                            for sid, seg in tree_segments.items()
                        }
                        if not finite or not all(
                            _finite(cast(float, item[key]))
                            for item in branches.values()
                            for key in ("p_series", "q_series", "p_shunt", "q_cap")
                        ):
                            state = _TREE_STATES[6]
                        else:
                            s_grid = 3.0 * solution.voltages[exit_id] * grid_current.conjugate()
                            ps = math.fsum(
                                cast(float, item["p_series"]) for item in branches.values()
                            )
                            qs = math.fsum(
                                cast(float, item["q_series"]) for item in branches.values()
                            )
                            pg = math.fsum(
                                cast(float, item["p_shunt"]) for item in branches.values()
                            )
                            qb = math.fsum(cast(float, item["q_cap"]) for item in branches.values())
                            pa = p_total - s_grid.real - ps - pg
                            qr = q_total + qb - s_grid.imag - qs
                            resolved = _close(pa, 0.0) and _close(qr, 0.0)
                            if not resolved:
                                state = _TREE_STATES[6]
                            else:
                                state = _TREE_STATES[9] if boundary_v == 0.0 else _TREE_STATES[10]
                                row.update(
                                    {
                                        "mv_hv_operating_solution_resolved": True,
                                        "p_export_at_grid_boundary_w": s_grid.real,
                                        "q_export_at_grid_boundary_var": s_grid.imag,
                                        "s_export_at_grid_boundary_magnitude_va": abs(s_grid),
                                        "total_series_active_loss_w": ps,
                                        "total_series_reactive_consumption_var": qs,
                                        "total_shunt_active_consumption_w": pg,
                                        "total_shunt_capacitive_reactive_injection_var": qb,
                                        "net_network_active_consumption_w": ps + pg,
                                        "net_network_reactive_consumption_var": qs - qb,
                                        "active_power_conservation_residual_w": pa,
                                        "reactive_power_conservation_residual_var": qr,
                                    }
                                )
                                tree_data[(timestamp, exit_id)] = {
                                    "solution": solution,
                                    "injections": injections,
                                    "branches": branches,
                                    "grid_power": s_grid,
                                    "tx_rows": tx_rows,
                                    "residuals": residuals,
                                }
            row["mv_hv_operating_state"] = state
            tree_records.append(row)
    tree = _make_frame(
        [(t, e) for t in times for e in exits],
        tree_records,
        _TREE_COLUMNS,
        ["timestamp", "network_exit_node_id"],
        _TREE_BOOL,
        frozenset(),
        _TREE_INT,
        _TREE_FLOAT,
    )
    tx = _transformer_frame(times, s12m, network, node_exit, tree, tree_data)
    nodes = _node_frame(times, network, node_exit, tree, tree_data)
    segments = _segment_frame(times, network, segment_exit, tree, tree_data)
    meters = _meter_frame(times, network, node_exit, tree, tree_data)
    states = tree["mv_hv_operating_state"]
    diagnostics = TopologyMvHvOperatingSolutionDiagnostics(
        len(times),
        len(exits),
        len(tree),
        int(tree["mv_hv_operating_solution_resolved"].sum()),
        int((~tree["mv_hv_operating_solution_resolved"]).sum()),
        len(tx),
        len(nodes),
        len(segments),
        len(meters),
        tuple((state, int((states == state).sum())) for state in _TREE_STATES),
        MV_HV_OPERATING_SOLUTION_MODEL_ID,
    )
    return TopologyMvHvOperatingSolutionResult(tree, tx, nodes, segments, meters, diagnostics)


def _make_frame(
    keys: list[tuple[Any, str]],
    rows: list[dict[str, object]],
    columns: tuple[str, ...],
    names: list[str],
    bool_columns: frozenset[str],
    nullable_bool_columns: frozenset[str],
    int_columns: frozenset[str],
    float_columns: frozenset[str],
) -> pd.DataFrame:
    index = (
        pd.MultiIndex.from_tuples(keys, names=names)
        if keys
        else pd.MultiIndex.from_arrays([[] for _ in names], names=names)
    )
    frame = pd.DataFrame.from_records(rows, columns=columns)
    frame.index = index
    for column in columns:
        if column in bool_columns:
            frame[column] = frame[column].astype("bool")
        elif column in nullable_bool_columns:
            frame[column] = frame[column].astype("boolean")
        elif column in int_columns:
            frame[column] = frame[column].astype("int64")
        elif column in float_columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
        else:
            frame[column] = frame[column].astype("object")
    return frame


def _transformer_frame(
    times: tuple[pd.Timestamp, ...],
    s12m: Any,
    network: Any,
    node_exit: Mapping[str, str | None],
    tree: pd.DataFrame,
    data: Mapping[tuple[pd.Timestamp, str], dict[str, Any]],
) -> pd.DataFrame:
    rows = []
    ids = tuple(network.transformer_terminal_binding_by_transformer_id)
    for timestamp in times:
        for tx in ids:
            binding = network.transformer_terminal_binding_by_transformer_id[tx]
            exit_id = node_exit[binding.node_id]
            upstream = (
                s12m.states.loc[(timestamp, tx)] if (timestamp, tx) in s12m.states.index else None
            )
            tree_resolved = exit_id is not None and bool(
                tree.loc[(timestamp, exit_id), "mv_hv_operating_solution_resolved"]
            )
            state = (
                upstream["transformer_advanced_operating_solution_state"]
                if upstream is not None
                else ""
            )
            ready = state in {
                "resolved_coupled_advanced_transformer_terminal_solution",
                "resolved_deenergised_transformer_zero_advanced_transfer",
            }
            energised = upstream["transformer_energised"] if upstream is not None else pd.NA
            applicable = state == "resolved_coupled_advanced_transformer_terminal_solution"
            if applicable:
                assert upstream is not None
                p = float(upstream["p_network_terminal_w"])
                q = float(upstream["q_network_terminal_var"])
                s12m_voltage = float(upstream["network_terminal_voltage_line_to_line_rms_v"])
            elif state == "resolved_deenergised_transformer_zero_advanced_transfer":
                p = q = 0.0
                s12m_voltage = math.nan
            else:
                p = q = s12m_voltage = math.nan
            solved = math.nan
            residual = math.nan
            candidate = data.get((timestamp, exit_id)) if exit_id is not None else None
            if applicable and candidate is not None:
                assert candidate is not None
                candidate_voltage = math.sqrt(3.0) * abs(
                    candidate["solution"].voltages[binding.node_id]
                )
                if applicable:
                    assert upstream is not None
                    residual = candidate_voltage - float(
                        upstream["network_terminal_voltage_line_to_line_rms_v"]
                    )
                if tree_resolved:
                    solved = candidate_voltage
            rows.append(
                {
                    "transformer_terminal_node_id": binding.node_id,
                    "network_exit_node_id": exit_id,
                    "transformer_connected_to_network_exit": exit_id is not None,
                    "s12m_row_present": upstream is not None,
                    "s12m_operating_state": state,
                    "s12m_injection_ready": ready,
                    "transformer_energised": energised,
                    "p_network_terminal_injection_w": p,
                    "q_network_terminal_injection_var": q,
                    "s_network_terminal_injection_magnitude_va": abs(complex(p, q))
                    if math.isfinite(p) and math.isfinite(q)
                    else math.nan,
                    "s12m_network_terminal_voltage_line_to_line_rms_v": s12m_voltage,
                    "solved_s13_terminal_voltage_line_to_line_rms_v": solved,
                    "terminal_voltage_consistency_applicable": applicable,
                    "terminal_voltage_magnitude_residual_v": residual,
                    "terminal_voltage_magnitude_consistency_satisfied": (not applicable)
                    or (candidate is not None and _close(residual, 0.0, terminal=True)),
                    "mv_hv_operating_solution_resolved": tree_resolved,
                    "transformer_terminal_operating_state": (
                        "resolved_transformer_terminal_mv_hv_operating_state"
                    )
                    if tree_resolved
                    else "unresolved_upstream_mv_hv_operating_solution",
                    "mv_hv_operating_solution_contract": MV_HV_OPERATING_SOLUTION_CONTRACT_ID,
                    "mv_hv_operating_solution_model": MV_HV_OPERATING_SOLUTION_MODEL_ID,
                }
            )
    return _make_frame(
        [(t, i) for t in times for i in ids],
        rows,
        _TX_COLUMNS,
        ["timestamp", "transformer_id"],
        _TX_BOOL,
        _TX_NULLABLE_BOOL,
        frozenset(),
        _TX_FLOAT,
    )


def _node_frame(
    times: tuple[pd.Timestamp, ...],
    network: Any,
    node_exit: Mapping[str, str | None],
    tree: pd.DataFrame,
    data: Mapping[tuple[pd.Timestamp, str], dict[str, Any]],
) -> pd.DataFrame:
    shunts = _node_shunts(network.nodes_by_id, network.segments_by_id)
    rows = []
    for timestamp in times:
        for node_id, node in network.nodes_by_id.items():
            exit_id = node_exit[node_id]
            resolved = exit_id is not None and bool(
                tree.loc[(timestamp, exit_id), "mv_hv_operating_solution_resolved"]
            )
            voltage = (
                data[(timestamp, cast(str, exit_id))]["solution"].voltages[node_id]
                if resolved
                else complex(math.nan, math.nan)
            )
            injection = (
                data[(timestamp, cast(str, exit_id))]["injections"].get(node_id, 0j)
                if resolved
                else complex(math.nan, math.nan)
            )
            rows.append(
                {
                    "node_kind": node.node_kind,
                    "voltage_level_id": node.voltage_level_id,
                    "network_exit_node_id": exit_id,
                    "node_connected_to_network_exit": exit_id is not None,
                    "mv_hv_operating_solution_resolved": resolved,
                    "local_transformer_p_injection_w": injection.real,
                    "local_transformer_q_injection_var": injection.imag,
                    "total_incident_half_shunt_conductance_siemens_per_phase": shunts[node_id].real,
                    "total_incident_half_shunt_susceptance_siemens_per_phase": shunts[node_id].imag,
                    "voltage_phase_real_v": voltage.real,
                    "voltage_phase_imag_v": voltage.imag,
                    "voltage_phase_magnitude_v": abs(voltage),
                    "voltage_line_to_line_rms_v": math.sqrt(3.0) * abs(voltage),
                    "voltage_phase_angle_deg_relative_to_grid_boundary_reference": math.degrees(
                        cmath.phase(voltage)
                    )
                    if resolved and voltage != 0j
                    else 0.0
                    if resolved
                    else math.nan,
                    "node_operating_state": "resolved_mv_hv_node_operating_state"
                    if resolved
                    else "unresolved_upstream_mv_hv_operating_solution",
                    "mv_hv_operating_solution_contract": MV_HV_OPERATING_SOLUTION_CONTRACT_ID,
                    "mv_hv_operating_solution_model": MV_HV_OPERATING_SOLUTION_MODEL_ID,
                }
            )
    return _make_frame(
        [(t, n) for t in times for n in network.nodes_by_id],
        rows,
        _NODE_COLUMNS,
        ["timestamp", "node_id"],
        _NODE_BOOL,
        frozenset(),
        frozenset(),
        _NODE_FLOAT,
    )


def _segment_frame(
    times: tuple[pd.Timestamp, ...],
    network: Any,
    segment_exit: Mapping[str, str | None],
    tree: pd.DataFrame,
    data: Mapping[tuple[pd.Timestamp, str], dict[str, Any]],
) -> pd.DataFrame:
    rows = []
    for timestamp in times:
        for sid, segment in network.segments_by_id.items():
            exit_id = segment_exit[sid]
            resolved = exit_id is not None and bool(
                tree.loc[(timestamp, exit_id), "mv_hv_operating_solution_resolved"]
            )
            values: dict[str, Any] = {column: math.nan for column in _SEG_COLUMNS}
            values.update(
                {
                    "from_node_id": segment.from_node_id,
                    "to_node_id": segment.to_node_id,
                    "network_exit_node_id": exit_id,
                    "segment_connected_to_network_exit": exit_id is not None,
                    "mv_hv_operating_solution_resolved": resolved,
                    "series_resistance_ohm_per_phase": segment.series_resistance_ohm_per_phase,
                    "series_reactance_ohm_per_phase": segment.series_reactance_ohm_per_phase,
                    "total_shunt_conductance_siemens_per_phase": (
                        segment.total_shunt_conductance_siemens_per_phase
                    ),
                    "total_shunt_susceptance_siemens_per_phase": (
                        segment.total_shunt_susceptance_siemens_per_phase
                    ),
                    "segment_operating_state": "resolved_nominal_pi_segment_operating_state"
                    if resolved
                    else "unresolved_upstream_mv_hv_operating_solution",
                    "mv_hv_operating_solution_contract": MV_HV_OPERATING_SOLUTION_CONTRACT_ID,
                    "mv_hv_operating_solution_model": MV_HV_OPERATING_SOLUTION_MODEL_ID,
                }
            )
            if resolved:
                solution = data[(timestamp, cast(str, exit_id))]["solution"]
                current = solution.currents[sid]
                vf, vt = (
                    solution.voltages[segment.from_node_id],
                    solution.voltages[segment.to_node_id],
                )
                branch = data[(timestamp, cast(str, exit_id))]["branches"][sid]
                delta = vf - vt
                values.update(
                    {
                        "series_current_real_a": current.real,
                        "series_current_imag_a": current.imag,
                        "series_current_magnitude_a": abs(current),
                        "series_current_angle_deg_relative_to_grid_reference": math.degrees(
                            cmath.phase(current)
                        )
                        if current
                        else 0.0,
                        "from_terminal_current_real_a": branch["i_from"].real,
                        "from_terminal_current_imag_a": branch["i_from"].imag,
                        "to_terminal_current_real_a": branch["i_to"].real,
                        "to_terminal_current_imag_a": branch["i_to"].imag,
                        "phase_voltage_difference_from_to_real_v": delta.real,
                        "phase_voltage_difference_from_to_imag_v": delta.imag,
                        "phase_voltage_difference_from_to_magnitude_v": abs(delta),
                        "line_to_line_voltage_magnitude_delta_from_to_v": math.sqrt(3.0)
                        * (abs(vf) - abs(vt)),
                        "p_from_terminal_into_segment_w": branch["s_from"].real,
                        "q_from_terminal_into_segment_var": branch["s_from"].imag,
                        "p_to_terminal_into_segment_w": branch["s_to"].real,
                        "q_to_terminal_into_segment_var": branch["s_to"].imag,
                        "active_series_loss_w": branch["p_series"],
                        "reactive_series_consumption_var": branch["q_series"],
                        "active_shunt_consumption_w": branch["p_shunt"],
                        "capacitive_shunt_reactive_injection_var": branch["q_cap"],
                        "net_active_consumption_w": branch["p_series"] + branch["p_shunt"],
                        "net_reactive_consumption_var": branch["q_series"] - branch["q_cap"],
                    }
                )
            rows.append(values)
    return _make_frame(
        [(t, s) for t in times for s in network.segments_by_id],
        rows,
        _SEG_COLUMNS,
        ["timestamp", "segment_id"],
        _SEG_BOOL,
        frozenset(),
        frozenset(),
        _SEG_FLOAT,
    )


def _meter_frame(
    times: tuple[pd.Timestamp, ...],
    network: Any,
    node_exit: Mapping[str, str | None],
    tree: pd.DataFrame,
    data: Mapping[tuple[pd.Timestamp, str], dict[str, Any]],
) -> pd.DataFrame:
    outgoing = {segment.from_node_id: segment for segment in network.segments_by_id.values()}
    grid_by_exit = {
        grid.node_id: grid.grid_boundary_id for grid in network.grid_boundary_by_id.values()
    }
    rows = []
    for timestamp in times:
        for meter in network.revenue_meter_boundary_by_id.values():
            node = network.nodes_by_id[meter.node_id]
            exit_id = node_exit[meter.node_id]
            resolved = exit_id is not None and bool(
                tree.loc[(timestamp, exit_id), "mv_hv_operating_solution_resolved"]
            )
            voltage = p = q = math.nan
            if resolved:
                solution = data[(timestamp, cast(str, exit_id))]["solution"]
                voltage = math.sqrt(3.0) * abs(solution.voltages[meter.node_id])
                power = (
                    data[(timestamp, cast(str, exit_id))]["grid_power"]
                    if meter.node_id == exit_id
                    else data[(timestamp, cast(str, exit_id))]["branches"][
                        outgoing[meter.node_id].segment_id
                    ]["s_from"]
                )
                p, q = power.real, power.imag
            rows.append(
                {
                    "revenue_meter_node_id": meter.node_id,
                    "revenue_meter_node_kind": node.node_kind,
                    "network_exit_node_id": exit_id,
                    "grid_boundary_id": grid_by_exit.get(exit_id),
                    "meter_connected_to_network_exit": exit_id is not None,
                    "mv_hv_operating_solution_resolved": resolved,
                    "expected_meter_voltage_line_to_line_rms_v": voltage,
                    "expected_p_at_revenue_meter_w": p,
                    "expected_q_at_revenue_meter_var": q,
                    "expected_s_at_revenue_meter_magnitude_va": abs(complex(p, q))
                    if resolved
                    else math.nan,
                    "active_power_sign_convention": meter.active_power_sign_convention,
                    "reactive_power_sign_convention": meter.reactive_power_sign_convention,
                    "power_basis": meter.power_basis,
                    "meter_boundary_cut_semantics": METER_CUT,
                    "revenue_meter_expected_state": "resolved_expected_revenue_meter_boundary_power"
                    if resolved
                    else "unresolved_upstream_mv_hv_operating_solution"
                    if exit_id is not None
                    else "unresolved_revenue_meter_node_not_connected_to_network_exit",
                    "mv_hv_operating_solution_contract": MV_HV_OPERATING_SOLUTION_CONTRACT_ID,
                    "mv_hv_operating_solution_model": MV_HV_OPERATING_SOLUTION_MODEL_ID,
                }
            )
    return _make_frame(
        [(t, m) for t in times for m in network.revenue_meter_boundary_by_id],
        rows,
        _METER_COLUMNS,
        ["timestamp", "revenue_meter_id"],
        _METER_BOOL,
        frozenset(),
        frozenset(),
        _METER_FLOAT,
    )


def calculate_topology_mv_hv_operating_solution(
    **values: Any,
) -> TopologyMvHvOperatingSolutionResult:
    parents = _parents(values)
    result = _build_result(parents)
    _validate_result(parents, result)
    return result


# Validator equations are separately implemented.  They do not call or alias
# production tree membership, sweep, solver, branch, meter, frame, or diagnostic builders.
def _validator_check_row(row: pd.Series, expected: Mapping[str, object], label: str) -> None:
    for column, value in expected.items():
        actual = row[column]
        if pd.isna(value) if not isinstance(value, tuple) else False:
            valid = pd.isna(actual)
        elif value is pd.NA:
            valid = actual is pd.NA or pd.isna(actual)
        else:
            valid = actual == value
        if not bool(valid):
            raise RuntimeError(f"S13C {label} failed independent exact closure")


def _validator_solve(
    exit_id: str,
    voltage_ll: float,
    nodes: Mapping[str, MvHvNetworkNodeAuthority],
    segments: Mapping[str, MvHvNetworkSegmentAuthority],
    injections: Mapping[str, complex],
) -> _Solution:
    incoming: dict[str, list[str]] = {node: [] for node in nodes}
    for sid, segment in segments.items():
        incoming[segment.to_node_id].append(sid)
    shunt = {node: 0j for node in nodes}
    for segment in segments.values():
        half = 0.5 * complex(
            segment.total_shunt_conductance_siemens_per_phase,
            segment.total_shunt_susceptance_siemens_per_phase,
        )
        shunt[segment.from_node_id] += half
        shunt[segment.to_node_id] += half
    if voltage_ll == 0.0:
        if any(value != 0j for value in injections.values()):
            return _Solution(False, "zero_nonzero", 0, math.nan, {}, {})
        return _Solution(
            True, "zero", 0, 0.0, {node: 0j for node in nodes}, {sid: 0j for sid in segments}
        )
    fixed = complex(voltage_ll / math.sqrt(3.0), 0.0)
    volts = {node: fixed for node in nodes}
    last = math.nan
    for iteration in range(1, MAX_ITERATIONS + 1):
        currents: dict[str, complex] = {}

        def aggregate(
            node: str,
            current_voltages: Mapping[str, complex] = volts,
            branch_currents: dict[str, complex] = currents,
        ) -> complex:
            power = injections.get(node, 0j)
            if power != 0j and current_voltages[node] == 0j:
                raise ZeroDivisionError
            value = (power / (3.0 * current_voltages[node])).conjugate() if power != 0j else 0j
            value -= shunt[node] * current_voltages[node]
            for sid in incoming[node]:
                child = segments[sid].from_node_id
                child_current = aggregate(child)
                branch_currents[sid] = child_current
                value += child_current
            return value

        try:
            aggregate(exit_id)
        except (OverflowError, ZeroDivisionError):
            return _Solution(False, "nonfinite", iteration, math.nan, {}, {})
        candidate = {exit_id: fixed}

        def descend(
            node: str,
            proposed_voltages: dict[str, complex] = candidate,
            branch_currents: Mapping[str, complex] = currents,
        ) -> None:
            for sid in incoming[node]:
                segment = segments[sid]
                z = complex(
                    segment.series_resistance_ohm_per_phase, segment.series_reactance_ohm_per_phase
                )
                proposed_voltages[segment.from_node_id] = (
                    proposed_voltages[node] + z * branch_currents[sid]
                )
                descend(segment.from_node_id)

        descend(exit_id)
        if not all(_finite(value) for value in (*candidate.values(), *currents.values())):
            return _Solution(False, "nonfinite", iteration, math.nan, {}, {})
        last = max(abs(candidate[node] - volts[node]) for node in nodes)
        close = all(
            math.isclose(
                abs(candidate[node] - volts[node]),
                0.0,
                rel_tol=VOLTAGE_REL_TOL,
                abs_tol=VOLTAGE_ABS_TOL_V,
            )
            for node in nodes
        )
        volts = candidate
        if close:
            # One extra independent iteration supplies fresh currents and implied voltages.
            fresh = _validator_sweep_once(
                exit_id, fixed, nodes, segments, injections, volts, incoming, shunt
            )
            if fresh is None:
                return _Solution(False, "nonfinite", iteration, math.nan, {}, {})
            implied, final_currents = fresh
            residual = max(abs(implied[node] - volts[node]) for node in nodes)
            if all(
                math.isclose(
                    abs(implied[node] - volts[node]),
                    0.0,
                    rel_tol=VOLTAGE_REL_TOL,
                    abs_tol=VOLTAGE_ABS_TOL_V,
                )
                for node in nodes
            ):
                return _Solution(True, "", iteration, max(last, residual), volts, final_currents)
    return _Solution(False, "nonconvergence", MAX_ITERATIONS, last, {}, {})


def _validator_sweep_once(
    exit_id: str,
    fixed: complex,
    nodes: Mapping[str, MvHvNetworkNodeAuthority],
    segments: Mapping[str, MvHvNetworkSegmentAuthority],
    injections: Mapping[str, complex],
    volts: Mapping[str, complex],
    incoming: Mapping[str, list[str]],
    shunt: Mapping[str, complex],
) -> tuple[dict[str, complex], dict[str, complex]] | None:
    currents: dict[str, complex] = {}

    def aggregate(node: str) -> complex:
        power = injections.get(node, 0j)
        value = (power / (3.0 * volts[node])).conjugate() if power != 0j else 0j
        value -= shunt[node] * volts[node]
        for sid in incoming[node]:
            current = aggregate(segments[sid].from_node_id)
            currents[sid] = current
            value += current
        return value

    try:
        aggregate(exit_id)
    except (OverflowError, ZeroDivisionError):
        return None
    implied = {exit_id: fixed}

    def descend(node: str) -> None:
        for sid in incoming[node]:
            segment = segments[sid]
            implied[segment.from_node_id] = (
                implied[node]
                + complex(
                    segment.series_resistance_ohm_per_phase, segment.series_reactance_ohm_per_phase
                )
                * currents[sid]
            )
            descend(segment.from_node_id)

    descend(exit_id)
    return implied, currents


def _validate_result(
    parents: tuple[Any, Any, Any], result: TopologyMvHvOperatingSolutionResult
) -> None:
    if type(result) is not TopologyMvHvOperatingSolutionResult:
        raise RuntimeError("S13C result type is invalid")
    s12m, network, voltage = parents
    frames: tuple[
        tuple[
            pd.DataFrame,
            tuple[str, ...],
            list[str],
            frozenset[str],
            frozenset[str],
            frozenset[str],
            frozenset[str],
        ],
        ...,
    ] = (
        (
            result.network_exit_states,
            _TREE_COLUMNS,
            ["timestamp", "network_exit_node_id"],
            _TREE_BOOL,
            frozenset(),
            _TREE_INT,
            _TREE_FLOAT,
        ),
        (
            result.transformer_terminal_states,
            _TX_COLUMNS,
            ["timestamp", "transformer_id"],
            _TX_BOOL,
            _TX_NULLABLE_BOOL,
            frozenset(),
            _TX_FLOAT,
        ),
        (
            result.node_states,
            _NODE_COLUMNS,
            ["timestamp", "node_id"],
            _NODE_BOOL,
            frozenset(),
            frozenset(),
            _NODE_FLOAT,
        ),
        (
            result.segment_states,
            _SEG_COLUMNS,
            ["timestamp", "segment_id"],
            _SEG_BOOL,
            frozenset(),
            frozenset(),
            _SEG_FLOAT,
        ),
        (
            result.revenue_meter_states,
            _METER_COLUMNS,
            ["timestamp", "revenue_meter_id"],
            _METER_BOOL,
            frozenset(),
            frozenset(),
            _METER_FLOAT,
        ),
    )
    for frame, columns, names, bools, nullable_bools, ints, floats in frames:
        if tuple(frame.columns) != columns or list(frame.index.names) != names:
            raise RuntimeError("S13C public schema/index failed independent exact closure")
        if frame.index.has_duplicates:
            raise RuntimeError("S13C public index contains duplicates")
        expected_dtypes = {
            column: (
                "bool"
                if column in bools
                else "boolean"
                if column in nullable_bools
                else "int64"
                if column in ints
                else "float64"
                if column in floats
                else "object"
            )
            for column in columns
        }
        if {column: str(dtype) for column, dtype in frame.dtypes.items()} != expected_dtypes:
            raise RuntimeError("S13C public dtypes failed independent exact closure")
    times = _timestamps(s12m, voltage)
    exits = tuple(
        key for key, node in network.nodes_by_id.items() if node.node_kind == "network_exit"
    )
    if tuple(result.network_exit_states.index) != tuple((t, e) for t in times for e in exits):
        raise RuntimeError("S13C tree index failed independent exact closure")
    expected_indexes = (
        (
            result.transformer_terminal_states,
            tuple(
                (t, i)
                for t in times
                for i in network.transformer_terminal_binding_by_transformer_id
            ),
        ),
        (result.node_states, tuple((t, i) for t in times for i in network.nodes_by_id)),
        (result.segment_states, tuple((t, i) for t in times for i in network.segments_by_id)),
        (
            result.revenue_meter_states,
            tuple((t, i) for t in times for i in network.revenue_meter_boundary_by_id),
        ),
    )
    if any(tuple(frame.index) != expected for frame, expected in expected_indexes):
        raise RuntimeError("S13C public index order failed independent exact closure")
    # Validator-only membership reconstruction.
    outgoing = {
        segment.from_node_id: segment.to_node_id for segment in network.segments_by_id.values()
    }
    node_exit: dict[str, str | None] = {}
    for start in network.nodes_by_id:
        current = start
        while current in outgoing:
            current = outgoing[current]
        node_exit[start] = (
            current if network.nodes_by_id[current].node_kind == "network_exit" else None
        )
    segment_exit = {
        sid: node_exit[segment.from_node_id] for sid, segment in network.segments_by_id.items()
    }
    grid_by_exit = {grid.node_id: grid for grid in network.grid_boundary_by_id.values()}
    binding_by_node = {
        binding.node_id: transformer_id
        for transformer_id, binding in (
            network.transformer_terminal_binding_by_transformer_id.items()
        )
    }
    semantic_tree = {
        "grid_boundary_phase_angle_treatment": GRID_ANGLE_TREATMENT,
        "transformer_terminal_voltage_coupling_treatment": TERMINAL_COUPLING,
        "transformer_terminal_phase_angle_coupling_applied": False,
        "shunt_susceptance_semantics": SHUNT_SEMANTICS,
        "transformer_loss_treatment": TRANSFORMER_LOSS_TREATMENT,
        "s13_series_loss_treatment": SERIES_LOSS_TREATMENT,
        "s13_shunt_active_treatment": SHUNT_ACTIVE_TREATMENT,
        "s13_shunt_reactive_treatment": SHUNT_REACTIVE_TREATMENT,
        "revenue_meter_expected_power_treatment": METER_TREATMENT,
        "transformer_advanced_operating_solution_contract": (
            TRANSFORMER_ADVANCED_OPERATING_SOLUTION_CONTRACT_ID
        ),
        "mv_hv_network_authority_contract": MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
        "mv_hv_grid_boundary_voltage_authority_contract": (
            MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_CONTRACT_ID
        ),
        "mv_hv_operating_solution_contract": MV_HV_OPERATING_SOLUTION_CONTRACT_ID,
        "mv_hv_operating_solution_model": MV_HV_OPERATING_SOLUTION_MODEL_ID,
        "mv_hv_operating_solution_scope": MV_HV_OPERATING_SOLUTION_SCOPE,
        "mv_hv_operating_solution_coverage_scope": MV_HV_OPERATING_SOLUTION_COVERAGE_SCOPE,
    }
    for timestamp in times:
        for exit_id in exits:
            row = result.network_exit_states.loc[(timestamp, exit_id)]
            tree_nodes = {
                key: value
                for key, value in network.nodes_by_id.items()
                if node_exit[key] == exit_id
            }
            tree_segments = {
                key: value
                for key, value in network.segments_by_id.items()
                if segment_exit[key] == exit_id
            }
            transformer_ids = tuple(
                binding_by_node[node] for node in tree_nodes if node in binding_by_node
            )
            grid = grid_by_exit.get(exit_id)
            missing: list[str] = []
            unresolved: list[str] = []
            injections: dict[str, complex] = {}
            energised: dict[str, pd.Series] = {}
            for transformer_id in transformer_ids:
                key = (timestamp, transformer_id)
                if key not in s12m.states.index:
                    missing.append(transformer_id)
                    continue
                upstream = s12m.states.loc[key]
                state = upstream["transformer_advanced_operating_solution_state"]
                node_id = network.transformer_terminal_binding_by_transformer_id[
                    transformer_id
                ].node_id
                if state == "resolved_coupled_advanced_transformer_terminal_solution":
                    injections[node_id] = complex(
                        upstream["p_network_terminal_w"], upstream["q_network_terminal_var"]
                    )
                    energised[transformer_id] = upstream
                elif state == "resolved_deenergised_transformer_zero_advanced_transfer":
                    injections[node_id] = 0j
                else:
                    unresolved.append(transformer_id)
            for transformer_id in transformer_ids:
                terminal_row = result.transformer_terminal_states.loc[(timestamp, transformer_id)]
                node_id = network.transformer_terminal_binding_by_transformer_id[
                    transformer_id
                ].node_id
                expected_injection = injections.get(node_id)
                upstream = (
                    s12m.states.loc[(timestamp, transformer_id)]
                    if (timestamp, transformer_id) in s12m.states.index
                    else None
                )
                upstream_state = (
                    upstream["transformer_advanced_operating_solution_state"]
                    if upstream is not None
                    else ""
                )
                ready = upstream_state in {
                    "resolved_coupled_advanced_transformer_terminal_solution",
                    "resolved_deenergised_transformer_zero_advanced_transfer",
                }
                terminal_static = {
                    "transformer_terminal_node_id": node_id,
                    "network_exit_node_id": exit_id,
                    "transformer_connected_to_network_exit": True,
                    "s12m_row_present": upstream is not None,
                    "s12m_operating_state": upstream_state,
                    "s12m_injection_ready": ready,
                    "transformer_energised": (
                        upstream["transformer_energised"] if upstream is not None else pd.NA
                    ),
                    "terminal_voltage_consistency_applicable": (
                        upstream_state == "resolved_coupled_advanced_transformer_terminal_solution"
                    ),
                    "mv_hv_operating_solution_contract": MV_HV_OPERATING_SOLUTION_CONTRACT_ID,
                    "mv_hv_operating_solution_model": MV_HV_OPERATING_SOLUTION_MODEL_ID,
                }
                _validator_check_row(terminal_row, terminal_static, "transformer_terminal_states")
                if expected_injection is None:
                    if not pd.isna(terminal_row["p_network_terminal_injection_w"]):
                        raise RuntimeError(
                            "S13C transformer_terminal_states failed independent exact closure"
                        )
                elif not math.isclose(
                    float(terminal_row["p_network_terminal_injection_w"]),
                    expected_injection.real,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                ) or not math.isclose(
                    float(terminal_row["q_network_terminal_injection_var"]),
                    expected_injection.imag,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                ):
                    raise RuntimeError(
                        "S13C transformer_terminal_states failed independent exact closure"
                    )
            boundary = None
            if grid is not None and (timestamp, grid.grid_boundary_id) in voltage.states.index:
                candidate = voltage.states.loc[(timestamp, grid.grid_boundary_id)]
                if bool(candidate["grid_boundary_voltage_authority_resolved"]):
                    boundary = float(candidate["voltage_line_to_line_rms_v"])
            tree_static = {
                "grid_boundary_id": grid.grid_boundary_id if grid is not None else None,
                "network_basis_resolved": network.network_basis is not None,
                "grid_boundary_present": grid is not None,
                "grid_boundary_voltage_resolved": boundary is not None,
                "grid_boundary_voltage_line_to_line_rms_v": (
                    boundary if boundary is not None else math.nan
                ),
                "tree_transformer_count": len(transformer_ids),
                "s12m_ready_transformer_count": len(injections),
                "missing_s12m_transformer_count": len(missing),
                "unresolved_s12m_transformer_count": len(unresolved),
                "missing_s12m_transformer_ids": tuple(missing),
                "unresolved_s12m_transformer_ids": tuple(unresolved),
                **semantic_tree,
            }
            _validator_check_row(row, tree_static, "network_exit_states")
            expected_state = (
                _TREE_STATES[0]
                if network.network_basis is None
                else _TREE_STATES[1]
                if grid is None
                else _TREE_STATES[2]
                if boundary is None
                else _TREE_STATES[3]
                if missing
                else _TREE_STATES[4]
                if unresolved
                else ""
            )
            if expected_state:
                if row["mv_hv_operating_state"] != expected_state:
                    raise RuntimeError(
                        "S13C unresolved tree state failed independent exact closure"
                    )
                _validator_check_row(
                    row,
                    {
                        "network_solve_attempted": False,
                        "network_solve_converged": False,
                        "mv_hv_operating_solution_resolved": False,
                        "solver_iteration_count": 0,
                        "p_export_at_grid_boundary_w": math.nan,
                        "q_export_at_grid_boundary_var": math.nan,
                    },
                    "network_exit_states",
                )
                continue
            assert boundary is not None
            solved = _validator_solve(exit_id, boundary, tree_nodes, tree_segments, injections)
            failure_state = {
                "zero_nonzero": _TREE_STATES[5],
                "nonfinite": _TREE_STATES[6],
                "nonconvergence": _TREE_STATES[7],
            }.get(solved.failure)
            if failure_state:
                if row["mv_hv_operating_state"] != failure_state:
                    raise RuntimeError("S13C numerical state failed independent exact closure")
                continue
            mismatched = []
            residuals: dict[str, float] = {}
            for transformer_id, upstream in energised.items():
                node_id = network.transformer_terminal_binding_by_transformer_id[
                    transformer_id
                ].node_id
                actual = math.sqrt(3.0) * abs(solved.voltages[node_id])
                expected_voltage = float(upstream["network_terminal_voltage_line_to_line_rms_v"])
                residuals[transformer_id] = actual - expected_voltage
                if not math.isclose(
                    actual,
                    expected_voltage,
                    rel_tol=TERMINAL_VOLTAGE_REL_TOL,
                    abs_tol=TERMINAL_VOLTAGE_ABS_TOL_V,
                ):
                    mismatched.append(transformer_id)
            if tuple(row["mismatched_transformer_ids"]) != tuple(mismatched):
                raise RuntimeError(
                    "S13C terminal mismatch evidence failed independent exact closure"
                )
            if mismatched:
                if row["mv_hv_operating_state"] != _TREE_STATES[8]:
                    raise RuntimeError(
                        "S13C terminal mismatch state failed independent exact closure"
                    )
                _validator_check_row(
                    row,
                    {
                        "network_solve_converged": True,
                        "mv_hv_operating_solution_resolved": False,
                        "mismatched_transformer_count": len(mismatched),
                        "maximum_transformer_terminal_voltage_magnitude_residual_v": max(
                            abs(value) for value in residuals.values()
                        ),
                        "p_export_at_grid_boundary_w": math.nan,
                        "q_export_at_grid_boundary_var": math.nan,
                    },
                    "network_exit_states",
                )
                for transformer_id, residual in residuals.items():
                    terminal_row = result.transformer_terminal_states.loc[
                        (timestamp, transformer_id)
                    ]
                    _validator_check_row(
                        terminal_row,
                        {
                            "solved_s13_terminal_voltage_line_to_line_rms_v": math.nan,
                            "terminal_voltage_magnitude_residual_v": residual,
                            "terminal_voltage_magnitude_consistency_satisfied": False,
                            "mv_hv_operating_solution_resolved": False,
                            "transformer_terminal_operating_state": (
                                "unresolved_upstream_mv_hv_operating_solution"
                            ),
                        },
                        "transformer_terminal_states",
                    )
                continue
            # Independently reconstruct currents, branch powers, conservation,
            # node voltages, and meter cuts from validator voltages.
            fresh = _validator_sweep_once(
                exit_id,
                complex(boundary / math.sqrt(3.0), 0.0),
                tree_nodes,
                tree_segments,
                injections,
                solved.voltages,
                _validator_incoming(tree_nodes, tree_segments),
                _validator_shunts(tree_nodes, tree_segments),
            )
            if fresh is None:
                raise RuntimeError("S13C validator fresh sweep is nonfinite")
            _, currents = fresh
            branch_values: dict[str, tuple[complex, complex, float, float, float, float]] = {}
            for sid, segment in tree_segments.items():
                vf = solved.voltages[segment.from_node_id]
                vt = solved.voltages[segment.to_node_id]
                current = currents[sid]
                y = complex(
                    segment.total_shunt_conductance_siemens_per_phase,
                    segment.total_shunt_susceptance_siemens_per_phase,
                )
                z = complex(
                    segment.series_resistance_ohm_per_phase,
                    segment.series_reactance_ohm_per_phase,
                )
                s_from = 3.0 * vf * (current + 0.5 * y * vf).conjugate()
                s_to = 3.0 * vt * (-current + 0.5 * y * vt).conjugate()
                v2 = abs(vf) ** 2 + abs(vt) ** 2
                branch_values[sid] = (
                    s_from,
                    s_to,
                    3.0 * z.real * abs(current) ** 2,
                    3.0 * z.imag * abs(current) ** 2,
                    1.5 * y.real * v2,
                    1.5 * y.imag * v2,
                )
                segment_row = result.segment_states.loc[(timestamp, sid)]
                i_from = current + 0.5 * y * vf
                i_to = -current + 0.5 * y * vt
                delta_voltage = vf - vt
                checks = (
                    (segment_row["series_current_real_a"], current.real),
                    (segment_row["series_current_imag_a"], current.imag),
                    (segment_row["series_current_magnitude_a"], abs(current)),
                    (
                        segment_row["series_current_angle_deg_relative_to_grid_reference"],
                        math.degrees(cmath.phase(current)) if current else 0.0,
                    ),
                    (segment_row["from_terminal_current_real_a"], i_from.real),
                    (segment_row["from_terminal_current_imag_a"], i_from.imag),
                    (segment_row["to_terminal_current_real_a"], i_to.real),
                    (segment_row["to_terminal_current_imag_a"], i_to.imag),
                    (
                        segment_row["phase_voltage_difference_from_to_real_v"],
                        delta_voltage.real,
                    ),
                    (
                        segment_row["phase_voltage_difference_from_to_imag_v"],
                        delta_voltage.imag,
                    ),
                    (
                        segment_row["phase_voltage_difference_from_to_magnitude_v"],
                        abs(delta_voltage),
                    ),
                    (
                        segment_row["line_to_line_voltage_magnitude_delta_from_to_v"],
                        math.sqrt(3.0) * (abs(vf) - abs(vt)),
                    ),
                    (segment_row["p_from_terminal_into_segment_w"], s_from.real),
                    (segment_row["q_from_terminal_into_segment_var"], s_from.imag),
                    (segment_row["p_to_terminal_into_segment_w"], s_to.real),
                    (segment_row["q_to_terminal_into_segment_var"], s_to.imag),
                    (segment_row["active_series_loss_w"], branch_values[sid][2]),
                    (segment_row["reactive_series_consumption_var"], branch_values[sid][3]),
                    (segment_row["active_shunt_consumption_w"], branch_values[sid][4]),
                    (
                        segment_row["capacitive_shunt_reactive_injection_var"],
                        branch_values[sid][5],
                    ),
                    (
                        segment_row["net_active_consumption_w"],
                        branch_values[sid][2] + branch_values[sid][4],
                    ),
                    (
                        segment_row["net_reactive_consumption_var"],
                        branch_values[sid][3] - branch_values[sid][5],
                    ),
                )
                if any(
                    not math.isclose(float(actual), expected, rel_tol=1e-12, abs_tol=1e-12)
                    for actual, expected in checks
                ):
                    raise RuntimeError("S13C segment_states failed independent exact closure")
                _validator_check_row(
                    segment_row,
                    {
                        "from_node_id": segment.from_node_id,
                        "to_node_id": segment.to_node_id,
                        "network_exit_node_id": exit_id,
                        "segment_connected_to_network_exit": True,
                        "mv_hv_operating_solution_resolved": True,
                        "series_resistance_ohm_per_phase": (
                            segment.series_resistance_ohm_per_phase
                        ),
                        "series_reactance_ohm_per_phase": (segment.series_reactance_ohm_per_phase),
                        "total_shunt_conductance_siemens_per_phase": (
                            segment.total_shunt_conductance_siemens_per_phase
                        ),
                        "total_shunt_susceptance_siemens_per_phase": (
                            segment.total_shunt_susceptance_siemens_per_phase
                        ),
                        "segment_operating_state": ("resolved_nominal_pi_segment_operating_state"),
                        "mv_hv_operating_solution_contract": (MV_HV_OPERATING_SOLUTION_CONTRACT_ID),
                        "mv_hv_operating_solution_model": MV_HV_OPERATING_SOLUTION_MODEL_ID,
                    },
                    "segment_states",
                )
            for node_id in tree_nodes:
                node_row = result.node_states.loc[(timestamp, node_id)]
                expected_node_voltage = solved.voltages[node_id]
                expected_injection = injections.get(node_id, 0j)
                expected_angle = (
                    math.degrees(cmath.phase(expected_node_voltage))
                    if expected_node_voltage != 0j
                    else 0.0
                )
                expected_shunt = _validator_shunts(tree_nodes, tree_segments)[node_id]
                _validator_check_row(
                    node_row,
                    {
                        "node_kind": network.nodes_by_id[node_id].node_kind,
                        "voltage_level_id": network.nodes_by_id[node_id].voltage_level_id,
                        "network_exit_node_id": exit_id,
                        "node_connected_to_network_exit": True,
                        "mv_hv_operating_solution_resolved": True,
                        "local_transformer_p_injection_w": expected_injection.real,
                        "local_transformer_q_injection_var": expected_injection.imag,
                        "total_incident_half_shunt_conductance_siemens_per_phase": (
                            expected_shunt.real
                        ),
                        "total_incident_half_shunt_susceptance_siemens_per_phase": (
                            expected_shunt.imag
                        ),
                        "voltage_phase_real_v": expected_node_voltage.real,
                        "voltage_phase_imag_v": expected_node_voltage.imag,
                        "voltage_phase_magnitude_v": abs(expected_node_voltage),
                        "voltage_line_to_line_rms_v": (math.sqrt(3.0) * abs(expected_node_voltage)),
                        "voltage_phase_angle_deg_relative_to_grid_boundary_reference": (
                            expected_angle
                        ),
                        "node_operating_state": "resolved_mv_hv_node_operating_state",
                        "mv_hv_operating_solution_contract": (MV_HV_OPERATING_SOLUTION_CONTRACT_ID),
                        "mv_hv_operating_solution_model": MV_HV_OPERATING_SOLUTION_MODEL_ID,
                    },
                    "node_states",
                )
            p_source = math.fsum(value.real for value in injections.values())
            q_source = math.fsum(value.imag for value in injections.values())
            shunts = _validator_shunts(tree_nodes, tree_segments)
            grid_current = (
                (injections.get(exit_id, 0j) / (3.0 * solved.voltages[exit_id])).conjugate()
                if injections.get(exit_id, 0j) != 0j
                else 0j
            ) - shunts[exit_id] * solved.voltages[exit_id]
            incoming = _validator_incoming(tree_nodes, tree_segments)
            grid_current += sum(currents[sid] for sid in incoming[exit_id])
            grid_power = 3.0 * solved.voltages[exit_id] * grid_current.conjugate()
            ps = math.fsum(item[2] for item in branch_values.values())
            qs = math.fsum(item[3] for item in branch_values.values())
            pg = math.fsum(item[4] for item in branch_values.values())
            qb = math.fsum(item[5] for item in branch_values.values())
            tree_checks = (
                (row["p_export_at_grid_boundary_w"], grid_power.real),
                (row["q_export_at_grid_boundary_var"], grid_power.imag),
                (row["total_series_active_loss_w"], ps),
                (row["total_series_reactive_consumption_var"], qs),
                (row["total_shunt_active_consumption_w"], pg),
                (row["total_shunt_capacitive_reactive_injection_var"], qb),
                (row["active_power_conservation_residual_w"], p_source - grid_power.real - ps - pg),
                (
                    row["reactive_power_conservation_residual_var"],
                    q_source + qb - grid_power.imag - qs,
                ),
                (row["transformer_injected_p_total_w"], p_source),
                (row["transformer_injected_q_total_var"], q_source),
                (
                    row["transformer_injected_s_vector_magnitude_va"],
                    abs(complex(p_source, q_source)),
                ),
                (row["s_export_at_grid_boundary_magnitude_va"], abs(grid_power)),
                (row["net_network_active_consumption_w"], ps + pg),
                (row["net_network_reactive_consumption_var"], qs - qb),
            )
            if any(
                not math.isclose(float(actual), expected, rel_tol=1e-12, abs_tol=1e-12)
                for actual, expected in tree_checks
            ):
                raise RuntimeError("S13C network_exit_states failed independent exact closure")
            _validator_check_row(
                row,
                {
                    "network_solve_attempted": boundary != 0.0,
                    "network_solve_converged": True,
                    "transformer_terminal_voltage_consistency_checked": bool(energised),
                    "transformer_terminal_voltage_consistency_satisfied": True,
                    "mismatched_transformer_count": 0,
                    "mismatched_transformer_ids": (),
                    "maximum_transformer_terminal_voltage_magnitude_residual_v": max(
                        (abs(value) for value in residuals.values()), default=0.0
                    ),
                    "mv_hv_operating_solution_resolved": True,
                    "solver_iteration_count": solved.iterations,
                    "solver_max_voltage_delta_v": solved.delta,
                    "mv_hv_operating_state": (
                        _TREE_STATES[9] if boundary == 0.0 else _TREE_STATES[10]
                    ),
                },
                "network_exit_states",
            )
            for transformer_id in transformer_ids:
                terminal_row = result.transformer_terminal_states.loc[(timestamp, transformer_id)]
                node_id = network.transformer_terminal_binding_by_transformer_id[
                    transformer_id
                ].node_id
                upstream = s12m.states.loc[(timestamp, transformer_id)]
                upstream_state = upstream["transformer_advanced_operating_solution_state"]
                applicable = (
                    upstream_state == "resolved_coupled_advanced_transformer_terminal_solution"
                )
                candidate_voltage = math.sqrt(3.0) * abs(solved.voltages[node_id])
                solved_voltage = candidate_voltage if applicable else math.nan
                residual = (
                    candidate_voltage
                    - float(upstream["network_terminal_voltage_line_to_line_rms_v"])
                    if applicable
                    else math.nan
                )
                _validator_check_row(
                    terminal_row,
                    {
                        "solved_s13_terminal_voltage_line_to_line_rms_v": solved_voltage,
                        "terminal_voltage_magnitude_residual_v": residual,
                        "terminal_voltage_magnitude_consistency_satisfied": True,
                        "mv_hv_operating_solution_resolved": True,
                        "transformer_terminal_operating_state": (
                            "resolved_transformer_terminal_mv_hv_operating_state"
                        ),
                    },
                    "transformer_terminal_states",
                )
            for meter_id, meter in network.revenue_meter_boundary_by_id.items():
                if node_exit[meter.node_id] != exit_id:
                    continue
                assert grid is not None
                expected_power = grid_power
                if meter.node_id != exit_id:
                    sid = next(
                        sid
                        for sid, segment in tree_segments.items()
                        if segment.from_node_id == meter.node_id
                    )
                    expected_power = branch_values[sid][0]
                meter_row = result.revenue_meter_states.loc[(timestamp, meter_id)]
                _validator_check_row(
                    meter_row,
                    {
                        "revenue_meter_node_id": meter.node_id,
                        "revenue_meter_node_kind": network.nodes_by_id[meter.node_id].node_kind,
                        "network_exit_node_id": exit_id,
                        "grid_boundary_id": grid.grid_boundary_id,
                        "meter_connected_to_network_exit": True,
                        "mv_hv_operating_solution_resolved": True,
                        "expected_meter_voltage_line_to_line_rms_v": (
                            math.sqrt(3.0) * abs(solved.voltages[meter.node_id])
                        ),
                        "expected_p_at_revenue_meter_w": expected_power.real,
                        "expected_q_at_revenue_meter_var": expected_power.imag,
                        "expected_s_at_revenue_meter_magnitude_va": abs(expected_power),
                        "active_power_sign_convention": meter.active_power_sign_convention,
                        "reactive_power_sign_convention": meter.reactive_power_sign_convention,
                        "power_basis": meter.power_basis,
                        "meter_boundary_cut_semantics": METER_CUT,
                        "revenue_meter_expected_state": (
                            "resolved_expected_revenue_meter_boundary_power"
                        ),
                        "mv_hv_operating_solution_contract": (MV_HV_OPERATING_SOLUTION_CONTRACT_ID),
                        "mv_hv_operating_solution_model": MV_HV_OPERATING_SOLUTION_MODEL_ID,
                    },
                    "revenue_meter_states",
                )
    states = result.network_exit_states["mv_hv_operating_state"]
    expected_diagnostics = TopologyMvHvOperatingSolutionDiagnostics(
        len(times),
        len(exits),
        len(result.network_exit_states),
        int(result.network_exit_states["mv_hv_operating_solution_resolved"].sum()),
        int((~result.network_exit_states["mv_hv_operating_solution_resolved"]).sum()),
        len(result.transformer_terminal_states),
        len(result.node_states),
        len(result.segment_states),
        len(result.revenue_meter_states),
        tuple((state, int((states == state).sum())) for state in _TREE_STATES),
        MV_HV_OPERATING_SOLUTION_MODEL_ID,
    )
    if result.diagnostics != expected_diagnostics:
        raise RuntimeError("S13C diagnostics failed independent exact closure")


def _validator_incoming(
    nodes: Mapping[str, MvHvNetworkNodeAuthority],
    segments: Mapping[str, MvHvNetworkSegmentAuthority],
) -> dict[str, list[str]]:
    incoming: dict[str, list[str]] = {node: [] for node in nodes}
    for sid, segment in segments.items():
        incoming[segment.to_node_id].append(sid)
    return incoming


def _validator_shunts(
    nodes: Mapping[str, MvHvNetworkNodeAuthority],
    segments: Mapping[str, MvHvNetworkSegmentAuthority],
) -> dict[str, complex]:
    shunts = {node: 0j for node in nodes}
    for segment in segments.values():
        half = 0.5 * complex(
            segment.total_shunt_conductance_siemens_per_phase,
            segment.total_shunt_susceptance_siemens_per_phase,
        )
        shunts[segment.from_node_id] += half
        shunts[segment.to_node_id] += half
    return shunts
