"""Dormant deterministic bounds through the exact discrete S14B functional.

Numerical evidence remains owned by the pointwise expected-model parent. This
layer never recalculates its bound or quantifies sparse-support/continuous-path
error. S14B benchmark eligibility is orthogonal to mathematical propagation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.physics import revenue_meter_expected_model_uncertainty as pointwise
from heliotelligence.physics import revenue_meter_interval_benchmark as s14b
from heliotelligence.physics.revenue_meter_interval_support_policy import (
    RevenueMeterIntervalSupportPolicyAuthority,
)

REVENUE_METER_EXPECTED_MODEL_INTERVAL_UNCERTAINTY_CONTRACT_ID = (
    "admitted_s14b_and_pointwise_expected_model_uncertainty_to_exact_interval_"
    "expected_model_uncertainty_state_v1"
)
REVENUE_METER_EXPECTED_MODEL_INTERVAL_UNCERTAINTY_MODEL_ID = (
    "deterministic_worst_case_trapezoidal_propagation_of_pointwise_symmetric_"
    "expected_model_bounds_v1"
)
REVENUE_METER_EXPECTED_MODEL_INTERVAL_UNCERTAINTY_SCOPE = (
    "exact_s14b_reconstructed_interval_expected_model_uncertainty_before_measurement_combination"
)
PROPAGATION_SEMANTICS = (
    "deterministic_worst_case_positive_trapezoidal_weight_propagation_no_probability_or_covariance"
)
WEIGHT_BASIS = (
    "sum_of_nonnegative_s14b_trapezoidal_weights_times_pointwise_symmetric_bound_magnitudes"
)
SUPPORT_ALIGNMENT_SEMANTICS = (
    "exact_canonical_s14b_support_timestamps_no_substitution_or_synthetic_support"
)
COVERAGE_LIMITATION = (
    "uncertainty_of_s14b_discrete_reconstructed_expected_path_not_support_gap_"
    "or_continuous_physical_truth"
)
_CHANNELS = (("active", "w", "wh"), ("reactive", "var", "varh"))
_STATES = (
    "unresolved_s14b_expected_interval_reconstruction",
    "unresolved_incomplete_active_reactive_pointwise_expected_model_uncertainty_support",
    "unresolved_nonfinite_expected_model_interval_uncertainty_arithmetic",
    "resolved_active_expected_model_interval_uncertainty_only",
    "resolved_reactive_expected_model_interval_uncertainty_only",
    "resolved_active_reactive_expected_model_interval_uncertainty",
)
_FIXED = {
    "expected_model_interval_uncertainty_contract": (
        REVENUE_METER_EXPECTED_MODEL_INTERVAL_UNCERTAINTY_CONTRACT_ID
    ),
    "expected_model_interval_uncertainty_model": (
        REVENUE_METER_EXPECTED_MODEL_INTERVAL_UNCERTAINTY_MODEL_ID
    ),
    "expected_model_interval_uncertainty_scope": (
        REVENUE_METER_EXPECTED_MODEL_INTERVAL_UNCERTAINTY_SCOPE
    ),
    "expected_model_interval_propagation_semantics": PROPAGATION_SEMANTICS,
    "expected_model_interval_weight_basis": WEIGHT_BASIS,
    "expected_model_interval_support_alignment_semantics": SUPPORT_ALIGNMENT_SEMANTICS,
    "expected_model_interval_coverage_limitation": COVERAGE_LIMITATION,
    "pointwise_expected_model_parent_contract": (
        pointwise.REVENUE_METER_EXPECTED_MODEL_UNCERTAINTY_CONTRACT_ID
    ),
    "pointwise_expected_model_parent_model": (
        pointwise.REVENUE_METER_EXPECTED_MODEL_UNCERTAINTY_MODEL_ID
    ),
    "s14b_parent_contract": s14b.REVENUE_METER_INTERVAL_BENCHMARK_CONTRACT_ID,
    "s14b_parent_model": s14b.REVENUE_METER_INTERVAL_BENCHMARK_MODEL_ID,
}
_BOOL = (
    "pointwise_expected_model_support_assessed",
    *(f"{c}_pointwise_expected_model_uncertainty_support_complete" for c, _, _ in _CHANNELS),
    *(f"{c}_expected_model_interval_uncertainty_resolved" for c, _, _ in _CHANNELS),
)
_INT = tuple(
    field
    for c, _, _ in _CHANNELS
    for field in (
        f"{c}_resolved_pointwise_uncertainty_support_count",
        f"{c}_unresolved_pointwise_uncertainty_support_count",
    )
)
_FLOAT = tuple(
    field
    for c, power, energy in _CHANNELS
    for field in (
        f"{c}_energy_expected_model_uncertainty_bound_{energy}",
        f"expected_{c}_energy_lower_bound_{energy}",
        f"expected_{c}_energy_upper_bound_{energy}",
        f"{c}_interval_average_power_expected_model_uncertainty_bound_{power}",
        f"expected_interval_average_{c}_power_lower_bound_{power}",
        f"expected_interval_average_{c}_power_upper_bound_{power}",
    )
)
_TUPLE = tuple(
    f"unresolved_{c}_pointwise_expected_model_support_timestamps" for c, _, _ in _CHANNELS
)
_TEXT = (
    "expected_model_interval_uncertainty_state",
    *(f"{c}_expected_model_interval_uncertainty_state" for c, _, _ in _CHANNELS),
    *_FIXED,
)
_EXTRA_COLUMNS = (*_BOOL, *_INT, *_FLOAT, *_TUPLE, *_TEXT)


@dataclass(frozen=True)
class RevenueMeterExpectedModelIntervalUncertaintyDiagnostics:
    """Coverage partitions follow reconstruction; eligibility counts are orthogonal."""

    interval_row_count: int
    reconstruction_resolved_count: int
    reconstruction_unresolved_count: int
    active_support_complete_count: int
    active_support_incomplete_count: int
    reactive_support_complete_count: int
    reactive_support_incomplete_count: int
    active_interval_uncertainty_resolved_count: int
    active_interval_uncertainty_unresolved_count: int
    reactive_interval_uncertainty_resolved_count: int
    reactive_interval_uncertainty_unresolved_count: int
    support_policy_eligible_count: int
    support_policy_ineligible_count: int
    benchmark_eligible_count: int
    benchmark_ineligible_count: int
    pointwise_support_snapshot_row_count: int
    state_counts: tuple[tuple[str, int], ...]
    model: str


@dataclass(frozen=True)
class RevenueMeterExpectedModelIntervalUncertaintyResult:
    states: pd.DataFrame
    pointwise_support_states: pd.DataFrame
    diagnostics: RevenueMeterExpectedModelIntervalUncertaintyDiagnostics


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


def _parents(values: Mapping[str, Any], point_authorities: Any, policies: Any) -> tuple[Any, Any]:
    benchmark = s14b.calculate_topology_revenue_meter_interval_benchmark(
        **values, revenue_meter_interval_support_policy_by_meter_id=policies
    )
    _replay("S14B", values["revenue_meter_interval_benchmark"], benchmark)
    bounds = pointwise.resolve_topology_revenue_meter_expected_model_uncertainty(
        **values, revenue_meter_expected_model_uncertainty_by_meter_id=point_authorities
    )
    _replay(
        "pointwise expected-model uncertainty",
        values["revenue_meter_expected_model_uncertainty"],
        bounds,
    )
    return benchmark, bounds


def _support(
    row: pd.Series, meter: str, bounds: Any
) -> tuple[tuple[pd.Timestamp, ...], list[pd.Series]]:
    times = row.expected_interval_sample_timestamps
    if type(times) is not tuple or len(times) < 2:
        raise ValueError("resolved S14B reconstruction lacks exact support tuple")
    samples = []
    for timestamp in times:
        if type(timestamp) is not pd.Timestamp or pd.isna(timestamp):
            raise ValueError("invalid S14B support identity")
        key = (timestamp, meter)
        if key not in bounds.states.index:
            raise ValueError("canonical parents disagree on exact S13C support universe")
        samples.append(bounds.states.loc[key])
    return times, samples


def _propagate(
    times: tuple[pd.Timestamp, ...],
    magnitudes: tuple[float, ...],
    seconds: float,
    central_energy: float,
    central_average: float,
) -> tuple[float, ...] | None:
    try:
        hours = seconds / 3600.0
        if (
            len(times) < 2
            or len(times) != len(magnitudes)
            or not math.isfinite(hours)
            or hours <= 0
        ):
            return None
        if any(not math.isfinite(b) or b < 0 for b in magnitudes):
            return None
        terms = []
        for i in range(len(times) - 1):
            elapsed = (times[i + 1] - times[i]).value / 1_000_000_000.0
            if not math.isfinite(elapsed) or elapsed <= 0:
                return None
            term = (magnitudes[i] / 2.0 + magnitudes[i + 1] / 2.0) * (elapsed / 3600.0)
            if not math.isfinite(term):
                return None
            terms.append(term)
        energy = math.fsum(terms)
        average = energy / hours
        numbers = (
            energy,
            central_energy - energy,
            central_energy + energy,
            average,
            central_average - average,
            central_average + average,
        )
        return numbers if all(math.isfinite(v) for v in numbers) else None
    except (OverflowError, ValueError, TypeError, ZeroDivisionError):
        return None


def _channel(
    out: dict[str, Any],
    row: pd.Series,
    times: tuple[pd.Timestamp, ...],
    samples: list[pd.Series],
    channel: str,
    power: str,
    energy: str,
) -> None:
    missing = []
    magnitudes = []
    for timestamp, sample in zip(times, samples, strict=True):
        magnitude = float(sample[f"{channel}_power_expected_model_uncertainty_bound_{power}"])
        if (
            not bool(sample[f"{channel}_power_expected_model_uncertainty_resolved"])
            or not math.isfinite(magnitude)
            or magnitude < 0
        ):
            missing.append(timestamp)
        magnitudes.append(magnitude)
    out[f"unresolved_{channel}_pointwise_expected_model_support_timestamps"] = tuple(missing)
    out[f"{channel}_resolved_pointwise_uncertainty_support_count"] = len(times) - len(missing)
    out[f"{channel}_unresolved_pointwise_uncertainty_support_count"] = len(missing)
    out[f"{channel}_pointwise_expected_model_uncertainty_support_complete"] = not missing
    state_field = f"{channel}_expected_model_interval_uncertainty_state"
    out[state_field] = (
        f"unresolved_incomplete_{channel}_pointwise_expected_model_uncertainty_support"
    )
    if missing:
        return
    numbers = _propagate(
        times,
        tuple(magnitudes),
        float(row.averaging_interval_seconds),
        float(row[f"expected_{channel}_energy_{energy}"]),
        float(row[f"expected_interval_average_{channel}_power_{power}"]),
    )
    out[state_field] = _STATES[2]
    if numbers is not None:
        names = (
            f"{channel}_energy_expected_model_uncertainty_bound_{energy}",
            f"expected_{channel}_energy_lower_bound_{energy}",
            f"expected_{channel}_energy_upper_bound_{energy}",
            f"{channel}_interval_average_power_expected_model_uncertainty_bound_{power}",
            f"expected_interval_average_{channel}_power_lower_bound_{power}",
            f"expected_interval_average_{channel}_power_upper_bound_{power}",
        )
        out.update(dict(zip(names, numbers, strict=True)))
        out[f"{channel}_expected_model_interval_uncertainty_resolved"] = True
        out[state_field] = f"resolved_{channel}_expected_model_interval_uncertainty"


def _record(meter: str, row: pd.Series, bounds: Any) -> dict[str, Any]:
    out: dict[str, Any] = dict.fromkeys(_BOOL, False)
    out.update(dict.fromkeys(_INT, 0))
    out.update(dict.fromkeys(_FLOAT, math.nan))
    out.update(dict.fromkeys(_TUPLE, ()))
    out.update(dict.fromkeys(_TEXT, ""))
    out.update(_FIXED)
    state = _STATES[0]
    for channel, _, _ in _CHANNELS:
        out[f"{channel}_expected_model_interval_uncertainty_state"] = state
    if bool(row.expected_interval_reconstruction_resolved):
        times, samples = _support(row, meter, bounds)
        out["pointwise_expected_model_support_assessed"] = True
        for channel, power, energy in _CHANNELS:
            _channel(out, row, times, samples, channel, power, energy)
        p, q = (
            out[f"{c}_expected_model_interval_uncertainty_resolved"] for c in ("active", "reactive")
        )
        state = (
            _STATES[5]
            if p and q
            else _STATES[3]
            if p
            else _STATES[4]
            if q
            else (
                _STATES[2]
                if any(
                    out[f"{c}_expected_model_interval_uncertainty_state"] == _STATES[2]
                    for c in ("active", "reactive")
                )
                else _STATES[1]
            )
        )
    out["expected_model_interval_uncertainty_state"] = state
    return out


def _support_snapshot(benchmark: Any, bounds: Any) -> pd.DataFrame:
    wanted = {
        (t, meter)
        for (_, meter), row in benchmark.states.iterrows()
        for t in row.expected_interval_sample_timestamps
    }
    if not wanted.issubset(set(bounds.states.index)):
        raise ValueError("canonical pointwise support row missing")
    return bounds.states.loc[[key in wanted for key in bounds.states.index]].copy(deep=True)


def _frame(benchmark: Any, rows: list[dict[str, Any]]) -> pd.DataFrame:
    original = benchmark.states
    if set(original.columns).intersection(_EXTRA_COLUMNS):
        raise ValueError("interval uncertainty schema collides with S14B")
    extra = pd.DataFrame(index=original.index.copy())
    for field in _EXTRA_COLUMNS:
        kind = (
            bool
            if field in _BOOL
            else int
            if field in _INT
            else float
            if field in _FLOAT
            else object
        )
        extra[field] = pd.Series([r[field] for r in rows], index=original.index, dtype=kind)
    return pd.concat([original.copy(deep=True), extra], axis=1)


def _diagnostics(
    frame: pd.DataFrame, snapshot: pd.DataFrame
) -> RevenueMeterExpectedModelIntervalUncertaintyDiagnostics:
    n = len(frame)
    reconstructed = frame.expected_interval_reconstruction_resolved
    ac = reconstructed & frame.active_pointwise_expected_model_uncertainty_support_complete
    qc = reconstructed & frame.reactive_pointwise_expected_model_uncertainty_support_complete
    p = int(frame.active_expected_model_interval_uncertainty_resolved.sum())
    q = int(frame.reactive_expected_model_interval_uncertainty_resolved.sum())
    eligible = int(frame.expected_interval_support_eligible.sum())
    benchmark = int(frame.benchmark_eligible.sum())
    return RevenueMeterExpectedModelIntervalUncertaintyDiagnostics(
        n,
        int(reconstructed.sum()),
        n - int(reconstructed.sum()),
        int(ac.sum()),
        int((reconstructed & ~ac).sum()),
        int(qc.sum()),
        int((reconstructed & ~qc).sum()),
        p,
        n - p,
        q,
        n - q,
        eligible,
        n - eligible,
        benchmark,
        n - benchmark,
        len(snapshot),
        tuple(
            (state, int(frame.expected_model_interval_uncertainty_state.eq(state).sum()))
            for state in _STATES
        ),
        REVENUE_METER_EXPECTED_MODEL_INTERVAL_UNCERTAINTY_MODEL_ID,
    )


def resolve_revenue_meter_expected_model_interval_uncertainty(
    *,
    revenue_meter_expected_model_uncertainty_by_meter_id: Mapping[
        str, pointwise.RevenueMeterExpectedModelUncertaintyAuthority
    ]
    | None = None,
    revenue_meter_interval_support_policy_by_meter_id: Mapping[
        str, RevenueMeterIntervalSupportPolicyAuthority
    ]
    | None = None,
    **values: Any,
) -> RevenueMeterExpectedModelIntervalUncertaintyResult:
    """Replay both parents from original inputs/maps, then propagate published bounds.

    Supplied result keys are ``revenue_meter_interval_benchmark`` and
    ``revenue_meter_expected_model_uncertainty``. No numerical authority is added.
    """
    benchmark, bounds = _parents(
        values,
        revenue_meter_expected_model_uncertainty_by_meter_id,
        revenue_meter_interval_support_policy_by_meter_id,
    )
    rows = [_record(meter, row, bounds) for (_, meter), row in benchmark.states.iterrows()]
    states = _frame(benchmark, rows)
    snapshot = _support_snapshot(benchmark, bounds)
    result = RevenueMeterExpectedModelIntervalUncertaintyResult(
        states, snapshot, _diagnostics(states, snapshot)
    )
    _validate_result(benchmark, bounds, result)
    return result


# Independent validator: never calls production composition, support selection,
# channel propagation, record/frame construction, snapshot or diagnostics helpers.
def _validator_parents(
    values: Mapping[str, Any], point_authorities: Any, policies: Any
) -> tuple[Any, Any]:
    interval = s14b.calculate_topology_revenue_meter_interval_benchmark(
        **values, revenue_meter_interval_support_policy_by_meter_id=policies
    )
    _replay("S14B", values["revenue_meter_interval_benchmark"], interval)
    point = pointwise.resolve_topology_revenue_meter_expected_model_uncertainty(
        **values, revenue_meter_expected_model_uncertainty_by_meter_id=point_authorities
    )
    _replay(
        "pointwise expected-model uncertainty",
        values["revenue_meter_expected_model_uncertainty"],
        point,
    )
    return interval, point


def _validator_record(meter: str, central: pd.Series, point: Any) -> dict[str, Any]:
    record: dict[str, Any] = {field: False for field in _BOOL}
    record.update({field: 0 for field in _INT})
    record.update({field: math.nan for field in _FLOAT})
    record.update({field: () for field in _TUPLE})
    record.update({field: "" for field in _TEXT})
    record.update(_FIXED)
    state = "unresolved_s14b_expected_interval_reconstruction"
    for channel, _, _ in _CHANNELS:
        record[f"{channel}_expected_model_interval_uncertainty_state"] = state
    if central.expected_interval_reconstruction_resolved:
        record["pointwise_expected_model_support_assessed"] = True
        times = central.expected_interval_sample_timestamps
        if type(times) is not tuple or len(times) < 2:
            raise ValueError("validator requires exact reconstructed support")
        for channel, unit, energy_unit in _CHANNELS:
            gaps = []
            limits = []
            for timestamp in times:
                if type(timestamp) is not pd.Timestamp or pd.isna(timestamp):
                    raise ValueError("validator support identity invalid")
                if (timestamp, meter) not in point.states.index:
                    raise ValueError("validator exact pointwise support missing")
                sample = point.states.loc[(timestamp, meter)]
                limit = float(sample[f"{channel}_power_expected_model_uncertainty_bound_{unit}"])
                if (
                    not sample[f"{channel}_power_expected_model_uncertainty_resolved"]
                    or not math.isfinite(limit)
                    or limit < 0
                ):
                    gaps.append(timestamp)
                limits.append(limit)
            record[f"unresolved_{channel}_pointwise_expected_model_support_timestamps"] = tuple(
                gaps
            )
            record[f"{channel}_resolved_pointwise_uncertainty_support_count"] = len(times) - len(
                gaps
            )
            record[f"{channel}_unresolved_pointwise_uncertainty_support_count"] = len(gaps)
            record[f"{channel}_pointwise_expected_model_uncertainty_support_complete"] = not gaps
            field = f"{channel}_expected_model_interval_uncertainty_state"
            record[field] = (
                f"unresolved_incomplete_{channel}_pointwise_expected_model_uncertainty_support"
            )
            if gaps:
                continue
            record[field] = "unresolved_nonfinite_expected_model_interval_uncertainty_arithmetic"
            try:
                duration_hours = float(central.averaging_interval_seconds) / 3600.0
                terms = []
                valid = math.isfinite(duration_hours) and duration_hours > 0
                for i in range(1, len(times)):
                    seconds = (times[i] - times[i - 1]).value / 1e9
                    valid = valid and math.isfinite(seconds) and seconds > 0
                    term = (limits[i - 1] / 2.0 + limits[i] / 2.0) * (seconds / 3600.0)
                    valid = valid and math.isfinite(term)
                    terms.append(term)
                total = math.fsum(terms)
                average = total / duration_hours
                ce = float(central[f"expected_{channel}_energy_{energy_unit}"])
                cp = float(central[f"expected_interval_average_{channel}_power_{unit}"])
                lower_energy, upper_energy = ce - total, ce + total
                lower_average, upper_average = cp - average, cp + average
                valid = valid and all(
                    math.isfinite(v)
                    for v in (
                        total,
                        average,
                        lower_energy,
                        upper_energy,
                        lower_average,
                        upper_average,
                    )
                )
            except (OverflowError, TypeError, ValueError, ZeroDivisionError):
                valid = False
            if valid:
                record[f"{channel}_energy_expected_model_uncertainty_bound_{energy_unit}"] = total
                record[f"expected_{channel}_energy_lower_bound_{energy_unit}"] = lower_energy
                record[f"expected_{channel}_energy_upper_bound_{energy_unit}"] = upper_energy
                record[
                    f"{channel}_interval_average_power_expected_model_uncertainty_bound_{unit}"
                ] = average
                record[f"expected_interval_average_{channel}_power_lower_bound_{unit}"] = (
                    lower_average
                )
                record[f"expected_interval_average_{channel}_power_upper_bound_{unit}"] = (
                    upper_average
                )
                record[f"{channel}_expected_model_interval_uncertainty_resolved"] = True
                record[field] = f"resolved_{channel}_expected_model_interval_uncertainty"
        a = record["active_expected_model_interval_uncertainty_resolved"]
        r = record["reactive_expected_model_interval_uncertainty_resolved"]
        if a and r:
            state = "resolved_active_reactive_expected_model_interval_uncertainty"
        elif a:
            state = "resolved_active_expected_model_interval_uncertainty_only"
        elif r:
            state = "resolved_reactive_expected_model_interval_uncertainty_only"
        elif any(
            record[f"{c}_expected_model_interval_uncertainty_state"] == _STATES[2]
            for c in ("active", "reactive")
        ):
            state = "unresolved_nonfinite_expected_model_interval_uncertainty_arithmetic"
        else:
            state = (
                "unresolved_incomplete_active_reactive_pointwise_expected_model_uncertainty_support"
            )
    record["expected_model_interval_uncertainty_state"] = state
    return record


def _validator_frames(interval: Any, point: Any) -> tuple[pd.DataFrame, pd.DataFrame]:
    original = interval.states
    if set(original.columns) & set(_EXTRA_COLUMNS):
        raise ValueError("validator schema collision")
    records = [_validator_record(meter, row, point) for (_, meter), row in original.iterrows()]
    columns = {}
    for field in _EXTRA_COLUMNS:
        dtype = (
            bool
            if field in _BOOL
            else int
            if field in _INT
            else float
            if field in _FLOAT
            else object
        )
        columns[field] = pd.Series([r[field] for r in records], index=original.index, dtype=dtype)
    states = pd.concat(
        [original.copy(deep=True), pd.DataFrame(columns, index=original.index)], axis=1
    )
    selected = set()
    for (_, meter), row in original.iterrows():
        for timestamp in row.expected_interval_sample_timestamps:
            selected.add((timestamp, meter))
    if selected.difference(point.states.index):
        raise ValueError("validator canonical parent support universe disagrees")
    snapshot = point.states.iloc[
        [i for i, key in enumerate(point.states.index) if key in selected]
    ].copy(deep=True)
    return states, snapshot


def _validator_diagnostics(
    frame: pd.DataFrame, snapshot: pd.DataFrame
) -> RevenueMeterExpectedModelIntervalUncertaintyDiagnostics:
    rows = len(frame.index)
    ready = frame["expected_interval_reconstruction_resolved"].astype(bool)
    a = ready & frame["active_pointwise_expected_model_uncertainty_support_complete"]
    q = ready & frame["reactive_pointwise_expected_model_uncertainty_support_complete"]
    ar = int(frame["active_expected_model_interval_uncertainty_resolved"].sum())
    qr = int(frame["reactive_expected_model_interval_uncertainty_resolved"].sum())
    policy = int(frame["expected_interval_support_eligible"].sum())
    eligible = int(frame["benchmark_eligible"].sum())
    return RevenueMeterExpectedModelIntervalUncertaintyDiagnostics(
        interval_row_count=rows,
        reconstruction_resolved_count=int(ready.sum()),
        reconstruction_unresolved_count=int((~ready).sum()),
        active_support_complete_count=int(a.sum()),
        active_support_incomplete_count=int((ready & ~a).sum()),
        reactive_support_complete_count=int(q.sum()),
        reactive_support_incomplete_count=int((ready & ~q).sum()),
        active_interval_uncertainty_resolved_count=ar,
        active_interval_uncertainty_unresolved_count=rows - ar,
        reactive_interval_uncertainty_resolved_count=qr,
        reactive_interval_uncertainty_unresolved_count=rows - qr,
        support_policy_eligible_count=policy,
        support_policy_ineligible_count=rows - policy,
        benchmark_eligible_count=eligible,
        benchmark_ineligible_count=rows - eligible,
        pointwise_support_snapshot_row_count=len(snapshot),
        state_counts=tuple(
            (name, int((frame["expected_model_interval_uncertainty_state"] == name).sum()))
            for name in _STATES
        ),
        model=REVENUE_METER_EXPECTED_MODEL_INTERVAL_UNCERTAINTY_MODEL_ID,
    )


def _validate_result(
    interval: Any, point: Any, result: RevenueMeterExpectedModelIntervalUncertaintyResult
) -> None:
    if type(result) is not RevenueMeterExpectedModelIntervalUncertaintyResult:
        raise ValueError("exact interval model uncertainty result required")
    states, snapshot = _validator_frames(interval, point)
    _replay("interval expected-model uncertainty", result.states, states)
    _replay("exact pointwise support provenance", result.pointwise_support_states, snapshot)
    _replay(
        "interval model uncertainty diagnostics",
        result.diagnostics,
        _validator_diagnostics(states, snapshot),
    )


def validate_revenue_meter_expected_model_interval_uncertainty(
    result: RevenueMeterExpectedModelIntervalUncertaintyResult,
    *,
    revenue_meter_expected_model_uncertainty_by_meter_id: Mapping[
        str, pointwise.RevenueMeterExpectedModelUncertaintyAuthority
    ]
    | None = None,
    revenue_meter_interval_support_policy_by_meter_id: Mapping[
        str, RevenueMeterIntervalSupportPolicyAuthority
    ]
    | None = None,
    **values: Any,
) -> None:
    """Independent parent replay and propagation reconstruction, never production helpers."""
    interval, point = _validator_parents(
        values,
        revenue_meter_expected_model_uncertainty_by_meter_id,
        revenue_meter_interval_support_policy_by_meter_id,
    )
    _validate_result(interval, point, result)
