"""Evaluate exact inverter P/Q dispatch requests against admitted capability.

S10B evaluates only. It never selects, clamps, persists, or modifies P/Q/S,
and it does not infer plant-export or network feasibility.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import dc_collection, electrical
from heliotelligence.physics.inverter_ac_authority import (
    InverterAcCapabilityAuthority,
    TopologyInverterAcCapabilityAuthorityResult,
)
from heliotelligence.physics.inverter_accounting import TopologySandiaInverterPowerAccountingResult
from heliotelligence.physics.inverter_authority import TopologyInverterAuthorityResult
from heliotelligence.physics.inverter_conversion import TopologySandiaInverterAcResult
from heliotelligence.physics.inverter_dispatch_request_authority import (
    InverterActivePowerDispatchRequest,
    TopologyInverterActivePowerDispatchRequestAuthorityResult,
    resolve_topology_inverter_active_power_dispatch_request_authority,
)
from heliotelligence.physics.inverter_potential import TopologySandiaPreLimitAcResult
from heliotelligence.physics.inverter_pqs_capability import (
    InverterReactivePowerRequest,
    TopologyInverterPqsCapabilityResult,
)
from heliotelligence.physics.inverter_temperature_capability import (
    InverterTemperatureState,
    TopologyInverterTemperatureCapabilityResult,
    calculate_topology_inverter_temperature_capability,
)
from heliotelligence.physics.inverter_thermal_authority import (
    InverterThermalDeratingAuthority,
    TopologyInverterThermalDeratingAuthorityResult,
)
from heliotelligence.physics.inverter_topology import (
    MpptDcCurrentLimitAuthority,
    TopologyInverterDcEnvelopeResult,
)

TOPOLOGY_INVERTER_DISPATCH_FEASIBILITY_CONTRACT_ID = (
    "admitted_inverter_capability_and_dispatch_request_to_feasibility_evaluation_v1"
)
TOPOLOGY_INVERTER_DISPATCH_FEASIBILITY_MODEL_ID = (
    "explicit_requested_pq_against_available_static_and_thermal_capability_v1"
)
TOPOLOGY_INVERTER_DISPATCH_FEASIBILITY_SCOPE = (
    "inverter_ac_dispatch_request_feasibility_before_selection_and_ac_network"
)
TOPOLOGY_INVERTER_DISPATCH_FEASIBILITY_COVERAGE_SCOPE = (
    "per_inverter_requested_pq_against_available_ac_static_and_thermal_capability"
)
_ABS_TOL = 1e-8

_NUMERIC = {
    "p_ac_available_w",
    "p_requested_w",
    "q_requested_var",
    "s_requested_va",
    "rated_apparent_power_va",
    "reactive_power_min_var",
    "reactive_power_max_var",
    "active_power_availability_limit_w",
    "active_power_availability_margin_w",
    "thermal_active_power_limit_w",
    "thermal_apparent_power_limit_va",
    "thermal_reactive_power_min_var",
    "thermal_reactive_power_max_var",
    "inverter_temperature_c",
}
_BOOL = {
    "active_power_dispatch_request_present",
    "reactive_power_request_present",
    "requested_pq_complete",
    "fixed_reactive_power_limits_resolved",
    "full_static_capability_authority_resolved",
    "active_power_availability_evaluated",
    "static_apparent_power_limit_evaluated",
    "static_fixed_q_limit_evaluated",
    "thermal_active_power_limit_evaluated",
    "thermal_apparent_power_limit_evaluated",
    "thermal_reactive_power_limit_evaluated",
    "full_thermal_capability_authority_resolved",
    "dispatch_feasibility_evaluation_applicable",
    "dispatch_feasibility_evaluation_resolved",
}
_NULLABLE = {
    "active_power_setpoint_is_zero",
    "active_power_availability_satisfied",
    "static_apparent_power_limit_satisfied",
    "static_fixed_q_limit_satisfied",
    "thermal_active_power_limit_satisfied",
    "thermal_apparent_power_limit_satisfied",
    "thermal_reactive_power_limit_satisfied",
    "dispatch_feasibility_violation_detected",
    "dispatch_feasibility_satisfied",
}
_COLUMNS = (
    "p_ac_available_w",
    "available_reference_plane",
    "active_power_dispatch_request_present",
    "p_requested_w",
    "active_power_setpoint_is_zero",
    "active_power_request_source",
    "active_power_request_confidence",
    "controller_mode",
    "reactive_power_request_present",
    "q_requested_var",
    "reactive_power_request_source",
    "reactive_power_request_confidence",
    "reactive_power_request_direction",
    "requested_pq_complete",
    "s_requested_va",
    "rated_apparent_power_va",
    "reactive_power_min_var",
    "reactive_power_max_var",
    "fixed_reactive_power_limits_resolved",
    "full_static_capability_authority_resolved",
    "active_power_availability_limit_w",
    "active_power_availability_margin_w",
    "active_power_availability_evaluated",
    "active_power_availability_satisfied",
    "static_apparent_power_limit_evaluated",
    "static_apparent_power_limit_satisfied",
    "static_fixed_q_limit_evaluated",
    "static_fixed_q_limit_satisfied",
    "inverter_temperature_c",
    "inverter_temperature_quantity",
    "thermal_authority_temperature_quantity",
    "thermal_derating_mode",
    "thermal_active_power_limit_w",
    "thermal_apparent_power_limit_va",
    "thermal_reactive_power_min_var",
    "thermal_reactive_power_max_var",
    "thermal_active_power_limit_evaluated",
    "thermal_active_power_limit_satisfied",
    "thermal_apparent_power_limit_evaluated",
    "thermal_apparent_power_limit_satisfied",
    "thermal_reactive_power_limit_evaluated",
    "thermal_reactive_power_limit_satisfied",
    "full_thermal_capability_authority_resolved",
    "thermal_evaluation_state",
    "dispatch_feasibility_violation_detected",
    "dispatch_feasibility_satisfied",
    "dispatch_feasibility_evaluation_applicable",
    "dispatch_feasibility_evaluation_resolved",
    "dispatch_feasibility_state",
    "topology_inverter_temperature_capability_contract",
    "topology_inverter_temperature_capability_model",
    "topology_inverter_temperature_capability_scope",
    "topology_inverter_temperature_capability_coverage_scope",
    "topology_inverter_active_power_dispatch_request_authority_contract",
    "topology_inverter_active_power_dispatch_request_authority_model",
    "topology_inverter_active_power_dispatch_request_authority_scope",
    "topology_inverter_active_power_dispatch_request_authority_coverage_scope",
    "topology_inverter_dispatch_feasibility_contract",
    "topology_inverter_dispatch_feasibility_model",
    "topology_inverter_dispatch_feasibility_scope",
    "topology_inverter_dispatch_feasibility_coverage_scope",
)


@dataclass(frozen=True)
class TopologyInverterDispatchFeasibilityDiagnostics:
    inverter_count: int
    represented_inverter_count: int
    timestamp_count: int
    row_count: int
    resolved_count: int
    unresolved_count: int
    applicable_count: int
    inactive_count: int
    missing_p_request_count: int
    missing_q_request_count: int
    missing_static_authority_count: int
    upstream_availability_unresolved_count: int
    thermal_prerequisite_unresolved_count: int
    availability_evaluated_count: int
    availability_violation_count: int
    static_s_evaluated_count: int
    static_s_violation_count: int
    fixed_q_evaluated_count: int
    fixed_q_violation_count: int
    thermal_p_violation_count: int
    thermal_s_violation_count: int
    thermal_q_violation_count: int
    full_feasible_count: int
    partial_authority_count: int
    known_infeasible_count: int
    model: str


@dataclass(frozen=True)
class TopologyInverterDispatchFeasibilityResult:
    feasibility: pd.DataFrame
    diagnostics: TopologyInverterDispatchFeasibilityDiagnostics


def calculate_topology_inverter_dispatch_feasibility(
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
    temperature_capability: TopologyInverterTemperatureCapabilityResult,
    active_power_dispatch_request_by_key: Mapping[
        tuple[pd.Timestamp, str], InverterActivePowerDispatchRequest
    ],
    dispatch_request_authority: TopologyInverterActivePowerDispatchRequestAuthorityResult,
) -> TopologyInverterDispatchFeasibilityResult:
    parent = _admit_parents(
        topology,
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        cec_sam_name_by_inverter_id,
        inverter_authority,
        mppt_current_limit_by_key,
        inverter_dc_envelope,
        inverter_ac,
        pre_limit_ac,
        inverter_power_accounting,
        ac_capability_by_inverter_id,
        ac_capability_authority,
        reactive_power_request_by_key,
        pqs_capability,
        thermal_derating_by_inverter_id,
        thermal_derating_authority,
        inverter_temperature_by_key,
        temperature_capability,
        active_power_dispatch_request_by_key,
        dispatch_request_authority,
    )
    thermal_states, request_states = parent
    output = _build(
        thermal_states,
        request_states,
        reactive_power_request_by_key,
        thermal_derating_by_inverter_id,
        inverter_temperature_by_key,
    )
    diagnostics = _diagnostics(topology, output)
    expected = _build(
        thermal_states,
        request_states,
        reactive_power_request_by_key,
        thermal_derating_by_inverter_id,
        inverter_temperature_by_key,
    )
    try:
        pd.testing.assert_frame_equal(output, expected, check_exact=True)
    except AssertionError as exc:
        raise RuntimeError("S10B feasibility result failed exact closure") from exc
    if diagnostics != _diagnostics(topology, expected):
        raise RuntimeError("S10B diagnostics failed exact closure")
    return TopologyInverterDispatchFeasibilityResult(output.copy(deep=True), diagnostics)


def _admit_parents(
    topology: ElectricalTopologyConfig,
    topology_string_iv: electrical.TopologyStringIVResult,
    branch_authority: dc_collection.DcBranchPathAuthorityResult,
    mppt_input_string_iv: dc_collection.TopologyMpptInputStringIVResult,
    mppt_input_operating_points: dc_collection.TopologyMpptInputOperatingPointResult,
    names: Mapping[str, str],
    inverter_authority: TopologyInverterAuthorityResult,
    limits: Mapping[tuple[str, str], MpptDcCurrentLimitAuthority],
    envelope: TopologyInverterDcEnvelopeResult,
    inverter_ac: TopologySandiaInverterAcResult,
    potential: TopologySandiaPreLimitAcResult,
    accounting: TopologySandiaInverterPowerAccountingResult,
    ac_mapping: Mapping[str, InverterAcCapabilityAuthority],
    ac_authority: TopologyInverterAcCapabilityAuthorityResult,
    q_requests: Mapping[tuple[pd.Timestamp, str], InverterReactivePowerRequest],
    pqs: TopologyInverterPqsCapabilityResult,
    thermal_mapping: Mapping[str, InverterThermalDeratingAuthority],
    thermal_authority: TopologyInverterThermalDeratingAuthorityResult,
    temperatures: Mapping[tuple[pd.Timestamp, str], InverterTemperatureState],
    supplied_temperature: object,
    p_requests: Mapping[tuple[pd.Timestamp, str], InverterActivePowerDispatchRequest],
    supplied_requests: object,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if type(supplied_temperature) is not TopologyInverterTemperatureCapabilityResult:
        raise ValueError("S9-4D result type is invalid")
    replayed_temperature = calculate_topology_inverter_temperature_capability(
        topology,
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        names,
        inverter_authority,
        limits,
        envelope,
        inverter_ac,
        potential,
        accounting,
        ac_mapping,
        ac_authority,
        q_requests,
        pqs,
        thermal_mapping,
        thermal_authority,
        temperatures,
    )
    try:
        pd.testing.assert_frame_equal(
            supplied_temperature.capability, replayed_temperature.capability, check_exact=True
        )
    except AssertionError as exc:
        raise ValueError("S9-4D capability does not match canonical replay") from exc
    if supplied_temperature.diagnostics != replayed_temperature.diagnostics:
        raise ValueError("S9-4D diagnostics do not match canonical replay")
    if type(supplied_requests) is not TopologyInverterActivePowerDispatchRequestAuthorityResult:
        raise ValueError("S10A result type is invalid")
    replayed_requests = resolve_topology_inverter_active_power_dispatch_request_authority(
        topology,
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        names,
        inverter_authority,
        limits,
        envelope,
        inverter_ac,
        potential,
        accounting,
        ac_mapping,
        ac_authority,
        q_requests,
        pqs,
        thermal_mapping,
        thermal_authority,
        temperatures,
        replayed_temperature,
        p_requests,
    )
    try:
        pd.testing.assert_frame_equal(
            supplied_requests.states, replayed_requests.states, check_exact=True
        )
    except AssertionError as exc:
        raise ValueError("S10A states do not match canonical replay") from exc
    if supplied_requests.diagnostics != replayed_requests.diagnostics or list(
        supplied_requests.requests_by_key.items()
    ) != list(replayed_requests.requests_by_key.items()):
        raise ValueError("S10A metadata does not match canonical replay")
    return replayed_temperature.capability.copy(deep=True), replayed_requests.states.copy(deep=True)


def _build(
    parent: pd.DataFrame,
    p_states: pd.DataFrame,
    q_requests: Mapping[tuple[pd.Timestamp, str], InverterReactivePowerRequest],
    thermal_mapping: Mapping[str, InverterThermalDeratingAuthority],
    temperatures: Mapping[tuple[pd.Timestamp, str], InverterTemperatureState],
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for key, upstream in parent.iterrows():
        canonical_key = (pd.Timestamp(key[0]), str(key[1]))
        p_state = p_states.loc[key]
        q_request = q_requests.get(canonical_key)
        authority = thermal_mapping.get(canonical_key[1])
        temperature = temperatures.get(canonical_key)
        records.append(_row(upstream, p_state, q_request, authority, temperature))
    frame = pd.DataFrame(records, index=parent.index.copy(), columns=_COLUMNS)
    for column in _NUMERIC:
        frame[column] = frame[column].astype("float64")
    for column in _BOOL:
        frame[column] = frame[column].astype("bool")
    for column in _NULLABLE:
        frame[column] = frame[column].astype("boolean")
    for column in set(_COLUMNS) - _NUMERIC - _BOOL - _NULLABLE:
        frame[column] = frame[column].astype("object")
    return frame


def _row(
    upstream: pd.Series,
    p_state: pd.Series,
    q_request: InverterReactivePowerRequest | None,
    authority: InverterThermalDeratingAuthority | None,
    temperature: InverterTemperatureState | None,
) -> dict[str, object]:
    p_present = bool(p_state["active_power_dispatch_request_present"])
    p = float(p_state["active_power_setpoint_w"]) if p_present else math.nan
    q_present = q_request is not None
    q = q_request.reactive_power_request_var if q_request else math.nan
    complete = p_present and q_present
    requested_s = math.hypot(p, q) if complete else math.nan
    available = float(upstream["p_ac_available_w"])
    smax = float(upstream["rated_apparent_power_va"])
    static_known = math.isfinite(smax)
    fixed_q = bool(upstream["fixed_reactive_power_limits_resolved"])
    qmin = float(upstream["reactive_power_min_var"])
    qmax = float(upstream["reactive_power_max_var"])
    inactive = upstream["pqs_capability_state"] == "resolved_pqs_not_applicable_inactive_ac_state"

    availability_eval = p_present and math.isfinite(available)
    availability_ok: object = p <= available + _ABS_TOL if availability_eval else pd.NA
    static_s_eval = static_known and (
        complete or (p_present and p > smax + _ABS_TOL) or (q_present and abs(q) > smax + _ABS_TOL)
    )
    static_s_ok: object = (
        ((requested_s <= smax + _ABS_TOL) if complete else False) if static_s_eval else pd.NA
    )
    fixed_q_eval = fixed_q and q_present
    fixed_q_ok: object = qmin - _ABS_TOL <= q <= qmax + _ABS_TOL if fixed_q_eval else pd.NA

    thermal = _thermal(authority, temperature, p if p_present else None, q if q_present else None)
    checks = [availability_ok, static_s_ok, fixed_q_ok] + [
        thermal[name]
        for name in (
            "thermal_active_power_limit_satisfied",
            "thermal_apparent_power_limit_satisfied",
            "thermal_reactive_power_limit_satisfied",
        )
    ]
    violation = any(not bool(value) for value in checks if not pd.isna(value))
    static_authority_present = static_known
    thermal_unresolved = str(thermal["thermal_evaluation_state"]).startswith("unresolved_")

    if inactive:
        state = "resolved_dispatch_feasibility_not_applicable_inactive_ac_state"
        resolved, applicable, violation_value, satisfied = True, False, pd.NA, pd.NA
    elif violation:
        state = "resolved_requested_dispatch_known_infeasible"
        resolved, applicable, violation_value, satisfied = True, True, True, False
    elif not p_present:
        state = "unresolved_no_explicit_active_power_dispatch_request"
        resolved, applicable, violation_value, satisfied = False, False, pd.NA, pd.NA
    elif not q_present:
        state = "unresolved_no_explicit_reactive_power_request"
        resolved, applicable, violation_value, satisfied = False, False, pd.NA, pd.NA
    elif not static_authority_present:
        state = "unresolved_no_explicit_ac_capability_authority"
        resolved, applicable, violation_value, satisfied = False, False, pd.NA, pd.NA
    elif not math.isfinite(available):
        state = "unresolved_upstream_inverter_ac_availability"
        resolved, applicable, violation_value, satisfied = False, False, pd.NA, pd.NA
    elif thermal_unresolved:
        state = str(thermal["thermal_evaluation_state"])
        resolved, applicable, violation_value, satisfied = False, False, pd.NA, pd.NA
    else:
        full_static = fixed_q
        full_thermal = bool(thermal["full_thermal_capability_authority_resolved"])
        if full_static and full_thermal:
            state = "resolved_requested_dispatch_feasible_full_capability"
            resolved, applicable, violation_value, satisfied = True, True, False, True
        else:
            state = "resolved_requested_dispatch_partial_capability_authority"
            resolved, applicable, violation_value, satisfied = True, True, False, pd.NA

    q_direction = (
        "not_evaluated"
        if not q_present
        else ("injection" if q > 0 else "absorption" if q < 0 else "zero")
    )
    record: dict[str, object] = {
        "p_ac_available_w": available,
        "available_reference_plane": upstream["available_reference_plane"],
        "active_power_dispatch_request_present": p_present,
        "p_requested_w": p,
        "active_power_setpoint_is_zero": p_state["active_power_setpoint_is_zero"],
        "active_power_request_source": p_state["parameter_source"],
        "active_power_request_confidence": p_state["confidence"],
        "controller_mode": p_state["controller_mode"],
        "reactive_power_request_present": q_present,
        "q_requested_var": q,
        "reactive_power_request_source": q_request.parameter_source if q_request else "",
        "reactive_power_request_confidence": q_request.confidence if q_request else "unknown",
        "reactive_power_request_direction": q_direction,
        "requested_pq_complete": complete,
        "s_requested_va": requested_s,
        "rated_apparent_power_va": smax,
        "reactive_power_min_var": qmin,
        "reactive_power_max_var": qmax,
        "fixed_reactive_power_limits_resolved": fixed_q,
        "full_static_capability_authority_resolved": fixed_q and static_known,
        "active_power_availability_limit_w": available if math.isfinite(available) else math.nan,
        "active_power_availability_margin_w": available - p if availability_eval else math.nan,
        "active_power_availability_evaluated": availability_eval,
        "active_power_availability_satisfied": availability_ok,
        "static_apparent_power_limit_evaluated": static_s_eval,
        "static_apparent_power_limit_satisfied": static_s_ok,
        "static_fixed_q_limit_evaluated": fixed_q_eval,
        "static_fixed_q_limit_satisfied": fixed_q_ok,
        "inverter_temperature_c": temperature.temperature_c if temperature else math.nan,
        "inverter_temperature_quantity": temperature.temperature_quantity if temperature else "",
        "thermal_authority_temperature_quantity": authority.temperature_quantity
        if authority
        else "",
        "thermal_derating_mode": authority.derating_mode if authority else "",
        **thermal,
        "dispatch_feasibility_violation_detected": violation_value,
        "dispatch_feasibility_satisfied": satisfied,
        "dispatch_feasibility_evaluation_applicable": applicable,
        "dispatch_feasibility_evaluation_resolved": resolved,
        "dispatch_feasibility_state": state,
    }
    for name in ("contract", "model", "scope", "coverage_scope"):
        record[f"topology_inverter_temperature_capability_{name}"] = upstream[
            f"topology_inverter_temperature_capability_{name}"
        ]
        record[f"topology_inverter_active_power_dispatch_request_authority_{name}"] = p_state[
            f"topology_inverter_active_power_dispatch_request_authority_{name}"
        ]
    record.update(
        topology_inverter_dispatch_feasibility_contract=TOPOLOGY_INVERTER_DISPATCH_FEASIBILITY_CONTRACT_ID,
        topology_inverter_dispatch_feasibility_model=TOPOLOGY_INVERTER_DISPATCH_FEASIBILITY_MODEL_ID,
        topology_inverter_dispatch_feasibility_scope=TOPOLOGY_INVERTER_DISPATCH_FEASIBILITY_SCOPE,
        topology_inverter_dispatch_feasibility_coverage_scope=TOPOLOGY_INVERTER_DISPATCH_FEASIBILITY_COVERAGE_SCOPE,
    )
    return record


def _thermal(
    authority: InverterThermalDeratingAuthority | None,
    temperature: InverterTemperatureState | None,
    p: float | None,
    q: float | None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "thermal_active_power_limit_w": math.nan,
        "thermal_apparent_power_limit_va": math.nan,
        "thermal_reactive_power_min_var": math.nan,
        "thermal_reactive_power_max_var": math.nan,
        "thermal_active_power_limit_evaluated": False,
        "thermal_active_power_limit_satisfied": pd.NA,
        "thermal_apparent_power_limit_evaluated": False,
        "thermal_apparent_power_limit_satisfied": pd.NA,
        "thermal_reactive_power_limit_evaluated": False,
        "thermal_reactive_power_limit_satisfied": pd.NA,
        "full_thermal_capability_authority_resolved": False,
        "thermal_evaluation_state": "unresolved_no_explicit_inverter_thermal_derating_authority",
    }
    if authority is None:
        return result
    full = authority.derating_mode == "explicit_no_derating" or all(
        channel is not None
        for channel in (
            authority.active_power_limit_w,
            authority.apparent_power_limit_va,
            authority.reactive_power_min_var,
            authority.reactive_power_max_var,
        )
    )
    result["full_thermal_capability_authority_resolved"] = full
    if temperature is None:
        result["thermal_evaluation_state"] = "unresolved_no_explicit_inverter_temperature_state"
        return result
    if temperature.temperature_quantity != authority.temperature_quantity:
        result["thermal_evaluation_state"] = "unresolved_inverter_temperature_quantity_mismatch"
        return result
    t = temperature.temperature_c
    if t < authority.temperature_points_c[0] or t > authority.temperature_points_c[-1]:
        result["thermal_evaluation_state"] = (
            "unresolved_inverter_temperature_outside_authority_domain"
        )
        return result
    if authority.derating_mode == "explicit_no_derating":
        result["thermal_evaluation_state"] = "explicit_no_derating_domain"
        return result
    channels = (
        ("active", authority.active_power_limit_w),
        ("apparent", authority.apparent_power_limit_va),
        ("qmin", authority.reactive_power_min_var),
        ("qmax", authority.reactive_power_max_var),
    )
    values = {
        name: _interpolate(authority.temperature_points_c, curve, t)
        for name, curve in channels
        if curve is not None
    }
    if "active" in values and p is not None:
        result.update(
            thermal_active_power_limit_w=values["active"],
            thermal_active_power_limit_evaluated=True,
            thermal_active_power_limit_satisfied=p <= values["active"] + _ABS_TOL,
        )
    if "apparent" in values:
        result["thermal_apparent_power_limit_va"] = values["apparent"]
        conclusive = p is not None and q is not None
        violation = (p is not None and p > values["apparent"] + _ABS_TOL) or (
            q is not None and abs(q) > values["apparent"] + _ABS_TOL
        )
        if conclusive or violation:
            result["thermal_apparent_power_limit_evaluated"] = True
            if p is not None and q is not None:
                result["thermal_apparent_power_limit_satisfied"] = (
                    math.hypot(p, q) <= values["apparent"] + _ABS_TOL
                )
            else:
                result["thermal_apparent_power_limit_satisfied"] = False
    if "qmin" in values and "qmax" in values:
        result["thermal_reactive_power_min_var"] = values["qmin"]
        result["thermal_reactive_power_max_var"] = values["qmax"]
        if q is not None:
            result["thermal_reactive_power_limit_evaluated"] = True
            result["thermal_reactive_power_limit_satisfied"] = (
                values["qmin"] - _ABS_TOL <= q <= values["qmax"] + _ABS_TOL
            )
    result["thermal_evaluation_state"] = "evaluated_piecewise_thermal_authority"
    return result


def _interpolate(points: tuple[float, ...], values: tuple[float, ...], t: float) -> float:
    for index, point in enumerate(points):
        if t == point:
            return values[index]
        if t < point:
            left = index - 1
            return values[left] + (values[index] - values[left]) * (
                (t - points[left]) / (point - points[left])
            )
    return values[-1]


def _diagnostics(
    topology: ElectricalTopologyConfig, frame: pd.DataFrame
) -> TopologyInverterDispatchFeasibilityDiagnostics:
    states = frame["dispatch_feasibility_state"].value_counts().to_dict()

    def failed(column: str) -> int:
        return int((frame[column] == False).sum())  # noqa: E712

    return TopologyInverterDispatchFeasibilityDiagnostics(
        inverter_count=len(topology.inverters),
        represented_inverter_count=len(set(frame.index.get_level_values("inverter_id"))),
        timestamp_count=len(set(frame.index.get_level_values("timestamp"))),
        row_count=len(frame),
        resolved_count=int(frame["dispatch_feasibility_evaluation_resolved"].sum()),
        unresolved_count=int((~frame["dispatch_feasibility_evaluation_resolved"]).sum()),
        applicable_count=int(frame["dispatch_feasibility_evaluation_applicable"].sum()),
        inactive_count=states.get(
            "resolved_dispatch_feasibility_not_applicable_inactive_ac_state", 0
        ),
        missing_p_request_count=states.get(
            "unresolved_no_explicit_active_power_dispatch_request", 0
        ),
        missing_q_request_count=states.get("unresolved_no_explicit_reactive_power_request", 0),
        missing_static_authority_count=states.get(
            "unresolved_no_explicit_ac_capability_authority", 0
        ),
        upstream_availability_unresolved_count=states.get(
            "unresolved_upstream_inverter_ac_availability", 0
        ),
        thermal_prerequisite_unresolved_count=sum(
            count
            for state, count in states.items()
            if state.startswith("unresolved_inverter_temperature")
            or state.startswith("unresolved_no_explicit_inverter_thermal")
        ),
        availability_evaluated_count=int(frame["active_power_availability_evaluated"].sum()),
        availability_violation_count=failed("active_power_availability_satisfied"),
        static_s_evaluated_count=int(frame["static_apparent_power_limit_evaluated"].sum()),
        static_s_violation_count=failed("static_apparent_power_limit_satisfied"),
        fixed_q_evaluated_count=int(frame["static_fixed_q_limit_evaluated"].sum()),
        fixed_q_violation_count=failed("static_fixed_q_limit_satisfied"),
        thermal_p_violation_count=failed("thermal_active_power_limit_satisfied"),
        thermal_s_violation_count=failed("thermal_apparent_power_limit_satisfied"),
        thermal_q_violation_count=failed("thermal_reactive_power_limit_satisfied"),
        full_feasible_count=states.get("resolved_requested_dispatch_feasible_full_capability", 0),
        partial_authority_count=states.get(
            "resolved_requested_dispatch_partial_capability_authority", 0
        ),
        known_infeasible_count=states.get("resolved_requested_dispatch_known_infeasible", 0),
        model=TOPOLOGY_INVERTER_DISPATCH_FEASIBILITY_MODEL_ID,
    )
