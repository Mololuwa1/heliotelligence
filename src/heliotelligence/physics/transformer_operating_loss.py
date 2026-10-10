"""Baseline transformer operating active-loss evaluation.

S12D combines canonical S11C and S12A/B/C results to evaluate an instantaneous
factory-reference-condition active-loss baseline. It does not solve transformer
voltage/current phasors, allocate loss to a terminal, or integrate energy.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

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
)
from heliotelligence.physics.inverter_dispatch_request_authority import (
    InverterActivePowerDispatchRequest,
    TopologyInverterActivePowerDispatchRequestAuthorityResult,
)
from heliotelligence.physics.inverter_dispatch_selection import (
    TopologyInverterDispatchSelectionResult,
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
from heliotelligence.physics.lv_ac_collection_authority import (
    LvAcCollectionNetworkBasisAuthority,
    LvAcCollectionNodeAuthority,
    LvAcCollectionSegmentAuthority,
    LvAcInverterTerminalBindingAuthority,
    TopologyLvAcCollectionAuthorityResult,
)
from heliotelligence.physics.lv_ac_collection_operating import (
    TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_CONTRACT_ID,
    TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_MODEL_ID,
    TopologyLvAcCollectionOperatingSolutionResult,
    calculate_topology_lv_ac_collection_operating_solution,
)
from heliotelligence.physics.lv_ac_collection_voltage_authority import (
    LvAcCollectionExitVoltageState,
    TopologyLvAcCollectionExitVoltageAuthorityResult,
)
from heliotelligence.physics.transformer_authority import (
    TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
    TopologyTransformerStaticAuthorityResult,
    TransformerBoundaryTopologyAuthority,
    TransformerStaticEquipmentAuthority,
    resolve_transformer_static_authority,
)
from heliotelligence.physics.transformer_energisation_authority import (
    TRANSFORMER_ENERGISATION_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_ENERGISATION_AUTHORITY_MODEL_ID,
    TopologyTransformerEnergisationAuthorityResult,
    TransformerEnergisationState,
    resolve_transformer_energisation_authority,
)
from heliotelligence.physics.transformer_loss_authority import (
    TRANSFORMER_LOSS_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_LOSS_AUTHORITY_MODEL_ID,
    TopologyTransformerLossAuthorityResult,
    TransformerNoLoadLossAuthority,
    TransformerRatedLoadLossAuthority,
    resolve_transformer_loss_authority,
)

TRANSFORMER_OPERATING_LOSS_CONTRACT_ID = (
    "admitted_lv_collection_transformer_static_factory_loss_and_"
    "energisation_to_reference_condition_active_loss_evaluation_v1"
)
TRANSFORMER_OPERATING_LOSS_MODEL_ID = (
    "balanced_three_phase_factory_test_current_squared_"
    "reference_condition_transformer_active_loss_v1"
)
TRANSFORMER_OPERATING_LOSS_SCOPE = (
    "timestamped_transformer_active_loss_baseline_before_"
    "transformer_network_power_flow_and_energy_integration"
)
TRANSFORMER_OPERATING_LOSS_COVERAGE_SCOPE = (
    "explicitly_energised_transformers_with_factory_test_loss_authority_"
    "and_resolved_s11_collection_boundary_operating_state"
)

_POWER_ZERO_ABS_TOL_VA = 1e-6
_FLOAT_REL_TOL = 1e-9
_FLOAT_ABS_TOL = 1e-7

_COLUMNS = (
    "transformer_static_authority_resolved",
    "transformer_factory_loss_authority_resolved",
    "transformer_energisation_authority_resolved",
    "transformer_energised",
    "s11_collection_exit_binding_resolved",
    "s11_collection_exit_node_id",
    "s11_operating_state_present",
    "s11_operating_solution_resolved",
    "s11_lv_ac_collection_operating_state",
    "collection_exit_voltage_line_to_line_rms_v",
    "p_delivered_at_collection_exit_w",
    "q_delivered_at_collection_exit_var",
    "s_delivered_vector_magnitude_va",
    "rated_apparent_power_va",
    "collection_side_rated_line_to_line_rms_v",
    "collection_side_rated_current_a",
    "collection_side_operating_current_a",
    "collection_current_loading_fraction",
    "collection_current_loading_fraction_squared",
    "collection_current_exceeds_rated",
    "no_load_loss_authority_present",
    "rated_load_loss_authority_present",
    "factory_no_load_loss_w",
    "factory_rated_load_loss_w",
    "factory_load_loss_reference_temperature_c",
    "factory_no_load_test_frequency_hz",
    "factory_load_loss_test_frequency_hz",
    "no_load_loss_component_resolved",
    "load_loss_component_resolved",
    "total_active_loss_baseline_resolved",
    "p_no_load_reference_condition_baseline_w",
    "p_load_reference_temperature_baseline_w",
    "p_total_reference_condition_baseline_w",
    "no_load_voltage_correction_applied",
    "load_loss_temperature_correction_applied",
    "frequency_correction_applied",
    "harmonic_correction_applied",
    "transformer_operating_loss_state",
    "topology_lv_ac_collection_operating_solution_contract",
    "topology_lv_ac_collection_operating_solution_model",
    "transformer_static_authority_contract",
    "transformer_static_authority_model",
    "transformer_loss_authority_contract",
    "transformer_loss_authority_model",
    "transformer_energisation_authority_contract",
    "transformer_energisation_authority_model",
    "transformer_operating_loss_contract",
    "transformer_operating_loss_model",
    "transformer_operating_loss_scope",
    "transformer_operating_loss_coverage_scope",
)
_BOOL_COLUMNS = {
    "transformer_static_authority_resolved",
    "transformer_factory_loss_authority_resolved",
    "transformer_energisation_authority_resolved",
    "s11_collection_exit_binding_resolved",
    "s11_operating_state_present",
    "s11_operating_solution_resolved",
    "no_load_loss_authority_present",
    "rated_load_loss_authority_present",
    "no_load_loss_component_resolved",
    "load_loss_component_resolved",
    "total_active_loss_baseline_resolved",
    "no_load_voltage_correction_applied",
    "load_loss_temperature_correction_applied",
    "frequency_correction_applied",
    "harmonic_correction_applied",
}
_NULLABLE_BOOL_COLUMNS = {"transformer_energised", "collection_current_exceeds_rated"}
_FLOAT_COLUMNS = (
    set(_COLUMNS)
    - _BOOL_COLUMNS
    - _NULLABLE_BOOL_COLUMNS
    - {
        "s11_collection_exit_node_id",
        "s11_lv_ac_collection_operating_state",
        "transformer_operating_loss_state",
        "topology_lv_ac_collection_operating_solution_contract",
        "topology_lv_ac_collection_operating_solution_model",
        "transformer_static_authority_contract",
        "transformer_static_authority_model",
        "transformer_loss_authority_contract",
        "transformer_loss_authority_model",
        "transformer_energisation_authority_contract",
        "transformer_energisation_authority_model",
        "transformer_operating_loss_contract",
        "transformer_operating_loss_model",
        "transformer_operating_loss_scope",
        "transformer_operating_loss_coverage_scope",
    }
)

_PRIMARY_STATES = (
    "unresolved_missing_transformer_energisation_state",
    "unresolved_deenergised_transformer_with_nonzero_collection_transfer",
    "resolved_deenergised_transformer_zero_loss",
    "unresolved_upstream_transformer_static_authority",
    "unresolved_missing_transformer_no_load_loss_authority",
    "unresolved_missing_transformer_rated_load_loss_authority",
    "unresolved_missing_s11_collection_exit_operating_state",
    "unresolved_s11_collection_exit_operating_solution",
    "unresolved_energised_transformer_with_zero_collection_voltage",
    "resolved_energised_transformer_reference_condition_baseline_loss",
)


@dataclass(frozen=True)
class TopologyTransformerOperatingLossDiagnostics:
    transformer_count: int
    timestamp_count: int
    row_count: int
    energisation_missing_count: int
    explicitly_deenergised_count: int
    explicitly_energised_count: int
    resolved_deenergised_zero_loss_count: int
    deenergised_nonzero_transfer_conflict_count: int
    static_authority_unresolved_energised_count: int
    missing_no_load_authority_count: int
    missing_rated_load_loss_authority_count: int
    missing_s11_operating_state_count: int
    unresolved_s11_operating_solution_count: int
    energised_zero_collection_voltage_count: int
    resolved_energised_baseline_loss_count: int
    no_load_component_resolved_count: int
    load_loss_component_resolved_count: int
    total_loss_resolved_count: int
    current_loading_resolved_count: int
    above_rated_current_count: int
    model: str


@dataclass(frozen=True)
class TopologyTransformerOperatingLossResult:
    transformer_loss_states: pd.DataFrame
    diagnostics: TopologyTransformerOperatingLossDiagnostics


def calculate_topology_transformer_operating_loss(
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
    dispatch_selection: TopologyInverterDispatchSelectionResult,
    network_basis: LvAcCollectionNetworkBasisAuthority | None,
    node_authority_by_id: Mapping[str, LvAcCollectionNodeAuthority],
    segment_authority_by_id: Mapping[str, LvAcCollectionSegmentAuthority],
    inverter_terminal_binding_by_inverter_id: Mapping[str, LvAcInverterTerminalBindingAuthority],
    lv_ac_collection_authority: TopologyLvAcCollectionAuthorityResult,
    collection_exit_voltage_by_key: Mapping[
        tuple[pd.Timestamp, str], LvAcCollectionExitVoltageState
    ],
    collection_exit_voltage_authority: TopologyLvAcCollectionExitVoltageAuthorityResult,
    lv_ac_collection_operating_solution: TopologyLvAcCollectionOperatingSolutionResult,
    transformer_equipment_by_id: Mapping[str, TransformerStaticEquipmentAuthority],
    transformer_topology_by_id: Mapping[str, TransformerBoundaryTopologyAuthority],
    transformer_static_authority: TopologyTransformerStaticAuthorityResult,
    transformer_no_load_loss_by_id: Mapping[str, TransformerNoLoadLossAuthority],
    transformer_rated_load_loss_by_id: Mapping[str, TransformerRatedLoadLossAuthority],
    transformer_loss_authority: TopologyTransformerLossAuthorityResult,
    transformer_energisation_by_key: Mapping[
        tuple[pd.Timestamp, str], TransformerEnergisationState
    ],
    transformer_energisation_authority: TopologyTransformerEnergisationAuthorityResult,
) -> TopologyTransformerOperatingLossResult:
    """Evaluate instantaneous transformer active-loss baselines at factory conditions."""
    canonical_s11c = calculate_topology_lv_ac_collection_operating_solution(
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
        dispatch_selection,
        network_basis,
        node_authority_by_id,
        segment_authority_by_id,
        inverter_terminal_binding_by_inverter_id,
        lv_ac_collection_authority,
        collection_exit_voltage_by_key,
        collection_exit_voltage_authority,
    )
    _replay_s11c(lv_ac_collection_operating_solution, canonical_s11c)
    canonical_static = resolve_transformer_static_authority(
        topology,
        network_basis,
        node_authority_by_id,
        segment_authority_by_id,
        inverter_terminal_binding_by_inverter_id,
        lv_ac_collection_authority,
        transformer_equipment_by_id,
        transformer_topology_by_id,
    )
    _replay_static(transformer_static_authority, canonical_static)
    canonical_loss = resolve_transformer_loss_authority(
        topology,
        network_basis,
        node_authority_by_id,
        segment_authority_by_id,
        inverter_terminal_binding_by_inverter_id,
        lv_ac_collection_authority,
        transformer_equipment_by_id,
        transformer_topology_by_id,
        canonical_static,
        transformer_no_load_loss_by_id,
        transformer_rated_load_loss_by_id,
    )
    _replay_loss(transformer_loss_authority, canonical_loss)
    canonical_energisation = resolve_transformer_energisation_authority(
        topology,
        network_basis,
        node_authority_by_id,
        segment_authority_by_id,
        inverter_terminal_binding_by_inverter_id,
        lv_ac_collection_authority,
        transformer_equipment_by_id,
        transformer_topology_by_id,
        canonical_static,
        transformer_energisation_by_key,
    )
    _replay_energisation(transformer_energisation_authority, canonical_energisation)
    result = _build_result(canonical_s11c, canonical_static, canonical_loss, canonical_energisation)
    _validate_result(
        canonical_s11c, canonical_static, canonical_loss, canonical_energisation, result
    )
    return result


def _replay_frame(label: str, supplied: pd.DataFrame, canonical: pd.DataFrame) -> None:
    try:
        pd.testing.assert_frame_equal(supplied, canonical, check_exact=True)
    except AssertionError as error:
        raise RuntimeError(f"supplied {label} frame failed exact replay") from error


def _replay_s11c(
    supplied: object, canonical: TopologyLvAcCollectionOperatingSolutionResult
) -> None:
    if type(supplied) is not TopologyLvAcCollectionOperatingSolutionResult:
        raise RuntimeError("supplied S11C result type is invalid")
    _replay_frame(
        "S11C collection-exit", supplied.collection_exit_states, canonical.collection_exit_states
    )
    _replay_frame("S11C node", supplied.node_states, canonical.node_states)
    _replay_frame("S11C segment", supplied.segment_states, canonical.segment_states)
    if supplied.diagnostics != canonical.diagnostics:
        raise RuntimeError("supplied S11C diagnostics failed exact replay")


def _immutable_equal(actual: object, expected: Mapping[Any, Any]) -> bool:
    return (
        type(actual).__name__ == "mappingproxy"
        and isinstance(actual, Mapping)
        and dict(actual) == dict(expected)
    )


def _replay_static(supplied: object, canonical: TopologyTransformerStaticAuthorityResult) -> None:
    if type(supplied) is not TopologyTransformerStaticAuthorityResult:
        raise RuntimeError("supplied S12A result type is invalid")
    if not _immutable_equal(
        supplied.equipment_by_id, canonical.equipment_by_id
    ) or not _immutable_equal(supplied.topology_by_id, canonical.topology_by_id):
        raise RuntimeError("supplied S12A mappings failed immutable exact replay")
    _replay_frame("S12A transformer", supplied.transformer_states, canonical.transformer_states)
    if supplied.diagnostics != canonical.diagnostics:
        raise RuntimeError("supplied S12A diagnostics failed exact replay")


def _replay_loss(supplied: object, canonical: TopologyTransformerLossAuthorityResult) -> None:
    if type(supplied) is not TopologyTransformerLossAuthorityResult:
        raise RuntimeError("supplied S12B result type is invalid")
    if not _immutable_equal(
        supplied.no_load_loss_by_id, canonical.no_load_loss_by_id
    ) or not _immutable_equal(supplied.rated_load_loss_by_id, canonical.rated_load_loss_by_id):
        raise RuntimeError("supplied S12B mappings failed immutable exact replay")
    _replay_frame("S12B transformer", supplied.transformer_states, canonical.transformer_states)
    if supplied.diagnostics != canonical.diagnostics:
        raise RuntimeError("supplied S12B diagnostics failed exact replay")


def _replay_energisation(
    supplied: object, canonical: TopologyTransformerEnergisationAuthorityResult
) -> None:
    if type(supplied) is not TopologyTransformerEnergisationAuthorityResult:
        raise RuntimeError("supplied S12C result type is invalid")
    if not _immutable_equal(
        supplied.energisation_states_by_key, canonical.energisation_states_by_key
    ):
        raise RuntimeError("supplied S12C mapping failed immutable exact replay")
    _replay_frame("S12C energisation", supplied.states, canonical.states)
    if supplied.diagnostics != canonical.diagnostics:
        raise RuntimeError("supplied S12C diagnostics failed exact replay")


def _timestamps(
    s11c: TopologyLvAcCollectionOperatingSolutionResult,
    energisation: TopologyTransformerEnergisationAuthorityResult,
) -> tuple[pd.Timestamp, ...]:
    values = set(s11c.collection_exit_states.index.get_level_values("timestamp"))
    values.update(energisation.states.index.get_level_values("timestamp"))
    try:
        return tuple(sorted(values))
    except TypeError as error:
        raise ValueError("S11C and S12C timestamps have incompatible timezone semantics") from error


def _close(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=_FLOAT_REL_TOL, abs_tol=_FLOAT_ABS_TOL)


def _row_inputs(
    timestamp: pd.Timestamp,
    transformer_id: str,
    s11c: TopologyLvAcCollectionOperatingSolutionResult,
    static: TopologyTransformerStaticAuthorityResult,
    loss: TopologyTransformerLossAuthorityResult,
    energisation: TopologyTransformerEnergisationAuthorityResult,
) -> dict[str, object]:
    static_row = static.transformer_states.loc[transformer_id]
    loss_row = loss.transformer_states.loc[transformer_id]
    energisation_key = (timestamp, transformer_id)
    energisation_state = energisation.energisation_states_by_key.get(energisation_key)
    topology_authority = static.topology_by_id.get(transformer_id)
    equipment = static.equipment_by_id.get(transformer_id)
    exit_id = topology_authority.s11_collection_exit_node_id if topology_authority else ""
    s11_key = (timestamp, exit_id)
    s11_present = bool(exit_id) and s11_key in s11c.collection_exit_states.index
    s11_row = s11c.collection_exit_states.loc[s11_key] if s11_present else None
    s11_resolved = (
        bool(s11_row["lv_ac_operating_solution_resolved"]) if s11_row is not None else False
    )
    voltage = float(s11_row["exit_voltage_line_to_line_rms_v"]) if s11_row is not None else math.nan
    p_value = (
        float(s11_row["p_delivered_at_collection_exit_w"]) if s11_row is not None else math.nan
    )
    q_value = (
        float(s11_row["q_delivered_at_collection_exit_var"]) if s11_row is not None else math.nan
    )
    reported_s = (
        float(s11_row["s_delivered_vector_magnitude_va"]) if s11_row is not None else math.nan
    )
    if s11_resolved:
        recomputed_s = math.hypot(p_value, q_value)
        if not _close(reported_s, recomputed_s):
            raise RuntimeError("canonical S11C delivered apparent-power magnitude failed closure")
        s_value = recomputed_s
    else:
        s_value = reported_s
    rated_s = equipment.rated_apparent_power_va if equipment else math.nan
    rated_v = equipment.collection_side_rated_line_to_line_rms_v if equipment else math.nan
    rated_current = rated_s / (math.sqrt(3.0) * rated_v) if equipment else math.nan
    loading_resolved = bool(equipment and topology_authority and s11_resolved and voltage > 0.0)
    operating_current = s_value / (math.sqrt(3.0) * voltage) if loading_resolved else math.nan
    beta = operating_current / rated_current if loading_resolved else math.nan
    beta_squared = beta * beta if loading_resolved else math.nan
    no_load = loss.no_load_loss_by_id.get(transformer_id)
    rated_load = loss.rated_load_loss_by_id.get(transformer_id)
    transfer_conflict = bool(
        energisation_state is not None
        and not energisation_state.energised
        and s11_resolved
        and s_value > _POWER_ZERO_ABS_TOL_VA
    )
    clean_deenergised = bool(
        energisation_state is not None
        and not energisation_state.energised
        and not transfer_conflict
    )
    no_load_resolved = clean_deenergised or bool(energisation_state and no_load)
    load_resolved = clean_deenergised or bool(
        energisation_state and loading_resolved and rated_load
    )
    p_no_load = (
        0.0
        if clean_deenergised
        else no_load.no_load_loss_w
        if no_load_resolved and no_load
        else math.nan
    )
    p_load = (
        0.0
        if clean_deenergised
        else rated_load.rated_load_loss_w * beta_squared
        if load_resolved and rated_load
        else math.nan
    )
    total_resolved = clean_deenergised or bool(
        no_load_resolved and load_resolved and not transfer_conflict
    )
    p_total = p_no_load + p_load if total_resolved else math.nan
    static_resolved = bool(static_row["transformer_static_authority_resolved"])
    if energisation_state is None:
        primary = _PRIMARY_STATES[0]
    elif transfer_conflict:
        primary = _PRIMARY_STATES[1]
        no_load_resolved = load_resolved = total_resolved = False
        p_no_load = p_load = p_total = math.nan
    elif not energisation_state.energised:
        primary = _PRIMARY_STATES[2]
    elif not static_resolved:
        primary = _PRIMARY_STATES[3]
    elif no_load is None:
        primary = _PRIMARY_STATES[4]
    elif rated_load is None:
        primary = _PRIMARY_STATES[5]
    elif not s11_present:
        primary = _PRIMARY_STATES[6]
    elif not s11_resolved:
        primary = _PRIMARY_STATES[7]
    elif voltage == 0.0:
        primary = _PRIMARY_STATES[8]
    else:
        primary = _PRIMARY_STATES[9]
    return {
        "static_resolved": static_resolved,
        "loss_resolved": bool(loss_row["transformer_factory_loss_authority_resolved"]),
        "energisation_state": energisation_state,
        "binding_resolved": topology_authority is not None,
        "exit_id": exit_id,
        "s11_present": s11_present,
        "s11_resolved": s11_resolved,
        "s11_state": str(s11_row["lv_ac_collection_operating_state"])
        if s11_row is not None
        else "",
        "voltage": voltage,
        "p": p_value,
        "q": q_value,
        "s": s_value,
        "rated_s": rated_s,
        "rated_v": rated_v,
        "rated_current": rated_current,
        "operating_current": operating_current,
        "beta": beta,
        "beta_squared": beta_squared,
        "overload": beta > 1.0 if loading_resolved else pd.NA,
        "no_load": no_load,
        "rated_load": rated_load,
        "no_load_resolved": no_load_resolved,
        "load_resolved": load_resolved,
        "total_resolved": total_resolved,
        "p_no_load": p_no_load,
        "p_load": p_load,
        "p_total": p_total,
        "primary": primary,
    }


def _record(values: Mapping[str, object]) -> dict[str, object]:
    energisation = values["energisation_state"]
    no_load = values["no_load"]
    rated_load = values["rated_load"]
    assert energisation is None or isinstance(energisation, TransformerEnergisationState)
    assert no_load is None or isinstance(no_load, TransformerNoLoadLossAuthority)
    assert rated_load is None or isinstance(rated_load, TransformerRatedLoadLossAuthority)
    return {
        "transformer_static_authority_resolved": values["static_resolved"],
        "transformer_factory_loss_authority_resolved": values["loss_resolved"],
        "transformer_energisation_authority_resolved": energisation is not None,
        "transformer_energised": energisation.energised if energisation else pd.NA,
        "s11_collection_exit_binding_resolved": values["binding_resolved"],
        "s11_collection_exit_node_id": values["exit_id"],
        "s11_operating_state_present": values["s11_present"],
        "s11_operating_solution_resolved": values["s11_resolved"],
        "s11_lv_ac_collection_operating_state": values["s11_state"],
        "collection_exit_voltage_line_to_line_rms_v": values["voltage"],
        "p_delivered_at_collection_exit_w": values["p"],
        "q_delivered_at_collection_exit_var": values["q"],
        "s_delivered_vector_magnitude_va": values["s"],
        "rated_apparent_power_va": values["rated_s"],
        "collection_side_rated_line_to_line_rms_v": values["rated_v"],
        "collection_side_rated_current_a": values["rated_current"],
        "collection_side_operating_current_a": values["operating_current"],
        "collection_current_loading_fraction": values["beta"],
        "collection_current_loading_fraction_squared": values["beta_squared"],
        "collection_current_exceeds_rated": values["overload"],
        "no_load_loss_authority_present": no_load is not None,
        "rated_load_loss_authority_present": rated_load is not None,
        "factory_no_load_loss_w": no_load.no_load_loss_w if no_load else math.nan,
        "factory_rated_load_loss_w": rated_load.rated_load_loss_w if rated_load else math.nan,
        "factory_load_loss_reference_temperature_c": rated_load.reference_temperature_c
        if rated_load
        else math.nan,
        "factory_no_load_test_frequency_hz": no_load.test_frequency_hz if no_load else math.nan,
        "factory_load_loss_test_frequency_hz": rated_load.test_frequency_hz
        if rated_load
        else math.nan,
        "no_load_loss_component_resolved": values["no_load_resolved"],
        "load_loss_component_resolved": values["load_resolved"],
        "total_active_loss_baseline_resolved": values["total_resolved"],
        "p_no_load_reference_condition_baseline_w": values["p_no_load"],
        "p_load_reference_temperature_baseline_w": values["p_load"],
        "p_total_reference_condition_baseline_w": values["p_total"],
        "no_load_voltage_correction_applied": False,
        "load_loss_temperature_correction_applied": False,
        "frequency_correction_applied": False,
        "harmonic_correction_applied": False,
        "transformer_operating_loss_state": values["primary"],
        "topology_lv_ac_collection_operating_solution_contract": (
            TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_CONTRACT_ID
        ),
        "topology_lv_ac_collection_operating_solution_model": (
            TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_MODEL_ID
        ),
        "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
        "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
        "transformer_loss_authority_contract": TRANSFORMER_LOSS_AUTHORITY_CONTRACT_ID,
        "transformer_loss_authority_model": TRANSFORMER_LOSS_AUTHORITY_MODEL_ID,
        "transformer_energisation_authority_contract": (
            TRANSFORMER_ENERGISATION_AUTHORITY_CONTRACT_ID
        ),
        "transformer_energisation_authority_model": TRANSFORMER_ENERGISATION_AUTHORITY_MODEL_ID,
        "transformer_operating_loss_contract": TRANSFORMER_OPERATING_LOSS_CONTRACT_ID,
        "transformer_operating_loss_model": TRANSFORMER_OPERATING_LOSS_MODEL_ID,
        "transformer_operating_loss_scope": TRANSFORMER_OPERATING_LOSS_SCOPE,
        "transformer_operating_loss_coverage_scope": TRANSFORMER_OPERATING_LOSS_COVERAGE_SCOPE,
    }


def _frame(
    keys: tuple[tuple[pd.Timestamp, str], ...], records: list[dict[str, object]]
) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(keys, names=["timestamp", "transformer_id"])
    frame = pd.DataFrame.from_records(records, columns=_COLUMNS, index=index)
    frame.index = index
    for column in _BOOL_COLUMNS:
        frame[column] = frame[column].astype("bool")
    for column in _NULLABLE_BOOL_COLUMNS:
        frame[column] = frame[column].astype("boolean")
    for column in _FLOAT_COLUMNS:
        frame[column] = frame[column].astype("float64")
    for column in set(_COLUMNS) - _BOOL_COLUMNS - _NULLABLE_BOOL_COLUMNS - _FLOAT_COLUMNS:
        frame[column] = frame[column].astype("object")
    return frame


def _diagnostics(
    transformer_count: int, timestamps: tuple[pd.Timestamp, ...], states: pd.DataFrame
) -> TopologyTransformerOperatingLossDiagnostics:
    counts = states["transformer_operating_loss_state"].value_counts()
    return TopologyTransformerOperatingLossDiagnostics(
        transformer_count=transformer_count,
        timestamp_count=len(timestamps),
        row_count=len(states),
        energisation_missing_count=int(counts.get(_PRIMARY_STATES[0], 0)),
        explicitly_deenergised_count=int((states["transformer_energised"] == False).sum()),  # noqa: E712
        explicitly_energised_count=int((states["transformer_energised"] == True).sum()),  # noqa: E712
        resolved_deenergised_zero_loss_count=int(counts.get(_PRIMARY_STATES[2], 0)),
        deenergised_nonzero_transfer_conflict_count=int(counts.get(_PRIMARY_STATES[1], 0)),
        static_authority_unresolved_energised_count=int(counts.get(_PRIMARY_STATES[3], 0)),
        missing_no_load_authority_count=int(counts.get(_PRIMARY_STATES[4], 0)),
        missing_rated_load_loss_authority_count=int(counts.get(_PRIMARY_STATES[5], 0)),
        missing_s11_operating_state_count=int(counts.get(_PRIMARY_STATES[6], 0)),
        unresolved_s11_operating_solution_count=int(counts.get(_PRIMARY_STATES[7], 0)),
        energised_zero_collection_voltage_count=int(counts.get(_PRIMARY_STATES[8], 0)),
        resolved_energised_baseline_loss_count=int(counts.get(_PRIMARY_STATES[9], 0)),
        no_load_component_resolved_count=int(states["no_load_loss_component_resolved"].sum()),
        load_loss_component_resolved_count=int(states["load_loss_component_resolved"].sum()),
        total_loss_resolved_count=int(states["total_active_loss_baseline_resolved"].sum()),
        current_loading_resolved_count=int(
            states["collection_current_loading_fraction"].notna().sum()
        ),
        above_rated_current_count=int(
            states["collection_current_exceeds_rated"].fillna(False).sum()
        ),
        model=TRANSFORMER_OPERATING_LOSS_MODEL_ID,
    )


def _build_result(
    s11c: TopologyLvAcCollectionOperatingSolutionResult,
    static: TopologyTransformerStaticAuthorityResult,
    loss: TopologyTransformerLossAuthorityResult,
    energisation: TopologyTransformerEnergisationAuthorityResult,
) -> TopologyTransformerOperatingLossResult:
    timestamps = _timestamps(s11c, energisation)
    transformer_ids = tuple(static.transformer_states.index.tolist())
    keys = tuple(
        (timestamp, transformer_id)
        for timestamp in timestamps
        for transformer_id in transformer_ids
    )
    records = [
        _record(_row_inputs(timestamp, transformer_id, s11c, static, loss, energisation))
        for timestamp, transformer_id in keys
    ]
    states = _frame(keys, records)
    return TopologyTransformerOperatingLossResult(
        transformer_loss_states=states.copy(deep=True),
        diagnostics=_diagnostics(len(transformer_ids), timestamps, states),
    )


def _value_equal(actual: object, expected: object) -> bool:
    if isinstance(expected, float):
        if math.isnan(expected):
            return bool(pd.isna(actual))
        return _close(_as_float(actual), expected)
    if expected is pd.NA:
        return bool(pd.isna(actual))
    return bool(actual == expected)


def _as_float(value: object) -> float:
    if not isinstance(value, (int, float)):
        raise RuntimeError("transformer operating-loss numeric value is invalid")
    return float(value)


def _validator_row(
    timestamp: pd.Timestamp,
    transformer_id: str,
    s11c: TopologyLvAcCollectionOperatingSolutionResult,
    static: TopologyTransformerStaticAuthorityResult,
    loss: TopologyTransformerLossAuthorityResult,
    energisation: TopologyTransformerEnergisationAuthorityResult,
) -> dict[str, object]:
    """Independently reconstruct a row without production calculation helpers."""
    static_row = static.transformer_states.loc[transformer_id]
    equipment = static.equipment_by_id.get(transformer_id)
    boundary = static.topology_by_id.get(transformer_id)
    no_load = loss.no_load_loss_by_id.get(transformer_id)
    rated_load = loss.rated_load_loss_by_id.get(transformer_id)
    energisation_state = energisation.energisation_states_by_key.get((timestamp, transformer_id))
    exit_id = boundary.s11_collection_exit_node_id if boundary else ""
    exit_key = (timestamp, exit_id)
    exit_present = bool(exit_id) and exit_key in s11c.collection_exit_states.index
    exit_row = s11c.collection_exit_states.loc[exit_key] if exit_present else None
    exit_resolved = (
        bool(exit_row["lv_ac_operating_solution_resolved"]) if exit_row is not None else False
    )
    voltage = (
        float(exit_row["exit_voltage_line_to_line_rms_v"]) if exit_row is not None else math.nan
    )
    p_value = (
        float(exit_row["p_delivered_at_collection_exit_w"]) if exit_row is not None else math.nan
    )
    q_value = (
        float(exit_row["q_delivered_at_collection_exit_var"]) if exit_row is not None else math.nan
    )
    reported_s = (
        float(exit_row["s_delivered_vector_magnitude_va"]) if exit_row is not None else math.nan
    )
    s_value = math.hypot(p_value, q_value) if exit_resolved else reported_s
    if exit_resolved and not _close(s_value, reported_s):
        raise RuntimeError("validator S11C apparent-power closure failed")
    rated_s = equipment.rated_apparent_power_va if equipment else math.nan
    rated_v = equipment.collection_side_rated_line_to_line_rms_v if equipment else math.nan
    rated_current = rated_s / (math.sqrt(3.0) * rated_v) if equipment else math.nan
    current_resolved = bool(equipment and boundary and exit_resolved and voltage > 0.0)
    operating_current = s_value / (math.sqrt(3.0) * voltage) if current_resolved else math.nan
    beta = operating_current / rated_current if current_resolved else math.nan
    beta_squared = beta**2 if current_resolved else math.nan
    conflict = bool(
        energisation_state is not None
        and not energisation_state.energised
        and exit_resolved
        and s_value > _POWER_ZERO_ABS_TOL_VA
    )
    clean_off = bool(
        energisation_state is not None and not energisation_state.energised and not conflict
    )
    no_load_resolved = clean_off or bool(energisation_state is not None and no_load)
    load_resolved = clean_off or bool(
        energisation_state is not None and rated_load and current_resolved
    )
    p_no_load = (
        0.0 if clean_off else no_load.no_load_loss_w if no_load_resolved and no_load else math.nan
    )
    p_load = (
        0.0
        if clean_off
        else rated_load.rated_load_loss_w * beta_squared
        if load_resolved and rated_load
        else math.nan
    )
    total_resolved = clean_off or bool(no_load_resolved and load_resolved and not conflict)
    p_total = p_no_load + p_load if total_resolved else math.nan
    static_resolved = bool(static_row["transformer_static_authority_resolved"])
    if energisation_state is None:
        primary = _PRIMARY_STATES[0]
    elif conflict:
        primary = _PRIMARY_STATES[1]
        no_load_resolved = load_resolved = total_resolved = False
        p_no_load = p_load = p_total = math.nan
    elif not energisation_state.energised:
        primary = _PRIMARY_STATES[2]
    elif not static_resolved:
        primary = _PRIMARY_STATES[3]
    elif no_load is None:
        primary = _PRIMARY_STATES[4]
    elif rated_load is None:
        primary = _PRIMARY_STATES[5]
    elif not exit_present:
        primary = _PRIMARY_STATES[6]
    elif not exit_resolved:
        primary = _PRIMARY_STATES[7]
    elif voltage == 0.0:
        primary = _PRIMARY_STATES[8]
    else:
        primary = _PRIMARY_STATES[9]
    return {
        "transformer_static_authority_resolved": static_resolved,
        "transformer_factory_loss_authority_resolved": bool(
            loss.transformer_states.loc[
                transformer_id, "transformer_factory_loss_authority_resolved"
            ]
        ),
        "transformer_energisation_authority_resolved": energisation_state is not None,
        "transformer_energised": energisation_state.energised if energisation_state else pd.NA,
        "s11_collection_exit_binding_resolved": boundary is not None,
        "s11_collection_exit_node_id": exit_id,
        "s11_operating_state_present": exit_present,
        "s11_operating_solution_resolved": exit_resolved,
        "s11_lv_ac_collection_operating_state": str(exit_row["lv_ac_collection_operating_state"])
        if exit_row is not None
        else "",
        "collection_exit_voltage_line_to_line_rms_v": voltage,
        "p_delivered_at_collection_exit_w": p_value,
        "q_delivered_at_collection_exit_var": q_value,
        "s_delivered_vector_magnitude_va": s_value,
        "rated_apparent_power_va": rated_s,
        "collection_side_rated_line_to_line_rms_v": rated_v,
        "collection_side_rated_current_a": rated_current,
        "collection_side_operating_current_a": operating_current,
        "collection_current_loading_fraction": beta,
        "collection_current_loading_fraction_squared": beta_squared,
        "collection_current_exceeds_rated": beta > 1.0 if current_resolved else pd.NA,
        "no_load_loss_authority_present": no_load is not None,
        "rated_load_loss_authority_present": rated_load is not None,
        "factory_no_load_loss_w": no_load.no_load_loss_w if no_load else math.nan,
        "factory_rated_load_loss_w": rated_load.rated_load_loss_w if rated_load else math.nan,
        "factory_load_loss_reference_temperature_c": rated_load.reference_temperature_c
        if rated_load
        else math.nan,
        "factory_no_load_test_frequency_hz": no_load.test_frequency_hz if no_load else math.nan,
        "factory_load_loss_test_frequency_hz": rated_load.test_frequency_hz
        if rated_load
        else math.nan,
        "no_load_loss_component_resolved": no_load_resolved,
        "load_loss_component_resolved": load_resolved,
        "total_active_loss_baseline_resolved": total_resolved,
        "p_no_load_reference_condition_baseline_w": p_no_load,
        "p_load_reference_temperature_baseline_w": p_load,
        "p_total_reference_condition_baseline_w": p_total,
        "no_load_voltage_correction_applied": False,
        "load_loss_temperature_correction_applied": False,
        "frequency_correction_applied": False,
        "harmonic_correction_applied": False,
        "transformer_operating_loss_state": primary,
        "topology_lv_ac_collection_operating_solution_contract": (
            TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_CONTRACT_ID
        ),
        "topology_lv_ac_collection_operating_solution_model": (
            TOPOLOGY_LV_AC_COLLECTION_OPERATING_SOLUTION_MODEL_ID
        ),
        "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
        "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
        "transformer_loss_authority_contract": TRANSFORMER_LOSS_AUTHORITY_CONTRACT_ID,
        "transformer_loss_authority_model": TRANSFORMER_LOSS_AUTHORITY_MODEL_ID,
        "transformer_energisation_authority_contract": (
            TRANSFORMER_ENERGISATION_AUTHORITY_CONTRACT_ID
        ),
        "transformer_energisation_authority_model": TRANSFORMER_ENERGISATION_AUTHORITY_MODEL_ID,
        "transformer_operating_loss_contract": TRANSFORMER_OPERATING_LOSS_CONTRACT_ID,
        "transformer_operating_loss_model": TRANSFORMER_OPERATING_LOSS_MODEL_ID,
        "transformer_operating_loss_scope": TRANSFORMER_OPERATING_LOSS_SCOPE,
        "transformer_operating_loss_coverage_scope": TRANSFORMER_OPERATING_LOSS_COVERAGE_SCOPE,
    }


def _validate_result(
    s11c: TopologyLvAcCollectionOperatingSolutionResult,
    static: TopologyTransformerStaticAuthorityResult,
    loss: TopologyTransformerLossAuthorityResult,
    energisation: TopologyTransformerEnergisationAuthorityResult,
    result: TopologyTransformerOperatingLossResult,
) -> None:
    if type(result) is not TopologyTransformerOperatingLossResult:
        raise RuntimeError("transformer operating-loss result type is invalid")
    transformer_ids = tuple(static.transformer_states.index.tolist())
    timestamps = _timestamps(s11c, energisation)
    keys = tuple(
        (timestamp, transformer_id)
        for timestamp in timestamps
        for transformer_id in transformer_ids
    )
    states = result.transformer_loss_states
    if tuple(states.columns) != _COLUMNS or not isinstance(states.index, pd.MultiIndex):
        raise RuntimeError("transformer operating-loss schema is invalid")
    if (
        list(states.index.names) != ["timestamp", "transformer_id"]
        or tuple(states.index.tolist()) != keys
        or states.index.has_duplicates
    ):
        raise RuntimeError("transformer operating-loss canonical index/order is invalid")
    for column in _COLUMNS:
        expected_dtype = (
            "bool"
            if column in _BOOL_COLUMNS
            else "boolean"
            if column in _NULLABLE_BOOL_COLUMNS
            else "float64"
            if column in _FLOAT_COLUMNS
            else "object"
        )
        if str(states[column].dtype) != expected_dtype:
            raise RuntimeError(f"transformer operating-loss dtype is invalid for {column}")
    independent_primary_counts = {state: 0 for state in _PRIMARY_STATES}
    no_load_count = load_count = total_count = loading_count = overload_count = 0
    energised_count = deenergised_count = 0
    for key, row in states.iterrows():
        expected_row = _validator_row(key[0], key[1], s11c, static, loss, energisation)
        for column, wanted in expected_row.items():
            if not _value_equal(row[column], wanted):
                raise RuntimeError(f"transformer operating-loss state does not close for {column}")
        primary = str(expected_row["transformer_operating_loss_state"])
        independent_primary_counts[primary] += 1
        no_load_count += int(bool(expected_row["no_load_loss_component_resolved"]))
        load_count += int(bool(expected_row["load_loss_component_resolved"]))
        total_count += int(bool(expected_row["total_active_loss_baseline_resolved"]))
        beta = expected_row["collection_current_loading_fraction"]
        loading_count += int(not math.isnan(_as_float(beta)))
        overload = expected_row["collection_current_exceeds_rated"]
        overload_count += int(overload is not pd.NA and bool(overload))
        energised = expected_row["transformer_energised"]
        if energised is not pd.NA:
            energised_count += int(bool(energised))
            deenergised_count += int(not bool(energised))
        if not math.isnan(_as_float(beta)):
            beta_squared = _as_float(expected_row["collection_current_loading_fraction_squared"])
            if not _close(beta_squared, _as_float(beta) ** 2):
                raise RuntimeError("transformer current-loading square does not close")
            rated_load = loss.rated_load_loss_by_id.get(key[1])
            if bool(expected_row["load_loss_component_resolved"]) and rated_load:
                wanted_load = rated_load.rated_load_loss_w * beta_squared
                if not _close(
                    _as_float(expected_row["p_load_reference_temperature_baseline_w"]),
                    wanted_load,
                ):
                    raise RuntimeError("transformer load-loss equation does not close")
    wanted_diagnostics = TopologyTransformerOperatingLossDiagnostics(
        transformer_count=len(transformer_ids),
        timestamp_count=len(timestamps),
        row_count=len(keys),
        energisation_missing_count=independent_primary_counts[_PRIMARY_STATES[0]],
        explicitly_deenergised_count=deenergised_count,
        explicitly_energised_count=energised_count,
        resolved_deenergised_zero_loss_count=independent_primary_counts[_PRIMARY_STATES[2]],
        deenergised_nonzero_transfer_conflict_count=independent_primary_counts[_PRIMARY_STATES[1]],
        static_authority_unresolved_energised_count=independent_primary_counts[_PRIMARY_STATES[3]],
        missing_no_load_authority_count=independent_primary_counts[_PRIMARY_STATES[4]],
        missing_rated_load_loss_authority_count=independent_primary_counts[_PRIMARY_STATES[5]],
        missing_s11_operating_state_count=independent_primary_counts[_PRIMARY_STATES[6]],
        unresolved_s11_operating_solution_count=independent_primary_counts[_PRIMARY_STATES[7]],
        energised_zero_collection_voltage_count=independent_primary_counts[_PRIMARY_STATES[8]],
        resolved_energised_baseline_loss_count=independent_primary_counts[_PRIMARY_STATES[9]],
        no_load_component_resolved_count=no_load_count,
        load_loss_component_resolved_count=load_count,
        total_loss_resolved_count=total_count,
        current_loading_resolved_count=loading_count,
        above_rated_current_count=overload_count,
        model=TRANSFORMER_OPERATING_LOSS_MODEL_ID,
    )
    diagnostics = result.diagnostics
    if diagnostics != wanted_diagnostics:
        raise RuntimeError("transformer operating-loss diagnostics failed independent closure")
    primary_total = sum(independent_primary_counts.values())
    if (
        diagnostics.row_count != diagnostics.transformer_count * diagnostics.timestamp_count
        or primary_total != diagnostics.row_count
    ):
        raise RuntimeError("transformer operating-loss row/state diagnostics do not close")
    if (
        diagnostics.total_loss_resolved_count
        != diagnostics.resolved_deenergised_zero_loss_count
        + diagnostics.resolved_energised_baseline_loss_count
    ):
        raise RuntimeError("transformer total-loss diagnostics do not close")
    if diagnostics.above_rated_current_count > diagnostics.current_loading_resolved_count:
        raise RuntimeError("transformer overload diagnostics are invalid")
    if diagnostics.model != TRANSFORMER_OPERATING_LOSS_MODEL_ID:
        raise RuntimeError("transformer operating-loss diagnostics model is invalid")
