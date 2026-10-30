"""Dormant pointwise complete-model bounds around canonical S13C meter P/Q.

No measurement-uncertainty or S14 dependency, component recombination, interval
propagation, probability interpretation or runtime activation is implemented.
The supplied envelope is already a complete-chain deterministic maximum bound.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from numbers import Real
from types import MappingProxyType
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.physics.mv_hv_network_authority import resolve_topology_mv_hv_network_authority
from heliotelligence.physics.mv_hv_operating_solution import (
    calculate_topology_mv_hv_operating_solution,
)

REVENUE_METER_EXPECTED_MODEL_UNCERTAINTY_AUTHORITY_CONTRACT_ID = (
    "explicit_complete_expected_model_chain_quantitative_uncertainty_authority_v1"
)
REVENUE_METER_EXPECTED_MODEL_UNCERTAINTY_CONTRACT_ID = (
    "admitted_s13a_s13c_and_expected_model_uncertainty_authority_to_timestamped_"
    "revenue_meter_expected_model_uncertainty_state_v1"
)
REVENUE_METER_EXPECTED_MODEL_UNCERTAINTY_MODEL_ID = (
    "explicit_complete_chain_symmetric_pq_expected_model_uncertainty_bound_evaluation_v1"
)
REVENUE_METER_EXPECTED_MODEL_UNCERTAINTY_SCOPE = (
    "timestamped_revenue_meter_expected_model_quantitative_uncertainty_before_"
    "interval_propagation_and_measurement_combination"
)
UNCERTAINTY_INTERPRETATION = "symmetric_maximum_absolute_error_bound"
RELATIVE_ERROR_REFERENCE_BASIS = "absolute_same_channel_expected_power_in_primary_engineering_units"
COMBINATION_BASIS = (
    "explicit_complete_expected_model_chain_bound_no_internal_component_recombination"
)
MODEL_CHAIN_SCOPE = "complete_expected_model_chain_at_canonical_s13c_revenue_meter_boundary_pq"
EXPECTED_TIME_SEMANTICS = "instantaneous_steady_state_solution_at_exact_timestamp"
_EVIDENCE = frozenset(
    {
        "validated_complete_model_chain_bound",
        "engineering_uncertainty_budget",
        "other_explicit",
    }
)
_SEMANTICS = (
    "uncertainty_interpretation",
    "relative_error_reference_basis",
    "combination_basis",
    "model_chain_scope",
    "expected_time_semantics",
)
_PROVENANCE = (
    "evidence_kind",
    "parameter_source",
    "confidence",
    "method_reference",
    "applicability_description",
)
_OPTIONAL = ("external_model_reference", "external_model_version", "external_study_reference")
_VALIDITY = ("valid_from_timestamp", "valid_to_timestamp")
_CHANNELS = (
    ("active", "w", "expected_p_at_revenue_meter_w"),
    ("reactive", "var", "expected_q_at_revenue_meter_var"),
)
_AUTHORITY_NUMBERS = tuple(
    field
    for channel, unit, _ in _CHANNELS
    for field in (
        f"{channel}_power_relative_error_bound_fraction",
        f"{channel}_power_absolute_error_bound_{unit}",
    )
)
_STATES = (
    "unresolved_missing_s13c_expected_power_state",
    "unresolved_s13c_expected_operating_solution",
    "unresolved_missing_expected_model_uncertainty_authority",
    "unresolved_expected_model_uncertainty_temporal_validity",
    "resolved_active_power_expected_model_uncertainty_only",
    "resolved_reactive_power_expected_model_uncertainty_only",
    "resolved_active_reactive_expected_model_uncertainty",
    "unresolved_nonfinite_expected_model_uncertainty_arithmetic",
)
_FIXED = {
    "expected_model_uncertainty_authority_contract": (
        REVENUE_METER_EXPECTED_MODEL_UNCERTAINTY_AUTHORITY_CONTRACT_ID
    ),
    "expected_model_uncertainty_contract": REVENUE_METER_EXPECTED_MODEL_UNCERTAINTY_CONTRACT_ID,
    "expected_model_uncertainty_model": REVENUE_METER_EXPECTED_MODEL_UNCERTAINTY_MODEL_ID,
    "expected_model_uncertainty_scope": REVENUE_METER_EXPECTED_MODEL_UNCERTAINTY_SCOPE,
    "expected_power_reference_plane": "revenue_meter_boundary",
    "expected_power_value_basis": "primary_engineering_units_at_revenue_meter_boundary",
}
_BOOL = (
    "expected_power_state_present",
    "expected_power_state_resolved",
    "expected_model_uncertainty_authority_present",
    "expected_model_uncertainty_temporally_applicable",
    *(f"{channel}_power_expected_model_uncertainty_resolved" for channel, _, _ in _CHANNELS),
)
_FLOAT = tuple(
    field
    for channel, unit, _ in _CHANNELS
    for field in (
        f"{channel}_power_relative_error_bound_fraction",
        f"{channel}_power_absolute_error_bound_{unit}",
        f"{channel}_power_relative_uncertainty_component_{unit}",
        f"{channel}_power_absolute_uncertainty_component_{unit}",
        f"{channel}_power_expected_model_uncertainty_bound_{unit}",
        f"expected_{channel}_power_lower_bound_{unit}",
        f"expected_{channel}_power_upper_bound_{unit}",
    )
)
_TEXT = (
    "expected_model_uncertainty_state",
    *_SEMANTICS,
    *("model_uncertainty_" + field for field in _PROVENANCE),
    *_FIXED,
    *(f"{channel}_power_expected_model_uncertainty_state" for channel, _, _ in _CHANNELS),
)
_EXTRA_COLUMNS = (*_BOOL, *_FLOAT, *_TEXT, *_VALIDITY, *_OPTIONAL)


def _text(value: object, label: str) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{label} must be an exact non-empty unpadded string")


def _number(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be real and non-Boolean")
    try:
        valid = math.isfinite(float(value)) and float(value) >= 0
    except (OverflowError, ValueError):
        valid = False
    if not valid:
        raise ValueError(f"{label} must be finite and non-negative")


@dataclass(frozen=True)
class RevenueMeterExpectedModelUncertaintyAuthority:
    """Already-combined complete-chain bound; no component budget is inferred.

    Relative terms attest to the same expected P/Q magnitude in primary units.
    Other reference bases need external conversion and its explicit provenance.
    Validity is inclusive at the exact instantaneous S13C solution timestamp.
    """

    active_power_relative_error_bound_fraction: float | None
    active_power_absolute_error_bound_w: float | None
    reactive_power_relative_error_bound_fraction: float | None
    reactive_power_absolute_error_bound_var: float | None
    uncertainty_interpretation: str
    relative_error_reference_basis: str
    combination_basis: str
    model_chain_scope: str
    expected_time_semantics: str
    evidence_kind: str
    parameter_source: str
    confidence: str
    method_reference: str
    applicability_description: str
    valid_from_timestamp: pd.Timestamp | None = None
    valid_to_timestamp: pd.Timestamp | None = None
    external_model_reference: str | None = None
    external_model_version: str | None = None
    external_study_reference: str | None = None

    def __post_init__(self) -> None:
        represented = False
        for field in _AUTHORITY_NUMBERS:
            value = getattr(self, field)
            if value is not None:
                _number(value, field)
                represented = True
        if not represented:
            raise ValueError("at least one explicit P/Q numerical uncertainty term required")
        for field in (*_SEMANTICS, *_PROVENANCE):
            _text(getattr(self, field), field)
        if (
            self.uncertainty_interpretation != UNCERTAINTY_INTERPRETATION
            or self.relative_error_reference_basis != RELATIVE_ERROR_REFERENCE_BASIS
            or self.combination_basis != COMBINATION_BASIS
            or self.model_chain_scope != MODEL_CHAIN_SCOPE
            or self.expected_time_semantics != EXPECTED_TIME_SEMANTICS
        ):
            raise ValueError("unsupported complete-model bound/reference/time semantics")
        if self.evidence_kind not in _EVIDENCE:
            raise ValueError("unsupported expected-model uncertainty evidence kind")
        if self.confidence not in {"high", "medium", "low", "unknown"}:
            raise ValueError("unsupported categorical confidence")
        for field in _OPTIONAL:
            value = getattr(self, field)
            if value is not None:
                _text(value, field)
        for field in _VALIDITY:
            value = getattr(self, field)
            if value is not None and (type(value) is not pd.Timestamp or pd.isna(value)):
                raise ValueError(f"{field} must be an exact non-NaT Timestamp or None")
        lower, upper = self.valid_from_timestamp, self.valid_to_timestamp
        if (
            lower is not None
            and upper is not None
            and ((lower.tz is None) != (upper.tz is None) or lower > upper)
        ):
            raise ValueError("invalid/incompatible expected-model validity range")


@dataclass(frozen=True)
class RevenueMeterExpectedModelUncertaintyDiagnostics:
    """Authority partitions apply only after resolved S13C; validity after authority."""

    revenue_meter_count: int
    timestamp_count: int
    row_count: int
    expected_power_state_present_count: int
    expected_power_state_missing_count: int
    expected_operating_solution_resolved_count: int
    expected_operating_solution_unresolved_count: int
    uncertainty_authority_present_count: int
    uncertainty_authority_missing_count: int
    temporally_applicable_count: int
    temporally_inapplicable_count: int
    active_power_uncertainty_resolved_count: int
    active_power_uncertainty_unresolved_count: int
    reactive_power_uncertainty_resolved_count: int
    reactive_power_uncertainty_unresolved_count: int
    state_counts: tuple[tuple[str, int], ...]
    model: str


@dataclass(frozen=True)
class RevenueMeterExpectedModelUncertaintyResult:
    states: pd.DataFrame
    diagnostics: RevenueMeterExpectedModelUncertaintyDiagnostics


def _call(function: Callable[..., Any], values: Mapping[str, Any]) -> Any:
    return function(**{name: values[name] for name in inspect.signature(function).parameters})


# Standalone exact replay plumbing, not an uncertainty equation/builder alias.
def _replay(label: str, supplied: Any, canonical: Any) -> None:
    """Strict recursive replay of canonical result frames, mappings and metadata."""
    if type(supplied) is not type(canonical):
        raise ValueError(f"{label} type failed canonical replay")
    if isinstance(canonical, pd.DataFrame):
        try:
            pd.testing.assert_frame_equal(supplied, canonical, check_exact=True)
        except AssertionError as error:
            raise ValueError(f"{label} frame failed canonical replay") from error
        # Object dtype equality treats timezone-equivalent timestamps and some
        # missing sentinels as interchangeable. Authority provenance is exact.
        for column in canonical.select_dtypes(include="object"):
            for actual, expected in zip(supplied[column], canonical[column], strict=True):
                if isinstance(expected, pd.Timestamp):
                    _replay(label + " timestamp", actual, expected)
                elif expected is None and actual is not None:
                    raise ValueError(f"{label} missing authority metadata failed replay")
    elif isinstance(canonical, Mapping):
        if len(supplied) != len(canonical):
            raise ValueError(f"{label} mapping failed canonical replay")
        for (key, value), (expected_key, expected_value) in zip(
            supplied.items(), canonical.items(), strict=True
        ):
            _replay(label + " key", key, expected_key)
            _replay(label + " value", value, expected_value)
    elif is_dataclass(canonical):
        for field in fields(canonical):
            _replay(
                label + "." + field.name,
                getattr(supplied, field.name),
                getattr(canonical, field.name),
            )
    elif isinstance(canonical, tuple):
        if len(supplied) != len(canonical):
            raise ValueError(f"{label} tuple failed canonical replay")
        for actual, expected in zip(supplied, canonical, strict=True):
            _replay(label, actual, expected)
    elif isinstance(canonical, pd.Timestamp):
        if supplied != canonical or str(supplied.tz) != str(canonical.tz):
            raise ValueError(f"{label} timestamp failed canonical replay")
    elif supplied != canonical:
        raise ValueError(f"{label} failed canonical replay")


def _parents(values: Mapping[str, Any]) -> tuple[Any, Any]:
    network = _call(resolve_topology_mv_hv_network_authority, values)
    _replay("S13A", values["mv_hv_network_authority"], network)
    for meter in network.revenue_meter_boundary_by_id.values():
        replace(meter)  # Revalidate frozen boundary evidence as well as replaying it.
    canonical = calculate_topology_mv_hv_operating_solution(
        **dict(values, mv_hv_network_authority=network)
    )
    _replay("S13C", values["mv_hv_operating_solution"], canonical)
    return network, canonical


def _admit_authorities(
    supplied: object, meter_ids: tuple[str, ...]
) -> Mapping[str, RevenueMeterExpectedModelUncertaintyAuthority]:
    if supplied is None:
        return MappingProxyType({})
    if not isinstance(supplied, Mapping):
        raise ValueError("expected-model uncertainty authority must be a meter-ID mapping")
    admitted = {}
    for meter, authority in supplied.items():
        if type(meter) is not str or meter not in meter_ids:
            raise ValueError("unknown or non-exact canonical revenue-meter ID")
        if type(authority) is not RevenueMeterExpectedModelUncertaintyAuthority:
            raise ValueError("exact expected-model uncertainty authority type required")
        admitted[meter] = replace(authority)
    return MappingProxyType(admitted)


def _channel(
    record: dict[str, Any],
    row: pd.Series,
    authority: RevenueMeterExpectedModelUncertaintyAuthority,
    channel: str,
    unit: str,
    source: str,
) -> None:
    fraction = getattr(authority, f"{channel}_power_relative_error_bound_fraction")
    absolute = getattr(authority, f"{channel}_power_absolute_error_bound_{unit}")
    state_key = f"{channel}_power_expected_model_uncertainty_state"
    if fraction is None and absolute is None:
        record[state_key] = "unresolved_channel_expected_model_uncertainty_not_represented"
        return
    power = float(row[source])
    relative = abs(power) * float(fraction) if fraction is not None else math.nan
    terms = [relative] if fraction is not None else []
    if absolute is not None:
        terms.append(float(absolute))
    try:
        bound = math.fsum(terms)
        lower, upper = power - bound, power + bound
        finite = all(math.isfinite(v) for v in (*terms, bound, lower, upper))
    except (OverflowError, ValueError):
        finite = False
    if not finite:
        record[state_key] = _STATES[7]
        return
    record.update(
        {
            f"{channel}_power_relative_uncertainty_component_{unit}": relative,
            f"{channel}_power_absolute_uncertainty_component_{unit}": (
                math.nan if absolute is None else float(absolute)
            ),
            f"{channel}_power_expected_model_uncertainty_bound_{unit}": bound,
            f"expected_{channel}_power_lower_bound_{unit}": lower,
            f"expected_{channel}_power_upper_bound_{unit}": upper,
            f"{channel}_power_expected_model_uncertainty_resolved": True,
            state_key: "resolved_pointwise_expected_model_uncertainty_bound",
        }
    )


def _record(
    timestamp: pd.Timestamp,
    row: pd.Series | None,
    authority: RevenueMeterExpectedModelUncertaintyAuthority | None,
) -> dict[str, Any]:
    out: dict[str, Any] = dict.fromkeys(_BOOL, False)
    out.update(dict.fromkeys(_FLOAT, math.nan))
    out.update(dict.fromkeys(_TEXT, ""))
    out.update(dict.fromkeys((*_VALIDITY, *_OPTIONAL), None))
    out.update(_FIXED)
    out["expected_model_uncertainty_authority_present"] = authority is not None
    if authority is not None:
        out.update(
            {field: getattr(authority, field) for field in (*_SEMANTICS, *_VALIDITY, *_OPTIONAL)}
        )
        out.update(
            {"model_uncertainty_" + field: getattr(authority, field) for field in _PROVENANCE}
        )
        out.update(
            {
                field: math.nan
                if getattr(authority, field) is None
                else float(getattr(authority, field))
                for field in _AUTHORITY_NUMBERS
            }
        )
    state = _STATES[0]
    if row is not None:
        out["expected_power_state_present"] = True
        ready = bool(row.mv_hv_operating_solution_resolved) and (
            row.revenue_meter_expected_state == "resolved_expected_revenue_meter_boundary_power"
        )
        out["expected_power_state_resolved"] = ready
        state = _STATES[1]
        if ready:
            state = _STATES[2]
            if authority is not None:
                bounds = (authority.valid_from_timestamp, authority.valid_to_timestamp)
                compatible = all(
                    t is None or (t.tz is None) == (timestamp.tz is None) for t in bounds
                )
                valid = (
                    compatible
                    and (bounds[0] is None or timestamp >= bounds[0])
                    and (bounds[1] is None or timestamp <= bounds[1])
                )
                out["expected_model_uncertainty_temporally_applicable"] = valid
                state = _STATES[3]
                if valid:
                    for channel, unit, source in _CHANNELS:
                        _channel(out, row, authority, channel, unit, source)
                    p, q = (
                        out[f"{c}_power_expected_model_uncertainty_resolved"]
                        for c in ("active", "reactive")
                    )
                    state = (
                        _STATES[6]
                        if p and q
                        else _STATES[4]
                        if p
                        else _STATES[5]
                        if q
                        else _STATES[7]
                    )
    if state in _STATES[:4]:
        for channel, _, _ in _CHANNELS:
            out[f"{channel}_power_expected_model_uncertainty_state"] = state
    out["expected_model_uncertainty_state"] = state
    return out


def _frame(baseline: pd.DataFrame, records: list[dict[str, Any]]) -> pd.DataFrame:
    if set(baseline.columns) & set(_EXTRA_COLUMNS):
        raise ValueError("expected-model annotation collides with S13C schema")
    extra = pd.DataFrame(index=baseline.index.copy())
    for field in _EXTRA_COLUMNS:
        dtype = bool if field in _BOOL else float if field in _FLOAT else object
        extra[field] = pd.Series([r[field] for r in records], index=baseline.index, dtype=dtype)
    return pd.concat([baseline.copy(deep=True), extra], axis=1)


def _diagnostics(
    network: Any, frame: pd.DataFrame
) -> RevenueMeterExpectedModelUncertaintyDiagnostics:
    present = frame.expected_power_state_present
    ready = frame.expected_power_state_resolved
    authority = ready & frame.expected_model_uncertainty_authority_present
    valid = authority & frame.expected_model_uncertainty_temporally_applicable
    p, q = (
        int(frame[f"{c}_power_expected_model_uncertainty_resolved"].sum())
        for c in ("active", "reactive")
    )
    n = len(frame)
    return RevenueMeterExpectedModelUncertaintyDiagnostics(
        len(network.revenue_meter_boundary_by_id),
        len(frame.index.get_level_values("timestamp").unique()),
        n,
        int(present.sum()),
        n - int(present.sum()),
        int(ready.sum()),
        int((present & ~ready).sum()),
        int(authority.sum()),
        int((ready & ~authority).sum()),
        int(valid.sum()),
        int((authority & ~valid).sum()),
        p,
        n - p,
        q,
        n - q,
        tuple(
            (state, int(frame.expected_model_uncertainty_state.eq(state).sum()))
            for state in _STATES
        ),
        REVENUE_METER_EXPECTED_MODEL_UNCERTAINTY_MODEL_ID,
    )


def resolve_topology_revenue_meter_expected_model_uncertainty(
    *,
    revenue_meter_expected_model_uncertainty_by_meter_id: Mapping[
        str, RevenueMeterExpectedModelUncertaintyAuthority
    ]
    | None = None,
    **values: Any,
) -> RevenueMeterExpectedModelUncertaintyResult:
    """Replay raw S13C inputs plus supplied S13A/S13C results, then annotate only.

    ``values`` includes ``mv_hv_network_authority`` and ``mv_hv_operating_solution``.
    Canonical row identity is retained; missing/tampered supplied parent rows fail
    replay rather than generating unsupported timestamps or fabricated physics.
    """
    network, model = _parents(values)
    authorities = _admit_authorities(
        revenue_meter_expected_model_uncertainty_by_meter_id,
        tuple(network.revenue_meter_boundary_by_id),
    )
    records = [
        _record(t, row, authorities.get(meter))
        for (t, meter), row in model.revenue_meter_states.iterrows()
    ]
    states = _frame(model.revenue_meter_states, records)
    result = RevenueMeterExpectedModelUncertaintyResult(states, _diagnostics(network, states))
    _validate_result(network, model, result, authorities)
    return result


# Validator-owned reconstruction. No production authority-admission, record,
# channel, frame, diagnostics or public uncertainty builder is invoked.
def _validator_parents(values: Mapping[str, Any]) -> tuple[Any, Any]:
    network = _call(resolve_topology_mv_hv_network_authority, values)
    _replay("S13A", values["mv_hv_network_authority"], network)
    for boundary in network.revenue_meter_boundary_by_id.values():
        replace(boundary)
    expected = calculate_topology_mv_hv_operating_solution(
        **dict(values, mv_hv_network_authority=network)
    )
    _replay("S13C", values["mv_hv_operating_solution"], expected)
    return network, expected


def _validator_record(
    timestamp: pd.Timestamp,
    row: pd.Series | None,
    authority: RevenueMeterExpectedModelUncertaintyAuthority | None,
) -> dict[str, Any]:
    record: dict[str, Any] = {key: math.nan for key in _FLOAT}
    record.update({key: False for key in _BOOL})
    record.update({key: "" for key in _TEXT})
    record.update({key: None for key in (*_VALIDITY, *_OPTIONAL)})
    record.update(_FIXED)
    record["expected_model_uncertainty_authority_present"] = authority is not None
    if authority is not None:
        for key in (*_SEMANTICS, *_VALIDITY, *_OPTIONAL):
            record[key] = getattr(authority, key)
        for key in _PROVENANCE:
            record["model_uncertainty_" + key] = getattr(authority, key)
        for key in _AUTHORITY_NUMBERS:
            value = getattr(authority, key)
            record[key] = math.nan if value is None else float(value)
    state = "unresolved_missing_s13c_expected_power_state"
    if row is not None:
        record["expected_power_state_present"] = True
        ready = (
            row.revenue_meter_expected_state == "resolved_expected_revenue_meter_boundary_power"
            and bool(row.mv_hv_operating_solution_resolved)
        )
        record["expected_power_state_resolved"] = ready
        state = "unresolved_s13c_expected_operating_solution"
        if ready:
            state = "unresolved_missing_expected_model_uncertainty_authority"
            if authority is not None:
                valid = True
                for limit, lower in (
                    (authority.valid_from_timestamp, True),
                    (authority.valid_to_timestamp, False),
                ):
                    if limit is not None and (
                        (timestamp.tz is None) != (limit.tz is None)
                        or (lower and timestamp < limit)
                        or (not lower and timestamp > limit)
                    ):
                        valid = False
                record["expected_model_uncertainty_temporally_applicable"] = valid
                state = "unresolved_expected_model_uncertainty_temporal_validity"
                if valid:
                    for channel, unit, source in _CHANNELS:
                        state_field = f"{channel}_power_expected_model_uncertainty_state"
                        fraction = getattr(
                            authority, f"{channel}_power_relative_error_bound_fraction"
                        )
                        absolute = getattr(
                            authority, f"{channel}_power_absolute_error_bound_{unit}"
                        )
                        if fraction is None and absolute is None:
                            record[state_field] = (
                                "unresolved_channel_expected_model_uncertainty_not_represented"
                            )
                            continue
                        value = float(row[source])
                        relative = math.nan
                        components = []
                        if fraction is not None:
                            relative = float(fraction) * abs(value)
                            components.append(relative)
                        if absolute is not None:
                            components.append(float(absolute))
                        total = sum(components)
                        power_lower, power_upper = value - total, value + total
                        if not all(
                            math.isfinite(v) for v in (*components, total, power_lower, power_upper)
                        ):
                            record[state_field] = (
                                "unresolved_nonfinite_expected_model_uncertainty_arithmetic"
                            )
                            continue
                        record[f"{channel}_power_relative_uncertainty_component_{unit}"] = relative
                        record[f"{channel}_power_absolute_uncertainty_component_{unit}"] = (
                            math.nan if absolute is None else float(absolute)
                        )
                        record[f"{channel}_power_expected_model_uncertainty_bound_{unit}"] = total
                        record[f"expected_{channel}_power_lower_bound_{unit}"] = power_lower
                        record[f"expected_{channel}_power_upper_bound_{unit}"] = power_upper
                        record[f"{channel}_power_expected_model_uncertainty_resolved"] = True
                        record[state_field] = "resolved_pointwise_expected_model_uncertainty_bound"
                    p = record["active_power_expected_model_uncertainty_resolved"]
                    q = record["reactive_power_expected_model_uncertainty_resolved"]
                    if p and q:
                        state = "resolved_active_reactive_expected_model_uncertainty"
                    elif p:
                        state = "resolved_active_power_expected_model_uncertainty_only"
                    elif q:
                        state = "resolved_reactive_power_expected_model_uncertainty_only"
                    else:
                        state = "unresolved_nonfinite_expected_model_uncertainty_arithmetic"
    if state in _STATES[:4]:
        for channel, _, _ in _CHANNELS:
            record[f"{channel}_power_expected_model_uncertainty_state"] = state
    record["expected_model_uncertainty_state"] = state
    return record


def _validator_frame(
    model: Any, authorities: Mapping[str, RevenueMeterExpectedModelUncertaintyAuthority]
) -> pd.DataFrame:
    baseline = model.revenue_meter_states
    rows = [
        _validator_record(timestamp, row, authorities.get(meter))
        for (timestamp, meter), row in baseline.iterrows()
    ]
    if set(baseline.columns).intersection(_EXTRA_COLUMNS):
        raise ValueError("validator S13C column collision")
    columns = {}
    for key in _EXTRA_COLUMNS:
        kind = bool if key in _BOOL else float if key in _FLOAT else object
        columns[key] = pd.Series([record[key] for record in rows], dtype=kind, index=baseline.index)
    return pd.concat(
        [baseline.copy(deep=True), pd.DataFrame(columns, index=baseline.index)], axis=1
    )


def _validator_diagnostics(
    network: Any, frame: pd.DataFrame
) -> RevenueMeterExpectedModelUncertaintyDiagnostics:
    present = frame["expected_power_state_present"].astype(bool)
    ready = frame["expected_power_state_resolved"].astype(bool)
    admitted = ready & frame["expected_model_uncertainty_authority_present"]
    applicable = admitted & frame["expected_model_uncertainty_temporally_applicable"]
    p = int(frame["active_power_expected_model_uncertainty_resolved"].sum())
    q = int(frame["reactive_power_expected_model_uncertainty_resolved"].sum())
    n = len(frame.index)
    return RevenueMeterExpectedModelUncertaintyDiagnostics(
        revenue_meter_count=len(network.revenue_meter_boundary_by_id),
        timestamp_count=len(set(frame.index.get_level_values("timestamp"))),
        row_count=n,
        expected_power_state_present_count=int(present.sum()),
        expected_power_state_missing_count=int((~present).sum()),
        expected_operating_solution_resolved_count=int(ready.sum()),
        expected_operating_solution_unresolved_count=int((present & ~ready).sum()),
        uncertainty_authority_present_count=int(admitted.sum()),
        uncertainty_authority_missing_count=int((ready & ~admitted).sum()),
        temporally_applicable_count=int(applicable.sum()),
        temporally_inapplicable_count=int((admitted & ~applicable).sum()),
        active_power_uncertainty_resolved_count=p,
        active_power_uncertainty_unresolved_count=n - p,
        reactive_power_uncertainty_resolved_count=q,
        reactive_power_uncertainty_unresolved_count=n - q,
        state_counts=tuple(
            (name, int((frame["expected_model_uncertainty_state"] == name).sum()))
            for name in _STATES
        ),
        model=REVENUE_METER_EXPECTED_MODEL_UNCERTAINTY_MODEL_ID,
    )


def _validate_result(
    network: Any, model: Any, result: RevenueMeterExpectedModelUncertaintyResult, supplied: object
) -> None:
    if type(result) is not RevenueMeterExpectedModelUncertaintyResult:
        raise ValueError("exact expected-model uncertainty result required")
    mapping = {} if supplied is None else supplied
    if not isinstance(mapping, Mapping):
        raise ValueError("validator requires explicit meter authority mapping")
    admitted = {}
    for identifier, evidence in mapping.items():
        if type(identifier) is not str or identifier not in network.revenue_meter_boundary_by_id:
            raise ValueError("validator rejects unknown/non-string meter key")
        if type(evidence) is not RevenueMeterExpectedModelUncertaintyAuthority:
            raise ValueError("validator rejects non-exact authority type")
        admitted[identifier] = replace(evidence)
    expected = _validator_frame(model, admitted)
    _replay("expected-model uncertainty", result.states, expected)
    _replay(
        "expected-model uncertainty diagnostics",
        result.diagnostics,
        _validator_diagnostics(network, expected),
    )


def validate_revenue_meter_expected_model_uncertainty(
    result: RevenueMeterExpectedModelUncertaintyResult,
    *,
    revenue_meter_expected_model_uncertainty_by_meter_id: Mapping[
        str, RevenueMeterExpectedModelUncertaintyAuthority
    ]
    | None = None,
    **values: Any,
) -> None:
    """Independently replay parents and reconstruct the complete pointwise annotation."""
    network, model = _validator_parents(values)
    _validate_result(network, model, result, revenue_meter_expected_model_uncertainty_by_meter_id)
