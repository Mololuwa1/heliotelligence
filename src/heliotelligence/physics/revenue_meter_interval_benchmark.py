"""Exact-interval revenue-meter average-power and energy benchmark (S14B)."""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
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
from heliotelligence.physics.revenue_meter_interval_support_policy import (
    REVENUE_METER_INTERVAL_SUPPORT_POLICY_CONTRACT_ID,
    RevenueMeterIntervalSupportPolicyAuthority,
)
from heliotelligence.physics.revenue_meter_measurement_authority import (
    REVENUE_METER_MEASUREMENT_AUTHORITY_CONTRACT_ID,
    REVENUE_METER_MEASUREMENT_AUTHORITY_MODEL_ID,
    resolve_topology_revenue_meter_measurement_authority,
)

REVENUE_METER_INTERVAL_BENCHMARK_CONTRACT_ID = (
    "admitted_s13a_s13c_s13d_and_support_policy_to_exact_interval_average_"
    "revenue_meter_energy_benchmark_v2"
)
REVENUE_METER_INTERVAL_BENCHMARK_MODEL_ID = (
    "piecewise_linear_s13c_expected_power_trapezoidal_interval_integration_"
    "with_explicit_maximum_support_gap_eligibility_v2"
)
REVENUE_METER_INTERVAL_BENCHMARK_SCOPE = (
    "revenue_meter_interval_average_power_and_energy_benchmark_before_component_loss_attribution"
)
REVENUE_METER_INTERVAL_BENCHMARK_COVERAGE_SCOPE = (
    "exact_revenue_meter_interval_boundaries_with_resolved_s13c_support_and_"
    "s13d_interval_average_power_and_explicit_meter_support_gap_policy"
)
TEMPORAL_RECONSTRUCTION_SEMANTICS = (
    "piecewise_linear_between_resolved_s13c_meter_samples_with_exact_interval_boundaries_v1"
)
ENERGY_INTEGRATION_SEMANTICS = "trapezoidal_time_integral_of_piecewise_linear_expected_power_v1"
TIMESTAMP_ALIGNMENT_SEMANTICS = (
    "s13d_exact_interval_boundaries_with_exact_s13c_support_points_no_nearest_or_extrapolation_v1"
)
BOUNDARY_ALIGNMENT_SEMANTICS = (
    "canonical_s13a_revenue_meter_identity_with_s13c_gridward_node_cut_"
    "expected_power_and_s13d_exact_measurement_plane_v1"
)
RESIDUAL_SIGN_SEMANTICS = "measured_minus_expected_under_positive_plant_to_grid_sign_convention"
INTERVAL_END_SEMANTICS = "s13d_measurement_interval_end_timestamp"
RESIDUAL_CONSISTENCY_REL_TOL = 1e-12
RESIDUAL_CONSISTENCY_ABS_TOL = 1e-12

_STATES = (
    "unresolved_missing_measured_revenue_meter_power_state",
    "unresolved_instantaneous_measurement_owned_by_s14a",
    "unresolved_interval_boundary_not_exactly_representable",
    "unresolved_missing_expected_interval_boundary_state",
    "unresolved_expected_interval_operating_solution",
    "unresolved_nonfinite_interval_benchmark_arithmetic",
    "resolved_interval_average_revenue_meter_energy_benchmark",
    "unresolved_missing_expected_interval_support_policy",
    "unresolved_expected_interval_support_gap_exceeds_policy",
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
    "measured_parent_row_present",
    "measured_power_state_present",
    "measured_power_authority_resolved",
    "measured_interval_average_active_power_w",
    "measured_interval_average_reactive_power_var",
    "measurement_time_semantics",
    "averaging_interval_seconds",
    "measurement_parameter_source",
    "measurement_confidence",
    "interval_start_timestamp",
    "interval_end_timestamp_semantics",
    "interval_boundary_exactly_representable",
    "expected_interval_start_row_present",
    "expected_interval_end_row_present",
    "expected_interval_sample_count",
    "expected_interval_resolved_sample_count",
    "expected_interval_unresolved_sample_count",
    "expected_interval_sample_timestamps",
    "unresolved_expected_sample_timestamps",
    "expected_interval_segment_count",
    "maximum_expected_sample_gap_seconds",
    "expected_interval_all_samples_resolved",
    "expected_start_active_power_w",
    "expected_start_reactive_power_var",
    "expected_end_active_power_w",
    "expected_end_reactive_power_var",
    "expected_temporal_reconstruction_semantics",
    "expected_energy_integration_semantics",
    "expected_interval_average_active_power_w",
    "expected_interval_average_reactive_power_var",
    "expected_active_energy_wh",
    "expected_reactive_energy_varh",
    "measured_active_energy_wh",
    "measured_reactive_energy_varh",
    "expected_interval_reconstruction_resolved",
    "expected_interval_support_policy_present",
    "maximum_expected_sample_gap_allowed_seconds",
    "maximum_expected_sample_gap_fraction_of_interval",
    "expected_interval_support_gap_policy_satisfied",
    "expected_interval_support_eligible",
    "support_policy_scope",
    "support_policy_evidence_kind",
    "support_policy_parameter_source",
    "support_policy_confidence",
    "support_policy_method_reference",
    "support_policy_applicability_description",
    "revenue_meter_interval_support_policy_contract",
    "benchmark_eligible",
    "active_power_residual_measured_minus_expected_w",
    "reactive_power_residual_measured_minus_expected_var",
    "absolute_active_power_residual_w",
    "absolute_reactive_power_residual_var",
    "active_energy_residual_measured_minus_expected_wh",
    "reactive_energy_residual_measured_minus_expected_varh",
    "absolute_active_energy_residual_wh",
    "absolute_reactive_energy_residual_varh",
    "timestamp_alignment_semantics",
    "boundary_alignment_semantics",
    "residual_sign_semantics",
    "revenue_meter_interval_benchmark_state",
    "mv_hv_network_authority_contract",
    "mv_hv_operating_solution_contract",
    "mv_hv_operating_solution_model",
    "revenue_meter_measurement_authority_contract",
    "revenue_meter_measurement_authority_model",
    "revenue_meter_interval_benchmark_contract",
    "revenue_meter_interval_benchmark_model",
    "revenue_meter_interval_benchmark_scope",
    "revenue_meter_interval_benchmark_coverage_scope",
)
_BOOL = {
    "network_basis_resolved",
    "revenue_meter_colocated_with_grid_boundary",
    "measured_parent_row_present",
    "measured_power_state_present",
    "measured_power_authority_resolved",
    "interval_boundary_exactly_representable",
    "expected_interval_start_row_present",
    "expected_interval_end_row_present",
    "expected_interval_all_samples_resolved",
    "expected_interval_reconstruction_resolved",
    "expected_interval_support_policy_present",
    "expected_interval_support_gap_policy_satisfied",
    "expected_interval_support_eligible",
    "benchmark_eligible",
}
_INT = {
    "expected_interval_sample_count",
    "expected_interval_resolved_sample_count",
    "expected_interval_unresolved_sample_count",
    "expected_interval_segment_count",
}
_FLOAT = {
    "measured_interval_average_active_power_w",
    "measured_interval_average_reactive_power_var",
    "averaging_interval_seconds",
    "maximum_expected_sample_gap_seconds",
    "maximum_expected_sample_gap_allowed_seconds",
    "maximum_expected_sample_gap_fraction_of_interval",
    "expected_start_active_power_w",
    "expected_start_reactive_power_var",
    "expected_end_active_power_w",
    "expected_end_reactive_power_var",
    "expected_interval_average_active_power_w",
    "expected_interval_average_reactive_power_var",
    "expected_active_energy_wh",
    "expected_reactive_energy_varh",
    "measured_active_energy_wh",
    "measured_reactive_energy_varh",
    "active_power_residual_measured_minus_expected_w",
    "reactive_power_residual_measured_minus_expected_var",
    "absolute_active_power_residual_w",
    "absolute_reactive_power_residual_var",
    "active_energy_residual_measured_minus_expected_wh",
    "reactive_energy_residual_measured_minus_expected_varh",
    "absolute_active_energy_residual_wh",
    "absolute_reactive_energy_residual_varh",
}


@dataclass(frozen=True)
class TopologyRevenueMeterIntervalBenchmarkDiagnostics:
    """Policy counts apply only to finite reconstructed interval rows.

    Present + missing = reconstruction resolved. Pass + fail = present.
    Policy presence/provenance columns may also describe earlier-failed rows;
    such rows do not enter these policy partitions. All rows enter the final
    benchmark eligible/unresolved partition.
    """

    revenue_meter_count: int
    timestamp_count: int
    row_count: int
    measured_parent_row_present_count: int
    measured_power_state_present_count: int
    interval_average_measurement_count: int
    instantaneous_snapshot_measurement_count: int
    exactly_representable_interval_count: int
    unrepresentable_interval_count: int
    expected_interval_boundary_complete_count: int
    expected_interval_boundary_incomplete_count: int
    expected_interval_all_samples_resolved_count: int
    expected_interval_with_unresolved_samples_count: int
    expected_interval_reconstruction_resolved_count: int
    support_policy_present_count: int
    support_policy_missing_count: int
    support_gap_policy_satisfied_count: int
    support_gap_policy_failed_count: int
    benchmark_eligible_count: int
    benchmark_unresolved_count: int
    total_expected_support_sample_count: int
    total_expected_support_segment_count: int
    state_counts: tuple[tuple[str, int], ...]
    model: str


@dataclass(frozen=True)
class TopologyRevenueMeterIntervalBenchmarkResult:
    states: pd.DataFrame
    diagnostics: TopologyRevenueMeterIntervalBenchmarkDiagnostics


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
    canonical = dict(values)
    canonical["mv_hv_network_authority"] = s13a
    s13c = _call(calculate_topology_mv_hv_operating_solution, canonical)
    _replay("S13C", values["mv_hv_operating_solution"], s13c)
    s13d = _call(resolve_topology_revenue_meter_measurement_authority, canonical)
    _replay("S13D", values["revenue_meter_measurement_authority"], s13d)
    return s13a, s13c, s13d


def _timestamps(s13c: Any, s13d: Any) -> tuple[pd.Timestamp, ...]:
    c = set(s13c.revenue_meter_states.index.get_level_values("timestamp"))
    d = set(s13d.states.index.get_level_values("timestamp"))
    try:
        sorted(c | d)
        return tuple(sorted(d))
    except TypeError as error:
        raise ValueError("S14B timestamps have incompatible timezone semantics") from error


def _check_static(s13a: Any, s13c: Any, s13d: Any) -> None:
    for frame, measured in ((s13c.revenue_meter_states, False), (s13d.states, True)):
        for (_, meter_id), row in frame.iterrows():
            meter = s13a.revenue_meter_boundary_by_id.get(meter_id)
            if meter is None:
                raise RuntimeError("dynamic meter identity contradicts canonical S13A")
            common = (
                row["revenue_meter_node_id"],
                row["active_power_sign_convention"],
                row["reactive_power_sign_convention"],
                row["power_basis"],
            )
            authority = (
                meter.node_id,
                meter.active_power_sign_convention,
                meter.reactive_power_sign_convention,
                meter.power_basis,
            )
            if common != authority or (
                measured and row["revenue_meter_reference_plane"] != meter.reference_plane
            ):
                raise RuntimeError("dynamic meter semantics contradict canonical S13A")


def _interval_start(end: pd.Timestamp, duration: float) -> tuple[bool, object]:
    try:
        product = duration * 1_000_000_000.0
        if not math.isfinite(product):
            return False, None
        nanoseconds = round(product)
        if (
            nanoseconds <= 0
            or nanoseconds > pd.Timedelta.max.value
            or nanoseconds / 1_000_000_000.0 != duration
        ):
            return False, None
        start = end - pd.Timedelta(nanoseconds, unit="ns")
        if pd.isna(start):
            return False, None
        return True, start
    except (OverflowError, ValueError, TypeError):
        return False, None


def _integrate(samples: pd.DataFrame) -> tuple[bool, float, float, float]:
    active: list[float] = []
    reactive: list[float] = []
    gaps: list[float] = []
    try:
        for position in range(len(samples) - 1):
            left = samples.iloc[position]
            right = samples.iloc[position + 1]
            t0 = samples.index[position]
            t1 = samples.index[position + 1]
            seconds = (t1 - t0).value / 1_000_000_000.0
            if not math.isfinite(seconds) or seconds <= 0.0:
                return False, math.nan, math.nan, math.nan
            hours = seconds / 3600.0
            ep = (
                float(left["expected_p_at_revenue_meter_w"]) / 2.0
                + float(right["expected_p_at_revenue_meter_w"]) / 2.0
            ) * hours
            eq = (
                float(left["expected_q_at_revenue_meter_var"]) / 2.0
                + float(right["expected_q_at_revenue_meter_var"]) / 2.0
            ) * hours
            if not math.isfinite(ep) or not math.isfinite(eq):
                return False, math.nan, math.nan, max(gaps, default=math.nan)
            active.append(ep)
            reactive.append(eq)
            gaps.append(seconds)
        p_energy = math.fsum(active)
        q_energy = math.fsum(reactive)
        if not math.isfinite(p_energy) or not math.isfinite(q_energy):
            return False, math.nan, math.nan, max(gaps, default=math.nan)
        return True, p_energy, q_energy, max(gaps, default=math.nan)
    except (OverflowError, ValueError, TypeError):
        return False, math.nan, math.nan, max(gaps, default=math.nan)


def _base_record(s13a: Any, timestamp: pd.Timestamp, meter_id: str) -> dict[str, object]:
    meter = s13a.revenue_meter_boundary_by_id[meter_id]
    node = s13a.nodes_by_id[meter.node_id]
    grids = {grid.node_id: identifier for identifier, grid in s13a.grid_boundary_by_id.items()}
    colocated = grids.get(meter.node_id)
    record: dict[str, object] = {column: "" for column in _COLUMNS}
    for column in _BOOL:
        record[column] = False
    for column in _INT:
        record[column] = 0
    for column in _FLOAT:
        record[column] = math.nan
    record.update(
        network_basis_resolved=s13a.network_basis is not None,
        revenue_meter_node_id=meter.node_id,
        revenue_meter_node_kind=node.node_kind,
        revenue_meter_reference_plane=meter.reference_plane,
        revenue_meter_colocated_with_grid_boundary=colocated is not None,
        colocated_grid_boundary_id=colocated,
        active_power_sign_convention=meter.active_power_sign_convention,
        reactive_power_sign_convention=meter.reactive_power_sign_convention,
        power_basis=meter.power_basis,
        interval_end_timestamp_semantics=INTERVAL_END_SEMANTICS,
        expected_interval_sample_timestamps=(),
        unresolved_expected_sample_timestamps=(),
        expected_temporal_reconstruction_semantics=TEMPORAL_RECONSTRUCTION_SEMANTICS,
        expected_energy_integration_semantics=ENERGY_INTEGRATION_SEMANTICS,
        timestamp_alignment_semantics=TIMESTAMP_ALIGNMENT_SEMANTICS,
        boundary_alignment_semantics=BOUNDARY_ALIGNMENT_SEMANTICS,
        residual_sign_semantics=RESIDUAL_SIGN_SEMANTICS,
        mv_hv_network_authority_contract=MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
        mv_hv_operating_solution_contract=MV_HV_OPERATING_SOLUTION_CONTRACT_ID,
        mv_hv_operating_solution_model=MV_HV_OPERATING_SOLUTION_MODEL_ID,
        revenue_meter_measurement_authority_contract=(
            REVENUE_METER_MEASUREMENT_AUTHORITY_CONTRACT_ID
        ),
        revenue_meter_measurement_authority_model=(REVENUE_METER_MEASUREMENT_AUTHORITY_MODEL_ID),
        revenue_meter_interval_benchmark_contract=(REVENUE_METER_INTERVAL_BENCHMARK_CONTRACT_ID),
        revenue_meter_interval_benchmark_model=REVENUE_METER_INTERVAL_BENCHMARK_MODEL_ID,
        revenue_meter_interval_benchmark_scope=REVENUE_METER_INTERVAL_BENCHMARK_SCOPE,
        revenue_meter_interval_benchmark_coverage_scope=(
            REVENUE_METER_INTERVAL_BENCHMARK_COVERAGE_SCOPE
        ),
    )
    return record


def _policies(
    meters: tuple[str, ...],
    supplied: Mapping[str, RevenueMeterIntervalSupportPolicyAuthority] | None,
) -> Mapping[str, RevenueMeterIntervalSupportPolicyAuthority]:
    if supplied is None:
        return MappingProxyType({})
    if not isinstance(supplied, Mapping):
        raise ValueError("interval support policy must be an explicit meter mapping")
    admitted = {}
    for meter_id, policy in supplied.items():
        if type(meter_id) is not str or meter_id not in meters:
            raise ValueError("interval support policy key must name a canonical revenue meter")
        if type(policy) is not RevenueMeterIntervalSupportPolicyAuthority:
            raise ValueError("exact RevenueMeterIntervalSupportPolicyAuthority required")
        admitted[meter_id] = replace(policy)
    return MappingProxyType(admitted)


def _record(
    s13a: Any,
    s13c: Any,
    s13d: Any,
    timestamp: pd.Timestamp,
    meter_id: str,
    policies: Mapping[str, RevenueMeterIntervalSupportPolicyAuthority] | None = None,
) -> dict[str, object]:
    record = _base_record(s13a, timestamp, meter_id)
    policy = policies.get(meter_id) if policies is not None else None
    record["revenue_meter_interval_support_policy_contract"] = (
        REVENUE_METER_INTERVAL_SUPPORT_POLICY_CONTRACT_ID
    )
    if policy is not None:
        record["expected_interval_support_policy_present"] = True
        record["maximum_expected_sample_gap_allowed_seconds"] = float(
            policy.maximum_expected_sample_gap_seconds
        )
        for field in (
            "policy_scope",
            "evidence_kind",
            "parameter_source",
            "confidence",
            "method_reference",
            "applicability_description",
        ):
            record["support_" + field if field == "policy_scope" else "support_policy_" + field] = (
                getattr(policy, field)
            )
    key = (timestamp, meter_id)
    present = key in s13d.states.index
    measured = s13d.states.loc[key] if present else None
    state_present = (
        bool(measured["measured_power_state_present"]) if measured is not None else False
    )
    resolved = (
        bool(measured["measured_power_authority_resolved"]) if measured is not None else False
    )
    record.update(
        measured_parent_row_present=present,
        measured_power_state_present=state_present,
        measured_power_authority_resolved=resolved,
        measured_interval_average_active_power_w=(
            measured["measured_active_power_w"] if measured is not None else math.nan
        ),
        measured_interval_average_reactive_power_var=(
            measured["measured_reactive_power_var"] if measured is not None else math.nan
        ),
        measurement_time_semantics=(
            measured["measurement_time_semantics"] if measured is not None else ""
        ),
        averaging_interval_seconds=(
            measured["averaging_interval_seconds"] if measured is not None else math.nan
        ),
        measurement_parameter_source=(measured["parameter_source"] if measured is not None else ""),
        measurement_confidence=(measured["confidence"] if measured is not None else ""),
    )
    if not resolved:
        record["revenue_meter_interval_benchmark_state"] = _STATES[0]
        return record
    assert measured is not None
    if measured["measurement_time_semantics"] == "instantaneous_snapshot":
        record["revenue_meter_interval_benchmark_state"] = _STATES[1]
        return record
    duration = float(measured["averaging_interval_seconds"])
    representable, start = _interval_start(timestamp, duration)
    record["interval_boundary_exactly_representable"] = representable
    record["interval_start_timestamp"] = start
    if not representable:
        record["revenue_meter_interval_benchmark_state"] = _STATES[2]
        return record
    assert isinstance(start, pd.Timestamp)
    if s13c.revenue_meter_states.empty:
        meter_frame = s13c.revenue_meter_states.droplevel("revenue_meter_id")
    else:
        meter_frame = s13c.revenue_meter_states.xs(
            meter_id, level="revenue_meter_id", drop_level=True
        )
    selected = meter_frame.loc[
        (meter_frame.index >= start) & (meter_frame.index <= timestamp)
    ].sort_index()
    start_present = start in meter_frame.index
    end_present = timestamp in meter_frame.index
    sample_times = tuple(selected.index)
    readiness = selected["mv_hv_operating_solution_resolved"].astype(bool) & (
        selected["revenue_meter_expected_state"] == "resolved_expected_revenue_meter_boundary_power"
    )
    unresolved_times = tuple(selected.index[~readiness])
    resolved_count = int(readiness.sum())
    count = len(selected)
    record.update(
        expected_interval_start_row_present=start_present,
        expected_interval_end_row_present=end_present,
        expected_interval_sample_count=count,
        expected_interval_resolved_sample_count=resolved_count,
        expected_interval_unresolved_sample_count=count - resolved_count,
        expected_interval_sample_timestamps=sample_times,
        unresolved_expected_sample_timestamps=unresolved_times,
        expected_interval_segment_count=max(count - 1, 0),
        expected_interval_all_samples_resolved=bool(count and resolved_count == count),
    )
    if start_present:
        row = meter_frame.loc[start]
        record["expected_start_active_power_w"] = row["expected_p_at_revenue_meter_w"]
        record["expected_start_reactive_power_var"] = row["expected_q_at_revenue_meter_var"]
    if end_present:
        row = meter_frame.loc[timestamp]
        record["expected_end_active_power_w"] = row["expected_p_at_revenue_meter_w"]
        record["expected_end_reactive_power_var"] = row["expected_q_at_revenue_meter_var"]
    if not start_present or not end_present:
        record["revenue_meter_interval_benchmark_state"] = _STATES[3]
        return record
    if unresolved_times:
        record["revenue_meter_interval_benchmark_state"] = _STATES[4]
        return record
    finite, expected_wh, expected_varh, gap = _integrate(selected)
    record["maximum_expected_sample_gap_seconds"] = gap
    if math.isfinite(gap) and duration > 0:
        record["maximum_expected_sample_gap_fraction_of_interval"] = gap / duration
    try:
        hours = duration / 3600.0
        expected_p = expected_wh / hours
        expected_q = expected_varh / hours
        measured_p = float(measured["measured_active_power_w"])
        measured_q = float(measured["measured_reactive_power_var"])
        measured_wh = measured_p * hours
        measured_varh = measured_q * hours
        dp = measured_p - expected_p
        dq = measured_q - expected_q
        de_p = measured_wh - expected_wh
        de_q = measured_varh - expected_varh
        derived = (expected_p, expected_q, measured_wh, measured_varh, dp, dq, de_p, de_q)
        finite = finite and all(math.isfinite(value) for value in derived)
        finite = finite and math.isclose(
            de_p,
            dp * hours,
            rel_tol=RESIDUAL_CONSISTENCY_REL_TOL,
            abs_tol=RESIDUAL_CONSISTENCY_ABS_TOL,
        )
        finite = finite and math.isclose(
            de_q,
            dq * hours,
            rel_tol=RESIDUAL_CONSISTENCY_REL_TOL,
            abs_tol=RESIDUAL_CONSISTENCY_ABS_TOL,
        )
    except (OverflowError, ValueError, ZeroDivisionError):
        finite = False
    if not finite:
        record["revenue_meter_interval_benchmark_state"] = _STATES[5]
        return record
    record.update(
        expected_interval_average_active_power_w=expected_p,
        expected_interval_average_reactive_power_var=expected_q,
        expected_active_energy_wh=expected_wh,
        expected_reactive_energy_varh=expected_varh,
        measured_active_energy_wh=measured_wh,
        measured_reactive_energy_varh=measured_varh,
        expected_interval_reconstruction_resolved=True,
    )
    if policy is None:
        record["revenue_meter_interval_benchmark_state"] = _STATES[7]
        return record
    if gap > float(policy.maximum_expected_sample_gap_seconds):
        record["revenue_meter_interval_benchmark_state"] = _STATES[8]
        return record
    record.update(
        expected_interval_support_gap_policy_satisfied=True,
        expected_interval_support_eligible=True,
        benchmark_eligible=True,
        active_power_residual_measured_minus_expected_w=dp,
        reactive_power_residual_measured_minus_expected_var=dq,
        absolute_active_power_residual_w=abs(dp),
        absolute_reactive_power_residual_var=abs(dq),
        active_energy_residual_measured_minus_expected_wh=de_p,
        reactive_energy_residual_measured_minus_expected_varh=de_q,
        absolute_active_energy_residual_wh=abs(de_p),
        absolute_reactive_energy_residual_varh=abs(de_q),
        revenue_meter_interval_benchmark_state=_STATES[6],
    )
    return record


def _frame(
    keys: tuple[tuple[pd.Timestamp, str], ...], records: list[dict[str, object]]
) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(keys, names=["timestamp", "revenue_meter_id"])
    frame = pd.DataFrame.from_records(records, columns=_COLUMNS, index=index)
    frame.index = index
    for column in _BOOL:
        frame[column] = frame[column].astype("bool")
    for column in _INT:
        frame[column] = frame[column].astype("int64")
    for column in _FLOAT:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    for column in set(_COLUMNS) - _BOOL - _INT - _FLOAT:
        frame[column] = frame[column].astype("object")
    return frame


def _diagnostics(
    meters: tuple[str, ...], timestamps: tuple[pd.Timestamp, ...], frame: pd.DataFrame
) -> TopologyRevenueMeterIntervalBenchmarkDiagnostics:
    rows = len(frame)
    semantics = frame["measurement_time_semantics"]
    boundary_complete = (
        frame["expected_interval_start_row_present"] & frame["expected_interval_end_row_present"]
    )
    eligible = int(frame["benchmark_eligible"].sum())
    states = frame["revenue_meter_interval_benchmark_state"]
    return TopologyRevenueMeterIntervalBenchmarkDiagnostics(
        len(meters),
        len(timestamps),
        rows,
        int(frame["measured_parent_row_present"].sum()),
        int(frame["measured_power_state_present"].sum()),
        int((semantics == "interval_average_ending_at_timestamp").sum()),
        int((semantics == "instantaneous_snapshot").sum()),
        int(frame["interval_boundary_exactly_representable"].sum()),
        int(
            (
                (semantics == "interval_average_ending_at_timestamp")
                & ~frame["interval_boundary_exactly_representable"]
            ).sum()
        ),
        int(boundary_complete.sum()),
        int((frame["interval_boundary_exactly_representable"] & ~boundary_complete).sum()),
        int(frame["expected_interval_all_samples_resolved"].sum()),
        int((frame["expected_interval_unresolved_sample_count"] > 0).sum()),
        int(frame["expected_interval_reconstruction_resolved"].sum()),
        int(
            (
                frame["expected_interval_reconstruction_resolved"]
                & frame["expected_interval_support_policy_present"]
            ).sum()
        ),
        int(
            (
                frame["expected_interval_reconstruction_resolved"]
                & ~frame["expected_interval_support_policy_present"]
            ).sum()
        ),
        int(
            (
                frame["expected_interval_reconstruction_resolved"]
                & frame["expected_interval_support_policy_present"]
                & frame["expected_interval_support_gap_policy_satisfied"]
            ).sum()
        ),
        int(
            (
                frame["expected_interval_reconstruction_resolved"]
                & frame["expected_interval_support_policy_present"]
                & ~frame["expected_interval_support_gap_policy_satisfied"]
            ).sum()
        ),
        eligible,
        rows - eligible,
        int(frame["expected_interval_sample_count"].sum()),
        int(frame["expected_interval_segment_count"].sum()),
        tuple((state, int((states == state).sum())) for state in _STATES),
        REVENUE_METER_INTERVAL_BENCHMARK_MODEL_ID,
    )


def calculate_topology_revenue_meter_interval_benchmark(
    *,
    revenue_meter_interval_support_policy_by_meter_id: Mapping[
        str, RevenueMeterIntervalSupportPolicyAuthority
    ]
    | None = None,
    **values: Any,
) -> TopologyRevenueMeterIntervalBenchmarkResult:
    """Benchmark S13D interval averages against integrated S13C meter power."""
    s13a, s13c, s13d = _parents(values)
    _check_static(s13a, s13c, s13d)
    timestamps = _timestamps(s13c, s13d)
    meters = tuple(s13a.revenue_meter_boundary_by_id)
    keys = tuple((timestamp, meter) for timestamp in timestamps for meter in meters)
    policies = _policies(meters, revenue_meter_interval_support_policy_by_meter_id)
    records = [_record(s13a, s13c, s13d, timestamp, meter, policies) for timestamp, meter in keys]
    frame = _frame(keys, records)
    result = TopologyRevenueMeterIntervalBenchmarkResult(
        frame.copy(deep=True), _diagnostics(meters, timestamps, frame)
    )
    _validate_result(
        (s13a, s13c, s13d), result, revenue_meter_interval_support_policy_by_meter_id=policies
    )
    return result


# The validator duplicates boundary arithmetic, integration, frame construction,
# and diagnostics without calling or capturing production builders/helpers.
def _validator_record(
    s13a: Any,
    s13c: Any,
    s13d: Any,
    timestamp: pd.Timestamp,
    meter_id: str,
    policies: Mapping[str, RevenueMeterIntervalSupportPolicyAuthority] | None = None,
) -> dict[str, object]:
    # Use a separately defined local implementation by evaluating the complete
    # contract from canonical parents.  No production helper is invoked.
    meter = s13a.revenue_meter_boundary_by_id[meter_id]
    node = s13a.nodes_by_id[meter.node_id]
    grids = {g.node_id: i for i, g in s13a.grid_boundary_by_id.items()}
    colocated = grids.get(meter.node_id)
    out: dict[str, object] = {column: "" for column in _COLUMNS}
    for column in _BOOL:
        out[column] = False
    for column in _INT:
        out[column] = 0
    for column in _FLOAT:
        out[column] = math.nan
    out.update(
        network_basis_resolved=s13a.network_basis is not None,
        revenue_meter_node_id=meter.node_id,
        revenue_meter_node_kind=node.node_kind,
        revenue_meter_reference_plane=meter.reference_plane,
        revenue_meter_colocated_with_grid_boundary=colocated is not None,
        colocated_grid_boundary_id=colocated,
        active_power_sign_convention=meter.active_power_sign_convention,
        reactive_power_sign_convention=meter.reactive_power_sign_convention,
        power_basis=meter.power_basis,
        interval_end_timestamp_semantics=INTERVAL_END_SEMANTICS,
        expected_interval_sample_timestamps=(),
        unresolved_expected_sample_timestamps=(),
        expected_temporal_reconstruction_semantics=TEMPORAL_RECONSTRUCTION_SEMANTICS,
        expected_energy_integration_semantics=ENERGY_INTEGRATION_SEMANTICS,
        timestamp_alignment_semantics=TIMESTAMP_ALIGNMENT_SEMANTICS,
        boundary_alignment_semantics=BOUNDARY_ALIGNMENT_SEMANTICS,
        residual_sign_semantics=RESIDUAL_SIGN_SEMANTICS,
        mv_hv_network_authority_contract=MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
        mv_hv_operating_solution_contract=MV_HV_OPERATING_SOLUTION_CONTRACT_ID,
        mv_hv_operating_solution_model=MV_HV_OPERATING_SOLUTION_MODEL_ID,
        revenue_meter_measurement_authority_contract=REVENUE_METER_MEASUREMENT_AUTHORITY_CONTRACT_ID,
        revenue_meter_measurement_authority_model=REVENUE_METER_MEASUREMENT_AUTHORITY_MODEL_ID,
        revenue_meter_interval_benchmark_contract=REVENUE_METER_INTERVAL_BENCHMARK_CONTRACT_ID,
        revenue_meter_interval_benchmark_model=REVENUE_METER_INTERVAL_BENCHMARK_MODEL_ID,
        revenue_meter_interval_benchmark_scope=REVENUE_METER_INTERVAL_BENCHMARK_SCOPE,
        revenue_meter_interval_benchmark_coverage_scope=REVENUE_METER_INTERVAL_BENCHMARK_COVERAGE_SCOPE,
    )
    selected_policy = policies.get(meter_id) if policies is not None else None
    out["revenue_meter_interval_support_policy_contract"] = (
        REVENUE_METER_INTERVAL_SUPPORT_POLICY_CONTRACT_ID
    )
    if selected_policy is not None:
        out.update(
            expected_interval_support_policy_present=True,
            maximum_expected_sample_gap_allowed_seconds=float(
                selected_policy.maximum_expected_sample_gap_seconds
            ),
            support_policy_scope=selected_policy.policy_scope,
            support_policy_evidence_kind=selected_policy.evidence_kind,
            support_policy_parameter_source=selected_policy.parameter_source,
            support_policy_confidence=selected_policy.confidence,
            support_policy_method_reference=selected_policy.method_reference,
            support_policy_applicability_description=selected_policy.applicability_description,
        )
    key = (timestamp, meter_id)
    present = key in s13d.states.index
    m = s13d.states.loc[key] if present else None
    m_present = bool(m["measured_power_state_present"]) if m is not None else False
    m_resolved = bool(m["measured_power_authority_resolved"]) if m is not None else False
    out.update(
        measured_parent_row_present=present,
        measured_power_state_present=m_present,
        measured_power_authority_resolved=m_resolved,
        measured_interval_average_active_power_w=m["measured_active_power_w"]
        if m is not None
        else math.nan,
        measured_interval_average_reactive_power_var=m["measured_reactive_power_var"]
        if m is not None
        else math.nan,
        measurement_time_semantics=m["measurement_time_semantics"] if m is not None else "",
        averaging_interval_seconds=m["averaging_interval_seconds"] if m is not None else math.nan,
        measurement_parameter_source=m["parameter_source"] if m is not None else "",
        measurement_confidence=m["confidence"] if m is not None else "",
    )
    if not m_resolved:
        out["revenue_meter_interval_benchmark_state"] = _STATES[0]
        return out
    assert m is not None
    if m["measurement_time_semantics"] == "instantaneous_snapshot":
        out["revenue_meter_interval_benchmark_state"] = _STATES[1]
        return out
    duration = float(m["averaging_interval_seconds"])
    try:
        product = duration * 1e9
        ns = round(product)
        exact = (
            math.isfinite(product)
            and ns > 0
            and ns <= pd.Timedelta.max.value
            and ns / 1e9 == duration
        )
        start = timestamp - pd.Timedelta(ns, unit="ns") if exact else None
        exact = bool(exact and start is not None and not pd.isna(start))
    except (OverflowError, ValueError, TypeError):
        exact, start = False, None
    out.update(interval_boundary_exactly_representable=exact, interval_start_timestamp=start)
    if not exact:
        out["revenue_meter_interval_benchmark_state"] = _STATES[2]
        return out
    assert isinstance(start, pd.Timestamp)
    if s13c.revenue_meter_states.empty:
        mf = s13c.revenue_meter_states.droplevel("revenue_meter_id")
    else:
        mf = s13c.revenue_meter_states.xs(meter_id, level="revenue_meter_id", drop_level=True)
    selected = mf.loc[(mf.index >= start) & (mf.index <= timestamp)].sort_index()
    sp, ep = start in mf.index, timestamp in mf.index
    ready = selected["mv_hv_operating_solution_resolved"].astype(bool) & (
        selected["revenue_meter_expected_state"] == "resolved_expected_revenue_meter_boundary_power"
    )
    unresolved = tuple(selected.index[~ready])
    count = len(selected)
    resolved_count = int(ready.sum())
    out.update(
        expected_interval_start_row_present=sp,
        expected_interval_end_row_present=ep,
        expected_interval_sample_count=count,
        expected_interval_resolved_sample_count=resolved_count,
        expected_interval_unresolved_sample_count=count - resolved_count,
        expected_interval_sample_timestamps=tuple(selected.index),
        unresolved_expected_sample_timestamps=unresolved,
        expected_interval_segment_count=max(count - 1, 0),
        expected_interval_all_samples_resolved=bool(count and resolved_count == count),
    )
    if sp:
        out.update(
            expected_start_active_power_w=mf.loc[start]["expected_p_at_revenue_meter_w"],
            expected_start_reactive_power_var=mf.loc[start]["expected_q_at_revenue_meter_var"],
        )
    if ep:
        out.update(
            expected_end_active_power_w=mf.loc[timestamp]["expected_p_at_revenue_meter_w"],
            expected_end_reactive_power_var=mf.loc[timestamp]["expected_q_at_revenue_meter_var"],
        )
    if not sp or not ep:
        out["revenue_meter_interval_benchmark_state"] = _STATES[3]
        return out
    if unresolved:
        out["revenue_meter_interval_benchmark_state"] = _STATES[4]
        return out
    active: list[float] = []
    reactive: list[float] = []
    gaps: list[float] = []
    finite = True
    try:
        for i in range(count - 1):
            left, right = selected.iloc[i], selected.iloc[i + 1]
            seconds = (selected.index[i + 1] - selected.index[i]).value / 1e9
            if not math.isfinite(seconds) or seconds <= 0:
                finite = False
                break
            hours = seconds / 3600
            pa = (
                float(left["expected_p_at_revenue_meter_w"]) / 2
                + float(right["expected_p_at_revenue_meter_w"]) / 2
            ) * hours
            qa = (
                float(left["expected_q_at_revenue_meter_var"]) / 2
                + float(right["expected_q_at_revenue_meter_var"]) / 2
            ) * hours
            if not math.isfinite(pa) or not math.isfinite(qa):
                finite = False
                break
            active.append(pa)
            reactive.append(qa)
            gaps.append(seconds)
        ewh = math.fsum(active)
        eqh = math.fsum(reactive)
        finite = finite and math.isfinite(ewh) and math.isfinite(eqh)
    except (OverflowError, ValueError, TypeError):
        finite = False
        ewh = eqh = math.nan
    max_gap = max(gaps, default=math.nan)
    out["maximum_expected_sample_gap_seconds"] = max_gap
    if math.isfinite(max_gap) and duration > 0:
        out["maximum_expected_sample_gap_fraction_of_interval"] = max_gap / duration
    try:
        hours = duration / 3600
        epa = ewh / hours
        eqa = eqh / hours
        mp = float(m["measured_active_power_w"])
        mq = float(m["measured_reactive_power_var"])
        mwh = mp * hours
        mqh = mq * hours
        dp = mp - epa
        dq = mq - eqa
        de = mwh - ewh
        dqe = mqh - eqh
        finite = finite and all(math.isfinite(v) for v in (epa, eqa, mwh, mqh, dp, dq, de, dqe))
        finite = finite and math.isclose(
            de,
            dp * hours,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        finite = finite and math.isclose(
            dqe,
            dq * hours,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
    except (OverflowError, ValueError, ZeroDivisionError):
        finite = False
    if not finite:
        out["revenue_meter_interval_benchmark_state"] = _STATES[5]
        return out
    out.update(
        expected_interval_average_active_power_w=epa,
        expected_interval_average_reactive_power_var=eqa,
        expected_active_energy_wh=ewh,
        expected_reactive_energy_varh=eqh,
        measured_active_energy_wh=mwh,
        measured_reactive_energy_varh=mqh,
        expected_interval_reconstruction_resolved=True,
    )
    if selected_policy is None:
        out["revenue_meter_interval_benchmark_state"] = (
            "unresolved_missing_expected_interval_support_policy"
        )
        return out
    if not max_gap <= float(selected_policy.maximum_expected_sample_gap_seconds):
        out["revenue_meter_interval_benchmark_state"] = (
            "unresolved_expected_interval_support_gap_exceeds_policy"
        )
        return out
    out.update(
        expected_interval_support_gap_policy_satisfied=True,
        expected_interval_support_eligible=True,
        benchmark_eligible=True,
        active_power_residual_measured_minus_expected_w=dp,
        reactive_power_residual_measured_minus_expected_var=dq,
        absolute_active_power_residual_w=abs(dp),
        absolute_reactive_power_residual_var=abs(dq),
        active_energy_residual_measured_minus_expected_wh=de,
        reactive_energy_residual_measured_minus_expected_varh=dqe,
        absolute_active_energy_residual_wh=abs(de),
        absolute_reactive_energy_residual_varh=abs(dqe),
        revenue_meter_interval_benchmark_state=_STATES[6],
    )
    return out


def _validator_frame(
    keys: tuple[tuple[pd.Timestamp, str], ...], records: list[dict[str, object]]
) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(keys, names=["timestamp", "revenue_meter_id"])
    frame = pd.DataFrame.from_records(records, columns=_COLUMNS, index=index)
    frame.index = index
    for c in _BOOL:
        frame[c] = frame[c].astype("bool")
    for c in _INT:
        frame[c] = frame[c].astype("int64")
    for c in _FLOAT:
        frame[c] = pd.to_numeric(frame[c], errors="coerce").astype("float64")
    for c in set(_COLUMNS) - _BOOL - _INT - _FLOAT:
        frame[c] = frame[c].astype("object")
    return frame


def _validator_diagnostics(
    meters: tuple[str, ...], timestamps: tuple[pd.Timestamp, ...], frame: pd.DataFrame
) -> TopologyRevenueMeterIntervalBenchmarkDiagnostics:
    rows = len(frame)
    sem = frame["measurement_time_semantics"]
    complete = (
        frame["expected_interval_start_row_present"] & frame["expected_interval_end_row_present"]
    )
    eligible = int(frame["benchmark_eligible"].sum())
    states = frame["revenue_meter_interval_benchmark_state"]
    return TopologyRevenueMeterIntervalBenchmarkDiagnostics(
        len(meters),
        len(timestamps),
        rows,
        int(frame["measured_parent_row_present"].sum()),
        int(frame["measured_power_state_present"].sum()),
        int((sem == "interval_average_ending_at_timestamp").sum()),
        int((sem == "instantaneous_snapshot").sum()),
        int(frame["interval_boundary_exactly_representable"].sum()),
        int(
            (
                (sem == "interval_average_ending_at_timestamp")
                & ~frame["interval_boundary_exactly_representable"]
            ).sum()
        ),
        int(complete.sum()),
        int((frame["interval_boundary_exactly_representable"] & ~complete).sum()),
        int(frame["expected_interval_all_samples_resolved"].sum()),
        int((frame["expected_interval_unresolved_sample_count"] > 0).sum()),
        int(frame["expected_interval_reconstruction_resolved"].sum()),
        int(
            (
                frame["expected_interval_reconstruction_resolved"]
                & frame["expected_interval_support_policy_present"]
            ).sum()
        ),
        int(
            (
                frame["expected_interval_reconstruction_resolved"]
                & ~frame["expected_interval_support_policy_present"]
            ).sum()
        ),
        int(
            (
                frame["expected_interval_reconstruction_resolved"]
                & frame["expected_interval_support_policy_present"]
                & frame["expected_interval_support_gap_policy_satisfied"]
            ).sum()
        ),
        int(
            (
                frame["expected_interval_reconstruction_resolved"]
                & frame["expected_interval_support_policy_present"]
                & ~frame["expected_interval_support_gap_policy_satisfied"]
            ).sum()
        ),
        eligible,
        rows - eligible,
        int(frame["expected_interval_sample_count"].sum()),
        int(frame["expected_interval_segment_count"].sum()),
        tuple((state, int((states == state).sum())) for state in _STATES),
        REVENUE_METER_INTERVAL_BENCHMARK_MODEL_ID,
    )


def _validate_result(
    parents: tuple[Any, Any, Any],
    result: TopologyRevenueMeterIntervalBenchmarkResult,
    *,
    revenue_meter_interval_support_policy_by_meter_id: Mapping[
        str, RevenueMeterIntervalSupportPolicyAuthority
    ]
    | None = None,
) -> None:
    if type(result) is not TopologyRevenueMeterIntervalBenchmarkResult:
        raise RuntimeError("S14B result type is invalid")
    s13a, s13c, s13d = parents
    _check_static(s13a, s13c, s13d)
    timestamps = _timestamps(s13c, s13d)
    meters = tuple(s13a.revenue_meter_boundary_by_id)
    keys = tuple((t, m) for t in timestamps for m in meters)
    # Independent policy admission: never call production _policies().
    supplied = revenue_meter_interval_support_policy_by_meter_id
    if supplied is None:
        supplied = {}
    if not isinstance(supplied, Mapping):
        raise ValueError("validator requires an explicit support-policy mapping")
    admitted = {}
    for identity, authority in supplied.items():
        if type(identity) is not str or identity not in meters:
            raise ValueError("validator policy meter identity is invalid")
        if type(authority) is not RevenueMeterIntervalSupportPolicyAuthority:
            raise ValueError("validator policy authority type is invalid")
        admitted[identity] = replace(authority)
    expected = _validator_frame(
        keys, [_validator_record(s13a, s13c, s13d, t, m, admitted) for t, m in keys]
    )
    try:
        pd.testing.assert_frame_equal(result.states, expected, check_exact=True)
    except AssertionError as error:
        raise RuntimeError("S14B state frame failed independent exact closure") from error
    if result.diagnostics != _validator_diagnostics(meters, timestamps, expected):
        raise RuntimeError("S14B diagnostics failed independent exact closure")
