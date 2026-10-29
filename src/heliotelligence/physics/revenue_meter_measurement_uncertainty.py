"""Dormant complete-chain measurement bounds; not total benchmark uncertainty.

Only admitted numerical coefficients affect the deterministic symmetric bound.
Accuracy/calibration descriptions and categorical confidence are provenance.
No component recombination, probability, expected-model uncertainty or S14
interpretation is performed. Validity covers the complete represented interval
for averages and the observation timestamp for snapshots; no dates are inferred.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from numbers import Real
from types import MappingProxyType
from typing import Any, TypeVar

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.physics.mv_hv_network_authority import resolve_topology_mv_hv_network_authority
from heliotelligence.physics.revenue_meter_measurement_authority import (
    RevenueMeterMeasuredPowerState,
    resolve_topology_revenue_meter_measurement_authority,
)

REVENUE_METER_MEASUREMENT_UNCERTAINTY_AUTHORITY_CONTRACT_ID = (
    "explicit_revenue_meter_complete_measurement_chain_quantitative_uncertainty_authority_v1"
)
REVENUE_METER_MEASUREMENT_UNCERTAINTY_AUTHORITY_SCOPE = (
    "complete_revenue_meter_measurement_chain_uncertainty_at_primary_engineering_units_boundary"
)
REVENUE_METER_MEASUREMENT_UNCERTAINTY_CONTRACT_ID = (
    "admitted_s13a_s13d_and_measurement_uncertainty_authority_to_timestamped_"
    "revenue_meter_measurement_uncertainty_state_v1"
)
REVENUE_METER_MEASUREMENT_UNCERTAINTY_MODEL_ID = (
    "explicit_complete_chain_symmetric_pq_measurement_uncertainty_bound_evaluation_v1"
)
REVENUE_METER_MEASUREMENT_UNCERTAINTY_SCOPE = (
    "timestamped_revenue_meter_measurement_quantitative_uncertainty_before_"
    "combined_model_measurement_benchmark_uncertainty"
)
UNCERTAINTY_INTERPRETATION = "symmetric_maximum_absolute_error_bound"
RELATIVE_ERROR_REFERENCE_BASIS = "absolute_same_channel_measured_power_in_primary_engineering_units"
COMBINATION_BASIS = "explicit_complete_chain_bound_no_internal_component_recombination"
MEASUREMENT_CHAIN_SCOPE = (
    "complete_revenue_meter_measurement_chain_after_instrument_transformers_scaling_and_calibration"
)
_EVIDENCE = frozenset(
    {
        "calibrated_complete_measurement_chain",
        "manufacturer_complete_chain_bound",
        "engineering_uncertainty_budget",
        "other_explicit",
    }
)
_TIME_SCOPES = frozenset(
    {
        "instantaneous_snapshot_only",
        "interval_average_only",
        "instantaneous_and_interval_average",
    }
)
_PROVENANCE = (
    "evidence_kind",
    "parameter_source",
    "confidence",
    "method_reference",
    "applicability_description",
)
_OPTIONAL_METADATA = (
    "meter_accuracy_specification",
    "current_transformer_accuracy_specification",
    "voltage_transformer_accuracy_specification",
    "scaling_chain_specification",
    "calibration_evidence_reference",
)
_AUTHORITY_SEMANTICS = (
    "uncertainty_interpretation",
    "relative_error_reference_basis",
    "combination_basis",
    "measurement_chain_scope",
    "measurement_time_scope",
)
_VALIDITY = ("valid_from_timestamp", "valid_to_timestamp")
_STATES = (
    "unresolved_missing_revenue_meter_measured_power_state",
    "unresolved_missing_measurement_uncertainty_authority",
    "unresolved_measurement_uncertainty_temporal_validity",
    "unresolved_measurement_uncertainty_time_scope_not_applicable",
    "resolved_active_power_measurement_uncertainty_only",
    "resolved_reactive_power_measurement_uncertainty_only",
    "resolved_active_reactive_measurement_uncertainty",
    "unresolved_nonfinite_measurement_uncertainty_arithmetic",
)
# Channel name and explicit engineering units. No accuracy-class lookup exists.
_CHANNELS = (("active", "w", "wh"), ("reactive", "var", "varh"))
_FIXED = {
    "revenue_meter_measurement_uncertainty_authority_contract": (
        REVENUE_METER_MEASUREMENT_UNCERTAINTY_AUTHORITY_CONTRACT_ID
    ),
    "revenue_meter_measurement_uncertainty_authority_scope": (
        REVENUE_METER_MEASUREMENT_UNCERTAINTY_AUTHORITY_SCOPE
    ),
    "revenue_meter_measurement_uncertainty_contract": (
        REVENUE_METER_MEASUREMENT_UNCERTAINTY_CONTRACT_ID
    ),
    "revenue_meter_measurement_uncertainty_model": REVENUE_METER_MEASUREMENT_UNCERTAINTY_MODEL_ID,
    "revenue_meter_measurement_uncertainty_scope": REVENUE_METER_MEASUREMENT_UNCERTAINTY_SCOPE,
}
_BOOL = (
    "measurement_uncertainty_authority_present",
    "measurement_uncertainty_temporally_applicable",
    "measurement_uncertainty_time_scope_applicable",
    *(
        f"{c}_{quantity}_measurement_uncertainty_resolved"
        for c, _, _ in _CHANNELS
        for quantity in ("power", "energy")
    ),
)
_FLOAT = tuple(
    column
    for c, unit, energy in _CHANNELS
    for column in (
        f"{c}_power_relative_error_bound_fraction",
        f"{c}_power_absolute_error_bound_{unit}",
        f"{c}_power_relative_uncertainty_component_{unit}",
        f"{c}_power_absolute_uncertainty_component_{unit}",
        f"{c}_power_measurement_uncertainty_bound_{unit}",
        f"measured_{c}_power_lower_bound_{unit}",
        f"measured_{c}_power_upper_bound_{unit}",
        f"{c}_energy_measurement_uncertainty_bound_{energy}",
        f"measured_{c}_energy_lower_bound_{energy}",
        f"measured_{c}_energy_upper_bound_{energy}",
    )
)
_AUTHORITY_NUMBERS = tuple(
    column
    for c, unit, _ in _CHANNELS
    for column in (
        f"{c}_power_relative_error_bound_fraction",
        f"{c}_power_absolute_error_bound_{unit}",
    )
)
_TEXT = (
    "measurement_uncertainty_state",
    *_AUTHORITY_SEMANTICS,
    *("uncertainty_" + field for field in _PROVENANCE),
    *_FIXED,
    *(
        f"{c}_{quantity}_measurement_uncertainty_state"
        for c, _, _ in _CHANNELS
        for quantity in ("power", "energy")
    ),
)
_EXTRA_COLUMNS = (*_BOOL, *_FLOAT, *_TEXT, *_VALIDITY, *_OPTIONAL_METADATA)


def _text(value: object, label: str) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{label} must be an exact non-empty unpadded string")


def _nonnegative(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a real non-Boolean bound")
    if not math.isfinite(float(value)) or float(value) < 0:
        raise ValueError(f"{label} must be finite and non-negative")


@dataclass(frozen=True)
class RevenueMeterMeasurementUncertaintyAuthority:
    """Already-combined complete-chain bound; descriptions do not set coefficients.

    None leaves a term unavailable. Explicit zero is numerical evidence.
    Validity covers complete intervals, or snapshot timestamps, inclusively.
    Aware zones may differ without coercing provenance. Relative terms refer
    only to the magnitude of the same measured channel in primary units.
    """

    active_power_relative_error_bound_fraction: float | None
    active_power_absolute_error_bound_w: float | None
    reactive_power_relative_error_bound_fraction: float | None
    reactive_power_absolute_error_bound_var: float | None
    uncertainty_interpretation: str
    relative_error_reference_basis: str
    combination_basis: str
    measurement_chain_scope: str
    measurement_time_scope: str
    evidence_kind: str
    parameter_source: str
    confidence: str
    method_reference: str
    applicability_description: str
    valid_from_timestamp: pd.Timestamp | None = None
    valid_to_timestamp: pd.Timestamp | None = None
    meter_accuracy_specification: str | None = None
    current_transformer_accuracy_specification: str | None = None
    voltage_transformer_accuracy_specification: str | None = None
    scaling_chain_specification: str | None = None
    calibration_evidence_reference: str | None = None

    def __post_init__(self) -> None:
        present = False
        for field in _AUTHORITY_NUMBERS:
            value = getattr(self, field)
            if value is not None:
                _nonnegative(value, field)
                present = True
        if not present:
            raise ValueError("at least one channel must have an explicit numerical bound")
        for field in (*_AUTHORITY_SEMANTICS, *_PROVENANCE):
            _text(getattr(self, field), field)
        if (
            self.uncertainty_interpretation != UNCERTAINTY_INTERPRETATION
            or self.relative_error_reference_basis != RELATIVE_ERROR_REFERENCE_BASIS
            or self.combination_basis != COMBINATION_BASIS
            or self.measurement_chain_scope != MEASUREMENT_CHAIN_SCOPE
        ):
            raise ValueError(
                "unsupported measurement bound interpretation/complete-chain ownership"
            )
        if self.measurement_time_scope not in _TIME_SCOPES or self.evidence_kind not in _EVIDENCE:
            raise ValueError("unsupported measurement time scope or uncertainty evidence kind")
        if self.confidence not in {"high", "medium", "low", "unknown"}:
            raise ValueError("unsupported confidence")
        for field in _OPTIONAL_METADATA:
            value = getattr(self, field)
            if value is not None:
                _text(value, field)
        for field in _VALIDITY:
            value = getattr(self, field)
            if value is not None and (type(value) is not pd.Timestamp or pd.isna(value)):
                raise ValueError(f"{field} must be an exact non-NaT pd.Timestamp or None")
        start, end = self.valid_from_timestamp, self.valid_to_timestamp
        if start is not None and end is not None:
            if (start.tz is None) != (end.tz is None):
                raise ValueError("validity boundaries have incompatible timezone semantics")
            if start > end:
                raise ValueError("valid_from_timestamp must not exceed valid_to_timestamp")


@dataclass(frozen=True)
class RevenueMeterMeasurementUncertaintyDiagnostics:
    """Nested partitions avoid counting earlier failures as uncertainty gaps.

    Authority counts partition measured rows; temporal counts partition those
    with authority; time-scope counts partition temporally applicable rows.
    Each P/Q resolved/unresolved partition covers the complete row universe.
    """

    revenue_meter_count: int
    timestamp_count: int
    row_count: int
    measured_power_state_present_count: int
    measured_power_state_missing_count: int
    uncertainty_authority_present_count: int
    uncertainty_authority_missing_count: int
    temporally_applicable_count: int
    temporally_inapplicable_count: int
    time_scope_applicable_count: int
    time_scope_inapplicable_count: int
    active_power_uncertainty_resolved_count: int
    active_power_uncertainty_unresolved_count: int
    reactive_power_uncertainty_resolved_count: int
    reactive_power_uncertainty_unresolved_count: int
    interval_active_energy_uncertainty_resolved_count: int
    interval_reactive_energy_uncertainty_resolved_count: int
    state_counts: tuple[tuple[str, int], ...]
    model: str


@dataclass(frozen=True)
class RevenueMeterMeasurementUncertaintyResult:
    states: pd.DataFrame
    diagnostics: RevenueMeterMeasurementUncertaintyDiagnostics


F = TypeVar("F", bound=Callable[..., Any])


def _call(function: F, values: Mapping[str, Any]) -> Any:
    return function(**{name: values[name] for name in inspect.signature(function).parameters})


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
    parent = _call(resolve_topology_mv_hv_network_authority, values)
    _replay("S13A", values["mv_hv_network_authority"], parent)
    supplied = values["revenue_meter_measured_power_by_key"]
    if not isinstance(supplied, Mapping):
        raise ValueError("S13D measured evidence must be a mapping")
    evidence = {}
    for key, state in supplied.items():
        if type(state) is not RevenueMeterMeasuredPowerState:
            raise ValueError("exact S13D measured-power authority required")
        evidence[key] = replace(state)
    canonical = dict(
        values, mv_hv_network_authority=parent, revenue_meter_measured_power_by_key=evidence
    )
    measurement = _call(resolve_topology_revenue_meter_measurement_authority, canonical)
    _replay("S13D", values["revenue_meter_measurement_authority"], measurement)
    return parent, measurement


def _admit_authorities(
    supplied: object, meter_ids: tuple[str, ...]
) -> Mapping[str, RevenueMeterMeasurementUncertaintyAuthority]:
    if supplied is None:
        return MappingProxyType({})
    if not isinstance(supplied, Mapping):
        raise ValueError("measurement uncertainty authorities must be a meter mapping")
    result = {}
    for meter, authority in supplied.items():
        if type(meter) is not str or meter not in meter_ids:
            raise ValueError("uncertainty mapping must use exact canonical meter IDs")
        if type(authority) is not RevenueMeterMeasurementUncertaintyAuthority:
            raise ValueError("exact RevenueMeterMeasurementUncertaintyAuthority required")
        result[meter] = replace(authority)
    return MappingProxyType(result)


def _channel(
    record: dict[str, Any],
    row: pd.Series,
    authority: RevenueMeterMeasurementUncertaintyAuthority,
    channel: str,
    unit: str,
    energy: str,
) -> None:
    fraction = getattr(authority, f"{channel}_power_relative_error_bound_fraction")
    absolute = getattr(authority, f"{channel}_power_absolute_error_bound_{unit}")
    power_state = f"{channel}_power_measurement_uncertainty_state"
    energy_state = f"{channel}_energy_measurement_uncertainty_state"
    if fraction is None and absolute is None:
        record[power_state] = "unresolved_channel_uncertainty_not_represented"
        return
    measured = float(row[f"measured_{channel}_power_{unit}"])
    relative_component = abs(measured) * float(fraction) if fraction is not None else math.nan
    terms = [relative_component] if fraction is not None else []
    if absolute is not None:
        terms.append(float(absolute))
    try:
        bound = math.fsum(terms)
        lower, upper = measured - bound, measured + bound
        finite = all(math.isfinite(value) for value in (*terms, bound, lower, upper))
    except (OverflowError, ValueError):
        finite = False
    if not finite:
        record[power_state] = _STATES[7]
        return
    record.update(
        {
            f"{channel}_power_relative_uncertainty_component_{unit}": relative_component,
            f"{channel}_power_absolute_uncertainty_component_{unit}": float(absolute)
            if absolute is not None
            else math.nan,
            f"{channel}_power_measurement_uncertainty_bound_{unit}": bound,
            f"measured_{channel}_power_lower_bound_{unit}": lower,
            f"measured_{channel}_power_upper_bound_{unit}": upper,
            f"{channel}_power_measurement_uncertainty_resolved": True,
            power_state: "resolved_power_measurement_uncertainty_bound",
        }
    )
    if row["measurement_time_semantics"] == "instantaneous_snapshot":
        record[energy_state] = "not_applicable_instantaneous_snapshot"
        return
    hours = float(row["averaging_interval_seconds"]) / 3600.0
    energy_bound = bound * hours
    measured_energy = measured * hours
    energy_lower, energy_upper = measured_energy - energy_bound, measured_energy + energy_bound
    if not all(
        math.isfinite(value)
        for value in (energy_bound, measured_energy, energy_lower, energy_upper)
    ):
        record[energy_state] = "unresolved_nonfinite_interval_energy_uncertainty_arithmetic"
        return
    record.update(
        {
            f"{channel}_energy_measurement_uncertainty_bound_{energy}": energy_bound,
            f"measured_{channel}_energy_lower_bound_{energy}": energy_lower,
            f"measured_{channel}_energy_upper_bound_{energy}": energy_upper,
            f"{channel}_energy_measurement_uncertainty_resolved": True,
            energy_state: "resolved_interval_measurement_energy_uncertainty_bound",
        }
    )


def _validity_interval_start(end: pd.Timestamp, seconds: float) -> pd.Timestamp | None:
    """Exact nanosecond round-trip and bounded elapsed-time arithmetic, or unavailable."""
    try:
        product = seconds * 1_000_000_000.0
        if not math.isfinite(product):
            return None
        nanoseconds = round(product)
        if (
            nanoseconds <= 0
            or nanoseconds > pd.Timedelta.max.value
            or nanoseconds / 1_000_000_000.0 != seconds
        ):
            return None
        start = end - pd.Timedelta(nanoseconds, unit="ns")
        return None if pd.isna(start) else start
    except (OverflowError, ValueError, TypeError):
        return None


def _record(
    timestamp: pd.Timestamp,
    row: pd.Series,
    authority: RevenueMeterMeasurementUncertaintyAuthority | None,
) -> dict[str, Any]:
    record: dict[str, Any] = {column: False for column in _BOOL}
    record.update(dict.fromkeys(_FLOAT, math.nan))
    record.update(dict.fromkeys(_TEXT, ""))
    record.update(dict.fromkeys((*_VALIDITY, *_OPTIONAL_METADATA), None))
    record.update(_FIXED)
    record["measurement_uncertainty_authority_present"] = authority is not None
    for channel, _, _ in _CHANNELS:
        record[f"{channel}_energy_measurement_uncertainty_state"] = (
            "unresolved_power_measurement_uncertainty"
        )
    if authority is not None:
        record.update(
            {
                field: getattr(authority, field)
                for field in (*_AUTHORITY_SEMANTICS, *_VALIDITY, *_OPTIONAL_METADATA)
            }
        )
        record.update({"uncertainty_" + field: getattr(authority, field) for field in _PROVENANCE})
        record.update(
            {
                field: float(getattr(authority, field))
                if getattr(authority, field) is not None
                else math.nan
                for field in _AUTHORITY_NUMBERS
            }
        )
    state = _STATES[0]
    if bool(row["measured_power_authority_resolved"]):
        state = _STATES[1]
        if authority is not None:
            bounds = (authority.valid_from_timestamp, authority.valid_to_timestamp)
            compatible = all(
                bound is None or (bound.tz is None) == (timestamp.tz is None) for bound in bounds
            )
            lower_instant = timestamp
            if (
                bounds[0] is not None
                and row["measurement_time_semantics"] == "interval_average_ending_at_timestamp"
            ):
                lower_instant = _validity_interval_start(
                    timestamp, float(row["averaging_interval_seconds"])
                )
            temporal = (
                compatible
                and (
                    bounds[0] is None or (lower_instant is not None and lower_instant >= bounds[0])
                )
                and (bounds[1] is None or timestamp <= bounds[1])
            )
            record["measurement_uncertainty_temporally_applicable"] = temporal
            state = _STATES[2]
            if temporal:
                semantics = row["measurement_time_semantics"]
                applicable = (
                    authority.measurement_time_scope == "instantaneous_and_interval_average"
                    or (
                        authority.measurement_time_scope == "instantaneous_snapshot_only"
                        and semantics == "instantaneous_snapshot"
                    )
                    or (
                        authority.measurement_time_scope == "interval_average_only"
                        and semantics == "interval_average_ending_at_timestamp"
                    )
                )
                record["measurement_uncertainty_time_scope_applicable"] = applicable
                state = _STATES[3]
                if applicable:
                    for channel, unit, energy in _CHANNELS:
                        _channel(record, row, authority, channel, unit, energy)
                    p = record["active_power_measurement_uncertainty_resolved"]
                    q = record["reactive_power_measurement_uncertainty_resolved"]
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
            record[f"{channel}_power_measurement_uncertainty_state"] = state
    record["measurement_uncertainty_state"] = state
    return record


def _frame(parent: pd.DataFrame, records: list[dict[str, Any]]) -> pd.DataFrame:
    if set(parent.columns) & set(_EXTRA_COLUMNS):
        raise ValueError("uncertainty schema collides with canonical S13D columns")
    extra = pd.DataFrame(records, index=parent.index.copy(), columns=_EXTRA_COLUMNS)
    for column in _BOOL:
        extra[column] = extra[column].astype(bool)
    for column in _FLOAT:
        extra[column] = extra[column].astype(float)
    for column in (*_TEXT, *_VALIDITY, *_OPTIONAL_METADATA):
        extra[column] = pd.Series(
            [record[column] for record in records], index=parent.index, dtype=object
        )
    return pd.concat([parent.copy(deep=True), extra], axis=1)


def _diagnostics(parent: Any, frame: pd.DataFrame) -> RevenueMeterMeasurementUncertaintyDiagnostics:
    measured = frame["measured_power_authority_resolved"]
    authority = measured & frame["measurement_uncertainty_authority_present"]
    temporal = authority & frame["measurement_uncertainty_temporally_applicable"]
    scope = temporal & frame["measurement_uncertainty_time_scope_applicable"]
    p, q = (
        int(frame[f"{c}_power_measurement_uncertainty_resolved"].sum())
        for c in ("active", "reactive")
    )
    n = len(frame)
    return RevenueMeterMeasurementUncertaintyDiagnostics(
        len(parent.revenue_meter_boundary_by_id),
        len(frame.index.get_level_values("timestamp").unique()),
        n,
        int(measured.sum()),
        n - int(measured.sum()),
        int(authority.sum()),
        int((measured & ~authority).sum()),
        int(temporal.sum()),
        int((authority & ~temporal).sum()),
        int(scope.sum()),
        int((temporal & ~scope).sum()),
        p,
        n - p,
        q,
        n - q,
        int(frame["active_energy_measurement_uncertainty_resolved"].sum()),
        int(frame["reactive_energy_measurement_uncertainty_resolved"].sum()),
        tuple(
            (state, int(frame.measurement_uncertainty_state.eq(state).sum())) for state in _STATES
        ),
        REVENUE_METER_MEASUREMENT_UNCERTAINTY_MODEL_ID,
    )


def resolve_topology_revenue_meter_measurement_uncertainty(
    *,
    revenue_meter_measurement_uncertainty_by_meter_id: Mapping[
        str, RevenueMeterMeasurementUncertaintyAuthority
    ]
    | None = None,
    **values: Any,
) -> RevenueMeterMeasurementUncertaintyResult:
    """Annotate canonical S13D measurements without changing measurements or S14.

    ``values`` supplies the native S13D raw builder inputs, canonical
    ``mv_hv_network_authority`` (S13A) and canonical
    ``revenue_meter_measurement_authority`` (S13D). Both parents are replayed.
    Omitted uncertainty mapping admits no numerical authority.
    """
    parent, measured = _parents(values)
    authorities = _admit_authorities(
        revenue_meter_measurement_uncertainty_by_meter_id,
        tuple(parent.revenue_meter_boundary_by_id),
    )
    records = [
        _record(key[0], row, authorities.get(key[1])) for key, row in measured.states.iterrows()
    ]
    frame = _frame(measured.states, records)
    result = RevenueMeterMeasurementUncertaintyResult(frame, _diagnostics(parent, frame))
    _validate_result(parent, measured, result, authorities)
    return result


def _validator_parents(values: Mapping[str, Any]) -> tuple[Any, Any]:
    # Native parent reconstruction is permitted; uncertainty production helpers
    # and private S13D builders are never used by the independent validator.
    canonical = _call(resolve_topology_mv_hv_network_authority, values)
    _replay("S13A", values["mv_hv_network_authority"], canonical)
    raw = values["revenue_meter_measured_power_by_key"]
    if not isinstance(raw, Mapping):
        raise ValueError("validator measured input must be a mapping")
    validated = {}
    for key, value in raw.items():
        if type(value) is not RevenueMeterMeasuredPowerState:
            raise ValueError("validator measured input type is invalid")
        validated[key] = replace(value)
    inputs = dict(
        values, mv_hv_network_authority=canonical, revenue_meter_measured_power_by_key=validated
    )
    measured = _call(resolve_topology_revenue_meter_measurement_authority, inputs)
    _replay("S13D", values["revenue_meter_measurement_authority"], measured)
    return canonical, measured


def _validator_frame(
    measured: pd.DataFrame, policies: Mapping[str, RevenueMeterMeasurementUncertaintyAuthority]
) -> pd.DataFrame:
    records = []
    for (timestamp, meter), row in measured.iterrows():
        policy = policies.get(meter)
        out: dict[str, Any] = {column: math.nan for column in _FLOAT}
        out.update({column: False for column in _BOOL})
        out.update({column: "" for column in _TEXT})
        out.update({column: None for column in (*_VALIDITY, *_OPTIONAL_METADATA)})
        out.update(_FIXED)
        out["measurement_uncertainty_authority_present"] = policy is not None
        for channel, _, _ in _CHANNELS:
            out[f"{channel}_energy_measurement_uncertainty_state"] = (
                "unresolved_power_measurement_uncertainty"
            )
        if policy is not None:
            for field in (*_AUTHORITY_SEMANTICS, *_VALIDITY, *_OPTIONAL_METADATA):
                out[field] = getattr(policy, field)
            for field in _PROVENANCE:
                out["uncertainty_" + field] = getattr(policy, field)
            for field in _AUTHORITY_NUMBERS:
                value = getattr(policy, field)
                out[field] = math.nan if value is None else float(value)
        state = "unresolved_missing_revenue_meter_measured_power_state"
        if row.measured_power_authority_resolved:
            state = "unresolved_missing_measurement_uncertainty_authority"
            if policy is not None:
                valid = True
                for boundary, lower in (
                    (policy.valid_from_timestamp, True),
                    (policy.valid_to_timestamp, False),
                ):
                    if boundary is None:
                        continue
                    comparison_time = timestamp
                    if lower and row.measurement_time_semantics == (
                        "interval_average_ending_at_timestamp"
                    ):
                        # Independent reconstruction; no production arithmetic helper.
                        try:
                            seconds = float(row.averaging_interval_seconds)
                            product = seconds * 1e9
                            ns = round(product)
                            exact = (
                                math.isfinite(product)
                                and 0 < ns <= pd.Timedelta.max.value
                                and ns / 1e9 == seconds
                            )
                            comparison_time = (
                                timestamp - pd.Timedelta(ns, unit="ns") if exact else None
                            )
                        except (OverflowError, ValueError, TypeError):
                            comparison_time = None
                    if (
                        comparison_time is None
                        or pd.isna(comparison_time)
                        or (comparison_time.tz is None) != (boundary.tz is None)
                        or (lower and comparison_time < boundary)
                        or (not lower and comparison_time > boundary)
                    ):
                        valid = False
                out["measurement_uncertainty_temporally_applicable"] = valid
                state = "unresolved_measurement_uncertainty_temporal_validity"
                if valid:
                    allowed = {
                        "instantaneous_snapshot_only": {"instantaneous_snapshot"},
                        "interval_average_only": {"interval_average_ending_at_timestamp"},
                        "instantaneous_and_interval_average": {
                            "instantaneous_snapshot",
                            "interval_average_ending_at_timestamp",
                        },
                    }[policy.measurement_time_scope]
                    time_ok = row.measurement_time_semantics in allowed
                    out["measurement_uncertainty_time_scope_applicable"] = time_ok
                    state = "unresolved_measurement_uncertainty_time_scope_not_applicable"
                    if time_ok:
                        for channel, unit, energy in _CHANNELS:
                            relative = getattr(
                                policy, f"{channel}_power_relative_error_bound_fraction"
                            )
                            absolute = getattr(
                                policy, f"{channel}_power_absolute_error_bound_{unit}"
                            )
                            power_state = f"{channel}_power_measurement_uncertainty_state"
                            if relative is None and absolute is None:
                                out[power_state] = "unresolved_channel_uncertainty_not_represented"
                                continue
                            reading = float(row[f"measured_{channel}_power_{unit}"])
                            components = []
                            rel_component = math.nan
                            if relative is not None:
                                rel_component = float(relative) * abs(reading)
                                components.append(rel_component)
                            if absolute is not None:
                                components.append(float(absolute))
                            total = sum(components)
                            lower_power, upper_power = reading - total, reading + total
                            if not all(
                                math.isfinite(v)
                                for v in (*components, total, lower_power, upper_power)
                            ):
                                out[power_state] = (
                                    "unresolved_nonfinite_measurement_uncertainty_arithmetic"
                                )
                                continue
                            out.update(
                                {
                                    f"{channel}_power_relative_uncertainty_component_{unit}": (
                                        rel_component
                                    ),
                                    f"{channel}_power_absolute_uncertainty_component_{unit}": (
                                        math.nan if absolute is None else float(absolute)
                                    ),
                                    f"{channel}_power_measurement_uncertainty_bound_{unit}": total,
                                    f"measured_{channel}_power_lower_bound_{unit}": lower_power,
                                    f"measured_{channel}_power_upper_bound_{unit}": upper_power,
                                    f"{channel}_power_measurement_uncertainty_resolved": True,
                                    power_state: "resolved_power_measurement_uncertainty_bound",
                                }
                            )
                            energy_state = f"{channel}_energy_measurement_uncertainty_state"
                            if row.measurement_time_semantics == "instantaneous_snapshot":
                                out[energy_state] = "not_applicable_instantaneous_snapshot"
                            else:
                                duration_hours = float(row.averaging_interval_seconds) / 3600
                                energy_bound = total * duration_hours
                                energy_reading = reading * duration_hours
                                lower_energy, upper_energy = (
                                    energy_reading - energy_bound,
                                    energy_reading + energy_bound,
                                )
                                if all(
                                    math.isfinite(v)
                                    for v in (
                                        energy_bound,
                                        energy_reading,
                                        lower_energy,
                                        upper_energy,
                                    )
                                ):
                                    bound_field = (
                                        f"{channel}_energy_measurement_uncertainty_bound_{energy}"
                                    )
                                    out.update(
                                        {
                                            bound_field: energy_bound,
                                            f"measured_{channel}_energy_lower_bound_{energy}": (
                                                lower_energy
                                            ),
                                            f"measured_{channel}_energy_upper_bound_{energy}": (
                                                upper_energy
                                            ),
                                            f"{channel}_energy_measurement_uncertainty_resolved": (
                                                True
                                            ),
                                            energy_state: (
                                                "resolved_interval_measurement_energy_uncertainty_bound"
                                            ),
                                        }
                                    )
                                else:
                                    out[energy_state] = (
                                        "unresolved_nonfinite_interval_energy_uncertainty_arithmetic"
                                    )
                        p_ok = out["active_power_measurement_uncertainty_resolved"]
                        q_ok = out["reactive_power_measurement_uncertainty_resolved"]
                        state = (
                            "resolved_active_reactive_measurement_uncertainty"
                            if p_ok and q_ok
                            else "resolved_active_power_measurement_uncertainty_only"
                            if p_ok
                            else "resolved_reactive_power_measurement_uncertainty_only"
                            if q_ok
                            else "unresolved_nonfinite_measurement_uncertainty_arithmetic"
                        )
        if state in _STATES[:4]:
            for channel, _, _ in _CHANNELS:
                out[f"{channel}_power_measurement_uncertainty_state"] = state
        out["measurement_uncertainty_state"] = state
        records.append(out)
    extra = pd.DataFrame(records, index=measured.index.copy(), columns=_EXTRA_COLUMNS)
    for field in _EXTRA_COLUMNS:
        extra[field] = extra[field].astype(
            bool if field in _BOOL else float if field in _FLOAT else object
        )
    for field in (*_VALIDITY, *_OPTIONAL_METADATA):
        extra[field] = pd.Series(
            [record[field] for record in records], index=measured.index, dtype=object
        )
    if set(measured.columns) & set(extra.columns):
        raise ValueError("validator uncertainty schema collides with measurement contract")
    return pd.concat([measured.copy(deep=True), extra], axis=1)


def _validator_diagnostics(
    parent: Any, frame: pd.DataFrame
) -> RevenueMeterMeasurementUncertaintyDiagnostics:
    present = frame.measured_power_authority_resolved.astype(bool)
    admitted = present & frame.measurement_uncertainty_authority_present
    in_date = admitted & frame.measurement_uncertainty_temporally_applicable
    in_scope = in_date & frame.measurement_uncertainty_time_scope_applicable
    active = int(frame.active_power_measurement_uncertainty_resolved.sum())
    reactive = int(frame.reactive_power_measurement_uncertainty_resolved.sum())
    return RevenueMeterMeasurementUncertaintyDiagnostics(
        len(parent.revenue_meter_boundary_by_id),
        len(set(frame.index.get_level_values("timestamp"))),
        len(frame),
        int(present.sum()),
        len(frame) - int(present.sum()),
        int(admitted.sum()),
        int(present.sum()) - int(admitted.sum()),
        int(in_date.sum()),
        int(admitted.sum()) - int(in_date.sum()),
        int(in_scope.sum()),
        int(in_date.sum()) - int(in_scope.sum()),
        active,
        len(frame) - active,
        reactive,
        len(frame) - reactive,
        int(frame.active_energy_measurement_uncertainty_resolved.sum()),
        int(frame.reactive_energy_measurement_uncertainty_resolved.sum()),
        tuple(
            (state, int((frame.measurement_uncertainty_state == state).sum())) for state in _STATES
        ),
        REVENUE_METER_MEASUREMENT_UNCERTAINTY_MODEL_ID,
    )


def _validate_result(
    parent: Any, measured: Any, result: RevenueMeterMeasurementUncertaintyResult, supplied: object
) -> None:
    if type(result) is not RevenueMeterMeasurementUncertaintyResult:
        raise ValueError("exact measurement uncertainty result required")
    mapping = {} if supplied is None else supplied
    if not isinstance(mapping, Mapping):
        raise ValueError("validator requires a meter authority mapping")
    policies = {}
    for meter, authority in mapping.items():
        if type(meter) is not str or meter not in parent.revenue_meter_boundary_by_id:
            raise ValueError("validator uncertainty meter identity is invalid")
        if type(authority) is not RevenueMeterMeasurementUncertaintyAuthority:
            raise ValueError("validator uncertainty authority type is invalid")
        policies[meter] = replace(authority)
    expected = _validator_frame(measured.states, policies)
    _replay("measurement uncertainty", result.states, expected)
    _replay(
        "measurement uncertainty diagnostics",
        result.diagnostics,
        _validator_diagnostics(parent, expected),
    )


def validate_revenue_meter_measurement_uncertainty(
    result: RevenueMeterMeasurementUncertaintyResult,
    *,
    revenue_meter_measurement_uncertainty_by_meter_id: Mapping[
        str, RevenueMeterMeasurementUncertaintyAuthority
    ]
    | None = None,
    **values: Any,
) -> None:
    """Strong parent replay plus independent uncertainty-state reconstruction."""
    parent, measured = _validator_parents(values)
    _validate_result(parent, measured, result, revenue_meter_measurement_uncertainty_by_meter_id)
