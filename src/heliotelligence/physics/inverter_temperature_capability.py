"""Evaluate inverter P/Q/S requests against explicit thermal capability.

S9-4D consumes an explicit timestamped inverter temperature whose physical
basis exactly matches admitted S9-4C authority. It evaluates only: it does not
model temperature, reuse module/cell temperature, extrapolate, dispatch, clamp,
or modify P/Q/S.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from typing import Literal

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import dc_collection, electrical
from heliotelligence.physics.inverter_ac_authority import (
    InverterAcCapabilityAuthority,
    TopologyInverterAcCapabilityAuthorityResult,
)
from heliotelligence.physics.inverter_accounting import (
    TopologySandiaInverterPowerAccountingResult,
)
from heliotelligence.physics.inverter_authority import TopologyInverterAuthorityResult
from heliotelligence.physics.inverter_conversion import TopologySandiaInverterAcResult
from heliotelligence.physics.inverter_potential import TopologySandiaPreLimitAcResult
from heliotelligence.physics.inverter_pqs_capability import (
    InverterReactivePowerRequest,
    TopologyInverterPqsCapabilityResult,
    calculate_topology_inverter_pqs_capability,
)
from heliotelligence.physics.inverter_thermal_authority import (
    InverterThermalDeratingAuthority,
    TopologyInverterThermalDeratingAuthorityResult,
    resolve_topology_inverter_thermal_derating_authority,
)
from heliotelligence.physics.inverter_topology import (
    MpptDcCurrentLimitAuthority,
    TopologyInverterDcEnvelopeResult,
)

TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_CONTRACT_ID = (
    "admitted_inverter_pqs_and_thermal_authority_to_temperature_capability_evaluation_v1"
)
TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_MODEL_ID = (
    "explicit_inverter_temperature_piecewise_thermal_capability_evaluation_v1"
)
TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_SCOPE = (
    "inverter_ac_temperature_dependent_capability_evaluation_before_dispatch_and_ac_network"
)
TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_COVERAGE_SCOPE = (
    "active_inverter_pqs_with_explicit_thermal_authority_and_matching_temperature_state"
)

Confidence = Literal["high", "medium", "low", "unknown"]
_CONFIDENCES = {"high", "medium", "low", "unknown"}
_ABS_TOL = 1e-8

_COLUMNS = (
    "p_ac_available_w", "q_requested_var", "s_requested_va",
    "rated_apparent_power_va", "reactive_power_min_var", "reactive_power_max_var",
    "fixed_reactive_power_limits_resolved", "capability_violation_detected",
    "pqs_capability_satisfied", "full_capability_authority_resolved",
    "pqs_evaluation_applicable", "pqs_evaluation_resolved", "pqs_capability_state",
    "available_reference_plane",
    "inverter_temperature_state_present", "inverter_temperature_c",
    "inverter_temperature_quantity", "inverter_temperature_parameter_source",
    "inverter_temperature_confidence", "temperature_quantity_matches_authority",
    "temperature_within_authority_domain",
    "thermal_authority_temperature_quantity", "thermal_derating_mode",
    "thermal_temperature_min_c", "thermal_temperature_max_c",
    "active_power_thermal_limit_resolved", "apparent_power_thermal_limit_resolved",
    "reactive_power_thermal_limits_resolved", "full_thermal_capability_authority_resolved",
    "thermal_authority_parameter_source", "thermal_authority_confidence",
    "thermal_derating_authority_state",
    "thermal_active_power_limit_w", "thermal_apparent_power_limit_va",
    "thermal_reactive_power_min_var", "thermal_reactive_power_max_var",
    "thermal_active_power_limit_evaluated", "thermal_active_power_limit_satisfied",
    "thermal_apparent_power_limit_evaluated", "thermal_apparent_power_limit_satisfied",
    "thermal_reactive_power_limit_evaluated", "thermal_reactive_power_limit_satisfied",
    "thermal_interpolation_state", "thermal_interpolation_performed",
    "thermal_capability_violation_detected", "thermal_capability_satisfied",
    "temperature_dependent_capability_violation_detected",
    "temperature_dependent_capability_satisfied",
    "temperature_capability_evaluation_applicable",
    "temperature_capability_evaluation_resolved", "temperature_capability_state",
    "topology_inverter_pqs_capability_contract", "topology_inverter_pqs_capability_model",
    "topology_inverter_pqs_capability_scope", "topology_inverter_pqs_capability_coverage_scope",
    "topology_inverter_thermal_derating_authority_contract",
    "topology_inverter_thermal_derating_authority_model",
    "topology_inverter_thermal_derating_authority_scope",
    "topology_inverter_thermal_derating_authority_coverage_scope",
    "topology_inverter_temperature_capability_contract",
    "topology_inverter_temperature_capability_model",
    "topology_inverter_temperature_capability_scope",
    "topology_inverter_temperature_capability_coverage_scope",
)
_NUMERIC = {
    "p_ac_available_w", "q_requested_var", "s_requested_va", "rated_apparent_power_va",
    "reactive_power_min_var", "reactive_power_max_var", "inverter_temperature_c",
    "thermal_temperature_min_c", "thermal_temperature_max_c",
    "thermal_active_power_limit_w", "thermal_apparent_power_limit_va",
    "thermal_reactive_power_min_var", "thermal_reactive_power_max_var",
}
_BOOL = {
    "fixed_reactive_power_limits_resolved", "full_capability_authority_resolved",
    "pqs_evaluation_applicable", "pqs_evaluation_resolved",
    "inverter_temperature_state_present", "active_power_thermal_limit_resolved",
    "apparent_power_thermal_limit_resolved", "reactive_power_thermal_limits_resolved",
    "full_thermal_capability_authority_resolved", "thermal_active_power_limit_evaluated",
    "thermal_apparent_power_limit_evaluated", "thermal_reactive_power_limit_evaluated",
    "thermal_interpolation_performed", "temperature_capability_evaluation_applicable",
    "temperature_capability_evaluation_resolved",
}
_NULLABLE = {
    "capability_violation_detected", "pqs_capability_satisfied",
    "temperature_quantity_matches_authority", "temperature_within_authority_domain",
    "thermal_active_power_limit_satisfied", "thermal_apparent_power_limit_satisfied",
    "thermal_reactive_power_limit_satisfied", "thermal_capability_violation_detected",
    "thermal_capability_satisfied", "temperature_dependent_capability_violation_detected",
    "temperature_dependent_capability_satisfied",
}


@dataclass(frozen=True)
class InverterTemperatureState:
    temperature_c: float
    temperature_quantity: str
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        value = self.temperature_c
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("temperature_c must be a real non-Boolean number")
        temperature = float(value)
        if not math.isfinite(temperature):
            raise ValueError("temperature_c must be finite")
        if type(self.temperature_quantity) is not str or not self.temperature_quantity.strip():
            raise ValueError("temperature_quantity must be a non-empty string")
        if type(self.parameter_source) is not str or not self.parameter_source.strip():
            raise ValueError("parameter_source must be a non-empty string")
        if type(self.confidence) is not str or self.confidence not in _CONFIDENCES:
            raise ValueError("confidence is unsupported")
        object.__setattr__(self, "temperature_c", temperature)


@dataclass(frozen=True)
class TopologyInverterTemperatureCapabilityDiagnostics:
    inverter_count: int
    represented_inverter_count: int
    timestamp_count: int
    row_count: int
    resolved_count: int
    unresolved_count: int
    applicable_count: int
    inactive_not_applicable_count: int
    upstream_pqs_unresolved_count: int
    upstream_known_violation_count: int
    missing_thermal_authority_count: int
    missing_temperature_state_count: int
    temperature_quantity_mismatch_count: int
    temperature_outside_domain_count: int
    explicit_no_derating_evaluated_count: int
    piecewise_thermal_evaluated_count: int
    exact_authority_point_count: int
    linear_interpolation_count: int
    active_thermal_limit_evaluated_count: int
    active_thermal_limit_violation_count: int
    apparent_thermal_limit_evaluated_count: int
    apparent_thermal_limit_violation_count: int
    reactive_thermal_limit_evaluated_count: int
    reactive_thermal_limit_violation_count: int
    full_thermal_authority_count: int
    partial_thermal_authority_count: int
    within_full_capability_count: int
    partial_capability_count: int
    known_capability_violation_count: int
    model: str


@dataclass(frozen=True)
class TopologyInverterTemperatureCapabilityResult:
    capability: pd.DataFrame
    diagnostics: TopologyInverterTemperatureCapabilityDiagnostics


def calculate_topology_inverter_temperature_capability(
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
) -> TopologyInverterTemperatureCapabilityResult:
    """Evaluate admitted P/Q/S against explicit matching-temperature authority."""
    pqs = _admit_pqs(
        topology, topology_string_iv, branch_authority, mppt_input_string_iv,
        mppt_input_operating_points, cec_sam_name_by_inverter_id, inverter_authority,
        mppt_current_limit_by_key, inverter_dc_envelope, inverter_ac, pre_limit_ac,
        inverter_power_accounting, ac_capability_by_inverter_id, ac_capability_authority,
        reactive_power_request_by_key, pqs_capability,
    )
    thermal = _admit_thermal(
        topology, thermal_derating_by_inverter_id, thermal_derating_authority
    )
    temperatures = _admit_temperatures(pqs.index, inverter_temperature_by_key)
    records: list[dict[str, object]] = []
    for key, upstream in pqs.iterrows():
        inverter_id = str(key[1])
        authority_row = thermal.loc[inverter_id]
        authority = thermal_derating_by_inverter_id.get(inverter_id)
        temperature = temperatures.get((pd.Timestamp(key[0]), inverter_id))
        record = _base_record(upstream, authority_row, temperature)
        _classify(record, upstream, authority_row, authority, temperature)
        records.append(record)
    output = pd.DataFrame(records, index=pqs.index.copy(), columns=_COLUMNS)
    _apply_dtypes(output)
    diagnostics = _diagnostics(topology, output)
    _validate_result(pqs, thermal, temperatures, output, diagnostics)
    return TopologyInverterTemperatureCapabilityResult(output.copy(deep=True), diagnostics)


def _admit_pqs(
    topology: ElectricalTopologyConfig,
    topology_string_iv: electrical.TopologyStringIVResult,
    branch_authority: dc_collection.DcBranchPathAuthorityResult,
    mppt_input_string_iv: dc_collection.TopologyMpptInputStringIVResult,
    mppt_input_operating_points: dc_collection.TopologyMpptInputOperatingPointResult,
    names: Mapping[str, str], inverter_authority: TopologyInverterAuthorityResult,
    limits: Mapping[tuple[str, str], MpptDcCurrentLimitAuthority],
    envelope: TopologyInverterDcEnvelopeResult, inverter_ac: TopologySandiaInverterAcResult,
    potential: TopologySandiaPreLimitAcResult,
    accounting: TopologySandiaInverterPowerAccountingResult,
    ac_mapping: Mapping[str, InverterAcCapabilityAuthority],
    ac_authority: TopologyInverterAcCapabilityAuthorityResult,
    requests: Mapping[tuple[pd.Timestamp, str], InverterReactivePowerRequest],
    supplied: object,
) -> pd.DataFrame:
    if type(supplied) is not TopologyInverterPqsCapabilityResult:
        raise ValueError("S9-4B result type is invalid")
    replayed = calculate_topology_inverter_pqs_capability(
        topology, topology_string_iv, branch_authority, mppt_input_string_iv,
        mppt_input_operating_points, names, inverter_authority, limits, envelope,
        inverter_ac, potential, accounting, ac_mapping, ac_authority, requests,
    )
    try:
        pd.testing.assert_frame_equal(supplied.capability, replayed.capability, check_exact=True)
    except AssertionError as exc:
        raise ValueError("S9-4B capability does not match canonical replay") from exc
    if type(supplied.diagnostics) is not type(replayed.diagnostics) or (
        supplied.diagnostics != replayed.diagnostics
    ):
        raise ValueError("S9-4B diagnostics do not match canonical replay")
    return replayed.capability.copy(deep=True)


def _admit_thermal(
    topology: ElectricalTopologyConfig,
    mapping: Mapping[str, InverterThermalDeratingAuthority],
    supplied: object,
) -> pd.DataFrame:
    if type(supplied) is not TopologyInverterThermalDeratingAuthorityResult:
        raise ValueError("S9-4C result type is invalid")
    replayed = resolve_topology_inverter_thermal_derating_authority(topology, mapping)
    try:
        pd.testing.assert_frame_equal(supplied.states, replayed.states, check_exact=True)
    except AssertionError as exc:
        raise ValueError("S9-4C authority does not match canonical replay") from exc
    if supplied.diagnostics != replayed.diagnostics or (
        list(supplied.authorities_by_inverter_id.items())
        != list(replayed.authorities_by_inverter_id.items())
    ):
        raise ValueError("S9-4C authority metadata does not match canonical replay")
    return replayed.states.copy(deep=True)


def _admit_temperatures(
    index: pd.Index,
    supplied: Mapping[tuple[pd.Timestamp, str], InverterTemperatureState],
) -> dict[tuple[pd.Timestamp, str], InverterTemperatureState]:
    if not isinstance(supplied, Mapping):
        raise TypeError("inverter_temperature_by_key must be a mapping")
    canonical = {(pd.Timestamp(key[0]), str(key[1])) for key in index}
    admitted: dict[tuple[pd.Timestamp, str], InverterTemperatureState] = {}
    for key, state in supplied.items():
        if type(key) is not tuple or len(key) != 2 or not isinstance(key[0], pd.Timestamp) or (
            type(key[1]) is not str
        ):
            raise ValueError("inverter temperature keys must be (pd.Timestamp, inverter_id)")
        normalized = (key[0], key[1])
        if normalized not in canonical:
            raise ValueError(f"unexpected inverter temperature key: {key!r}")
        if type(state) is not InverterTemperatureState:
            raise TypeError("every inverter temperature must use the exact state type")
        admitted[normalized] = state
    return admitted


def _base_record(
    upstream: pd.Series, authority: pd.Series, temperature: InverterTemperatureState | None
) -> dict[str, object]:
    copied_pqs = {name: upstream[name] for name in _COLUMNS if name in upstream.index}
    record: dict[str, object] = dict(copied_pqs)
    for source, target in (
        ("temperature_quantity", "thermal_authority_temperature_quantity"),
        ("derating_mode", "thermal_derating_mode"),
        ("temperature_min_c", "thermal_temperature_min_c"),
        ("temperature_max_c", "thermal_temperature_max_c"),
        ("parameter_source", "thermal_authority_parameter_source"),
        ("confidence", "thermal_authority_confidence"),
    ):
        record[target] = authority[source]
    for name in (
        "active_power_thermal_limit_resolved", "apparent_power_thermal_limit_resolved",
        "reactive_power_thermal_limits_resolved", "thermal_derating_authority_state",
        "topology_inverter_thermal_derating_authority_contract",
        "topology_inverter_thermal_derating_authority_model",
        "topology_inverter_thermal_derating_authority_scope",
        "topology_inverter_thermal_derating_authority_coverage_scope",
    ):
        record[name] = authority[name]
    record.update(
        inverter_temperature_state_present=temperature is not None,
        inverter_temperature_c=np.nan if temperature is None else temperature.temperature_c,
        inverter_temperature_quantity=(
            "" if temperature is None else temperature.temperature_quantity
        ),
        inverter_temperature_parameter_source=(
            "" if temperature is None else temperature.parameter_source
        ),
        inverter_temperature_confidence=(
            "unknown" if temperature is None else temperature.confidence
        ),
        temperature_quantity_matches_authority=pd.NA,
        temperature_within_authority_domain=pd.NA,
        full_thermal_capability_authority_resolved=_full_thermal(authority),
        thermal_active_power_limit_w=np.nan,
        thermal_apparent_power_limit_va=np.nan,
        thermal_reactive_power_min_var=np.nan,
        thermal_reactive_power_max_var=np.nan,
        thermal_active_power_limit_evaluated=False,
        thermal_active_power_limit_satisfied=pd.NA,
        thermal_apparent_power_limit_evaluated=False,
        thermal_apparent_power_limit_satisfied=pd.NA,
        thermal_reactive_power_limit_evaluated=False,
        thermal_reactive_power_limit_satisfied=pd.NA,
        thermal_interpolation_state="not_evaluated",
        thermal_interpolation_performed=False,
        thermal_capability_violation_detected=pd.NA,
        thermal_capability_satisfied=pd.NA,
        temperature_dependent_capability_violation_detected=pd.NA,
        temperature_dependent_capability_satisfied=pd.NA,
        temperature_capability_evaluation_applicable=False,
        temperature_capability_evaluation_resolved=False,
        temperature_capability_state="",
        topology_inverter_temperature_capability_contract=(
            TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_CONTRACT_ID
        ),
        topology_inverter_temperature_capability_model=(
            TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_MODEL_ID
        ),
        topology_inverter_temperature_capability_scope=(
            TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_SCOPE
        ),
        topology_inverter_temperature_capability_coverage_scope=(
            TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_COVERAGE_SCOPE
        ),
    )
    return record


def _full_thermal(authority: pd.Series) -> bool:
    if not bool(authority["thermal_derating_authority_resolved"]):
        return False
    return authority["derating_mode"] == "explicit_no_derating" or all(
        bool(authority[name])
        for name in (
            "active_power_thermal_limit_resolved",
            "apparent_power_thermal_limit_resolved",
            "reactive_power_thermal_limits_resolved",
        )
    )


def _classify(
    record: dict[str, object], upstream: pd.Series, authority_row: pd.Series,
    authority: InverterThermalDeratingAuthority | None,
    temperature: InverterTemperatureState | None,
) -> None:
    if not bool(upstream["pqs_evaluation_resolved"]):
        record["temperature_capability_state"] = "unresolved_upstream_pqs_capability"
        return
    if not bool(upstream["pqs_evaluation_applicable"]):
        record.update(
            temperature_capability_evaluation_resolved=True,
            temperature_capability_state=(
                "resolved_temperature_capability_not_applicable_inactive_ac_state"
            ),
        )
        return
    if _is_true(upstream["capability_violation_detected"]):
        record.update(
            temperature_capability_evaluation_resolved=True,
            temperature_capability_evaluation_applicable=True,
            temperature_dependent_capability_violation_detected=True,
            temperature_dependent_capability_satisfied=False,
            temperature_capability_state=(
                "resolved_temperature_dependent_known_capability_violation"
            ),
        )
        return
    if authority is None or not bool(authority_row["thermal_derating_authority_resolved"]):
        record["temperature_capability_state"] = (
            "unresolved_no_explicit_inverter_thermal_derating_authority"
        )
        return
    if temperature is None:
        record["temperature_capability_state"] = (
            "unresolved_no_explicit_inverter_temperature_state"
        )
        return
    matches = temperature.temperature_quantity == authority.temperature_quantity
    record["temperature_quantity_matches_authority"] = matches
    if not matches:
        record["temperature_capability_state"] = (
            "unresolved_inverter_temperature_quantity_mismatch"
        )
        return
    inside = authority.temperature_points_c[0] <= temperature.temperature_c <= (
        authority.temperature_points_c[-1]
    )
    record["temperature_within_authority_domain"] = inside
    if not inside:
        record["temperature_capability_state"] = (
            "unresolved_inverter_temperature_outside_authority_domain"
        )
        return
    if authority.derating_mode == "explicit_no_derating":
        record.update(
            thermal_interpolation_state="explicit_no_derating_domain",
            thermal_capability_violation_detected=False,
            thermal_capability_satisfied=True,
        )
    else:
        exact = temperature.temperature_c in authority.temperature_points_c
        record["thermal_interpolation_state"] = (
            "exact_authority_point" if exact else "between_authority_points"
        )
        record["thermal_interpolation_performed"] = not exact
        _evaluate_channels(record, upstream, authority, temperature.temperature_c)
    thermal_violation = bool(record["thermal_capability_violation_detected"])
    static_pass = _is_true(upstream["pqs_capability_satisfied"])
    thermal_pass = _is_true(record["thermal_capability_satisfied"])
    known_violation = thermal_violation
    satisfied: object = (
        False if known_violation else True if static_pass and thermal_pass else pd.NA
    )
    full_success = satisfied is True
    record.update(
        temperature_capability_evaluation_resolved=True,
        temperature_capability_evaluation_applicable=True,
        temperature_dependent_capability_violation_detected=known_violation,
        temperature_dependent_capability_satisfied=satisfied,
        temperature_capability_state=(
            "resolved_temperature_dependent_known_capability_violation"
            if known_violation
            else "resolved_temperature_dependent_within_full_capability"
            if full_success
            else "resolved_temperature_dependent_partial_capability_authority"
        ),
    )


def _is_true(value: object) -> bool:
    return not pd.isna(value) and bool(value)


def _evaluate_channels(
    record: dict[str, object], upstream: pd.Series,
    authority: InverterThermalDeratingAuthority, temperature: float,
) -> None:
    results: list[bool] = []
    if authority.active_power_limit_w is not None:
        limit = _interpolate(
            authority.temperature_points_c, authority.active_power_limit_w, temperature
        )
        passed = float(upstream["p_ac_available_w"]) <= limit + _ABS_TOL
        record.update(thermal_active_power_limit_w=limit,
                      thermal_active_power_limit_evaluated=True,
                      thermal_active_power_limit_satisfied=passed)
        results.append(passed)
    if authority.apparent_power_limit_va is not None:
        limit = _interpolate(
            authority.temperature_points_c, authority.apparent_power_limit_va, temperature
        )
        passed = float(upstream["s_requested_va"]) <= limit + _ABS_TOL
        record.update(thermal_apparent_power_limit_va=limit,
                      thermal_apparent_power_limit_evaluated=True,
                      thermal_apparent_power_limit_satisfied=passed)
        results.append(passed)
    if (
        authority.reactive_power_min_var is not None
        and authority.reactive_power_max_var is not None
    ):
        low = _interpolate(
            authority.temperature_points_c, authority.reactive_power_min_var, temperature
        )
        high = _interpolate(
            authority.temperature_points_c, authority.reactive_power_max_var, temperature
        )
        q = float(upstream["q_requested_var"])
        passed = low - _ABS_TOL <= q <= high + _ABS_TOL
        record.update(thermal_reactive_power_min_var=low,
                      thermal_reactive_power_max_var=high,
                      thermal_reactive_power_limit_evaluated=True,
                      thermal_reactive_power_limit_satisfied=passed)
        results.append(passed)
    violation = any(not result for result in results)
    record["thermal_capability_violation_detected"] = violation
    record["thermal_capability_satisfied"] = (
        False if violation else True if bool(record["full_thermal_capability_authority_resolved"])
        else pd.NA
    )


def _interpolate(points: tuple[float, ...], values: tuple[float, ...], temperature: float) -> float:
    for point, value in zip(points, values, strict=True):
        if temperature == point:
            return value
    for index in range(len(points) - 1):
        low_t, high_t = points[index], points[index + 1]
        if low_t < temperature < high_t:
            low_y, high_y = values[index], values[index + 1]
            return low_y + (high_y - low_y) * (temperature - low_t) / (high_t - low_t)
    raise RuntimeError("temperature is outside admitted authority domain")


def _apply_dtypes(frame: pd.DataFrame) -> None:
    frame.index = pd.MultiIndex.from_tuples(
        frame.index.tolist(), names=["timestamp", "inverter_id"]
    )
    for column in _NUMERIC:
        frame[column] = frame[column].astype("float64")
    for column in _BOOL:
        frame[column] = frame[column].astype(bool)
    for column in _NULLABLE:
        frame[column] = frame[column].astype("boolean")
    for column in set(_COLUMNS) - _NUMERIC - _BOOL - _NULLABLE:
        frame[column] = frame[column].astype(object)


def _diagnostics(
    topology: ElectricalTopologyConfig, output: pd.DataFrame
) -> TopologyInverterTemperatureCapabilityDiagnostics:
    states = output["temperature_capability_state"]
    def count(state: str) -> int:
        return int((states == state).sum())
    active_eval = output["thermal_active_power_limit_evaluated"]
    apparent_eval = output["thermal_apparent_power_limit_evaluated"]
    reactive_eval = output["thermal_reactive_power_limit_evaluated"]
    return TopologyInverterTemperatureCapabilityDiagnostics(
        inverter_count=topology.inverter_count,
        represented_inverter_count=len(set(output.index.get_level_values("inverter_id"))),
        timestamp_count=len(set(output.index.get_level_values("timestamp"))),
        row_count=len(output),
        resolved_count=int(output["temperature_capability_evaluation_resolved"].sum()),
        unresolved_count=int((~output["temperature_capability_evaluation_resolved"]).sum()),
        applicable_count=int(output["temperature_capability_evaluation_applicable"].sum()),
        inactive_not_applicable_count=count(
            "resolved_temperature_capability_not_applicable_inactive_ac_state"
        ),
        upstream_pqs_unresolved_count=count("unresolved_upstream_pqs_capability"),
        upstream_known_violation_count=int(
            ((output["temperature_capability_state"] ==
              "resolved_temperature_dependent_known_capability_violation") &
             (output["capability_violation_detected"] == True)).sum()  # noqa: E712
        ),
        missing_thermal_authority_count=count(
            "unresolved_no_explicit_inverter_thermal_derating_authority"
        ),
        missing_temperature_state_count=count(
            "unresolved_no_explicit_inverter_temperature_state"
        ),
        temperature_quantity_mismatch_count=count(
            "unresolved_inverter_temperature_quantity_mismatch"
        ),
        temperature_outside_domain_count=count(
            "unresolved_inverter_temperature_outside_authority_domain"
        ),
        explicit_no_derating_evaluated_count=int(
            (output["thermal_interpolation_state"] == "explicit_no_derating_domain").sum()
        ),
        piecewise_thermal_evaluated_count=int(
            output["thermal_interpolation_state"].isin(
                ["exact_authority_point", "between_authority_points"]
            ).sum()
        ),
        exact_authority_point_count=int(
            (output["thermal_interpolation_state"] == "exact_authority_point").sum()
        ),
        linear_interpolation_count=int(output["thermal_interpolation_performed"].sum()),
        active_thermal_limit_evaluated_count=int(active_eval.sum()),
        active_thermal_limit_violation_count=int(
            (active_eval & (output["thermal_active_power_limit_satisfied"] == False)).sum()  # noqa: E712
        ),
        apparent_thermal_limit_evaluated_count=int(apparent_eval.sum()),
        apparent_thermal_limit_violation_count=int(
            (apparent_eval & (output["thermal_apparent_power_limit_satisfied"] == False)).sum()  # noqa: E712
        ),
        reactive_thermal_limit_evaluated_count=int(reactive_eval.sum()),
        reactive_thermal_limit_violation_count=int(
            (reactive_eval & (output["thermal_reactive_power_limit_satisfied"] == False)).sum()  # noqa: E712
        ),
        full_thermal_authority_count=int(
            output["full_thermal_capability_authority_resolved"].sum()
        ),
        partial_thermal_authority_count=int(
            ((output["thermal_derating_authority_state"] !=
              "unresolved_no_explicit_inverter_thermal_derating_authority") &
             ~output["full_thermal_capability_authority_resolved"]).sum()
        ),
        within_full_capability_count=count(
            "resolved_temperature_dependent_within_full_capability"
        ),
        partial_capability_count=count(
            "resolved_temperature_dependent_partial_capability_authority"
        ),
        known_capability_violation_count=count(
            "resolved_temperature_dependent_known_capability_violation"
        ),
        model=TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_MODEL_ID,
    )


def _validate_result(
    pqs: pd.DataFrame, thermal: pd.DataFrame,
    temperatures: Mapping[tuple[pd.Timestamp, str], InverterTemperatureState],
    output: pd.DataFrame, diagnostics: TopologyInverterTemperatureCapabilityDiagnostics,
) -> None:
    if tuple(output.columns) != _COLUMNS or output.index.names != ["timestamp", "inverter_id"]:
        raise RuntimeError("temperature capability schema or index is invalid")
    if output.index.has_duplicates or not output.index.equals(pqs.index):
        raise RuntimeError("temperature capability ordering is invalid")
    if diagnostics.row_count != len(output) or (
        diagnostics.resolved_count + diagnostics.unresolved_count != len(output)
    ):
        raise RuntimeError("temperature capability diagnostics do not close")
    if diagnostics.model != TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_MODEL_ID:
        raise RuntimeError("temperature capability diagnostics model is invalid")
    for key, row in output.iterrows():
        upstream = pqs.loc[key]
        for name in (
            "p_ac_available_w", "q_requested_var", "s_requested_va", "pqs_capability_state",
            "available_reference_plane", "pqs_evaluation_resolved",
            "pqs_evaluation_applicable", "full_capability_authority_resolved",
        ):
            expected, actual = upstream[name], row[name]
            if pd.isna(expected):
                if not pd.isna(actual):
                    raise RuntimeError(f"S9-4B replay field {name} is invalid")
            elif actual != expected:
                raise RuntimeError(f"S9-4B replay field {name} is invalid")
        authority = thermal.loc[str(key[1])]
        if row["thermal_derating_authority_state"] != authority["thermal_derating_authority_state"]:
            raise RuntimeError("S9-4C replay state is invalid")
        temperature = temperatures.get((pd.Timestamp(key[0]), str(key[1])))
        if bool(row["inverter_temperature_state_present"]) != (temperature is not None):
            raise RuntimeError("temperature-state presence is invalid")
        if row["topology_inverter_temperature_capability_contract"] != (
            TOPOLOGY_INVERTER_TEMPERATURE_CAPABILITY_CONTRACT_ID
        ):
            raise RuntimeError("temperature capability provenance is invalid")
