"""Exact-timestamp instantaneous expected/measured revenue-meter benchmark.

S14A is the first layer allowed to place S13C expected meter power beside
S13D measured meter power.  It aligns only identical revenue-meter IDs and
exact pandas timestamps, and publishes raw measured-minus-expected P/Q
residuals only for instantaneous measurements.  It performs no network
physics, temporal aggregation, energy integration, tolerance classification,
or causal attribution.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, TypeVar

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.physics.mv_hv_network_authority import (
    MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
    resolve_topology_mv_hv_network_authority,
)
from heliotelligence.physics.mv_hv_operating_solution import (
    MV_HV_OPERATING_SOLUTION_CONTRACT_ID,
    MV_HV_OPERATING_SOLUTION_MODEL_ID,
    calculate_topology_mv_hv_operating_solution,
)
from heliotelligence.physics.revenue_meter_measurement_authority import (
    REVENUE_METER_MEASUREMENT_AUTHORITY_CONTRACT_ID,
    REVENUE_METER_MEASUREMENT_AUTHORITY_MODEL_ID,
    resolve_topology_revenue_meter_measurement_authority,
)

REVENUE_METER_POWER_BENCHMARK_CONTRACT_ID = (
    "admitted_s13a_s13c_s13d_to_exact_timestamp_instantaneous_revenue_meter_"
    "power_benchmark_v1"
)
REVENUE_METER_POWER_BENCHMARK_MODEL_ID = (
    "same_revenue_meter_same_timestamp_instantaneous_expected_measured_pq_"
    "residual_v1"
)
REVENUE_METER_POWER_BENCHMARK_SCOPE = (
    "timestamped_revenue_meter_expected_measured_power_alignment_before_"
    "interval_energy_and_loss_attribution"
)
REVENUE_METER_POWER_BENCHMARK_COVERAGE_SCOPE = (
    "exact_revenue_meter_id_exact_timestamp_snapshot_measurements_against_"
    "resolved_s13c_expected_power"
)

EXPECTED_TIME_SEMANTICS = "instantaneous_steady_state_solution_at_exact_timestamp"
TIMESTAMP_ALIGNMENT_SEMANTICS = (
    "exact_pd_timestamp_match_no_alignment_resampling_or_nearest_neighbor"
)
BOUNDARY_ALIGNMENT_SEMANTICS = (
    "canonical_s13a_revenue_meter_identity_with_s13c_gridward_node_cut_"
    "expected_power_v1"
)
RESIDUAL_SIGN_SEMANTICS = (
    "measured_minus_expected_under_positive_plant_to_grid_sign_convention"
)

_STATES = (
    "unresolved_missing_expected_revenue_meter_state",
    "unresolved_expected_revenue_meter_operating_solution",
    "unresolved_missing_measured_revenue_meter_power_state",
    "unresolved_interval_average_measurement_requires_temporal_aggregation",
    "resolved_instantaneous_revenue_meter_power_benchmark",
)
_COLUMNS = (
    "network_basis_resolved",
    "revenue_meter_node_id",
    "revenue_meter_node_kind",
    "revenue_meter_reference_plane",
    "revenue_meter_colocated_with_grid_boundary",
    "colocated_grid_boundary_id",
    "active_power_sign_convention",
    "reactive_power_sign_convention",
    "power_basis",
    "expected_parent_row_present",
    "expected_power_resolved",
    "expected_revenue_meter_state",
    "expected_meter_voltage_line_to_line_rms_v",
    "expected_active_power_w",
    "expected_reactive_power_var",
    "expected_apparent_power_magnitude_va",
    "expected_meter_boundary_cut_semantics",
    "expected_time_semantics",
    "measured_parent_row_present",
    "measured_power_state_present",
    "measured_power_authority_resolved",
    "measured_active_power_w",
    "measured_reactive_power_var",
    "measured_apparent_power_magnitude_va",
    "measurement_value_basis",
    "measurement_time_semantics",
    "averaging_interval_seconds",
    "measurement_parameter_source",
    "measurement_confidence",
    "temporal_basis_compatible",
    "benchmark_eligible",
    "timestamp_alignment_semantics",
    "boundary_alignment_semantics",
    "active_power_residual_measured_minus_expected_w",
    "reactive_power_residual_measured_minus_expected_var",
    "absolute_active_power_residual_w",
    "absolute_reactive_power_residual_var",
    "power_residual_vector_magnitude_va",
    "residual_sign_semantics",
    "revenue_meter_power_benchmark_state",
    "mv_hv_network_authority_contract",
    "mv_hv_operating_solution_contract",
    "mv_hv_operating_solution_model",
    "revenue_meter_measurement_authority_contract",
    "revenue_meter_measurement_authority_model",
    "revenue_meter_power_benchmark_contract",
    "revenue_meter_power_benchmark_model",
    "revenue_meter_power_benchmark_scope",
    "revenue_meter_power_benchmark_coverage_scope",
)
_BOOL_COLUMNS = {
    "network_basis_resolved",
    "revenue_meter_colocated_with_grid_boundary",
    "expected_parent_row_present",
    "expected_power_resolved",
    "measured_parent_row_present",
    "measured_power_state_present",
    "measured_power_authority_resolved",
    "benchmark_eligible",
}
_NULLABLE_BOOL_COLUMNS = {"temporal_basis_compatible"}
_FLOAT_COLUMNS = {
    "expected_meter_voltage_line_to_line_rms_v",
    "expected_active_power_w",
    "expected_reactive_power_var",
    "expected_apparent_power_magnitude_va",
    "measured_active_power_w",
    "measured_reactive_power_var",
    "measured_apparent_power_magnitude_va",
    "averaging_interval_seconds",
    "active_power_residual_measured_minus_expected_w",
    "reactive_power_residual_measured_minus_expected_var",
    "absolute_active_power_residual_w",
    "absolute_reactive_power_residual_var",
    "power_residual_vector_magnitude_va",
}


@dataclass(frozen=True)
class TopologyRevenueMeterInstantaneousBenchmarkDiagnostics:
    revenue_meter_count: int
    timestamp_count: int
    row_count: int
    expected_parent_row_present_count: int
    expected_parent_row_missing_count: int
    expected_power_resolved_count: int
    expected_power_unresolved_count: int
    measured_parent_row_present_count: int
    measured_parent_row_missing_count: int
    measured_power_state_present_count: int
    measured_power_state_missing_count: int
    instantaneous_snapshot_measurement_count: int
    interval_average_measurement_count: int
    temporal_basis_compatible_count: int
    temporal_basis_incompatible_count: int
    benchmark_eligible_count: int
    benchmark_unresolved_count: int
    state_counts: tuple[tuple[str, int], ...]
    model: str


@dataclass(frozen=True)
class TopologyRevenueMeterInstantaneousBenchmarkResult:
    states: pd.DataFrame
    diagnostics: TopologyRevenueMeterInstantaneousBenchmarkDiagnostics


F = TypeVar("F", bound=Callable[..., Any])


def _call(function: F, values: Mapping[str, Any]) -> Any:
    parameters = inspect.signature(function).parameters
    if any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()):
        return function(**values)
    return function(**{name: values[name] for name in parameters})


def _replay(label: str, supplied: object, canonical: object) -> None:
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
    s13a = _call(resolve_topology_mv_hv_network_authority, values)
    _replay("S13A", values["mv_hv_network_authority"], s13a)
    canonical_values = dict(values)
    canonical_values["mv_hv_network_authority"] = s13a
    s13c = _call(calculate_topology_mv_hv_operating_solution, canonical_values)
    _replay("S13C", values["mv_hv_operating_solution"], s13c)
    s13d = _call(resolve_topology_revenue_meter_measurement_authority, canonical_values)
    _replay("S13D", values["revenue_meter_measurement_authority"], s13d)
    return s13a, s13c, s13d


def _timestamps(s13c: Any, s13d: Any) -> tuple[pd.Timestamp, ...]:
    groups = []
    for frame in (s13c.revenue_meter_states, s13d.states):
        groups.append(set(frame.index.get_level_values("timestamp")) if len(frame) else set())
    try:
        return tuple(sorted(set().union(*groups)))
    except TypeError as error:
        raise ValueError("S14A timestamps have incompatible timezone semantics") from error


def _check_static_rows(s13a: Any, s13c: Any, s13d: Any) -> None:
    for (_, meter_id), row in s13c.revenue_meter_states.iterrows():
        if meter_id not in s13a.revenue_meter_boundary_by_id:
            raise RuntimeError("S13C meter identity contradicts canonical S13A")
        meter = s13a.revenue_meter_boundary_by_id[meter_id]
        expected_measurement = (
            meter.node_id,
            meter.active_power_sign_convention,
            meter.reactive_power_sign_convention,
            meter.power_basis,
        )
        actual_measurement = (
            row["revenue_meter_node_id"],
            row["active_power_sign_convention"],
            row["reactive_power_sign_convention"],
            row["power_basis"],
        )
        if actual_measurement != expected_measurement:
            raise RuntimeError("S13C meter semantics contradict canonical S13A")
    for (_, meter_id), row in s13d.states.iterrows():
        if meter_id not in s13a.revenue_meter_boundary_by_id:
            raise RuntimeError("S13D meter identity contradicts canonical S13A")
        meter = s13a.revenue_meter_boundary_by_id[meter_id]
        expected = (
            meter.node_id,
            meter.reference_plane,
            meter.active_power_sign_convention,
            meter.reactive_power_sign_convention,
            meter.power_basis,
        )
        actual = (
            row["revenue_meter_node_id"],
            row["revenue_meter_reference_plane"],
            row["active_power_sign_convention"],
            row["reactive_power_sign_convention"],
            row["power_basis"],
        )
        if actual != expected:
            raise RuntimeError("S13D meter semantics contradict canonical S13A")


def _record(
    s13a: Any,
    s13c: Any,
    s13d: Any,
    timestamp: pd.Timestamp,
    meter_id: str,
) -> dict[str, object]:
    meter = s13a.revenue_meter_boundary_by_id[meter_id]
    node = s13a.nodes_by_id[meter.node_id]
    grid_by_node = {
        grid.node_id: identifier for identifier, grid in s13a.grid_boundary_by_id.items()
    }
    colocated = grid_by_node.get(meter.node_id)
    key = (timestamp, meter_id)
    expected_present = key in s13c.revenue_meter_states.index
    measured_present = key in s13d.states.index
    expected = s13c.revenue_meter_states.loc[key] if expected_present else None
    measured = s13d.states.loc[key] if measured_present else None
    expected_resolved = bool(
        expected_present
        and expected is not None
        and expected["mv_hv_operating_solution_resolved"]
        and expected["revenue_meter_expected_state"]
        == "resolved_expected_revenue_meter_boundary_power"
    )
    measured_state_present = bool(
        measured["measured_power_state_present"]
        if measured_present and measured is not None
        else False
    )
    measured_resolved = bool(
        measured["measured_power_authority_resolved"]
        if measured_present and measured is not None
        else False
    )
    temporal: object = pd.NA
    if measured_resolved:
        assert measured is not None
        temporal = measured["measurement_time_semantics"] == "instantaneous_snapshot"
    eligible = expected_resolved and measured_resolved and temporal is True
    if not expected_present:
        primary = _STATES[0]
    elif not expected_resolved:
        primary = _STATES[1]
    elif not measured_resolved:
        primary = _STATES[2]
    elif temporal is False:
        primary = _STATES[3]
    else:
        primary = _STATES[4]
    expected_p = (
        float(expected["expected_p_at_revenue_meter_w"])
        if expected is not None
        else math.nan
    )
    expected_q = (
        float(expected["expected_q_at_revenue_meter_var"])
        if expected is not None
        else math.nan
    )
    measured_p = (
        float(measured["measured_active_power_w"])
        if measured is not None
        else math.nan
    )
    measured_q = (
        float(measured["measured_reactive_power_var"])
        if measured is not None
        else math.nan
    )
    dp = measured_p - expected_p if eligible else math.nan
    dq = measured_q - expected_q if eligible else math.nan
    return {
        "network_basis_resolved": s13a.network_basis is not None,
        "revenue_meter_node_id": meter.node_id,
        "revenue_meter_node_kind": node.node_kind,
        "revenue_meter_reference_plane": meter.reference_plane,
        "revenue_meter_colocated_with_grid_boundary": colocated is not None,
        "colocated_grid_boundary_id": colocated,
        "active_power_sign_convention": meter.active_power_sign_convention,
        "reactive_power_sign_convention": meter.reactive_power_sign_convention,
        "power_basis": meter.power_basis,
        "expected_parent_row_present": expected_present,
        "expected_power_resolved": expected_resolved,
        "expected_revenue_meter_state": (
            expected["revenue_meter_expected_state"] if expected is not None else ""
        ),
        "expected_meter_voltage_line_to_line_rms_v": (
            expected["expected_meter_voltage_line_to_line_rms_v"]
            if expected is not None
            else math.nan
        ),
        "expected_active_power_w": expected_p,
        "expected_reactive_power_var": expected_q,
        "expected_apparent_power_magnitude_va": (
            expected["expected_s_at_revenue_meter_magnitude_va"]
            if expected is not None
            else math.nan
        ),
        "expected_meter_boundary_cut_semantics": (
            expected["meter_boundary_cut_semantics"] if expected is not None else ""
        ),
        "expected_time_semantics": EXPECTED_TIME_SEMANTICS if expected_present else "",
        "measured_parent_row_present": measured_present,
        "measured_power_state_present": measured_state_present,
        "measured_power_authority_resolved": measured_resolved,
        "measured_active_power_w": measured_p,
        "measured_reactive_power_var": measured_q,
        "measured_apparent_power_magnitude_va": (
            measured["measured_apparent_power_magnitude_va"]
            if measured is not None
            else math.nan
        ),
        "measurement_value_basis": (
            measured["measurement_value_basis"] if measured is not None else ""
        ),
        "measurement_time_semantics": (
            measured["measurement_time_semantics"] if measured is not None else ""
        ),
        "averaging_interval_seconds": (
            measured["averaging_interval_seconds"] if measured is not None else math.nan
        ),
        "measurement_parameter_source": (
            measured["parameter_source"] if measured is not None else ""
        ),
        "measurement_confidence": measured["confidence"] if measured is not None else "",
        "temporal_basis_compatible": temporal,
        "benchmark_eligible": eligible,
        "timestamp_alignment_semantics": TIMESTAMP_ALIGNMENT_SEMANTICS,
        "boundary_alignment_semantics": BOUNDARY_ALIGNMENT_SEMANTICS,
        "active_power_residual_measured_minus_expected_w": dp,
        "reactive_power_residual_measured_minus_expected_var": dq,
        "absolute_active_power_residual_w": abs(dp) if eligible else math.nan,
        "absolute_reactive_power_residual_var": abs(dq) if eligible else math.nan,
        "power_residual_vector_magnitude_va": math.hypot(dp, dq) if eligible else math.nan,
        "residual_sign_semantics": RESIDUAL_SIGN_SEMANTICS,
        "revenue_meter_power_benchmark_state": primary,
        "mv_hv_network_authority_contract": MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
        "mv_hv_operating_solution_contract": MV_HV_OPERATING_SOLUTION_CONTRACT_ID,
        "mv_hv_operating_solution_model": MV_HV_OPERATING_SOLUTION_MODEL_ID,
        "revenue_meter_measurement_authority_contract": (
            REVENUE_METER_MEASUREMENT_AUTHORITY_CONTRACT_ID
        ),
        "revenue_meter_measurement_authority_model": (
            REVENUE_METER_MEASUREMENT_AUTHORITY_MODEL_ID
        ),
        "revenue_meter_power_benchmark_contract": REVENUE_METER_POWER_BENCHMARK_CONTRACT_ID,
        "revenue_meter_power_benchmark_model": REVENUE_METER_POWER_BENCHMARK_MODEL_ID,
        "revenue_meter_power_benchmark_scope": REVENUE_METER_POWER_BENCHMARK_SCOPE,
        "revenue_meter_power_benchmark_coverage_scope": (
            REVENUE_METER_POWER_BENCHMARK_COVERAGE_SCOPE
        ),
    }


def _apply_dtypes(frame: pd.DataFrame) -> None:
    for column in _BOOL_COLUMNS:
        frame[column] = frame[column].astype("bool")
    for column in _NULLABLE_BOOL_COLUMNS:
        frame[column] = frame[column].astype("boolean")
    for column in _FLOAT_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    for column in set(_COLUMNS) - _BOOL_COLUMNS - _NULLABLE_BOOL_COLUMNS - _FLOAT_COLUMNS:
        frame[column] = frame[column].astype("object")


def _frame(
    keys: tuple[tuple[pd.Timestamp, str], ...], records: list[dict[str, object]]
) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(keys, names=["timestamp", "revenue_meter_id"])
    frame = pd.DataFrame.from_records(records, columns=_COLUMNS, index=index)
    frame.index = index
    _apply_dtypes(frame)
    return frame


def _diagnostics(
    meter_ids: tuple[str, ...], timestamps: tuple[pd.Timestamp, ...], frame: pd.DataFrame
) -> TopologyRevenueMeterInstantaneousBenchmarkDiagnostics:
    rows = len(frame)
    expected_present = int(frame["expected_parent_row_present"].sum())
    expected_resolved = int(frame["expected_power_resolved"].sum())
    measured_parent = int(frame["measured_parent_row_present"].sum())
    measured_state = int(frame["measured_power_state_present"].sum())
    compatible = int((frame["temporal_basis_compatible"] == True).sum())  # noqa: E712
    incompatible = int((frame["temporal_basis_compatible"] == False).sum())  # noqa: E712
    eligible = int(frame["benchmark_eligible"].sum())
    semantics = frame["measurement_time_semantics"]
    states = frame["revenue_meter_power_benchmark_state"]
    return TopologyRevenueMeterInstantaneousBenchmarkDiagnostics(
        len(meter_ids),
        len(timestamps),
        rows,
        expected_present,
        rows - expected_present,
        expected_resolved,
        rows - expected_resolved,
        measured_parent,
        rows - measured_parent,
        measured_state,
        rows - measured_state,
        int((semantics == "instantaneous_snapshot").sum()),
        int((semantics == "interval_average_ending_at_timestamp").sum()),
        compatible,
        incompatible,
        eligible,
        rows - eligible,
        tuple((state, int((states == state).sum())) for state in _STATES),
        REVENUE_METER_POWER_BENCHMARK_MODEL_ID,
    )


def calculate_topology_revenue_meter_power_benchmark(
    **values: Any,
) -> TopologyRevenueMeterInstantaneousBenchmarkResult:
    """Compare exact-timestamp S13C expected and S13D snapshot meter power."""

    s13a, s13c, s13d = _parents(values)
    _check_static_rows(s13a, s13c, s13d)
    timestamps = _timestamps(s13c, s13d)
    meter_ids = tuple(s13a.revenue_meter_boundary_by_id)
    keys = tuple((timestamp, meter_id) for timestamp in timestamps for meter_id in meter_ids)
    records = [_record(s13a, s13c, s13d, timestamp, meter_id) for timestamp, meter_id in keys]
    frame = _frame(keys, records)
    result = TopologyRevenueMeterInstantaneousBenchmarkResult(
        frame.copy(deep=True), _diagnostics(meter_ids, timestamps, frame)
    )
    _validate_result((s13a, s13c, s13d), result)
    return result


# Validator construction deliberately duplicates benchmark assembly and does
# not call or capture production record, frame, or diagnostics builders.
def _validator_record(
    s13a: Any,
    s13c: Any,
    s13d: Any,
    timestamp: pd.Timestamp,
    meter_id: str,
) -> dict[str, object]:
    meter = s13a.revenue_meter_boundary_by_id[meter_id]
    node = s13a.nodes_by_id[meter.node_id]
    colocated = {
        grid.node_id: identifier for identifier, grid in s13a.grid_boundary_by_id.items()
    }.get(meter.node_id)
    key = (timestamp, meter_id)
    has_expected = key in s13c.revenue_meter_states.index
    has_measured = key in s13d.states.index
    e = s13c.revenue_meter_states.loc[key] if has_expected else None
    m = s13d.states.loc[key] if has_measured else None
    e_resolved = bool(
        e is not None
        and e["mv_hv_operating_solution_resolved"]
        and e["revenue_meter_expected_state"]
        == "resolved_expected_revenue_meter_boundary_power"
    )
    m_present = bool(m["measured_power_state_present"] if m is not None else False)
    m_resolved = bool(m["measured_power_authority_resolved"] if m is not None else False)
    compatibility: object = pd.NA
    if m_resolved:
        assert m is not None
        compatibility = m["measurement_time_semantics"] == "instantaneous_snapshot"
    eligible = e_resolved and m_resolved and compatibility is True
    state = (
        _STATES[0]
        if not has_expected
        else _STATES[1]
        if not e_resolved
        else _STATES[2]
        if not m_resolved
        else _STATES[3]
        if compatibility is False
        else _STATES[4]
    )
    ep = float(e["expected_p_at_revenue_meter_w"]) if e is not None else math.nan
    eq = float(e["expected_q_at_revenue_meter_var"]) if e is not None else math.nan
    mp = float(m["measured_active_power_w"]) if m is not None else math.nan
    mq = float(m["measured_reactive_power_var"]) if m is not None else math.nan
    dp, dq = (mp - ep, mq - eq) if eligible else (math.nan, math.nan)
    return {
        "network_basis_resolved": s13a.network_basis is not None,
        "revenue_meter_node_id": meter.node_id,
        "revenue_meter_node_kind": node.node_kind,
        "revenue_meter_reference_plane": meter.reference_plane,
        "revenue_meter_colocated_with_grid_boundary": colocated is not None,
        "colocated_grid_boundary_id": colocated,
        "active_power_sign_convention": meter.active_power_sign_convention,
        "reactive_power_sign_convention": meter.reactive_power_sign_convention,
        "power_basis": meter.power_basis,
        "expected_parent_row_present": has_expected,
        "expected_power_resolved": e_resolved,
        "expected_revenue_meter_state": e["revenue_meter_expected_state"] if e is not None else "",
        "expected_meter_voltage_line_to_line_rms_v": (
            e["expected_meter_voltage_line_to_line_rms_v"] if e is not None else math.nan
        ),
        "expected_active_power_w": ep,
        "expected_reactive_power_var": eq,
        "expected_apparent_power_magnitude_va": (
            e["expected_s_at_revenue_meter_magnitude_va"] if e is not None else math.nan
        ),
        "expected_meter_boundary_cut_semantics": (
            e["meter_boundary_cut_semantics"] if e is not None else ""
        ),
        "expected_time_semantics": EXPECTED_TIME_SEMANTICS if has_expected else "",
        "measured_parent_row_present": has_measured,
        "measured_power_state_present": m_present,
        "measured_power_authority_resolved": m_resolved,
        "measured_active_power_w": mp,
        "measured_reactive_power_var": mq,
        "measured_apparent_power_magnitude_va": (
            m["measured_apparent_power_magnitude_va"] if m is not None else math.nan
        ),
        "measurement_value_basis": m["measurement_value_basis"] if m is not None else "",
        "measurement_time_semantics": m["measurement_time_semantics"] if m is not None else "",
        "averaging_interval_seconds": (
            m["averaging_interval_seconds"] if m is not None else math.nan
        ),
        "measurement_parameter_source": m["parameter_source"] if m is not None else "",
        "measurement_confidence": m["confidence"] if m is not None else "",
        "temporal_basis_compatible": compatibility,
        "benchmark_eligible": eligible,
        "timestamp_alignment_semantics": TIMESTAMP_ALIGNMENT_SEMANTICS,
        "boundary_alignment_semantics": BOUNDARY_ALIGNMENT_SEMANTICS,
        "active_power_residual_measured_minus_expected_w": dp,
        "reactive_power_residual_measured_minus_expected_var": dq,
        "absolute_active_power_residual_w": abs(dp) if eligible else math.nan,
        "absolute_reactive_power_residual_var": abs(dq) if eligible else math.nan,
        "power_residual_vector_magnitude_va": math.hypot(dp, dq) if eligible else math.nan,
        "residual_sign_semantics": RESIDUAL_SIGN_SEMANTICS,
        "revenue_meter_power_benchmark_state": state,
        "mv_hv_network_authority_contract": MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
        "mv_hv_operating_solution_contract": MV_HV_OPERATING_SOLUTION_CONTRACT_ID,
        "mv_hv_operating_solution_model": MV_HV_OPERATING_SOLUTION_MODEL_ID,
        "revenue_meter_measurement_authority_contract": (
            REVENUE_METER_MEASUREMENT_AUTHORITY_CONTRACT_ID
        ),
        "revenue_meter_measurement_authority_model": (
            REVENUE_METER_MEASUREMENT_AUTHORITY_MODEL_ID
        ),
        "revenue_meter_power_benchmark_contract": REVENUE_METER_POWER_BENCHMARK_CONTRACT_ID,
        "revenue_meter_power_benchmark_model": REVENUE_METER_POWER_BENCHMARK_MODEL_ID,
        "revenue_meter_power_benchmark_scope": REVENUE_METER_POWER_BENCHMARK_SCOPE,
        "revenue_meter_power_benchmark_coverage_scope": (
            REVENUE_METER_POWER_BENCHMARK_COVERAGE_SCOPE
        ),
    }


def _validator_frame(
    keys: tuple[tuple[pd.Timestamp, str], ...], records: list[dict[str, object]]
) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(keys, names=["timestamp", "revenue_meter_id"])
    frame = pd.DataFrame.from_records(records, columns=_COLUMNS, index=index)
    frame.index = index
    for column in _BOOL_COLUMNS:
        frame[column] = frame[column].astype("bool")
    for column in _NULLABLE_BOOL_COLUMNS:
        frame[column] = frame[column].astype("boolean")
    for column in _FLOAT_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    for column in set(_COLUMNS) - _BOOL_COLUMNS - _NULLABLE_BOOL_COLUMNS - _FLOAT_COLUMNS:
        frame[column] = frame[column].astype("object")
    return frame


def _validator_diagnostics(
    meter_ids: tuple[str, ...], timestamps: tuple[pd.Timestamp, ...], frame: pd.DataFrame
) -> TopologyRevenueMeterInstantaneousBenchmarkDiagnostics:
    rows = len(frame)
    ep = int(frame["expected_parent_row_present"].sum())
    er = int(frame["expected_power_resolved"].sum())
    mp = int(frame["measured_parent_row_present"].sum())
    ms = int(frame["measured_power_state_present"].sum())
    compatible = int((frame["temporal_basis_compatible"] == True).sum())  # noqa: E712
    incompatible = int((frame["temporal_basis_compatible"] == False).sum())  # noqa: E712
    eligible = int(frame["benchmark_eligible"].sum())
    semantics = frame["measurement_time_semantics"]
    states = frame["revenue_meter_power_benchmark_state"]
    return TopologyRevenueMeterInstantaneousBenchmarkDiagnostics(
        len(meter_ids),
        len(timestamps),
        rows,
        ep,
        rows - ep,
        er,
        rows - er,
        mp,
        rows - mp,
        ms,
        rows - ms,
        int((semantics == "instantaneous_snapshot").sum()),
        int((semantics == "interval_average_ending_at_timestamp").sum()),
        compatible,
        incompatible,
        eligible,
        rows - eligible,
        tuple((state, int((states == state).sum())) for state in _STATES),
        REVENUE_METER_POWER_BENCHMARK_MODEL_ID,
    )


def _validate_result(
    parents: tuple[Any, Any, Any],
    result: TopologyRevenueMeterInstantaneousBenchmarkResult,
) -> None:
    """Independently reconstruct and close the complete S14A result."""

    if type(result) is not TopologyRevenueMeterInstantaneousBenchmarkResult:
        raise RuntimeError("S14A result type is invalid")
    s13a, s13c, s13d = parents
    _check_static_rows(s13a, s13c, s13d)
    timestamps = _timestamps(s13c, s13d)
    meter_ids = tuple(s13a.revenue_meter_boundary_by_id)
    keys = tuple((timestamp, meter_id) for timestamp in timestamps for meter_id in meter_ids)
    expected = _validator_frame(
        keys,
        [
            _validator_record(s13a, s13c, s13d, timestamp, meter_id)
            for timestamp, meter_id in keys
        ],
    )
    try:
        pd.testing.assert_frame_equal(result.states, expected, check_exact=True)
    except AssertionError as error:
        raise RuntimeError("S14A state frame failed independent exact closure") from error
    diagnostics = _validator_diagnostics(meter_ids, timestamps, expected)
    if result.diagnostics != diagnostics:
        raise RuntimeError("S14A diagnostics failed independent exact closure")
