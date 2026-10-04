"""Select only an exact, fully feasible inverter P/Q/S request.

S10C never clamps, projects, optimizes, persists, or substitutes a request.
It establishes a selected target only when canonical S10B proves the exact
requested point fully feasible at ``inverter_ac_output``.
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
from heliotelligence.physics.inverter_dispatch_feasibility import (
    TopologyInverterDispatchFeasibilityResult,
    calculate_topology_inverter_dispatch_feasibility,
)
from heliotelligence.physics.inverter_dispatch_request_authority import (
    InverterActivePowerDispatchRequest,
    TopologyInverterActivePowerDispatchRequestAuthorityResult,
)
from heliotelligence.physics.inverter_potential import TopologySandiaPreLimitAcResult
from heliotelligence.physics.inverter_pqs_capability import (
    InverterReactivePowerRequest,
    TopologyInverterPqsCapabilityResult,
)
from heliotelligence.physics.inverter_temperature_capability import (
    InverterTemperatureState,
    TopologyInverterTemperatureCapabilityResult,
)
from heliotelligence.physics.inverter_thermal_authority import (
    InverterThermalDeratingAuthority,
    TopologyInverterThermalDeratingAuthorityResult,
)
from heliotelligence.physics.inverter_topology import (
    MpptDcCurrentLimitAuthority,
    TopologyInverterDcEnvelopeResult,
)

TOPOLOGY_INVERTER_DISPATCH_SELECTION_CONTRACT_ID = (
    "admitted_dispatch_feasibility_to_selected_inverter_dispatch_state_v1"
)
TOPOLOGY_INVERTER_DISPATCH_SELECTION_MODEL_ID = (
    "exact_fully_feasible_request_passthrough_selection_v1"
)
TOPOLOGY_INVERTER_DISPATCH_SELECTION_SCOPE = (
    "inverter_ac_dispatch_selection_before_ac_current_and_network"
)
TOPOLOGY_INVERTER_DISPATCH_SELECTION_COVERAGE_SCOPE = (
    "fully_feasible_per_inverter_requested_pq_at_inverter_ac_output"
)

_PARENT_FIELDS = (
    "p_ac_available_w",
    "p_requested_w",
    "q_requested_var",
    "s_requested_va",
    "active_power_request_source",
    "active_power_request_confidence",
    "controller_mode",
    "reactive_power_request_source",
    "reactive_power_request_confidence",
    "reactive_power_request_direction",
    "dispatch_feasibility_violation_detected",
    "dispatch_feasibility_satisfied",
    "dispatch_feasibility_evaluation_applicable",
    "dispatch_feasibility_evaluation_resolved",
    "dispatch_feasibility_state",
    "active_power_availability_limit_w",
    "active_power_availability_satisfied",
    "rated_apparent_power_va",
    "static_apparent_power_limit_satisfied",
    "static_fixed_q_limit_satisfied",
    "full_static_capability_authority_resolved",
    "thermal_active_power_limit_w",
    "thermal_apparent_power_limit_va",
    "thermal_reactive_power_min_var",
    "thermal_reactive_power_max_var",
    "thermal_active_power_limit_satisfied",
    "thermal_apparent_power_limit_satisfied",
    "thermal_reactive_power_limit_satisfied",
    "full_thermal_capability_authority_resolved",
    "thermal_evaluation_state",
    "topology_inverter_dispatch_feasibility_contract",
    "topology_inverter_dispatch_feasibility_model",
    "topology_inverter_dispatch_feasibility_scope",
    "topology_inverter_dispatch_feasibility_coverage_scope",
)
_SELECTION_FIELDS = (
    "selected_dispatch_present",
    "p_selected_w",
    "q_selected_var",
    "s_selected_va",
    "selected_active_power_is_zero",
    "selected_reactive_power_direction",
    "selected_dispatch_reference_plane",
    "dispatch_selection_method",
    "dispatch_selection_evaluation_resolved",
    "dispatch_selection_evaluation_applicable",
    "selected_dispatch_state_resolved",
    "dispatch_selection_state",
    "topology_inverter_dispatch_selection_contract",
    "topology_inverter_dispatch_selection_model",
    "topology_inverter_dispatch_selection_scope",
    "topology_inverter_dispatch_selection_coverage_scope",
)
_COLUMNS = _PARENT_FIELDS + _SELECTION_FIELDS
_NUMERIC = {
    "p_ac_available_w",
    "p_requested_w",
    "q_requested_var",
    "s_requested_va",
    "active_power_availability_limit_w",
    "rated_apparent_power_va",
    "thermal_active_power_limit_w",
    "thermal_apparent_power_limit_va",
    "thermal_reactive_power_min_var",
    "thermal_reactive_power_max_var",
    "p_selected_w",
    "q_selected_var",
    "s_selected_va",
}
_BOOL = {
    "dispatch_feasibility_evaluation_applicable",
    "dispatch_feasibility_evaluation_resolved",
    "full_static_capability_authority_resolved",
    "full_thermal_capability_authority_resolved",
    "selected_dispatch_present",
    "dispatch_selection_evaluation_resolved",
    "dispatch_selection_evaluation_applicable",
    "selected_dispatch_state_resolved",
}
_NULLABLE = {
    "dispatch_feasibility_violation_detected",
    "dispatch_feasibility_satisfied",
    "active_power_availability_satisfied",
    "static_apparent_power_limit_satisfied",
    "static_fixed_q_limit_satisfied",
    "thermal_active_power_limit_satisfied",
    "thermal_apparent_power_limit_satisfied",
    "thermal_reactive_power_limit_satisfied",
    "selected_active_power_is_zero",
}


@dataclass(frozen=True)
class TopologyInverterDispatchSelectionDiagnostics:
    inverter_count: int
    represented_inverter_count: int
    timestamp_count: int
    row_count: int
    evaluation_resolved_count: int
    evaluation_unresolved_count: int
    applicable_count: int
    selected_dispatch_count: int
    no_selection_known_infeasible_count: int
    no_selection_partial_authority_count: int
    upstream_feasibility_unresolved_count: int
    inactive_not_applicable_count: int
    selected_zero_active_power_count: int
    selected_positive_active_power_count: int
    selected_q_injection_count: int
    selected_q_absorption_count: int
    selected_q_zero_count: int
    model: str


@dataclass(frozen=True)
class TopologyInverterDispatchSelectionResult:
    dispatch: pd.DataFrame
    diagnostics: TopologyInverterDispatchSelectionDiagnostics


def calculate_topology_inverter_dispatch_selection(
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
    dispatch_feasibility: TopologyInverterDispatchFeasibilityResult,
) -> TopologyInverterDispatchSelectionResult:
    canonical = _admit_feasibility(
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
        dispatch_feasibility,
    )
    output = _build(canonical)
    diagnostics = _diagnostics(topology, output)
    _validate_result(topology, canonical, output, diagnostics)
    return TopologyInverterDispatchSelectionResult(output.copy(deep=True), diagnostics)


def _admit_feasibility(
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
    temperature_capability: TopologyInverterTemperatureCapabilityResult,
    p_requests: Mapping[tuple[pd.Timestamp, str], InverterActivePowerDispatchRequest],
    request_authority: TopologyInverterActivePowerDispatchRequestAuthorityResult,
    supplied: object,
) -> pd.DataFrame:
    if type(supplied) is not TopologyInverterDispatchFeasibilityResult:
        raise ValueError("S10B result type is invalid")
    replayed = calculate_topology_inverter_dispatch_feasibility(
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
        temperature_capability,
        p_requests,
        request_authority,
    )
    try:
        pd.testing.assert_frame_equal(supplied.feasibility, replayed.feasibility, check_exact=True)
    except AssertionError as exc:
        raise ValueError("S10B feasibility does not match canonical replay") from exc
    if type(supplied.diagnostics) is not type(replayed.diagnostics) or (
        supplied.diagnostics != replayed.diagnostics
    ):
        raise ValueError("S10B diagnostics do not match canonical replay")
    return replayed.feasibility.copy(deep=True)


def _build(parent: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for _, upstream in parent.iterrows():
        record = {name: upstream[name] for name in _PARENT_FIELDS}
        state = upstream["dispatch_feasibility_state"]
        selected = state == "resolved_requested_dispatch_feasible_full_capability"
        if selected:
            p = float(upstream["p_requested_w"])
            q = float(upstream["q_requested_var"])
            s = float(upstream["s_requested_va"])
            selection = {
                "selected_dispatch_present": True,
                "p_selected_w": p,
                "q_selected_var": q,
                "s_selected_va": s,
                "selected_active_power_is_zero": p == 0.0,
                "selected_reactive_power_direction": (
                    "injection" if q > 0.0 else "absorption" if q < 0.0 else "zero"
                ),
                "selected_dispatch_reference_plane": "inverter_ac_output",
                "dispatch_selection_method": "exact_feasible_request_passthrough",
                "dispatch_selection_evaluation_resolved": True,
                "dispatch_selection_evaluation_applicable": True,
                "selected_dispatch_state_resolved": True,
                "dispatch_selection_state": "resolved_selected_dispatch_exact_feasible_request",
            }
        else:
            if state == "resolved_requested_dispatch_known_infeasible":
                selection_state = "resolved_no_selected_dispatch_known_infeasible_request"
                evaluation_resolved, applicable = True, True
            elif state == "resolved_dispatch_feasibility_not_applicable_inactive_ac_state":
                selection_state = "resolved_dispatch_selection_not_applicable_inactive_ac_state"
                evaluation_resolved, applicable = True, False
            elif state == "resolved_requested_dispatch_partial_capability_authority":
                selection_state = "unresolved_no_selected_dispatch_partial_capability_authority"
                evaluation_resolved, applicable = False, True
            else:
                selection_state = "unresolved_upstream_dispatch_feasibility"
                evaluation_resolved, applicable = False, False
            selection = {
                "selected_dispatch_present": False,
                "p_selected_w": math.nan,
                "q_selected_var": math.nan,
                "s_selected_va": math.nan,
                "selected_active_power_is_zero": pd.NA,
                "selected_reactive_power_direction": "not_selected",
                "selected_dispatch_reference_plane": "",
                "dispatch_selection_method": "",
                "dispatch_selection_evaluation_resolved": evaluation_resolved,
                "dispatch_selection_evaluation_applicable": applicable,
                "selected_dispatch_state_resolved": False,
                "dispatch_selection_state": selection_state,
            }
        record.update(selection)
        record.update(
            topology_inverter_dispatch_selection_contract=TOPOLOGY_INVERTER_DISPATCH_SELECTION_CONTRACT_ID,
            topology_inverter_dispatch_selection_model=TOPOLOGY_INVERTER_DISPATCH_SELECTION_MODEL_ID,
            topology_inverter_dispatch_selection_scope=TOPOLOGY_INVERTER_DISPATCH_SELECTION_SCOPE,
            topology_inverter_dispatch_selection_coverage_scope=TOPOLOGY_INVERTER_DISPATCH_SELECTION_COVERAGE_SCOPE,
        )
        records.append(record)
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


def _validate_result(
    topology: ElectricalTopologyConfig,
    parent: pd.DataFrame,
    output: pd.DataFrame,
    diagnostics: TopologyInverterDispatchSelectionDiagnostics,
) -> None:
    expected = _build(parent)
    if tuple(output.columns) != _COLUMNS or output.index.has_duplicates:
        raise RuntimeError("S10C schema or duplicate-free index is invalid")
    if not output.index.equals(parent.index) or output.index.names != ["timestamp", "inverter_id"]:
        raise RuntimeError("S10C canonical index/order is invalid")
    for column in _COLUMNS:
        expected_dtype = (
            "float64"
            if column in _NUMERIC
            else "bool"
            if column in _BOOL
            else "boolean"
            if column in _NULLABLE
            else "object"
        )
        if str(output[column].dtype) != expected_dtype:
            raise RuntimeError(f"S10C dtype is invalid for {column}")
    try:
        pd.testing.assert_frame_equal(output, expected, check_exact=True)
    except AssertionError as exc:
        raise RuntimeError("S10C dispatch failed exact canonical closure") from exc
    for _, row in output.loc[output["selected_dispatch_present"]].iterrows():
        if not (
            row["p_selected_w"] == row["p_requested_w"]
            and row["q_selected_var"] == row["q_requested_var"]
            and row["s_selected_va"] == row["s_requested_va"]
            and row["s_selected_va"] == math.hypot(row["p_selected_w"], row["q_selected_var"])
        ):
            raise RuntimeError("S10C exact selected P/Q/S passthrough is invalid")
    not_selected = output.loc[~output["selected_dispatch_present"]]
    if not not_selected[["p_selected_w", "q_selected_var", "s_selected_va"]].isna().all().all():
        raise RuntimeError("S10C non-selected P/Q/S values must be NaN")
    canonical_diagnostics = _diagnostics(topology, expected)
    if diagnostics != canonical_diagnostics:
        raise RuntimeError("S10C diagnostics failed exact closure")
    if diagnostics.evaluation_resolved_count + diagnostics.evaluation_unresolved_count != len(
        output
    ):
        raise RuntimeError("S10C evaluation diagnostics do not close")
    primary_total = sum(
        int(output["dispatch_selection_state"].eq(state).sum())
        for state in (
            "resolved_selected_dispatch_exact_feasible_request",
            "resolved_no_selected_dispatch_known_infeasible_request",
            "resolved_dispatch_selection_not_applicable_inactive_ac_state",
            "unresolved_no_selected_dispatch_partial_capability_authority",
            "unresolved_upstream_dispatch_feasibility",
        )
    )
    if primary_total != len(output):
        raise RuntimeError("S10C primary states do not close")


def _diagnostics(
    topology: ElectricalTopologyConfig, frame: pd.DataFrame
) -> TopologyInverterDispatchSelectionDiagnostics:
    states = frame["dispatch_selection_state"].value_counts().to_dict()
    selected = frame.loc[frame["selected_dispatch_present"]]
    return TopologyInverterDispatchSelectionDiagnostics(
        inverter_count=len(topology.inverters),
        represented_inverter_count=len(set(frame.index.get_level_values("inverter_id"))),
        timestamp_count=len(set(frame.index.get_level_values("timestamp"))),
        row_count=len(frame),
        evaluation_resolved_count=int(frame["dispatch_selection_evaluation_resolved"].sum()),
        evaluation_unresolved_count=int((~frame["dispatch_selection_evaluation_resolved"]).sum()),
        applicable_count=int(frame["dispatch_selection_evaluation_applicable"].sum()),
        selected_dispatch_count=len(selected),
        no_selection_known_infeasible_count=states.get(
            "resolved_no_selected_dispatch_known_infeasible_request", 0
        ),
        no_selection_partial_authority_count=states.get(
            "unresolved_no_selected_dispatch_partial_capability_authority", 0
        ),
        upstream_feasibility_unresolved_count=states.get(
            "unresolved_upstream_dispatch_feasibility", 0
        ),
        inactive_not_applicable_count=states.get(
            "resolved_dispatch_selection_not_applicable_inactive_ac_state", 0
        ),
        selected_zero_active_power_count=int((selected["p_selected_w"] == 0.0).sum()),
        selected_positive_active_power_count=int((selected["p_selected_w"] > 0.0).sum()),
        selected_q_injection_count=int((selected["q_selected_var"] > 0.0).sum()),
        selected_q_absorption_count=int((selected["q_selected_var"] < 0.0).sum()),
        selected_q_zero_count=int((selected["q_selected_var"] == 0.0).sum()),
        model=TOPOLOGY_INVERTER_DISPATCH_SELECTION_MODEL_ID,
    )
