"""Dormant deterministic envelope relations for eligible canonical interval residuals.

The combined parent owns residuals, eligibility and numerical bounds. This layer
never regenerates them and makes no causal, commercial or probability claim.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from numbers import Real
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.physics import revenue_meter_combined_interval_uncertainty as combined

REVENUE_METER_INTERVAL_UNCERTAINTY_INTERPRETATION_CONTRACT_ID = (
    "admitted_combined_interval_uncertainty_and_eligible_s14b_residual_to_"
    "revenue_meter_interval_uncertainty_interpretation_state_v1"
)
REVENUE_METER_INTERVAL_UNCERTAINTY_INTERPRETATION_MODEL_ID = (
    "deterministic_zero_centered_combined_uncertainty_envelope_residual_comparison_v1"
)
REVENUE_METER_INTERVAL_UNCERTAINTY_INTERPRETATION_SCOPE = (
    "eligible_s14b_interval_residual_uncertainty_envelope_interpretation_"
    "before_causal_or_commercial_attribution"
)
INTERPRETATION_SEMANTICS = (
    "deterministic_residual_vs_symmetric_combined_maximum_bound_"
    "no_probability_or_statistical_significance"
)
OUTSIDE_ENVELOPE_MEANING = (
    "outside_envelope_means_absolute_canonical_residual_exceeds_"
    "admitted_combined_maximum_bound_only"
)
COVERAGE_LIMITATION = (
    "uncertainty_envelope_relation_only_not_causality_fault_classification_"
    "loss_attribution_or_commercial_impact"
)
_RELATIONS = (
    "within_combined_uncertainty_envelope",
    "on_combined_uncertainty_envelope_boundary",
    "outside_positive_combined_uncertainty_envelope",
    "outside_negative_combined_uncertainty_envelope",
)
_STATES = (
    "unresolved_benchmark_ineligible",
    "unresolved_no_complete_interval_uncertainty_interpretation_channel",
    "unresolved_nonfinite_interval_uncertainty_interpretation",
    "resolved_active_interval_uncertainty_interpretation_only",
    "resolved_reactive_interval_uncertainty_interpretation_only",
    "resolved_active_reactive_interval_uncertainty_interpretation",
)
_UNAVAILABLE = "unresolved_combined_interval_uncertainty_unavailable"
_RESOLVED = "resolved_interval_uncertainty_envelope_interpretation"
_CHANNELS = (("active", "w", "wh"), ("reactive", "var", "varh"))
# Immutable schema describes the four independently published parent quantities.
_QUANTITIES = tuple(
    (prefix, unit, residual, bound)
    for c, power, energy in _CHANNELS
    for prefix, unit, residual, bound in (
        (
            f"{c}_interval_average_power",
            power,
            f"{c}_power_residual_measured_minus_expected_{power}",
            f"{c}_interval_average_power_combined_uncertainty_bound_{power}",
        ),
        (
            f"{c}_energy",
            energy,
            f"{c}_energy_residual_measured_minus_expected_{energy}",
            f"{c}_energy_combined_uncertainty_bound_{energy}",
        ),
    )
)
_FIXED = {
    "interval_uncertainty_interpretation_contract": (
        REVENUE_METER_INTERVAL_UNCERTAINTY_INTERPRETATION_CONTRACT_ID
    ),
    "interval_uncertainty_interpretation_model": (
        REVENUE_METER_INTERVAL_UNCERTAINTY_INTERPRETATION_MODEL_ID
    ),
    "interval_uncertainty_interpretation_scope": (
        REVENUE_METER_INTERVAL_UNCERTAINTY_INTERPRETATION_SCOPE
    ),
    "interval_uncertainty_interpretation_semantics": INTERPRETATION_SEMANTICS,
    "interval_uncertainty_interpretation_outside_envelope_meaning": OUTSIDE_ENVELOPE_MEANING,
    "interval_uncertainty_interpretation_coverage_limitation": COVERAGE_LIMITATION,
    "combined_interval_uncertainty_parent_contract": (
        combined.REVENUE_METER_COMBINED_INTERVAL_UNCERTAINTY_CONTRACT_ID
    ),
    "combined_interval_uncertainty_parent_model": (
        combined.REVENUE_METER_COMBINED_INTERVAL_UNCERTAINTY_MODEL_ID
    ),
}
_BOOL = (
    *(f"{prefix}_uncertainty_interpretation_resolved" for prefix, _, _, _ in _QUANTITIES),
    *(f"{c}_interval_uncertainty_interpretation_resolved" for c, _, _ in _CHANNELS),
)
_FLOAT = tuple(
    name
    for prefix, unit, _, _ in _QUANTITIES
    for name in (
        f"{prefix}_combined_uncertainty_envelope_lower_{unit}",
        f"{prefix}_combined_uncertainty_envelope_upper_{unit}",
        f"{prefix}_residual_excess_beyond_combined_uncertainty_{unit}",
    )
)
_TEXT = (
    *(f"{prefix}_uncertainty_envelope_relation" for prefix, _, _, _ in _QUANTITIES),
    *(f"{c}_interval_uncertainty_interpretation_state" for c, _, _ in _CHANNELS),
    "interval_uncertainty_interpretation_state",
    *_FIXED,
)
_EXTRA_COLUMNS = (*_BOOL, *_FLOAT, *_TEXT)


@dataclass(frozen=True)
class RevenueMeterIntervalUncertaintyInterpretationDiagnostics:
    """Availability partitions eligible rows; channel unresolved counts span all rows.

    Quantity relations count only finite, interpreted quantities. A channel needs
    both quantities, so one finite quantity may remain auditable on a failed channel.
    """

    interval_row_count: int
    benchmark_eligible_count: int
    benchmark_ineligible_count: int
    active_combined_uncertainty_available_count: int
    active_combined_uncertainty_unavailable_count: int
    reactive_combined_uncertainty_available_count: int
    reactive_combined_uncertainty_unavailable_count: int
    active_interpretation_resolved_count: int
    active_interpretation_unresolved_count: int
    reactive_interpretation_resolved_count: int
    reactive_interpretation_unresolved_count: int
    active_nonfinite_interpretation_count: int
    reactive_nonfinite_interpretation_count: int
    quantity_relation_counts: tuple[tuple[str, tuple[tuple[str, int], ...]], ...]
    state_counts: tuple[tuple[str, int], ...]
    model: str


@dataclass(frozen=True)
class RevenueMeterIntervalUncertaintyInterpretationResult:
    states: pd.DataFrame
    diagnostics: RevenueMeterIntervalUncertaintyInterpretationDiagnostics


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


def _parent(
    values: Mapping[str, Any], ma: Any, ea: Any, policies: Any
) -> combined.RevenueMeterCombinedIntervalUncertaintyResult:
    canonical = combined.resolve_revenue_meter_combined_interval_uncertainty(
        **values,
        revenue_meter_measurement_uncertainty_by_meter_id=ma,
        revenue_meter_expected_model_uncertainty_by_meter_id=ea,
        revenue_meter_interval_support_policy_by_meter_id=policies,
    )
    _replay(
        "combined interval parent", values["revenue_meter_combined_interval_uncertainty"], canonical
    )
    return canonical


def _quantity(residual: Any, bound: Any) -> tuple[str, float, float, float] | None:
    try:
        if (
            any(
                isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(v)
                for v in (residual, bound)
            )
            or bound < 0
        ):
            return None
        lower, upper = -bound, bound
        if residual > upper:
            relation = _RELATIONS[2]
        elif residual < lower:
            relation = _RELATIONS[3]
        elif residual in (lower, upper):
            relation = _RELATIONS[1]
        else:
            relation = _RELATIONS[0]
        excess = max(abs(residual) - bound, 0.0)
        if not all(math.isfinite(v) for v in (lower, upper, excess)):
            return None
        return relation, float(lower), float(upper), float(excess)
    except (OverflowError, TypeError, ValueError):
        return None


def _channel(out: dict[str, Any], row: pd.Series, channel: str) -> None:
    state = f"{channel}_interval_uncertainty_interpretation_state"
    out[state] = _UNAVAILABLE
    if not bool(row[f"{channel}_combined_interval_uncertainty_resolved"]):
        return
    out[state] = _STATES[2]
    for prefix, unit, residual, bound in _QUANTITIES:
        if not prefix.startswith(channel + "_"):
            continue
        interpreted = _quantity(row[residual], row[bound])
        if interpreted is not None:
            relation, lower, upper, excess = interpreted
            out[f"{prefix}_uncertainty_interpretation_resolved"] = True
            out[f"{prefix}_uncertainty_envelope_relation"] = relation
            out[f"{prefix}_combined_uncertainty_envelope_lower_{unit}"] = lower
            out[f"{prefix}_combined_uncertainty_envelope_upper_{unit}"] = upper
            out[f"{prefix}_residual_excess_beyond_combined_uncertainty_{unit}"] = excess
    ready = all(
        out[f"{prefix}_uncertainty_interpretation_resolved"]
        for prefix, _, _, _ in _QUANTITIES
        if prefix.startswith(channel + "_")
    )
    out[f"{channel}_interval_uncertainty_interpretation_resolved"] = ready
    if ready:
        out[state] = _RESOLVED


def _record(row: pd.Series) -> dict[str, Any]:
    out: dict[str, Any] = {
        **dict.fromkeys(_BOOL, False),
        **dict.fromkeys(_FLOAT, math.nan),
        **dict.fromkeys(_TEXT, ""),
        **_FIXED,
    }
    out["interval_uncertainty_interpretation_state"] = _STATES[0]
    for c, _, _ in _CHANNELS:
        out[f"{c}_interval_uncertainty_interpretation_state"] = _STATES[0]
    # First gate: do not even read residuals/bounds on an ineligible benchmark.
    if not bool(row["benchmark_eligible"]):
        return out
    for c, _, _ in _CHANNELS:
        _channel(out, row, c)
    p, q = (
        out[f"{c}_interval_uncertainty_interpretation_resolved"] for c in ("active", "reactive")
    )
    arithmetic = any(
        out[f"{c}_interval_uncertainty_interpretation_state"] == _STATES[2]
        for c in ("active", "reactive")
    )
    out["interval_uncertainty_interpretation_state"] = (
        _STATES[5]
        if p and q
        else _STATES[3]
        if p
        else _STATES[4]
        if q
        else _STATES[2]
        if arithmetic
        else _STATES[1]
    )
    return out


def _frame(
    parent: combined.RevenueMeterCombinedIntervalUncertaintyResult, records: list[dict[str, Any]]
) -> pd.DataFrame:
    if set(parent.states.columns).intersection(_EXTRA_COLUMNS):
        raise ValueError("interpretation schema collision")
    extra = pd.DataFrame(records, index=parent.states.index.copy(), columns=_EXTRA_COLUMNS)
    for field in _EXTRA_COLUMNS:
        extra[field] = extra[field].astype(
            bool if field in _BOOL else float if field in _FLOAT else object
        )
    return pd.concat([parent.states.copy(deep=True), extra], axis=1)


def _diagnostics(frame: pd.DataFrame) -> RevenueMeterIntervalUncertaintyInterpretationDiagnostics:
    n = len(frame)
    eligible = frame.benchmark_eligible
    counts: dict[str, Any] = {
        "interval_row_count": n,
        "benchmark_eligible_count": int(eligible.sum()),
        "benchmark_ineligible_count": int((~eligible).sum()),
    }
    for c, _, _ in _CHANNELS:
        available = frame[f"{c}_combined_interval_uncertainty_resolved"]
        resolved = int(frame[f"{c}_interval_uncertainty_interpretation_resolved"].sum())
        counts[f"{c}_combined_uncertainty_available_count"] = int((eligible & available).sum())
        counts[f"{c}_combined_uncertainty_unavailable_count"] = int((eligible & ~available).sum())
        counts[f"{c}_interpretation_resolved_count"] = resolved
        counts[f"{c}_interpretation_unresolved_count"] = n - resolved
        counts[f"{c}_nonfinite_interpretation_count"] = int(
            frame[f"{c}_interval_uncertainty_interpretation_state"].eq(_STATES[2]).sum()
        )
    counts["quantity_relation_counts"] = tuple(
        (
            prefix,
            tuple(
                (r, int(frame[f"{prefix}_uncertainty_envelope_relation"].eq(r).sum()))
                for r in _RELATIONS
            ),
        )
        for prefix, _, _, _ in _QUANTITIES
    )
    counts["state_counts"] = tuple(
        (s, int(frame.interval_uncertainty_interpretation_state.eq(s).sum())) for s in _STATES
    )
    counts["model"] = REVENUE_METER_INTERVAL_UNCERTAINTY_INTERPRETATION_MODEL_ID
    return RevenueMeterIntervalUncertaintyInterpretationDiagnostics(**counts)


def resolve_revenue_meter_interval_uncertainty_interpretation(
    *,
    revenue_meter_measurement_uncertainty_by_meter_id: Mapping[str, Any] | None = None,
    revenue_meter_expected_model_uncertainty_by_meter_id: Mapping[str, Any] | None = None,
    revenue_meter_interval_support_policy_by_meter_id: Mapping[str, Any] | None = None,
    **values: Any,
) -> RevenueMeterIntervalUncertaintyInterpretationResult:
    """Replay the supplied ``revenue_meter_combined_interval_uncertainty`` parent.

    ``values`` and the three mappings are the original inputs used by that
    parent's public resolver. Interpretation never changes those inputs.
    """
    parent = _parent(
        values,
        revenue_meter_measurement_uncertainty_by_meter_id,
        revenue_meter_expected_model_uncertainty_by_meter_id,
        revenue_meter_interval_support_policy_by_meter_id,
    )
    frame = _frame(parent, [_record(row) for _, row in parent.states.iterrows()])
    result = RevenueMeterIntervalUncertaintyInterpretationResult(frame, _diagnostics(frame))
    _validate_result(parent, result)
    return result


def _validate_result(
    parent: combined.RevenueMeterCombinedIntervalUncertaintyResult,
    result: RevenueMeterIntervalUncertaintyInterpretationResult,
) -> None:
    """Independent interpretation replay after canonical parent reconstruction."""
    if set(parent.states.columns) & set(_EXTRA_COLUMNS):
        raise ValueError("validator: interpretation schema collision")
    records: list[dict[str, Any]] = []
    counts: dict[str, Any] = {
        f.name: 0
        for f in fields(RevenueMeterIntervalUncertaintyInterpretationDiagnostics)
        if f.name not in ("quantity_relation_counts", "state_counts", "model")
    }
    relations = {prefix: {r: 0 for r in _RELATIONS} for prefix, _, _, _ in _QUANTITIES}
    states = {s: 0 for s in _STATES}
    for _, row in parent.states.iterrows():
        record: dict[str, Any] = {k: False for k in _BOOL}
        record.update({k: math.nan for k in _FLOAT})
        record.update({k: "" for k in _TEXT})
        record.update(_FIXED)
        eligible = bool(row["benchmark_eligible"])
        counts["benchmark_eligible_count" if eligible else "benchmark_ineligible_count"] += 1
        numeric_failure = False
        for c, _, _ in _CHANNELS:
            state = _STATES[0]
            complete = False
            if eligible:
                available = bool(row[f"{c}_combined_interval_uncertainty_resolved"])
                counts[
                    f"{c}_combined_uncertainty_{'available' if available else 'unavailable'}_count"
                ] += 1
                state = _UNAVAILABLE
                if available:
                    state = _STATES[2]
                    successes = 0
                    for prefix, unit, residual_field, bound_field in _QUANTITIES:
                        if not prefix.startswith(c + "_"):
                            continue
                        r, b = row[residual_field], row[bound_field]
                        try:
                            if (
                                any(
                                    isinstance(v, bool)
                                    or not isinstance(v, Real)
                                    or not math.isfinite(v)
                                    for v in (r, b)
                                )
                                or b < 0
                            ):
                                continue
                        except (OverflowError, TypeError, ValueError):
                            continue
                        magnitude = abs(r)
                        if magnitude == b:
                            relation = _RELATIONS[1]
                        elif magnitude < b:
                            relation = _RELATIONS[0]
                        else:
                            relation = _RELATIONS[2] if r > 0 else _RELATIONS[3]
                        difference = magnitude - b
                        excess = difference if difference > 0 else 0.0
                        lower, upper = -b, b
                        if any(not math.isfinite(v) for v in (lower, upper, excess)):
                            continue
                        record[f"{prefix}_uncertainty_interpretation_resolved"] = True
                        record[f"{prefix}_uncertainty_envelope_relation"] = relation
                        record[f"{prefix}_combined_uncertainty_envelope_lower_{unit}"] = float(
                            lower
                        )
                        record[f"{prefix}_combined_uncertainty_envelope_upper_{unit}"] = float(
                            upper
                        )
                        record[f"{prefix}_residual_excess_beyond_combined_uncertainty_{unit}"] = (
                            float(excess)
                        )
                        relations[prefix][relation] += 1
                        successes += 1
                    complete = successes == 2
                    if complete:
                        state = _RESOLVED
                    else:
                        numeric_failure = True
                        counts[f"{c}_nonfinite_interpretation_count"] += 1
            record[f"{c}_interval_uncertainty_interpretation_state"] = state
            record[f"{c}_interval_uncertainty_interpretation_resolved"] = complete
            counts[f"{c}_interpretation_{'resolved' if complete else 'unresolved'}_count"] += 1
        p, q = (
            record[f"{c}_interval_uncertainty_interpretation_resolved"]
            for c in ("active", "reactive")
        )
        selected = (
            _STATES[0]
            if not eligible
            else _STATES[5]
            if p and q
            else _STATES[3]
            if p
            else _STATES[4]
            if q
            else _STATES[2]
            if numeric_failure
            else _STATES[1]
        )
        record["interval_uncertainty_interpretation_state"] = selected
        states[selected] += 1
        records.append(record)
    extra = pd.DataFrame(records, index=parent.states.index.copy(), columns=_EXTRA_COLUMNS)
    for key in _EXTRA_COLUMNS:
        extra[key] = extra[key].astype(bool if key in _BOOL else float if key in _FLOAT else object)
    frame = pd.concat([parent.states.copy(deep=True), extra], axis=1)
    counts["interval_row_count"] = len(parent.states)
    counts["quantity_relation_counts"] = tuple((p, tuple(r.items())) for p, r in relations.items())
    counts["state_counts"] = tuple(states.items())
    counts["model"] = REVENUE_METER_INTERVAL_UNCERTAINTY_INTERPRETATION_MODEL_ID
    expected = RevenueMeterIntervalUncertaintyInterpretationResult(
        frame, RevenueMeterIntervalUncertaintyInterpretationDiagnostics(**counts)
    )
    _replay("interval uncertainty interpretation", result, expected)


def validate_revenue_meter_interval_uncertainty_interpretation(
    result: RevenueMeterIntervalUncertaintyInterpretationResult,
    *,
    revenue_meter_measurement_uncertainty_by_meter_id: Mapping[str, Any] | None = None,
    revenue_meter_expected_model_uncertainty_by_meter_id: Mapping[str, Any] | None = None,
    revenue_meter_interval_support_policy_by_meter_id: Mapping[str, Any] | None = None,
    **values: Any,
) -> None:
    # Independently compose the public parent: no production interpretation helper.
    canonical = combined.resolve_revenue_meter_combined_interval_uncertainty(
        **values,
        revenue_meter_measurement_uncertainty_by_meter_id=revenue_meter_measurement_uncertainty_by_meter_id,
        revenue_meter_expected_model_uncertainty_by_meter_id=revenue_meter_expected_model_uncertainty_by_meter_id,
        revenue_meter_interval_support_policy_by_meter_id=revenue_meter_interval_support_policy_by_meter_id,
    )
    _replay(
        "combined interval parent", values["revenue_meter_combined_interval_uncertainty"], canonical
    )
    _validate_result(canonical, result)
