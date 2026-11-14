"""Deterministic Method B errors against complete represented Method A references.

Explicit durations and caller policy only. Total-energy relative error is NOT
annual electrical-mismatch-loss percentage-point error. No runtime dispatch.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from numbers import Real
from typing import cast

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.physics.string_method_a import (
    METHOD_A_CONTRACT_ID,
    METHOD_A_COVERAGE_SCOPE,
    METHOD_A_MODEL_ID,
    METHOD_A_SCOPE,
    Stage4aMethodAResult,
)
from heliotelligence.physics.string_method_b import (
    METHOD_B_CONTRACT_ID,
    METHOD_B_COVERAGE_SCOPE,
    METHOD_B_MODEL_ID,
    METHOD_B_SCOPE,
    Stage4aMethodBResult,
)
from heliotelligence.physics.string_operating_classes import _detach, _same
from heliotelligence.physics.string_section_electrical_state_authority import (
    validate_section_observation_timestamp,
)

METHOD_B_VALIDATION_CONTRACT_ID = "advanced_string_method_b_against_method_a_validation_v1"
METHOD_B_VALIDATION_MODEL_ID = "explicit_snapshot_and_duration_weighted_method_b_error_metrics_v1"
METHOD_B_VALIDATION_SCOPE = "advanced_s8_method_b_validation_against_method_a_reference"
METHOD_B_VALIDATION_COVERAGE_SCOPE = (
    "shared_complete_method_a_and_method_b_string_terminal_observations"
)


@dataclass(frozen=True)
class StringMethodComparison:
    string_id: str
    method_a_power_w: float | None
    method_a_voltage_v: float | None
    method_a_current_a: float | None
    method_b_power_w: float | None
    method_b_voltage_v: float | None
    method_b_current_a: float | None
    power_error_w: float | None
    absolute_power_error_w: float | None
    relative_power_error_fraction: float | None
    voltage_error_v: float | None
    current_error_a: float | None
    selected_point_exact_match: bool
    comparison_resolved: bool
    comparison_state: str


@dataclass(frozen=True)
class MethodBSnapshotComparison:
    observation_timestamp: pd.Timestamp
    geometry_revision: str
    optical_snapshot_reference: str | None
    rows: tuple[StringMethodComparison, ...]
    compared_string_ids: tuple[str, ...]
    compared_string_count: int
    reference_unavailable_string_count: int
    method_b_unavailable_string_count: int
    method_a_power_w: float
    method_b_power_w: float
    power_error_w: float
    absolute_power_error_w: float
    relative_power_error_fraction: float | None
    comparison_complete: bool
    contract: str = METHOD_B_VALIDATION_CONTRACT_ID
    model: str = METHOD_B_VALIDATION_MODEL_ID
    scope: str = METHOD_B_VALIDATION_SCOPE
    coverage_scope: str = METHOD_B_VALIDATION_COVERAGE_SCOPE


def _relative(reference: float, actual: float) -> float | None:
    result = abs(actual - reference) / reference if reference > 0 else 0.0 if actual == 0 else None
    if result is not None and not math.isfinite(result):
        raise ValueError("unrepresentable relative error")
    return result


def _point(values: tuple[object, object, object]) -> tuple[float, float, float]:
    if any(
        isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(v) or v < 0
        for v in values
    ):
        raise ValueError("selected point must be finite nonnegative P/V/I")
    p, v, i = (float(cast(float, x)) for x in values)
    # Numerical power closure, not an approximation/admission threshold.
    if abs(p - v * i) > 1e-8 + 1e-9 * max(1.0, p):
        raise ValueError("selected point power closure failed")
    return p, v, i


def _selected(frame: pd.DataFrame, sid: str, flag: str) -> tuple[float, float, float]:
    if type(frame) is not pd.DataFrame or not {
        "string_id",
        flag,
        "power_w",
        "voltage_v",
        "current_a",
    } <= set(frame.columns):
        raise ValueError("missing selected-point columns")
    if any(type(v) is not bool for v in frame[flag].tolist()):
        raise ValueError("selection flags must be Boolean")
    rows = frame.loc[frame.string_id.eq(sid) & frame[flag]]
    if len(rows) != 1:
        raise ValueError("expected exactly one owner-selected point")
    row = rows.iloc[0]
    return _point((row.power_w, row.voltage_v, row.current_a))


def _row(
    sid: str, a: tuple[float, float, float] | None, b: tuple[float, float, float] | None
) -> StringMethodComparison:
    if a is None or b is None:
        ap, av, ai = a if a is not None else (None, None, None)
        bp, bv, bi = b if b is not None else (None, None, None)
        return StringMethodComparison(
            sid,
            ap,
            av,
            ai,
            bp,
            bv,
            bi,
            None,
            None,
            None,
            None,
            None,
            False,
            False,
            "unavailable_incomplete_method_a_reference" if a is None else "unavailable_method_b",
        )
    error = b[0] - a[0]
    relative = _relative(a[0], b[0])
    resolved = relative is not None
    return StringMethodComparison(
        sid,
        *a,
        *b,
        error,
        abs(error),
        relative,
        b[1] - a[1],
        b[2] - a[2],
        a == b,
        resolved,
        "resolved" if resolved else "unresolved_zero_reference_positive_method_b",
    )


def _snapshot(
    timestamp: pd.Timestamp,
    revision: str,
    reference: str | None,
    rows: tuple[StringMethodComparison, ...],
) -> MethodBSnapshotComparison:
    compared = tuple(
        r.string_id
        for r in rows
        if r.method_a_power_w is not None and r.method_b_power_w is not None
    )
    a = math.fsum(
        r.method_a_power_w
        for r in rows
        if r.string_id in compared and r.method_a_power_w is not None
    )
    b = math.fsum(
        r.method_b_power_w
        for r in rows
        if r.string_id in compared and r.method_b_power_w is not None
    )
    if not math.isfinite(a) or not math.isfinite(b):
        raise ValueError("nonfinite snapshot aggregate")
    return MethodBSnapshotComparison(
        timestamp,
        revision,
        reference,
        rows,
        compared,
        len(compared),
        sum(r.method_a_power_w is None for r in rows),
        sum(r.method_b_power_w is None for r in rows),
        a,
        b,
        b - a,
        abs(b - a),
        _relative(a, b),
        bool(rows) and all(r.comparison_resolved for r in rows),
    )


def compare_string_methods(
    method_a: Stage4aMethodAResult, method_b: Stage4aMethodBResult
) -> MethodBSnapshotComparison:
    """Compare selected owner points only; partial universe is explicitly labelled.

    Results must retain identical electrical/topology/reverse/diode evidence and
    optical observation. This comparison is not evidence authentication or a
    substitute for the original authority admission/replay at execution time.
    """
    if type(method_a) is not Stage4aMethodAResult or type(method_b) is not Stage4aMethodBResult:
        raise ValueError("expected canonical Method A/B results")
    for result, constants in (
        (
            method_a,
            (METHOD_A_CONTRACT_ID, METHOD_A_MODEL_ID, METHOD_A_SCOPE, METHOD_A_COVERAGE_SCOPE),
        ),
        (
            method_b,
            (METHOD_B_CONTRACT_ID, METHOD_B_MODEL_ID, METHOD_B_SCOPE, METHOD_B_COVERAGE_SCOPE),
        ),
    ):
        for field, expected in zip(
            ("contract", "model", "scope", "coverage_scope"), constants, strict=True
        ):
            _same(getattr(result, field), expected)
        validate_section_observation_timestamp(result.observation_timestamp)
        authority = result.section_electrical_state_authority
        if (
            result.observation_timestamp != authority.observation_timestamp
            or result.observation_timestamp.tz != authority.observation_timestamp.tz
            or result.geometry_revision != authority.geometry_revision
            or result.optical_snapshot_reference != authority.optical_snapshot_reference
        ):
            raise ValueError("result observation differs from electrical authority")
    if (
        method_a.observation_timestamp != method_b.observation_timestamp
        or method_a.observation_timestamp.tz != method_b.observation_timestamp.tz
        or method_a.geometry_revision != method_b.geometry_revision
        or method_a.optical_snapshot_reference != method_b.optical_snapshot_reference
    ):
        raise ValueError("Method A/B optical observation mismatch")
    _same(method_a.section_electrical_state_authority, method_b.section_electrical_state_authority)
    _same(
        method_b.string_classes.electrical_state_authority,
        method_b.section_electrical_state_authority,
    )
    source = method_a.advanced_string_candidates.source_composition
    if (
        source.reference_plane != "string_terminal"
        or method_b.composition.reference_plane != "string_terminal"
        or method_a.advanced_string_candidates.reference_plane != "string_terminal"
    ):
        raise ValueError("comparison requires the physical string_terminal reference plane")
    _same(
        source.topology_authorities_by_string_id,
        method_b.composition.topology_authorities_by_string_id,
    )
    _same(source.section_inputs_by_identity, method_b.composition.section_inputs_by_identity)
    _same(source.missing_evidence_by_string_id, method_b.composition.missing_evidence_by_string_id)
    a_states = method_a.advanced_string_candidates.states
    b_states = method_b.states
    ids = tuple(a_states.string_id)
    if ids != tuple(b_states.string_id) or len(set(ids)) != len(ids):
        raise ValueError("different physical string universes")
    if any(
        type(v) is not bool for v in a_states.search_complete.tolist() + b_states.resolved.tolist()
    ):
        raise ValueError("invalid result resolution flags")
    rows = []
    for sid, complete, b_resolved in zip(
        ids, a_states.search_complete.tolist(), b_states.resolved.tolist(), strict=True
    ):
        a = (
            _selected(method_a.advanced_string_candidates.candidates, sid, "is_selected_global")
            if complete
            else None
        )
        b = _selected(method_b.candidates, sid, "is_selected_method_b") if b_resolved else None
        rows.append(_row(sid, a, b))
    return _snapshot(
        method_a.observation_timestamp,
        method_a.geometry_revision,
        method_a.optical_snapshot_reference,
        tuple(rows),
    )


@dataclass(frozen=True)
class MethodBValidationPolicy:
    max_abs_string_relative_power_error_fraction: float
    max_abs_snapshot_relative_power_error_fraction: float
    max_abs_energy_relative_error_fraction: float
    parameter_source: str
    confidence: str
    method_reference: str
    applicability_description: str

    def __post_init__(self) -> None:
        _validate_policy(self)


def _validate_policy(policy: MethodBValidationPolicy) -> None:
    if type(policy) is not MethodBValidationPolicy:
        raise ValueError("expected exact validation policy")
    for value in (
        policy.max_abs_string_relative_power_error_fraction,
        policy.max_abs_snapshot_relative_power_error_fraction,
        policy.max_abs_energy_relative_error_fraction,
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, Real)
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError("explicit finite nonnegative policy thresholds required")
    for text in (
        policy.parameter_source,
        policy.confidence,
        policy.method_reference,
        policy.applicability_description,
    ):
        if type(text) is not str or not text or text != text.strip():
            raise ValueError("invalid policy provenance")
    if policy.confidence not in {"high", "medium", "low", "unknown"}:
        raise ValueError("unknown policy confidence")


@dataclass(frozen=True)
class MethodBEnergyValidation:
    comparisons: tuple[MethodBSnapshotComparison, ...]
    interval_duration_hours_by_timestamp: Mapping[pd.Timestamp, float]
    method_a_energy_wh: float
    method_b_energy_wh: float
    energy_error_wh: float
    absolute_energy_error_wh: float
    relative_energy_error_fraction: float | None
    max_abs_snapshot_relative_power_error_fraction: float | None
    max_abs_string_relative_power_error_fraction: float | None
    timestamp_count: int
    complete_timestamp_count: int
    comparison_complete: bool
    policy: MethodBValidationPolicy | None
    policy_state: str
    contract: str = METHOD_B_VALIDATION_CONTRACT_ID
    model: str = METHOD_B_VALIDATION_MODEL_ID
    scope: str = METHOD_B_VALIDATION_SCOPE
    coverage_scope: str = METHOD_B_VALIDATION_COVERAGE_SCOPE


def _validate_snapshot(result: MethodBSnapshotComparison) -> None:
    if type(result) is not MethodBSnapshotComparison or type(result.rows) is not tuple:
        raise ValueError("expected immutable snapshot comparison")
    validate_section_observation_timestamp(result.observation_timestamp)
    if (
        type(result.geometry_revision) is not str
        or not result.geometry_revision
        or result.geometry_revision != result.geometry_revision.strip()
    ):
        raise ValueError("comparison requires exact geometry revision")
    reference = result.optical_snapshot_reference
    if reference is not None and (
        type(reference) is not str or not reference or reference != reference.strip()
    ):
        raise ValueError("invalid comparison optical snapshot reference")
    if result.comparison_complete and reference is None:
        raise ValueError("complete comparison requires an optical observation reference")
    if any(type(row) is not StringMethodComparison for row in result.rows):
        raise ValueError("invalid comparison row type")
    if len({r.string_id for r in result.rows}) != len(result.rows):
        raise ValueError("duplicate comparison string")
    rows = []
    for r in result.rows:
        if type(r) is not StringMethodComparison:
            raise ValueError("invalid comparison row")
        if type(r.string_id) is not str or not r.string_id or r.string_id != r.string_id.strip():
            raise ValueError("invalid comparison identity")
        a = (
            None
            if r.method_a_power_w is None
            else _point((r.method_a_power_w, r.method_a_voltage_v, r.method_a_current_a))
        )
        b = (
            None
            if r.method_b_power_w is None
            else _point((r.method_b_power_w, r.method_b_voltage_v, r.method_b_current_a))
        )
        expected = _row(r.string_id, a, b)
        _same(r, expected)
        rows.append(expected)
    _same(
        result,
        _snapshot(
            result.observation_timestamp,
            result.geometry_revision,
            result.optical_snapshot_reference,
            tuple(rows),
        ),
    )


def aggregate_method_b_validation(
    comparisons: tuple[MethodBSnapshotComparison, ...],
    interval_duration_hours_by_timestamp: Mapping[pd.Timestamp, float],
    policy: MethodBValidationPolicy | None = None,
) -> MethodBEnergyValidation:
    """Explicit duration-weighted Wh; optional policy never activates a runtime.

    Powers include only each snapshot's declared comparable string subset. All
    snapshots must share the same ordered physical string universe. Incomplete
    or undefined relative references cannot certify policy, regardless of errors.
    """
    if type(comparisons) is not tuple or not comparisons:
        raise ValueError("nonempty explicit comparison tuple required")
    for result in comparisons:
        _validate_snapshot(result)
    ordered = tuple(sorted(comparisons, key=lambda r: r.observation_timestamp.value))
    timestamps = tuple(r.observation_timestamp for r in ordered)
    if len(set(timestamps)) != len(timestamps):
        raise ValueError("duplicate observation timestamp")
    universe = tuple(r.string_id for r in ordered[0].rows)
    if any(tuple(r.string_id for r in x.rows) != universe for x in ordered):
        raise ValueError("inconsistent comparison string universe")
    if not isinstance(interval_duration_hours_by_timestamp, Mapping) or len(
        interval_duration_hours_by_timestamp
    ) != len(timestamps):
        raise ValueError("exact duration coverage required")
    durations: dict[pd.Timestamp, float] = {}
    for timestamp, value in interval_duration_hours_by_timestamp.items():
        validate_section_observation_timestamp(timestamp)
        if not any(timestamp == t and timestamp.tz == t.tz for t in timestamps):
            raise ValueError("duration timestamp/timezone mismatch")
        if (
            isinstance(value, bool)
            or not isinstance(value, Real)
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError("duration must be finite positive non-Boolean hours")
        durations[timestamp] = float(value)
    a = math.fsum(x.method_a_power_w * durations[x.observation_timestamp] for x in ordered)
    b = math.fsum(x.method_b_power_w * durations[x.observation_timestamp] for x in ordered)
    if not math.isfinite(a) or not math.isfinite(b):
        raise ValueError("nonfinite energy accumulation")
    energy_relative = _relative(a, b)
    complete = all(x.comparison_complete for x in ordered) and energy_relative is not None
    snapshot_errors = [x.relative_power_error_fraction for x in ordered]
    string_errors = [r.relative_power_error_fraction for x in ordered for r in x.rows]
    snapshot_max = max(v for v in snapshot_errors if v is not None) if complete else None
    string_max = max(v for v in string_errors if v is not None) if complete else None
    state = "not_evaluated_no_policy"
    if policy is not None:
        _validate_policy(policy)
        if not complete:
            state = "unresolved_incomplete_reference"
        else:
            assert (
                energy_relative is not None and snapshot_max is not None and string_max is not None
            )
            inside = (
                string_max <= policy.max_abs_string_relative_power_error_fraction
                and snapshot_max <= policy.max_abs_snapshot_relative_power_error_fraction
                and energy_relative <= policy.max_abs_energy_relative_error_fraction
            )
            state = "resolved_within_policy" if inside else "resolved_outside_policy"
    return MethodBEnergyValidation(
        _detach(ordered),
        _detach({t: durations[t] for t in timestamps}),
        a,
        b,
        b - a,
        abs(b - a),
        energy_relative,
        snapshot_max,
        string_max,
        len(ordered),
        sum(x.comparison_complete for x in ordered),
        complete,
        replace(policy) if policy is not None else None,
        state,
    )
