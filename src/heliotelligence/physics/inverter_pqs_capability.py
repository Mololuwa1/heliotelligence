"""Evaluate explicit inverter P/Q/S requests against admitted capability.

S9-4B is evaluation only.  Positive reactive power is injection into the AC
network, negative reactive power is absorption, and zero is an explicit
unity-reactive request.  Missing request authority is never interpreted as
zero.  This stage does not dispatch, clamp, curtail, or calculate AC current.
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
    TopologyInverterAcCapabilityAuthorityDiagnostics,
    TopologyInverterAcCapabilityAuthorityResult,
    resolve_topology_inverter_ac_capability_authority,
)
from heliotelligence.physics.inverter_accounting import (
    TopologySandiaInverterPowerAccountingDiagnostics,
    TopologySandiaInverterPowerAccountingResult,
    calculate_topology_sandia_inverter_power_accounting,
)
from heliotelligence.physics.inverter_authority import TopologyInverterAuthorityResult
from heliotelligence.physics.inverter_conversion import TopologySandiaInverterAcResult
from heliotelligence.physics.inverter_potential import TopologySandiaPreLimitAcResult
from heliotelligence.physics.inverter_topology import (
    MpptDcCurrentLimitAuthority,
    TopologyInverterDcEnvelopeResult,
)

TOPOLOGY_INVERTER_PQS_CAPABILITY_CONTRACT_ID = (
    "admitted_inverter_ac_and_capability_to_pqs_evaluation_v1"
)
TOPOLOGY_INVERTER_PQS_CAPABILITY_MODEL_ID = (
    "explicit_q_request_apparent_power_circle_and_fixed_q_limits_v1"
)
TOPOLOGY_INVERTER_PQS_CAPABILITY_SCOPE = (
    "inverter_ac_pqs_capability_evaluation_before_dispatch_and_ac_network"
)
TOPOLOGY_INVERTER_PQS_CAPABILITY_COVERAGE_SCOPE = (
    "active_sandia_ac_with_explicit_smax_q_request_and_optional_fixed_q_limits"
)

Confidence = Literal["high", "medium", "low", "unknown"]
_CONFIDENCES = {"high", "medium", "low", "unknown"}
_ACTIVE_STATES = {"resolved_sandia_producing", "resolved_sandia_ac_limited"}
_INACTIVE_STATES = {"resolved_sandia_night_tare", "resolved_sandia_non_producing"}
_ABS_TOL = 1e-8

_COLUMNS = (
    "p_ac_available_w",
    "inverter_conversion_state",
    "accounting_resolved",
    "accounting_state",
    "available_reference_plane",
    "nominal_ac_voltage_v",
    "ac_voltage_basis",
    "phase_configuration",
    "rated_apparent_power_va",
    "reactive_power_min_var",
    "reactive_power_max_var",
    "fixed_reactive_power_limits_resolved",
    "ac_capability_authority_resolved",
    "ac_capability_authority_state",
    "ac_capability_parameter_source",
    "ac_capability_confidence",
    "reactive_power_request_present",
    "q_requested_var",
    "reactive_power_request_source",
    "reactive_power_request_confidence",
    "reactive_power_request_direction",
    "s_requested_va",
    "power_factor_magnitude",
    "q_apparent_power_circle_limit_var",
    "apparent_power_margin_va",
    "active_power_alone_exceeds_smax",
    "apparent_power_limit_satisfied",
    "fixed_q_limit_evaluated",
    "fixed_q_limit_satisfied",
    "full_capability_authority_resolved",
    "capability_violation_detected",
    "pqs_capability_satisfied",
    "pqs_evaluation_applicable",
    "pqs_evaluation_resolved",
    "pqs_capability_state",
    "topology_sandia_inverter_accounting_contract",
    "topology_sandia_inverter_accounting_model",
    "topology_sandia_inverter_accounting_scope",
    "topology_sandia_inverter_accounting_coverage_scope",
    "topology_inverter_ac_capability_authority_contract",
    "topology_inverter_ac_capability_authority_model",
    "topology_inverter_ac_capability_authority_scope",
    "topology_inverter_ac_capability_authority_coverage_scope",
    "topology_inverter_pqs_capability_contract",
    "topology_inverter_pqs_capability_model",
    "topology_inverter_pqs_capability_scope",
    "topology_inverter_pqs_capability_coverage_scope",
)
_NUMERIC_COLUMNS = {
    "p_ac_available_w",
    "nominal_ac_voltage_v",
    "rated_apparent_power_va",
    "reactive_power_min_var",
    "reactive_power_max_var",
    "q_requested_var",
    "s_requested_va",
    "power_factor_magnitude",
    "q_apparent_power_circle_limit_var",
    "apparent_power_margin_va",
}
_BOOL_COLUMNS = {
    "accounting_resolved",
    "fixed_reactive_power_limits_resolved",
    "ac_capability_authority_resolved",
    "reactive_power_request_present",
    "fixed_q_limit_evaluated",
    "full_capability_authority_resolved",
    "pqs_evaluation_applicable",
    "pqs_evaluation_resolved",
}
_NULLABLE_BOOL_COLUMNS = {
    "active_power_alone_exceeds_smax",
    "apparent_power_limit_satisfied",
    "fixed_q_limit_satisfied",
    "capability_violation_detected",
    "pqs_capability_satisfied",
}


@dataclass(frozen=True)
class InverterReactivePowerRequest:
    """Explicit requested Q; positive injects and negative absorbs VAR."""

    reactive_power_request_var: float
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        value = self.reactive_power_request_var
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("reactive_power_request_var must be a real non-Boolean number")
        q = float(value)
        if not math.isfinite(q):
            raise ValueError("reactive_power_request_var must be finite")
        if type(self.parameter_source) is not str or not self.parameter_source.strip():
            raise ValueError("parameter_source must be a non-empty string")
        if type(self.confidence) is not str or self.confidence not in _CONFIDENCES:
            raise ValueError("confidence is unsupported")
        object.__setattr__(self, "reactive_power_request_var", q)


@dataclass(frozen=True)
class TopologyInverterPqsCapabilityDiagnostics:
    inverter_count: int
    represented_inverter_count: int
    timestamp_count: int
    row_count: int
    resolved_count: int
    unresolved_count: int
    applicable_count: int
    inactive_not_applicable_count: int
    upstream_unresolved_count: int
    missing_ac_capability_authority_count: int
    missing_reactive_request_count: int
    explicit_reactive_request_count: int
    explicit_zero_q_request_count: int
    positive_q_injection_request_count: int
    negative_q_absorption_request_count: int
    full_capability_authority_count: int
    partial_no_fixed_q_authority_count: int
    within_explicit_capability_count: int
    known_capability_violation_count: int
    active_power_alone_exceeds_smax_count: int
    apparent_power_violation_count: int
    fixed_q_limit_violation_count: int
    model: str


@dataclass(frozen=True)
class TopologyInverterPqsCapabilityResult:
    capability: pd.DataFrame
    diagnostics: TopologyInverterPqsCapabilityDiagnostics


def calculate_topology_inverter_pqs_capability(
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
) -> TopologyInverterPqsCapabilityResult:
    """Evaluate, but never alter, explicit inverter P/Q requests."""

    accounting = _admit_accounting(
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
    )
    capability = _admit_capability(topology, ac_capability_by_inverter_id, ac_capability_authority)
    requests = _admit_requests(accounting.index, reactive_power_request_by_key)
    records: list[dict[str, object]] = []
    for key, upstream in accounting.iterrows():
        inverter_id = str(key[1])
        authority = capability.loc[inverter_id]
        request = requests.get((pd.Timestamp(key[0]), inverter_id))
        record = _base_record(upstream, authority, request)
        _classify(record, upstream, authority, request)
        records.append(record)
    output = pd.DataFrame(records, index=accounting.index.copy(), columns=_COLUMNS)
    _apply_dtypes(output)
    diagnostics = _diagnostics(topology, output)
    _validate_result(accounting, capability, requests, output, diagnostics)
    return TopologyInverterPqsCapabilityResult(output.copy(deep=True), diagnostics)


def _admit_accounting(
    topology: ElectricalTopologyConfig,
    topology_string_iv: electrical.TopologyStringIVResult,
    branch_authority: dc_collection.DcBranchPathAuthorityResult,
    mppt_input_string_iv: dc_collection.TopologyMpptInputStringIVResult,
    mppt_input_operating_points: dc_collection.TopologyMpptInputOperatingPointResult,
    names: Mapping[str, str],
    authority: TopologyInverterAuthorityResult,
    limits: Mapping[tuple[str, str], MpptDcCurrentLimitAuthority],
    envelope: TopologyInverterDcEnvelopeResult,
    inverter_ac: TopologySandiaInverterAcResult,
    pre_limit_ac: TopologySandiaPreLimitAcResult,
    supplied: object,
) -> pd.DataFrame:
    if type(supplied) is not TopologySandiaInverterPowerAccountingResult:
        raise ValueError("S9-3B result type is invalid")
    if type(supplied.diagnostics) is not TopologySandiaInverterPowerAccountingDiagnostics:
        raise ValueError("S9-3B diagnostics type is invalid")
    replayed = calculate_topology_sandia_inverter_power_accounting(
        topology,
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        names,
        authority,
        limits,
        envelope,
        inverter_ac,
        pre_limit_ac,
    )
    try:
        pd.testing.assert_frame_equal(supplied.accounting, replayed.accounting, check_exact=True)
    except AssertionError as error:
        raise ValueError("S9-3B accounting does not match canonical replay") from error
    if supplied.diagnostics != replayed.diagnostics:
        raise ValueError("S9-3B diagnostics do not match canonical replay")
    return replayed.accounting.copy(deep=True)


def _admit_capability(
    topology: ElectricalTopologyConfig,
    explicit: Mapping[str, InverterAcCapabilityAuthority],
    supplied: object,
) -> pd.DataFrame:
    if type(supplied) is not TopologyInverterAcCapabilityAuthorityResult:
        raise ValueError("S9-4A result type is invalid")
    if type(supplied.diagnostics) is not TopologyInverterAcCapabilityAuthorityDiagnostics:
        raise ValueError("S9-4A diagnostics type is invalid")
    replayed = resolve_topology_inverter_ac_capability_authority(topology, explicit)
    try:
        pd.testing.assert_frame_equal(supplied.states, replayed.states, check_exact=True)
    except AssertionError as error:
        raise ValueError("S9-4A states do not match canonical replay") from error
    if supplied.diagnostics != replayed.diagnostics:
        raise ValueError("S9-4A diagnostics do not match canonical replay")
    if tuple(supplied.authorities_by_inverter_id.items()) != tuple(
        replayed.authorities_by_inverter_id.items()
    ):
        raise ValueError("S9-4A authority mapping does not match canonical replay")
    return replayed.states.copy(deep=True)


def _admit_requests(
    index: pd.Index,
    supplied: Mapping[tuple[pd.Timestamp, str], InverterReactivePowerRequest],
) -> dict[tuple[pd.Timestamp, str], InverterReactivePowerRequest]:
    if not isinstance(supplied, Mapping):
        raise TypeError("reactive_power_request_by_key must be a mapping")
    valid = {(pd.Timestamp(ts), str(inv)) for ts, inv in index.tolist()}
    admitted: dict[tuple[pd.Timestamp, str], InverterReactivePowerRequest] = {}
    for key, request in supplied.items():
        if type(key) is not tuple or len(key) != 2 or not isinstance(key[0], pd.Timestamp):
            raise ValueError("reactive-power request keys must be (Timestamp, inverter_id)")
        canonical = (key[0], key[1])
        if canonical not in valid:
            raise ValueError(f"unexpected reactive-power request key: {key!r}")
        if type(request) is not InverterReactivePowerRequest:
            raise TypeError("every reactive-power request must use the exact request type")
        admitted[canonical] = request
    return admitted


def _base_record(
    upstream: pd.Series,
    authority: pd.Series,
    request: InverterReactivePowerRequest | None,
) -> dict[str, object]:
    q_present = request is not None
    q = request.reactive_power_request_var if request is not None else np.nan
    direction = (
        "injection"
        if q_present and q > 0
        else "absorption"
        if q_present and q < 0
        else "zero"
        if q_present
        else "not_evaluated"
    )
    record: dict[str, object] = {
        "p_ac_available_w": upstream["p_ac_available_w"],
        "inverter_conversion_state": upstream["inverter_conversion_state"],
        "accounting_resolved": upstream["accounting_resolved"],
        "accounting_state": upstream["accounting_state"],
        "available_reference_plane": upstream["available_reference_plane"],
        "nominal_ac_voltage_v": authority["nominal_ac_voltage_v"],
        "ac_voltage_basis": authority["ac_voltage_basis"],
        "phase_configuration": authority["phase_configuration"],
        "rated_apparent_power_va": authority["rated_apparent_power_va"],
        "reactive_power_min_var": authority["reactive_power_min_var"],
        "reactive_power_max_var": authority["reactive_power_max_var"],
        "fixed_reactive_power_limits_resolved": authority["fixed_reactive_power_limits_resolved"],
        "ac_capability_authority_resolved": authority["ac_capability_authority_resolved"],
        "ac_capability_authority_state": authority["ac_capability_authority_state"],
        "ac_capability_parameter_source": authority["parameter_source"],
        "ac_capability_confidence": authority["confidence"],
        "reactive_power_request_present": q_present,
        "q_requested_var": q,
        "reactive_power_request_source": request.parameter_source if request else "",
        "reactive_power_request_confidence": request.confidence if request else "unknown",
        "reactive_power_request_direction": direction,
        "s_requested_va": np.nan,
        "power_factor_magnitude": np.nan,
        "q_apparent_power_circle_limit_var": np.nan,
        "apparent_power_margin_va": np.nan,
        "active_power_alone_exceeds_smax": pd.NA,
        "apparent_power_limit_satisfied": pd.NA,
        "fixed_q_limit_evaluated": False,
        "fixed_q_limit_satisfied": pd.NA,
        "full_capability_authority_resolved": False,
        "capability_violation_detected": pd.NA,
        "pqs_capability_satisfied": pd.NA,
        "pqs_evaluation_applicable": False,
        "pqs_evaluation_resolved": False,
        "pqs_capability_state": "unresolved_upstream_sandia_power_accounting",
    }
    for column in _COLUMNS[35:43]:
        source = column.replace("topology_inverter_ac_capability_authority_", "")
        if column.startswith("topology_sandia"):
            record[column] = upstream[column]
        else:
            record[column] = authority[f"topology_inverter_ac_capability_authority_{source}"]
    record.update(
        topology_inverter_pqs_capability_contract=(TOPOLOGY_INVERTER_PQS_CAPABILITY_CONTRACT_ID),
        topology_inverter_pqs_capability_model=TOPOLOGY_INVERTER_PQS_CAPABILITY_MODEL_ID,
        topology_inverter_pqs_capability_scope=TOPOLOGY_INVERTER_PQS_CAPABILITY_SCOPE,
        topology_inverter_pqs_capability_coverage_scope=(
            TOPOLOGY_INVERTER_PQS_CAPABILITY_COVERAGE_SCOPE
        ),
    )
    return record


def _classify(
    record: dict[str, object],
    upstream: pd.Series,
    authority: pd.Series,
    request: InverterReactivePowerRequest | None,
) -> None:
    if not bool(upstream["accounting_resolved"]):
        return
    conversion_state = str(upstream["inverter_conversion_state"])
    if conversion_state in _INACTIVE_STATES:
        record.update(
            pqs_evaluation_resolved=True,
            pqs_capability_state="resolved_pqs_not_applicable_inactive_ac_state",
        )
        return
    if conversion_state not in _ACTIVE_STATES:
        return
    if not bool(authority["ac_capability_authority_resolved"]):
        record["pqs_capability_state"] = "unresolved_no_explicit_ac_capability_authority"
        return
    p = float(upstream["p_ac_available_w"])
    smax = float(authority["rated_apparent_power_va"])
    p_alone_violation = abs(p) > smax + _ABS_TOL
    record["active_power_alone_exceeds_smax"] = p_alone_violation
    record["q_apparent_power_circle_limit_var"] = (
        smax * math.sqrt(max(1.0 - (abs(p) / smax) ** 2, 0.0)) if abs(p) <= smax else 0.0
    )
    if request is None:
        if p_alone_violation:
            record.update(
                apparent_power_limit_satisfied=False,
                capability_violation_detected=True,
                pqs_capability_satisfied=False,
                pqs_evaluation_applicable=True,
                pqs_evaluation_resolved=True,
                pqs_capability_state="resolved_pqs_known_capability_violation",
            )
        else:
            record["pqs_capability_state"] = "unresolved_no_explicit_reactive_power_request"
        return
    q = request.reactive_power_request_var
    apparent = math.hypot(p, q)
    apparent_ok = apparent <= smax + _ABS_TOL
    fixed = bool(authority["fixed_reactive_power_limits_resolved"])
    fixed_ok: bool | pd._libs.missing.NAType = pd.NA
    if fixed:
        fixed_ok = (
            float(authority["reactive_power_min_var"]) - _ABS_TOL
            <= q
            <= float(authority["reactive_power_max_var"]) + _ABS_TOL
        )
    violation = not apparent_ok or (fixed and not bool(fixed_ok))
    satisfied: bool | pd._libs.missing.NAType = False if violation else True if fixed else pd.NA
    state = (
        "resolved_pqs_known_capability_violation"
        if violation
        else "resolved_pqs_within_explicit_capability"
        if fixed
        else "resolved_pqs_partial_no_fixed_q_authority"
    )
    record.update(
        s_requested_va=apparent,
        power_factor_magnitude=p / apparent,
        apparent_power_margin_va=smax - apparent,
        apparent_power_limit_satisfied=apparent_ok,
        fixed_q_limit_evaluated=fixed,
        fixed_q_limit_satisfied=fixed_ok,
        full_capability_authority_resolved=fixed,
        capability_violation_detected=violation,
        pqs_capability_satisfied=satisfied,
        pqs_evaluation_applicable=True,
        pqs_evaluation_resolved=True,
        pqs_capability_state=state,
    )


def _apply_dtypes(output: pd.DataFrame) -> None:
    for column in _NUMERIC_COLUMNS:
        output[column] = output[column].astype(float)
    for column in _BOOL_COLUMNS:
        output[column] = output[column].astype(bool)
    for column in _NULLABLE_BOOL_COLUMNS:
        output[column] = output[column].astype("boolean")
    for column in set(_COLUMNS) - _NUMERIC_COLUMNS - _BOOL_COLUMNS - _NULLABLE_BOOL_COLUMNS:
        output[column] = output[column].astype(object)


def _diagnostics(
    topology: ElectricalTopologyConfig, output: pd.DataFrame
) -> TopologyInverterPqsCapabilityDiagnostics:
    states = output["pqs_capability_state"].value_counts()
    directions = output.loc[
        output["reactive_power_request_present"], "reactive_power_request_direction"
    ].value_counts()
    apparent_violation = output["apparent_power_limit_satisfied"].eq(False).fillna(False)
    fixed_violation = output["fixed_q_limit_satisfied"].eq(False).fillna(False)
    return TopologyInverterPqsCapabilityDiagnostics(
        inverter_count=topology.inverter_count,
        represented_inverter_count=len(output.index.get_level_values("inverter_id").unique())
        if len(output)
        else 0,
        timestamp_count=len(output.index.get_level_values("timestamp").unique())
        if len(output)
        else 0,
        row_count=len(output),
        resolved_count=int(output["pqs_evaluation_resolved"].sum()) if len(output) else 0,
        unresolved_count=int((~output["pqs_evaluation_resolved"]).sum()) if len(output) else 0,
        applicable_count=int(output["pqs_evaluation_applicable"].sum()) if len(output) else 0,
        inactive_not_applicable_count=int(
            states.get("resolved_pqs_not_applicable_inactive_ac_state", 0)
        ),
        upstream_unresolved_count=int(states.get("unresolved_upstream_sandia_power_accounting", 0)),
        missing_ac_capability_authority_count=int(
            states.get("unresolved_no_explicit_ac_capability_authority", 0)
        ),
        missing_reactive_request_count=int(
            states.get("unresolved_no_explicit_reactive_power_request", 0)
        ),
        explicit_reactive_request_count=int(output["reactive_power_request_present"].sum())
        if len(output)
        else 0,
        explicit_zero_q_request_count=int(directions.get("zero", 0)),
        positive_q_injection_request_count=int(directions.get("injection", 0)),
        negative_q_absorption_request_count=int(directions.get("absorption", 0)),
        full_capability_authority_count=int(output["full_capability_authority_resolved"].sum())
        if len(output)
        else 0,
        partial_no_fixed_q_authority_count=int(
            states.get("resolved_pqs_partial_no_fixed_q_authority", 0)
        ),
        within_explicit_capability_count=int(
            states.get("resolved_pqs_within_explicit_capability", 0)
        ),
        known_capability_violation_count=int(
            states.get("resolved_pqs_known_capability_violation", 0)
        ),
        active_power_alone_exceeds_smax_count=int(
            output["active_power_alone_exceeds_smax"].fillna(False).sum()
        )
        if len(output)
        else 0,
        apparent_power_violation_count=int(apparent_violation.sum()) if len(output) else 0,
        fixed_q_limit_violation_count=int(fixed_violation.sum()) if len(output) else 0,
        model=TOPOLOGY_INVERTER_PQS_CAPABILITY_MODEL_ID,
    )


def _validate_result(
    accounting: pd.DataFrame,
    capability: pd.DataFrame,
    requests: Mapping[tuple[pd.Timestamp, str], InverterReactivePowerRequest],
    output: pd.DataFrame,
    diagnostics: TopologyInverterPqsCapabilityDiagnostics,
) -> None:
    if tuple(output.columns) != _COLUMNS or not output.index.equals(accounting.index):
        raise RuntimeError("S9-4B schema or S9-3B alignment is invalid")
    if output.index.names != ["timestamp", "inverter_id"] or output.index.has_duplicates:
        raise RuntimeError("S9-4B index is invalid")
    for column in _NUMERIC_COLUMNS:
        if output[column].dtype != np.dtype("float64"):
            raise RuntimeError(f"S9-4B numeric dtype is invalid for {column}")
    for column in _BOOL_COLUMNS:
        if output[column].dtype != np.dtype("bool"):
            raise RuntimeError(f"S9-4B boolean dtype is invalid for {column}")
    for column in _NULLABLE_BOOL_COLUMNS:
        if str(output[column].dtype) != "boolean":
            raise RuntimeError(f"S9-4B nullable boolean dtype is invalid for {column}")
    if diagnostics.row_count != diagnostics.resolved_count + diagnostics.unresolved_count:
        raise RuntimeError("S9-4B resolution counts do not close")
    primary = (
        diagnostics.applicable_count
        + diagnostics.inactive_not_applicable_count
        + diagnostics.upstream_unresolved_count
        + diagnostics.missing_ac_capability_authority_count
        + diagnostics.missing_reactive_request_count
    )
    if diagnostics.row_count != primary:
        raise RuntimeError("S9-4B primary categories do not close")
    if diagnostics.explicit_reactive_request_count != (
        diagnostics.explicit_zero_q_request_count
        + diagnostics.positive_q_injection_request_count
        + diagnostics.negative_q_absorption_request_count
    ):
        raise RuntimeError("S9-4B request direction counts do not close")
    for key, row in output.iterrows():
        upstream = accounting.loc[key]
        authority = capability.loc[key[1]]
        request = requests.get((pd.Timestamp(key[0]), str(key[1])))
        if row["p_ac_available_w"] != upstream["p_ac_available_w"]:
            raise RuntimeError("S9-4B altered admitted active power")
        if request is None:
            if bool(row["reactive_power_request_present"]) or pd.notna(row["q_requested_var"]):
                raise RuntimeError("S9-4B fabricated a reactive-power request")
        elif row["q_requested_var"] != request.reactive_power_request_var:
            raise RuntimeError("S9-4B altered the reactive-power request")
        if row["rated_apparent_power_va"] != authority["rated_apparent_power_va"] and not (
            pd.isna(row["rated_apparent_power_va"])
            and pd.isna(authority["rated_apparent_power_va"])
        ):
            raise RuntimeError("S9-4B altered AC capability authority")
        authority_pairs = {
            "nominal_ac_voltage_v": "nominal_ac_voltage_v",
            "ac_voltage_basis": "ac_voltage_basis",
            "phase_configuration": "phase_configuration",
            "reactive_power_min_var": "reactive_power_min_var",
            "reactive_power_max_var": "reactive_power_max_var",
            "fixed_reactive_power_limits_resolved": (
                "fixed_reactive_power_limits_resolved"
            ),
            "ac_capability_authority_resolved": "ac_capability_authority_resolved",
            "ac_capability_authority_state": "ac_capability_authority_state",
            "ac_capability_parameter_source": "parameter_source",
            "ac_capability_confidence": "confidence",
        }
        for result_column, authority_column in authority_pairs.items():
            actual = row[result_column]
            expected_authority = authority[authority_column]
            if actual != expected_authority and not (
                pd.isna(actual) and pd.isna(expected_authority)
            ):
                raise RuntimeError("S9-4B altered AC capability authority")
        for column, expected in {
            "topology_inverter_pqs_capability_contract": (
                TOPOLOGY_INVERTER_PQS_CAPABILITY_CONTRACT_ID
            ),
            "topology_inverter_pqs_capability_model": TOPOLOGY_INVERTER_PQS_CAPABILITY_MODEL_ID,
            "topology_inverter_pqs_capability_scope": TOPOLOGY_INVERTER_PQS_CAPABILITY_SCOPE,
            "topology_inverter_pqs_capability_coverage_scope": (
                TOPOLOGY_INVERTER_PQS_CAPABILITY_COVERAGE_SCOPE
            ),
        }.items():
            if row[column] != expected:
                raise RuntimeError(f"S9-4B {column} is invalid")
        if bool(row["pqs_evaluation_applicable"]) and pd.notna(row["q_requested_var"]):
            p = float(row["p_ac_available_w"])
            q = float(row["q_requested_var"])
            apparent = math.hypot(p, q)
            if not math.isclose(float(row["s_requested_va"]), apparent, abs_tol=_ABS_TOL):
                raise RuntimeError("S9-4B apparent power does not close")
            if not math.isclose(
                float(row["apparent_power_margin_va"]),
                float(row["rated_apparent_power_va"]) - apparent,
                abs_tol=_ABS_TOL,
            ):
                raise RuntimeError("S9-4B apparent-power margin does not close")
