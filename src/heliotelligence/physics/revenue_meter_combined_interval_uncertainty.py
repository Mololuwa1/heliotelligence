"""Dormant deterministic comparison-bound magnitudes; never reconstruct residuals.

Only the independently replayed parents own numerical evidence and interval
propagation. Mathematical combination does not admit a benchmark comparison.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from numbers import Real
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.physics import revenue_meter_expected_model_interval_uncertainty as model
from heliotelligence.physics import revenue_meter_measurement_uncertainty as measurement

REVENUE_METER_COMBINED_INTERVAL_UNCERTAINTY_CONTRACT_ID = (
    "admitted_measurement_and_expected_model_interval_uncertainty_to_combined_"
    "revenue_meter_interval_uncertainty_state_v1"
)
REVENUE_METER_COMBINED_INTERVAL_UNCERTAINTY_MODEL_ID = (
    "deterministic_sum_of_symmetric_measurement_and_expected_model_interval_maximum_bounds_v1"
)
REVENUE_METER_COMBINED_INTERVAL_UNCERTAINTY_SCOPE = (
    "revenue_meter_interval_combined_measurement_expected_model_"
    "uncertainty_before_residual_interpretation"
)
COMBINATION_SEMANTICS = (
    "deterministic_worst_case_difference_bound_sum_no_probability_independence_or_covariance"
)
COMBINATION_BASIS = (
    "sum_of_independently_admitted_symmetric_maximum_absolute_measurement_and_expected_model_bounds"
)
COVERAGE_LIMITATION = (
    "combined_uncertainty_magnitude_only_not_benchmark_eligibility_"
    "residual_reconstruction_or_significance"
)
_CHANNELS = (("active", "w", "wh"), ("reactive", "var", "varh"))
_STATES = (
    "unresolved_no_complete_combined_interval_uncertainty_channel",
    "unresolved_nonfinite_combined_interval_uncertainty_arithmetic",
    "resolved_active_combined_interval_uncertainty_only",
    "resolved_reactive_combined_interval_uncertainty_only",
    "resolved_active_reactive_combined_interval_uncertainty",
)
_FIXED = {
    "combined_interval_uncertainty_contract": (
        REVENUE_METER_COMBINED_INTERVAL_UNCERTAINTY_CONTRACT_ID
    ),
    "combined_interval_uncertainty_model": REVENUE_METER_COMBINED_INTERVAL_UNCERTAINTY_MODEL_ID,
    "combined_interval_uncertainty_scope": REVENUE_METER_COMBINED_INTERVAL_UNCERTAINTY_SCOPE,
    "combined_interval_uncertainty_combination_semantics": COMBINATION_SEMANTICS,
    "combined_interval_uncertainty_combination_basis": COMBINATION_BASIS,
    "combined_interval_uncertainty_coverage_limitation": COVERAGE_LIMITATION,
    "measurement_uncertainty_parent_contract": (
        measurement.REVENUE_METER_MEASUREMENT_UNCERTAINTY_CONTRACT_ID
    ),
    "measurement_uncertainty_parent_model": (
        measurement.REVENUE_METER_MEASUREMENT_UNCERTAINTY_MODEL_ID
    ),
    "expected_model_interval_uncertainty_parent_contract": (
        model.REVENUE_METER_EXPECTED_MODEL_INTERVAL_UNCERTAINTY_CONTRACT_ID
    ),
    "expected_model_interval_uncertainty_parent_model": (
        model.REVENUE_METER_EXPECTED_MODEL_INTERVAL_UNCERTAINTY_MODEL_ID
    ),
}
_BOOL = tuple(
    f"{c}_{suffix}"
    for c, _, _ in _CHANNELS
    for suffix in (
        "measurement_interval_uncertainty_available",
        "model_interval_uncertainty_available",
        "combined_interval_uncertainty_resolved",
    )
)
_FLOAT = tuple(
    field
    for c, power, energy in _CHANNELS
    for field in (
        f"{c}_interval_average_power_combined_uncertainty_bound_{power}",
        f"{c}_energy_combined_uncertainty_bound_{energy}",
    )
)
_TEXT = (
    "combined_interval_uncertainty_state",
    *(f"{c}_combined_interval_uncertainty_state" for c, _, _ in _CHANNELS),
    *_FIXED,
)
_EXTRA_COLUMNS = (*_BOOL, *_FLOAT, *_TEXT)
_SHARED = (
    "network_basis_resolved",
    "revenue_meter_node_id",
    "revenue_meter_node_kind",
    "revenue_meter_reference_plane",
    "revenue_meter_colocated_with_grid_boundary",
    "colocated_grid_boundary_id",
    "active_power_sign_convention",
    "reactive_power_sign_convention",
    "power_basis",
    "measured_power_state_present",
    "measured_power_authority_resolved",
    "measurement_time_semantics",
    "averaging_interval_seconds",
)


@dataclass(frozen=True)
class RevenueMeterCombinedIntervalUncertaintyDiagnostics:
    interval_row_count: int
    active_measurement_resolved_count: int
    active_measurement_unresolved_count: int
    reactive_measurement_resolved_count: int
    reactive_measurement_unresolved_count: int
    active_model_resolved_count: int
    active_model_unresolved_count: int
    reactive_model_resolved_count: int
    reactive_model_unresolved_count: int
    active_combined_resolved_count: int
    active_combined_unresolved_count: int
    reactive_combined_resolved_count: int
    reactive_combined_unresolved_count: int
    active_measurement_only_unavailable_count: int
    active_model_only_unavailable_count: int
    active_both_unavailable_count: int
    active_arithmetic_failure_count: int
    reactive_measurement_only_unavailable_count: int
    reactive_model_only_unavailable_count: int
    reactive_both_unavailable_count: int
    reactive_arithmetic_failure_count: int
    support_policy_eligible_count: int
    support_policy_ineligible_count: int
    benchmark_eligible_count: int
    benchmark_ineligible_count: int
    measurement_snapshot_row_count: int
    state_counts: tuple[tuple[str, int], ...]
    model: str


@dataclass(frozen=True)
class RevenueMeterCombinedIntervalUncertaintyResult:
    states: pd.DataFrame
    measurement_uncertainty_states: pd.DataFrame
    diagnostics: RevenueMeterCombinedIntervalUncertaintyDiagnostics


def _replay(label: str, actual: Any, expected: Any) -> None:
    """Exact comparison, including timezone representation inside support tuples."""
    if type(actual) is not type(expected):
        raise ValueError(f"{label} type failed canonical replay")
    if isinstance(expected, pd.DataFrame):
        try:
            pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        except AssertionError as error:
            raise ValueError(f"{label} frame failed canonical replay") from error
        for field in expected.columns:
            if not pd.api.types.is_object_dtype(expected[field].dtype):
                continue
            for supplied, canonical in zip(actual[field], expected[field], strict=True):
                if isinstance(canonical, (pd.Timestamp, tuple)):
                    _replay(label + " structured value", supplied, canonical)
                elif canonical is None and supplied is not None:
                    raise ValueError(f"{label} absent provenance failed replay")
    elif is_dataclass(expected):
        for field in fields(expected):
            _replay(
                label + "." + field.name, getattr(actual, field.name), getattr(expected, field.name)
            )
    elif isinstance(expected, Mapping):
        if tuple(actual.keys()) != tuple(expected.keys()):
            raise ValueError(f"{label} mapping keys failed canonical replay")
        for key in expected:
            _replay(label, actual[key], expected[key])
    elif isinstance(expected, tuple):
        if len(actual) != len(expected):
            raise ValueError(f"{label} tuple failed canonical replay")
        for supplied, canonical in zip(actual, expected, strict=True):
            _replay(label, supplied, canonical)
    elif isinstance(expected, pd.Timestamp):
        if actual != expected or str(actual.tz) != str(expected.tz):
            raise ValueError(f"{label} timestamp failed canonical replay")
    elif actual != expected:
        raise ValueError(f"{label} failed canonical replay")


def _parents(values: Mapping[str, Any], ma: Any, ea: Any, policies: Any) -> tuple[Any, Any]:
    measured = measurement.resolve_topology_revenue_meter_measurement_uncertainty(
        **values, revenue_meter_measurement_uncertainty_by_meter_id=ma
    )
    _replay("measurement uncertainty", values["revenue_meter_measurement_uncertainty"], measured)
    expected = model.resolve_revenue_meter_expected_model_interval_uncertainty(
        **values,
        revenue_meter_expected_model_uncertainty_by_meter_id=ea,
        revenue_meter_interval_support_policy_by_meter_id=policies,
    )
    _replay(
        "expected-model interval uncertainty",
        values["revenue_meter_expected_model_interval_uncertainty"],
        expected,
    )
    return measured, expected


def _align(measured: Any, expected: Any) -> None:
    left, right = measured.states, expected.states
    if left.index.names != right.index.names or len(left) != len(right):
        raise ValueError("canonical parent row universes disagree")
    _replay("parent row identity", tuple(left.index), tuple(right.index))
    for field in _SHARED:
        for a, b in zip(left[field], right[field], strict=True):
            if pd.isna(a) and pd.isna(b):
                continue
            if a != b:
                raise ValueError(f"canonical parent semantics disagree: {field}")
    for a, b in (
        ("parameter_source", "measurement_parameter_source"),
        ("confidence", "measurement_confidence"),
    ):
        if tuple(left[a]) != tuple(right[b]):
            raise ValueError("canonical measurement provenance disagrees")


def _combine(bounds: tuple[Any, ...]) -> tuple[float, float] | None:
    try:
        if any(
            isinstance(x, bool) or not isinstance(x, Real) or not math.isfinite(x) or x < 0
            for x in bounds
        ):
            return None
        power = math.fsum((bounds[0], bounds[1]))
        energy = math.fsum((bounds[2], bounds[3]))
        return (power, energy) if math.isfinite(power) and math.isfinite(energy) else None
    except (OverflowError, ValueError):
        return None


def _record(measured: pd.Series, expected: pd.Series) -> dict[str, Any]:
    out: dict[str, Any] = {
        **dict.fromkeys(_BOOL, False),
        **dict.fromkeys(_FLOAT, math.nan),
        **_FIXED,
    }
    arithmetic = False
    for c, power, energy in _CHANNELS:
        m = bool(measured[f"{c}_energy_measurement_uncertainty_resolved"]) and bool(
            measured[f"{c}_power_measurement_uncertainty_resolved"]
        )
        e = bool(expected[f"{c}_expected_model_interval_uncertainty_resolved"])
        out[f"{c}_measurement_interval_uncertainty_available"] = m
        out[f"{c}_model_interval_uncertainty_available"] = e
        state = "unresolved_both_parent_interval_uncertainties_unavailable"
        if m and not e:
            state = "unresolved_expected_model_interval_uncertainty_unavailable"
        elif e and not m:
            state = "unresolved_measurement_interval_uncertainty_unavailable"
        elif m and e:
            numbers = _combine(
                (
                    measured[f"{c}_power_measurement_uncertainty_bound_{power}"],
                    expected[
                        f"{c}_interval_average_power_expected_model_uncertainty_bound_{power}"
                    ],
                    measured[f"{c}_energy_measurement_uncertainty_bound_{energy}"],
                    expected[f"{c}_energy_expected_model_uncertainty_bound_{energy}"],
                )
            )
            state = _STATES[1]
            if numbers is None:
                arithmetic = True
            else:
                out[f"{c}_interval_average_power_combined_uncertainty_bound_{power}"] = numbers[0]
                out[f"{c}_energy_combined_uncertainty_bound_{energy}"] = numbers[1]
                out[f"{c}_combined_interval_uncertainty_resolved"] = True
                state = f"resolved_{c}_combined_interval_uncertainty"
        out[f"{c}_combined_interval_uncertainty_state"] = state
    p, q = (out[f"{c}_combined_interval_uncertainty_resolved"] for c in ("active", "reactive"))
    out["combined_interval_uncertainty_state"] = (
        _STATES[4]
        if p and q
        else _STATES[2]
        if p
        else _STATES[3]
        if q
        else _STATES[1]
        if arithmetic
        else _STATES[0]
    )
    return out


def _frame(expected: Any, records: list[dict[str, Any]]) -> pd.DataFrame:
    if set(expected.states.columns) & set(_EXTRA_COLUMNS):
        raise ValueError("combined uncertainty schema collision")
    extra = pd.DataFrame(records, index=expected.states.index.copy(), columns=_EXTRA_COLUMNS)
    for col in _BOOL:
        extra[col] = extra[col].astype(bool)
    for col in _FLOAT:
        extra[col] = extra[col].astype(float)
    for col in _TEXT:
        extra[col] = extra[col].astype(object)
    return pd.concat([expected.states.copy(deep=True), extra], axis=1)


def _measurement_snapshot(measured: Any) -> pd.DataFrame:
    return measured.states.copy(deep=True)


def _diagnostics(
    frame: pd.DataFrame, snapshot: pd.DataFrame
) -> RevenueMeterCombinedIntervalUncertaintyDiagnostics:
    n = len(frame)
    counts: dict[str, Any] = {"interval_row_count": n}
    for c, _, _ in _CHANNELS:
        for owner, suffix in (
            ("measurement", "measurement_interval_uncertainty_available"),
            ("model", "model_interval_uncertainty_available"),
            ("combined", "combined_interval_uncertainty_resolved"),
        ):
            count = int(frame[f"{c}_{suffix}"].sum())
            counts[f"{c}_{owner}_resolved_count"] = count
            counts[f"{c}_{owner}_unresolved_count"] = n - count
        for name, state in (
            (
                "measurement_only_unavailable",
                "unresolved_measurement_interval_uncertainty_unavailable",
            ),
            (
                "model_only_unavailable",
                "unresolved_expected_model_interval_uncertainty_unavailable",
            ),
            ("both_unavailable", "unresolved_both_parent_interval_uncertainties_unavailable"),
            ("arithmetic_failure", _STATES[1]),
        ):
            counts[f"{c}_{name}_count"] = int(
                frame[f"{c}_combined_interval_uncertainty_state"].eq(state).sum()
            )
    for name, field in (
        ("support_policy", "expected_interval_support_eligible"),
        ("benchmark", "benchmark_eligible"),
    ):
        count = int(frame[field].sum())
        counts[f"{name}_eligible_count"] = count
        counts[f"{name}_ineligible_count"] = n - count
    counts["measurement_snapshot_row_count"] = len(snapshot)
    counts["state_counts"] = tuple(
        (s, int(frame.combined_interval_uncertainty_state.eq(s).sum())) for s in _STATES
    )
    counts["model"] = REVENUE_METER_COMBINED_INTERVAL_UNCERTAINTY_MODEL_ID
    return RevenueMeterCombinedIntervalUncertaintyDiagnostics(**counts)


def resolve_revenue_meter_combined_interval_uncertainty(
    *,
    revenue_meter_measurement_uncertainty_by_meter_id: Mapping[
        str, measurement.RevenueMeterMeasurementUncertaintyAuthority
    ]
    | None = None,
    revenue_meter_expected_model_uncertainty_by_meter_id: Mapping[str, Any] | None = None,
    revenue_meter_interval_support_policy_by_meter_id: Mapping[str, Any] | None = None,
    **values: Any,
) -> RevenueMeterCombinedIntervalUncertaintyResult:
    """Replay independently owned parents from their original inputs and mappings.

    No residual is reconstructed, including when S14B withholds its residuals.
    """
    measured, expected = _parents(
        values,
        revenue_meter_measurement_uncertainty_by_meter_id,
        revenue_meter_expected_model_uncertainty_by_meter_id,
        revenue_meter_interval_support_policy_by_meter_id,
    )
    _align(measured, expected)
    records = [
        _record(measured.states.iloc[i], row)
        for i, (_, row) in enumerate(expected.states.iterrows())
    ]
    frame = _frame(expected, records)
    snapshot = _measurement_snapshot(measured)
    result = RevenueMeterCombinedIntervalUncertaintyResult(
        frame, snapshot, _diagnostics(frame, snapshot)
    )
    _validate_result(measured, expected, result)
    return result


def _validator_parents(
    values: Mapping[str, Any], ma: Any, ea: Any, policies: Any
) -> tuple[Any, Any]:
    measured = measurement.resolve_topology_revenue_meter_measurement_uncertainty(
        **values, revenue_meter_measurement_uncertainty_by_meter_id=ma
    )
    _replay("measurement uncertainty", values["revenue_meter_measurement_uncertainty"], measured)
    expected = model.resolve_revenue_meter_expected_model_interval_uncertainty(
        **values,
        revenue_meter_expected_model_uncertainty_by_meter_id=ea,
        revenue_meter_interval_support_policy_by_meter_id=policies,
    )
    _replay(
        "expected-model interval uncertainty",
        values["revenue_meter_expected_model_interval_uncertainty"],
        expected,
    )
    return measured, expected


def _validate_result(
    measured: Any, expected: Any, result: RevenueMeterCombinedIntervalUncertaintyResult
) -> None:
    """Independent alignment, arithmetic, schema, snapshot and diagnostic replay.

    Parents here have already been canonically reconstructed by the public API.
    No production combined-layer helper is used.
    """
    left, right = measured.states, expected.states
    if left.index.names != right.index.names or len(left) != len(right):
        raise ValueError("validator: parent row universe mismatch")
    if tuple(left.index) != tuple(right.index):
        raise ValueError("validator: exact ordered keys mismatch")
    for (mt, mi), (et, ei) in zip(left.index, right.index, strict=True):
        if mi != ei or mt != et or str(mt.tz) != str(et.tz):
            raise ValueError("validator: parent timezone/identity mismatch")
    for name in (*_SHARED, "measurement_parameter_source", "measurement_confidence"):
        mname = {
            "measurement_parameter_source": "parameter_source",
            "measurement_confidence": "confidence",
        }.get(name, name)
        for mvalue, evalue in zip(left[mname], right[name], strict=True):
            if pd.isna(mvalue) and pd.isna(evalue):
                continue
            if mvalue != evalue:
                raise ValueError(f"validator: parent semantics mismatch: {name}")
    if set(right.columns).intersection(_EXTRA_COLUMNS):
        raise ValueError("validator: annotation schema collision")
    records: list[dict[str, Any]] = []
    counts: dict[str, Any] = {
        field.name: 0
        for field in fields(RevenueMeterCombinedIntervalUncertaintyDiagnostics)
        if field.name not in ("state_counts", "model")
    }
    totals = {state: 0 for state in _STATES}
    for position in range(len(right)):
        mr, er = left.iloc[position], right.iloc[position]
        record: dict[str, Any] = dict(_FIXED)
        record.update({key: math.nan for key in _FLOAT})
        record.update({key: False for key in _BOOL})
        failure = False
        for c, pu, eu in _CHANNELS:
            mready = bool(mr[f"{c}_energy_measurement_uncertainty_resolved"]) and bool(
                mr[f"{c}_power_measurement_uncertainty_resolved"]
            )
            eready = bool(er[f"{c}_expected_model_interval_uncertainty_resolved"])
            record[f"{c}_measurement_interval_uncertainty_available"] = mready
            record[f"{c}_model_interval_uncertainty_available"] = eready
            for owner, ready in (("measurement", mready), ("model", eready)):
                counts[f"{c}_{owner}_{'resolved' if ready else 'unresolved'}_count"] += 1
            state = "unresolved_both_parent_interval_uncertainties_unavailable"
            reason = "both_unavailable"
            if mready and not eready:
                state, reason = (
                    "unresolved_expected_model_interval_uncertainty_unavailable",
                    "model_only_unavailable",
                )
            elif eready and not mready:
                state, reason = (
                    "unresolved_measurement_interval_uncertainty_unavailable",
                    "measurement_only_unavailable",
                )
            elif mready and eready:
                state, reason = _STATES[1], "arithmetic_failure"
                power_inputs = (
                    mr[f"{c}_power_measurement_uncertainty_bound_{pu}"],
                    er[f"{c}_interval_average_power_expected_model_uncertainty_bound_{pu}"],
                )
                energy_inputs = (
                    mr[f"{c}_energy_measurement_uncertainty_bound_{eu}"],
                    er[f"{c}_energy_expected_model_uncertainty_bound_{eu}"],
                )
                numbers: list[float] = []
                try:
                    for pair in (power_inputs, energy_inputs):
                        if any(
                            isinstance(x, bool)
                            or not isinstance(x, Real)
                            or not math.isfinite(x)
                            or x < 0
                            for x in pair
                        ):
                            break
                        total = math.fsum(pair)
                        if not math.isfinite(total):
                            break
                        numbers.append(total)
                except (OverflowError, ValueError):
                    numbers = []
                if len(numbers) == 2:
                    record[f"{c}_interval_average_power_combined_uncertainty_bound_{pu}"] = numbers[
                        0
                    ]
                    record[f"{c}_energy_combined_uncertainty_bound_{eu}"] = numbers[1]
                    record[f"{c}_combined_interval_uncertainty_resolved"] = True
                    state = f"resolved_{c}_combined_interval_uncertainty"
                else:
                    failure = True
            ready = record[f"{c}_combined_interval_uncertainty_resolved"]
            counts[f"{c}_combined_{'resolved' if ready else 'unresolved'}_count"] += 1
            if not ready:
                counts[f"{c}_{reason}_count"] += 1
            record[f"{c}_combined_interval_uncertainty_state"] = state
        a, b = (
            record[f"{c}_combined_interval_uncertainty_resolved"] for c in ("active", "reactive")
        )
        selected = (
            _STATES[4]
            if a and b
            else _STATES[2]
            if a
            else _STATES[3]
            if b
            else _STATES[1]
            if failure
            else _STATES[0]
        )
        record["combined_interval_uncertainty_state"] = selected
        totals[selected] += 1
        records.append(record)
        for prefix, field in (
            ("support_policy", "expected_interval_support_eligible"),
            ("benchmark", "benchmark_eligible"),
        ):
            counts[f"{prefix}_{'eligible' if bool(er[field]) else 'ineligible'}_count"] += 1
    additions = pd.DataFrame(records, index=right.index.copy(), columns=_EXTRA_COLUMNS)
    for key in _EXTRA_COLUMNS:
        additions[key] = additions[key].astype(
            bool if key in _BOOL else float if key in _FLOAT else object
        )
    canonical_frame = pd.concat([right.copy(deep=True), additions], axis=1)
    snapshot = left.copy(deep=True)
    counts["interval_row_count"] = len(right)
    counts["measurement_snapshot_row_count"] = len(left)
    counts["state_counts"] = tuple(totals.items())
    counts["model"] = REVENUE_METER_COMBINED_INTERVAL_UNCERTAINTY_MODEL_ID
    canonical = RevenueMeterCombinedIntervalUncertaintyResult(
        canonical_frame, snapshot, RevenueMeterCombinedIntervalUncertaintyDiagnostics(**counts)
    )
    _replay("combined interval uncertainty", result, canonical)


def validate_revenue_meter_combined_interval_uncertainty(
    result: RevenueMeterCombinedIntervalUncertaintyResult,
    *,
    revenue_meter_measurement_uncertainty_by_meter_id: Mapping[
        str, measurement.RevenueMeterMeasurementUncertaintyAuthority
    ]
    | None = None,
    revenue_meter_expected_model_uncertainty_by_meter_id: Mapping[str, Any] | None = None,
    revenue_meter_interval_support_policy_by_meter_id: Mapping[str, Any] | None = None,
    **values: Any,
) -> None:
    measured, expected = _validator_parents(
        values,
        revenue_meter_measurement_uncertainty_by_meter_id,
        revenue_meter_expected_model_uncertainty_by_meter_id,
        revenue_meter_interval_support_policy_by_meter_id,
    )
    _validate_result(measured, expected, result)
