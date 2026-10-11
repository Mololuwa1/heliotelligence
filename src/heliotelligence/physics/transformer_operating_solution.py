"""S12G balanced positive-sequence transformer terminal operating solution."""

from __future__ import annotations

import cmath
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import dc_collection, electrical
from heliotelligence.physics import inverter_ac_authority as ac_authority_module
from heliotelligence.physics import inverter_accounting as accounting_module
from heliotelligence.physics import inverter_authority as inverter_authority_module
from heliotelligence.physics import inverter_conversion as conversion_module
from heliotelligence.physics import inverter_dispatch_feasibility as feasibility_module
from heliotelligence.physics import inverter_dispatch_request_authority as request_module
from heliotelligence.physics import inverter_dispatch_selection as selection_module
from heliotelligence.physics import inverter_potential as potential_module
from heliotelligence.physics import inverter_pqs_capability as pqs_module
from heliotelligence.physics import inverter_temperature_capability as temperature_module
from heliotelligence.physics import inverter_thermal_authority as thermal_module
from heliotelligence.physics import inverter_topology as inverter_topology_module
from heliotelligence.physics import lv_ac_collection_authority as s11a_module
from heliotelligence.physics import lv_ac_collection_operating as s11c_module
from heliotelligence.physics import lv_ac_collection_voltage_authority as s11b_module
from heliotelligence.physics import transformer_authority as s12a_module
from heliotelligence.physics import transformer_energisation_authority as s12c_module
from heliotelligence.physics import transformer_loss_authority as s12b_module
from heliotelligence.physics import transformer_network_authority as s12e_module
from heliotelligence.physics import transformer_series_equivalent as s12f_module

TRANSFORMER_OPERATING_SOLUTION_CONTRACT_ID = (
    "admitted_s11_collection_transformer_energisation_network_and_series_"
    "equivalent_to_balanced_terminal_operating_solution_v1"
)
TRANSFORMER_OPERATING_SOLUTION_MODEL_ID = (
    "balanced_three_phase_positive_sequence_transformer_forward_series_"
    "equivalent_with_separate_no_load_active_sink_v1"
)
TRANSFORMER_OPERATING_SOLUTION_SCOPE = (
    "timestamped_transformer_terminal_operating_solve_from_lv_collection_exit_"
    "to_network_side_before_mv_hv_network"
)
TRANSFORMER_OPERATING_SOLUTION_COVERAGE_SCOPE = (
    "energised_two_winding_transformers_with_explicit_transfer_series_equivalent_"
    "no_load_loss_and_resolved_s11_collection_state"
)
LOAD_DEPENDENT_ACTIVE_LOSS_OWNERSHIP = "s12f_effective_series_resistance_operating_i2r_once"
NO_LOAD_ACTIVE_LOSS_OWNERSHIP = "s12b_factory_no_load_loss_separate_active_sink_once"
S12D_OPERATING_LOSS_TREATMENT = (
    "independent_reference_condition_baseline_not_added_to_terminal_solve"
)
OUTPUT_REFERENCE_PLANE = "transformer_network_side_terminal"
_POWER_ZERO_ABS_TOL_VA = 1e-6
_REL_TOL = 1e-9

_STATES = (
    "unresolved_missing_transformer_energisation_state",
    "unresolved_deenergised_transformer_with_nonzero_collection_transfer",
    "resolved_deenergised_transformer_no_transfer",
    "unresolved_upstream_transformer_static_authority",
    "unresolved_missing_transformer_no_load_loss_authority",
    "unresolved_upstream_transformer_positive_sequence_network_authority",
    "unresolved_upstream_transformer_series_equivalent",
    "unresolved_missing_s11_collection_exit_operating_state",
    "unresolved_s11_collection_exit_operating_solution",
    "unresolved_energised_transformer_with_zero_collection_voltage",
    "unresolved_nonfinite_transformer_operating_state",
    "resolved_energised_transformer_terminal_operating_solution",
)
_BOOL = {
    "transformer_static_authority_resolved",
    "transformer_energisation_authority_resolved",
    "s11_operating_state_present",
    "s11_operating_solution_resolved",
    "transformer_positive_sequence_network_authority_resolved",
    "transformer_series_equivalent_resolved",
    "transformer_terminal_operating_solution_resolved",
    "no_load_voltage_correction_applied",
    "frequency_correction_applied",
    "harmonic_correction_applied",
    "excitation_no_load_q_modeled",
}
_TEXT = {
    "s11_collection_exit_node_id",
    "transformer_collection_terminal_id",
    "transformer_network_terminal_id",
    "output_reference_plane",
    "series_equivalent_reference_side",
    "transformer_operating_solution_state",
    "load_dependent_active_loss_ownership",
    "no_load_active_loss_ownership",
    "s12d_operating_loss_treatment",
    "transformer_operating_solution_contract",
    "transformer_operating_solution_model",
    "transformer_operating_solution_scope",
    "transformer_operating_solution_coverage_scope",
}
_COLUMNS = (
    "transformer_static_authority_resolved",
    "transformer_energisation_authority_resolved",
    "transformer_energised",
    "s11_operating_state_present",
    "s11_operating_solution_resolved",
    "transformer_positive_sequence_network_authority_resolved",
    "transformer_series_equivalent_resolved",
    "transformer_terminal_operating_solution_resolved",
    "s11_collection_exit_node_id",
    "transformer_collection_terminal_id",
    "transformer_network_terminal_id",
    "output_reference_plane",
    "collection_voltage_line_to_line_rms_v",
    "collection_p_w",
    "collection_q_var",
    "collection_s_magnitude_va",
    "network_to_collection_voltage_ratio",
    "network_side_phase_displacement_deg",
    "series_equivalent_reference_side",
    "effective_series_resistance_ohm_per_phase",
    "effective_series_reactance_ohm_per_phase",
    "collection_phase_voltage_real_v",
    "collection_phase_voltage_imag_v",
    "collection_phase_voltage_magnitude_v",
    "collection_series_current_real_a",
    "collection_series_current_imag_a",
    "collection_series_current_magnitude_a",
    "collection_series_current_angle_deg",
    "network_series_current_real_a",
    "network_series_current_imag_a",
    "network_series_current_magnitude_a",
    "network_series_current_angle_deg",
    "network_terminal_phase_voltage_real_v",
    "network_terminal_phase_voltage_imag_v",
    "network_terminal_phase_voltage_magnitude_v",
    "network_terminal_voltage_line_to_line_rms_v",
    "network_terminal_phase_angle_deg",
    "p_entering_series_transfer_w",
    "q_entering_series_transfer_var",
    "p_network_terminal_w",
    "q_network_terminal_var",
    "s_network_terminal_magnitude_va",
    "p_no_load_active_sink_w",
    "p_series_active_loss_w",
    "q_series_consumption_var",
    "p_total_transformer_active_loss_w",
    "active_power_conservation_residual_w",
    "reactive_power_conservation_residual_var",
    "no_load_voltage_correction_applied",
    "frequency_correction_applied",
    "harmonic_correction_applied",
    "excitation_no_load_q_modeled",
    "load_dependent_active_loss_ownership",
    "no_load_active_loss_ownership",
    "s12d_operating_loss_treatment",
    "transformer_operating_solution_state",
    "transformer_operating_solution_contract",
    "transformer_operating_solution_model",
    "transformer_operating_solution_scope",
    "transformer_operating_solution_coverage_scope",
)


@dataclass(frozen=True)
class TopologyTransformerOperatingSolutionDiagnostics:
    transformer_count: int
    timestamp_count: int
    row_count: int
    resolved_energised_count: int
    resolved_deenergised_count: int
    unresolved_count: int
    state_counts: tuple[tuple[str, int], ...]
    model: str


@dataclass(frozen=True)
class TopologyTransformerOperatingSolutionResult:
    transformer_operating_states: pd.DataFrame
    diagnostics: TopologyTransformerOperatingSolutionDiagnostics


def _frame_equal(label: str, actual: pd.DataFrame, expected: pd.DataFrame) -> None:
    try:
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    except AssertionError as error:
        raise RuntimeError(f"supplied {label} failed exact replay") from error


def _immutable_equal(actual: object, expected: Mapping[Any, Any]) -> bool:
    return (
        type(actual).__name__ == "mappingproxy"
        and isinstance(actual, Mapping)
        and dict(actual) == dict(expected)
    )


def _replay(
    label: str, supplied: Any, canonical: Any, mappings: tuple[str, ...], frames: tuple[str, ...]
) -> None:
    if type(supplied) is not type(canonical):
        raise RuntimeError(f"supplied {label} result type is invalid")
    if any(
        not _immutable_equal(getattr(supplied, name), getattr(canonical, name)) for name in mappings
    ):
        raise RuntimeError(f"supplied {label} mappings failed immutable exact replay")
    for name in frames:
        _frame_equal(f"{label} {name}", getattr(supplied, name), getattr(canonical, name))
    if supplied.diagnostics != canonical.diagnostics:
        raise RuntimeError(f"supplied {label} diagnostics failed exact replay")


def _canonical_parents(values: Mapping[str, Any]) -> tuple[Any, ...]:
    s11_keys = (
        "topology",
        "topology_string_iv",
        "branch_authority",
        "mppt_input_string_iv",
        "mppt_input_operating_points",
        "cec_sam_name_by_inverter_id",
        "inverter_authority",
        "mppt_current_limit_by_key",
        "inverter_dc_envelope",
        "inverter_ac",
        "pre_limit_ac",
        "inverter_power_accounting",
        "ac_capability_by_inverter_id",
        "ac_capability_authority",
        "reactive_power_request_by_key",
        "pqs_capability",
        "thermal_derating_by_inverter_id",
        "thermal_derating_authority",
        "inverter_temperature_by_key",
        "temperature_capability",
        "active_power_dispatch_request_by_key",
        "dispatch_request_authority",
        "dispatch_feasibility",
        "dispatch_selection",
        "network_basis",
        "node_authority_by_id",
        "segment_authority_by_id",
        "inverter_terminal_binding_by_inverter_id",
        "lv_ac_collection_authority",
        "collection_exit_voltage_by_key",
        "collection_exit_voltage_authority",
    )
    s11 = s11c_module.calculate_topology_lv_ac_collection_operating_solution(
        *(values[name] for name in s11_keys)
    )
    common = (
        values["topology"],
        values["network_basis"],
        values["node_authority_by_id"],
        values["segment_authority_by_id"],
        values["inverter_terminal_binding_by_inverter_id"],
        values["lv_ac_collection_authority"],
        values["transformer_equipment_by_id"],
        values["transformer_topology_by_id"],
    )
    static = s12a_module.resolve_transformer_static_authority(*common)
    loss = s12b_module.resolve_transformer_loss_authority(
        *common,
        static,
        values["transformer_no_load_loss_by_id"],
        values["transformer_rated_load_loss_by_id"],
    )
    energisation = s12c_module.resolve_transformer_energisation_authority(
        *common, static, values["transformer_energisation_by_key"]
    )
    network = s12e_module.resolve_transformer_network_authority(
        *common,
        static,
        values["transformer_voltage_transfer_by_id"],
        values["transformer_short_circuit_impedance_by_id"],
    )
    series = s12f_module.resolve_transformer_series_equivalent(
        *common,
        static,
        values["transformer_no_load_loss_by_id"],
        values["transformer_rated_load_loss_by_id"],
        loss,
        values["transformer_voltage_transfer_by_id"],
        values["transformer_short_circuit_impedance_by_id"],
        network,
        values["transformer_rated_load_loss_reference_condition_by_id"],
    )
    supplied = (
        values["lv_ac_collection_operating_solution"],
        values["transformer_static_authority"],
        values["transformer_loss_authority"],
        values["transformer_energisation_authority"],
        values["transformer_network_authority"],
        values["transformer_series_equivalent"],
    )
    canonical = (s11, static, loss, energisation, network, series)
    specifications = (
        ("S11C", (), ("collection_exit_states", "node_states", "segment_states")),
        ("S12A", ("equipment_by_id", "topology_by_id"), ("transformer_states",)),
        ("S12B", ("no_load_loss_by_id", "rated_load_loss_by_id"), ("transformer_states",)),
        ("S12C", ("energisation_states_by_key",), ("states",)),
        (
            "S12E",
            ("voltage_transfer_by_id", "short_circuit_impedance_by_id"),
            ("transformer_states",),
        ),
        ("S12F", ("rated_load_loss_reference_condition_by_id",), ("transformer_states",)),
    )
    for provided, replayed, specification in zip(supplied, canonical, specifications, strict=True):
        _replay(specification[0], provided, replayed, specification[1], specification[2])
    return canonical


def _timestamps(s11: Any, energisation: Any) -> tuple[pd.Timestamp, ...]:
    values = set(s11.collection_exit_states.index.get_level_values("timestamp"))
    values.update(energisation.states.index.get_level_values("timestamp"))
    try:
        return tuple(sorted(values))
    except TypeError as error:
        raise ValueError("S11C and S12C timestamps have incompatible timezone semantics") from error


def _blank() -> dict[str, object]:
    record: dict[str, object] = {name: math.nan for name in _COLUMNS}
    record.update({name: "" for name in _TEXT})
    record.update({name: False for name in _BOOL})
    record["transformer_energised"] = pd.NA
    record.update(
        {
            "output_reference_plane": OUTPUT_REFERENCE_PLANE,
            "load_dependent_active_loss_ownership": LOAD_DEPENDENT_ACTIVE_LOSS_OWNERSHIP,
            "no_load_active_loss_ownership": NO_LOAD_ACTIVE_LOSS_OWNERSHIP,
            "s12d_operating_loss_treatment": S12D_OPERATING_LOSS_TREATMENT,
            "transformer_operating_solution_contract": TRANSFORMER_OPERATING_SOLUTION_CONTRACT_ID,
            "transformer_operating_solution_model": TRANSFORMER_OPERATING_SOLUTION_MODEL_ID,
            "transformer_operating_solution_scope": TRANSFORMER_OPERATING_SOLUTION_SCOPE,
            "transformer_operating_solution_coverage_scope": (
                TRANSFORMER_OPERATING_SOLUTION_COVERAGE_SCOPE
            ),
        }
    )
    return record


def _record(
    timestamp: pd.Timestamp, transformer_id: str, parents: tuple[Any, ...]
) -> dict[str, object]:
    s11, static, loss, energisation, network, series = parents
    record = _blank()
    static_row = static.transformer_states.loc[transformer_id]
    network_row = network.transformer_states.loc[transformer_id]
    series_row = series.transformer_states.loc[transformer_id]
    boundary = static.topology_by_id.get(transformer_id)
    state = energisation.energisation_states_by_key.get((timestamp, transformer_id))
    no_load = loss.no_load_loss_by_id.get(transformer_id)
    exit_id = boundary.s11_collection_exit_node_id if boundary else ""
    s11_key = (timestamp, exit_id)
    present = bool(exit_id) and s11_key in s11.collection_exit_states.index
    s11_row = s11.collection_exit_states.loc[s11_key] if present else None
    s11_resolved = (
        bool(s11_row["lv_ac_operating_solution_resolved"]) if s11_row is not None else False
    )
    p = float(s11_row["p_delivered_at_collection_exit_w"]) if s11_row is not None else math.nan
    q = float(s11_row["q_delivered_at_collection_exit_var"]) if s11_row is not None else math.nan
    s_magnitude = math.hypot(p, q) if s11_resolved else math.nan
    voltage = float(s11_row["exit_voltage_line_to_line_rms_v"]) if s11_row is not None else math.nan
    record.update(
        {
            "transformer_static_authority_resolved": bool(
                static_row["transformer_static_authority_resolved"]
            ),
            "transformer_energisation_authority_resolved": state is not None,
            "transformer_energised": state.energised if state is not None else pd.NA,
            "s11_operating_state_present": present,
            "s11_operating_solution_resolved": s11_resolved,
            "transformer_positive_sequence_network_authority_resolved": bool(
                network_row["transformer_positive_sequence_network_authority_resolved"]
            ),
            "transformer_series_equivalent_resolved": bool(
                series_row["transformer_series_equivalent_resolved"]
            ),
            "s11_collection_exit_node_id": exit_id,
            "transformer_collection_terminal_id": boundary.transformer_collection_terminal_id
            if boundary
            else "",
            "transformer_network_terminal_id": boundary.transformer_network_terminal_id
            if boundary
            else "",
            "collection_voltage_line_to_line_rms_v": voltage,
            "collection_p_w": p,
            "collection_q_var": q,
            "collection_s_magnitude_va": s_magnitude,
        }
    )
    transfer = network.voltage_transfer_by_id.get(transformer_id)
    if transfer is not None:
        record.update(
            {
                "network_to_collection_voltage_ratio": (
                    transfer.network_to_collection_voltage_ratio
                ),
                "network_side_phase_displacement_deg": (
                    transfer.network_side_phase_displacement_deg
                ),
            }
        )
    if bool(series_row["transformer_series_equivalent_resolved"]):
        record.update(
            {
                "series_equivalent_reference_side": series_row[
                    "series_equivalent_reference_side"
                ],
                "effective_series_resistance_ohm_per_phase": series_row[
                    "effective_series_resistance_ohm_per_phase"
                ],
                "effective_series_reactance_ohm_per_phase": series_row[
                    "effective_series_reactance_ohm_per_phase"
                ],
            }
        )
    if state is None:
        primary = _STATES[0]
    elif not state.energised:
        if s11_resolved and s_magnitude > _POWER_ZERO_ABS_TOL_VA:
            primary = _STATES[1]
        else:
            primary = _STATES[2]
            record.update(
                {
                    "transformer_terminal_operating_solution_resolved": True,
                    "collection_series_current_real_a": 0.0,
                    "collection_series_current_imag_a": 0.0,
                    "collection_series_current_magnitude_a": 0.0,
                    "network_series_current_real_a": 0.0,
                    "network_series_current_imag_a": 0.0,
                    "network_series_current_magnitude_a": 0.0,
                    "p_network_terminal_w": 0.0,
                    "q_network_terminal_var": 0.0,
                    "s_network_terminal_magnitude_va": 0.0,
                    "p_no_load_active_sink_w": 0.0,
                    "p_series_active_loss_w": 0.0,
                    "q_series_consumption_var": 0.0,
                    "p_total_transformer_active_loss_w": 0.0,
                    "active_power_conservation_residual_w": 0.0,
                    "reactive_power_conservation_residual_var": 0.0,
                }
            )
    elif not bool(static_row["transformer_static_authority_resolved"]):
        primary = _STATES[3]
    elif no_load is None:
        primary = _STATES[4]
    elif not bool(network_row["transformer_positive_sequence_network_authority_resolved"]):
        primary = _STATES[5]
    elif not bool(series_row["transformer_series_equivalent_resolved"]):
        primary = _STATES[6]
    elif not present:
        primary = _STATES[7]
    elif not s11_resolved:
        primary = _STATES[8]
    elif voltage == 0.0:
        primary = _STATES[9]
    else:
        assert transfer is not None
        try:
            vc = complex(voltage / math.sqrt(3.0), 0.0)
            sc_series = complex(p - no_load.no_load_loss_w, q)
            ic = (sc_series / (3.0 * vc)).conjugate()
            k = transfer.network_to_collection_voltage_ratio * cmath.exp(
                1j * math.radians(transfer.network_side_phase_displacement_deg)
            )
            current_n = ic / k.conjugate()
            resistance = float(series_row["effective_series_resistance_ohm_per_phase"])
            reactance = float(series_row["effective_series_reactance_ohm_per_phase"])
            impedance = complex(resistance, reactance)
            side = str(series_row["series_equivalent_reference_side"])
            if side == "collection_side":
                vn = k * (vc - impedance * ic)
                current_ref = ic
            else:
                vn = k * vc - impedance * current_n
                current_ref = current_n
            sn = 3.0 * vn * current_n.conjugate()
            current_magnitude = abs(current_ref)
            current_squared = current_magnitude * current_magnitude
            if not math.isfinite(current_squared):
                raise OverflowError
            series_loss = 3.0 * impedance * current_squared
            derived = {
                "collection_phase_voltage_real_v": vc.real,
                "collection_phase_voltage_imag_v": vc.imag,
                "collection_phase_voltage_magnitude_v": abs(vc),
                "collection_series_current_real_a": ic.real,
                "collection_series_current_imag_a": ic.imag,
                "collection_series_current_magnitude_a": abs(ic),
                "collection_series_current_angle_deg": math.degrees(cmath.phase(ic)),
                "network_series_current_real_a": current_n.real,
                "network_series_current_imag_a": current_n.imag,
                "network_series_current_magnitude_a": abs(current_n),
                "network_series_current_angle_deg": math.degrees(cmath.phase(current_n)),
                "network_terminal_phase_voltage_real_v": vn.real,
                "network_terminal_phase_voltage_imag_v": vn.imag,
                "network_terminal_phase_voltage_magnitude_v": abs(vn),
                "network_terminal_voltage_line_to_line_rms_v": abs(vn) * math.sqrt(3.0),
                "network_terminal_phase_angle_deg": math.degrees(cmath.phase(vn)),
                "p_entering_series_transfer_w": sc_series.real,
                "q_entering_series_transfer_var": sc_series.imag,
                "p_network_terminal_w": sn.real,
                "q_network_terminal_var": sn.imag,
                "s_network_terminal_magnitude_va": abs(sn),
                "p_no_load_active_sink_w": no_load.no_load_loss_w,
                "p_series_active_loss_w": series_loss.real,
                "q_series_consumption_var": series_loss.imag,
                "p_total_transformer_active_loss_w": no_load.no_load_loss_w + series_loss.real,
                "active_power_conservation_residual_w": (
                    p - sn.real - no_load.no_load_loss_w - series_loss.real
                ),
                "reactive_power_conservation_residual_var": q - sn.imag - series_loss.imag,
            }
            derived_finite = all(math.isfinite(value) for value in derived.values())
        except (OverflowError, ZeroDivisionError):
            derived_finite = False
        if not derived_finite:
            primary = _STATES[10]
        else:
            record.update(derived)
            record["transformer_terminal_operating_solution_resolved"] = True
            primary = _STATES[11]
    record["transformer_operating_solution_state"] = primary
    return record


def _state_frame(
    keys: list[tuple[pd.Timestamp, str]], records: list[dict[str, object]]
) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(keys, names=("timestamp", "transformer_id"))
    frame = pd.DataFrame(records, index=index, columns=_COLUMNS)
    for name in _BOOL:
        frame[name] = frame[name].astype(bool)
    frame["transformer_energised"] = frame["transformer_energised"].astype("boolean")
    for name in set(_COLUMNS) - _BOOL - _TEXT - {"transformer_energised"}:
        frame[name] = frame[name].astype("float64")
    for name in _TEXT:
        frame[name] = frame[name].astype(object)
    return frame


def _diagnostics(
    frame: pd.DataFrame, transformer_count: int, timestamp_count: int
) -> TopologyTransformerOperatingSolutionDiagnostics:
    counts = tuple(
        (state, int((frame["transformer_operating_solution_state"] == state).sum()))
        for state in _STATES
    )
    energised = dict(counts)[_STATES[11]]
    deenergised = dict(counts)[_STATES[2]]
    return TopologyTransformerOperatingSolutionDiagnostics(
        transformer_count,
        timestamp_count,
        len(frame),
        energised,
        deenergised,
        len(frame) - energised - deenergised,
        counts,
        TRANSFORMER_OPERATING_SOLUTION_MODEL_ID,
    )


def calculate_topology_transformer_operating_solution(
    topology: ElectricalTopologyConfig,
    topology_string_iv: electrical.TopologyStringIVResult,
    branch_authority: dc_collection.DcBranchPathAuthorityResult,
    mppt_input_string_iv: dc_collection.TopologyMpptInputStringIVResult,
    mppt_input_operating_points: dc_collection.TopologyMpptInputOperatingPointResult,
    cec_sam_name_by_inverter_id: Mapping[str, str],
    inverter_authority: inverter_authority_module.TopologyInverterAuthorityResult,
    mppt_current_limit_by_key: Mapping[
        tuple[str, str], inverter_topology_module.MpptDcCurrentLimitAuthority
    ],
    inverter_dc_envelope: inverter_topology_module.TopologyInverterDcEnvelopeResult,
    inverter_ac: conversion_module.TopologySandiaInverterAcResult,
    pre_limit_ac: potential_module.TopologySandiaPreLimitAcResult,
    inverter_power_accounting: accounting_module.TopologySandiaInverterPowerAccountingResult,
    ac_capability_by_inverter_id: Mapping[
        str, ac_authority_module.InverterAcCapabilityAuthority
    ],
    ac_capability_authority: ac_authority_module.TopologyInverterAcCapabilityAuthorityResult,
    reactive_power_request_by_key: Mapping[
        tuple[pd.Timestamp, str], pqs_module.InverterReactivePowerRequest
    ],
    pqs_capability: pqs_module.TopologyInverterPqsCapabilityResult,
    thermal_derating_by_inverter_id: Mapping[
        str, thermal_module.InverterThermalDeratingAuthority
    ],
    thermal_derating_authority: thermal_module.TopologyInverterThermalDeratingAuthorityResult,
    inverter_temperature_by_key: Mapping[
        tuple[pd.Timestamp, str], temperature_module.InverterTemperatureState
    ],
    temperature_capability: temperature_module.TopologyInverterTemperatureCapabilityResult,
    active_power_dispatch_request_by_key: Mapping[
        tuple[pd.Timestamp, str], request_module.InverterActivePowerDispatchRequest
    ],
    dispatch_request_authority: (
        request_module.TopologyInverterActivePowerDispatchRequestAuthorityResult
    ),
    dispatch_feasibility: feasibility_module.TopologyInverterDispatchFeasibilityResult,
    dispatch_selection: selection_module.TopologyInverterDispatchSelectionResult,
    network_basis: s11a_module.LvAcCollectionNetworkBasisAuthority | None,
    node_authority_by_id: Mapping[str, s11a_module.LvAcCollectionNodeAuthority],
    segment_authority_by_id: Mapping[str, s11a_module.LvAcCollectionSegmentAuthority],
    inverter_terminal_binding_by_inverter_id: Mapping[
        str, s11a_module.LvAcInverterTerminalBindingAuthority
    ],
    lv_ac_collection_authority: s11a_module.TopologyLvAcCollectionAuthorityResult,
    collection_exit_voltage_by_key: Mapping[
        tuple[pd.Timestamp, str], s11b_module.LvAcCollectionExitVoltageState
    ],
    collection_exit_voltage_authority: s11b_module.TopologyLvAcCollectionExitVoltageAuthorityResult,
    lv_ac_collection_operating_solution: s11c_module.TopologyLvAcCollectionOperatingSolutionResult,
    transformer_equipment_by_id: Mapping[
        str, s12a_module.TransformerStaticEquipmentAuthority
    ],
    transformer_topology_by_id: Mapping[
        str, s12a_module.TransformerBoundaryTopologyAuthority
    ],
    transformer_static_authority: s12a_module.TopologyTransformerStaticAuthorityResult,
    transformer_no_load_loss_by_id: Mapping[
        str, s12b_module.TransformerNoLoadLossAuthority
    ],
    transformer_rated_load_loss_by_id: Mapping[
        str, s12b_module.TransformerRatedLoadLossAuthority
    ],
    transformer_loss_authority: s12b_module.TopologyTransformerLossAuthorityResult,
    transformer_energisation_by_key: Mapping[
        tuple[pd.Timestamp, str], s12c_module.TransformerEnergisationState
    ],
    transformer_energisation_authority: s12c_module.TopologyTransformerEnergisationAuthorityResult,
    transformer_voltage_transfer_by_id: Mapping[
        str, s12e_module.TransformerVoltageTransferAuthority
    ],
    transformer_short_circuit_impedance_by_id: Mapping[
        str, s12e_module.TransformerShortCircuitImpedanceAuthority
    ],
    transformer_network_authority: s12e_module.TopologyTransformerNetworkAuthorityResult,
    transformer_rated_load_loss_reference_condition_by_id: Mapping[
        str, s12f_module.TransformerRatedLoadLossReferenceConditionAuthority
    ],
    transformer_series_equivalent: s12f_module.TopologyTransformerSeriesEquivalentResult,
) -> TopologyTransformerOperatingSolutionResult:
    """Replay canonical parents and solve exact network-side transformer terminal states."""
    inputs: dict[str, Any] = locals()
    parents = _canonical_parents(inputs)
    s11, static, _loss, energisation, _network, _series = parents
    ids = static.transformer_states.index.tolist()
    timestamps = _timestamps(s11, energisation)
    keys = [(timestamp, transformer_id) for timestamp in timestamps for transformer_id in ids]
    frame = _state_frame(
        keys, [_record(timestamp, transformer_id, parents) for timestamp, transformer_id in keys]
    )
    result = TopologyTransformerOperatingSolutionResult(
        frame.copy(deep=True), _diagnostics(frame, len(ids), len(timestamps))
    )
    _validate_result(parents, result)
    return result


def _validator_record(
    timestamp: pd.Timestamp, transformer_id: str, parents: tuple[Any, ...]
) -> dict[str, object]:
    """Independently reconstruct one expected row without using ``_record``."""
    s11, static, loss, energisation, network, series = parents
    expected = _blank()
    static_row = static.transformer_states.loc[transformer_id]
    network_row = network.transformer_states.loc[transformer_id]
    series_row = series.transformer_states.loc[transformer_id]
    boundary = static.topology_by_id.get(transformer_id)
    state = energisation.energisation_states_by_key.get((timestamp, transformer_id))
    no_load = loss.no_load_loss_by_id.get(transformer_id)
    transfer = network.voltage_transfer_by_id.get(transformer_id)
    exit_id = boundary.s11_collection_exit_node_id if boundary is not None else ""
    key = (timestamp, exit_id)
    present = bool(exit_id) and key in s11.collection_exit_states.index
    s11_row = s11.collection_exit_states.loc[key] if present else None
    s11_resolved = (
        bool(s11_row["lv_ac_operating_solution_resolved"]) if s11_row is not None else False
    )
    voltage = (
        float(s11_row["exit_voltage_line_to_line_rms_v"])
        if s11_row is not None
        else math.nan
    )
    p_value = (
        float(s11_row["p_delivered_at_collection_exit_w"])
        if s11_row is not None
        else math.nan
    )
    q_value = (
        float(s11_row["q_delivered_at_collection_exit_var"])
        if s11_row is not None
        else math.nan
    )
    s_magnitude = math.hypot(p_value, q_value) if s11_resolved else math.nan
    expected.update(
        {
            "transformer_static_authority_resolved": bool(
                static_row["transformer_static_authority_resolved"]
            ),
            "transformer_energisation_authority_resolved": state is not None,
            "transformer_energised": state.energised if state is not None else pd.NA,
            "s11_operating_state_present": present,
            "s11_operating_solution_resolved": s11_resolved,
            "transformer_positive_sequence_network_authority_resolved": bool(
                network_row["transformer_positive_sequence_network_authority_resolved"]
            ),
            "transformer_series_equivalent_resolved": bool(
                series_row["transformer_series_equivalent_resolved"]
            ),
            "s11_collection_exit_node_id": exit_id,
            "transformer_collection_terminal_id": (
                boundary.transformer_collection_terminal_id if boundary is not None else ""
            ),
            "transformer_network_terminal_id": (
                boundary.transformer_network_terminal_id if boundary is not None else ""
            ),
            "collection_voltage_line_to_line_rms_v": voltage,
            "collection_p_w": p_value,
            "collection_q_var": q_value,
            "collection_s_magnitude_va": s_magnitude,
        }
    )
    if transfer is not None:
        expected["network_to_collection_voltage_ratio"] = (
            transfer.network_to_collection_voltage_ratio
        )
        expected["network_side_phase_displacement_deg"] = (
            transfer.network_side_phase_displacement_deg
        )
    series_resolved = bool(series_row["transformer_series_equivalent_resolved"])
    if series_resolved:
        expected["series_equivalent_reference_side"] = series_row[
            "series_equivalent_reference_side"
        ]
        expected["effective_series_resistance_ohm_per_phase"] = series_row[
            "effective_series_resistance_ohm_per_phase"
        ]
        expected["effective_series_reactance_ohm_per_phase"] = series_row[
            "effective_series_reactance_ohm_per_phase"
        ]

    if state is None:
        primary = _STATES[0]
    elif not state.energised:
        if s11_resolved and s_magnitude > _POWER_ZERO_ABS_TOL_VA:
            primary = _STATES[1]
        else:
            primary = _STATES[2]
            expected.update(
                {
                    "transformer_terminal_operating_solution_resolved": True,
                    "collection_series_current_real_a": 0.0,
                    "collection_series_current_imag_a": 0.0,
                    "collection_series_current_magnitude_a": 0.0,
                    "network_series_current_real_a": 0.0,
                    "network_series_current_imag_a": 0.0,
                    "network_series_current_magnitude_a": 0.0,
                    "p_network_terminal_w": 0.0,
                    "q_network_terminal_var": 0.0,
                    "s_network_terminal_magnitude_va": 0.0,
                    "p_no_load_active_sink_w": 0.0,
                    "p_series_active_loss_w": 0.0,
                    "q_series_consumption_var": 0.0,
                    "p_total_transformer_active_loss_w": 0.0,
                    "active_power_conservation_residual_w": 0.0,
                    "reactive_power_conservation_residual_var": 0.0,
                }
            )
    elif not bool(static_row["transformer_static_authority_resolved"]):
        primary = _STATES[3]
    elif no_load is None:
        primary = _STATES[4]
    elif not bool(network_row["transformer_positive_sequence_network_authority_resolved"]):
        primary = _STATES[5]
    elif not series_resolved:
        primary = _STATES[6]
    elif not present:
        primary = _STATES[7]
    elif not s11_resolved:
        primary = _STATES[8]
    elif voltage == 0.0:
        primary = _STATES[9]
    else:
        assert transfer is not None and no_load is not None
        try:
            collection_voltage = complex(voltage / math.sqrt(3.0), 0.0)
            series_power = complex(p_value - no_load.no_load_loss_w, q_value)
            collection_current = (series_power / (3.0 * collection_voltage)).conjugate()
            transfer_factor = transfer.network_to_collection_voltage_ratio * cmath.exp(
                1j * math.radians(transfer.network_side_phase_displacement_deg)
            )
            network_current = collection_current / transfer_factor.conjugate()
            impedance = complex(
                float(series_row["effective_series_resistance_ohm_per_phase"]),
                float(series_row["effective_series_reactance_ohm_per_phase"]),
            )
            reference_current = (
                collection_current
                if str(series_row["series_equivalent_reference_side"]) == "collection_side"
                else network_current
            )
            network_voltage = (
                transfer_factor * (collection_voltage - impedance * collection_current)
                if reference_current is collection_current
                else transfer_factor * collection_voltage - impedance * network_current
            )
            network_power = 3.0 * network_voltage * network_current.conjugate()
            current_magnitude = abs(reference_current)
            current_squared = current_magnitude * current_magnitude
            if not math.isfinite(current_squared):
                raise OverflowError
            series_loss = 3.0 * impedance * current_squared
            derived = {
                "collection_phase_voltage_real_v": collection_voltage.real,
                "collection_phase_voltage_imag_v": collection_voltage.imag,
                "collection_phase_voltage_magnitude_v": abs(collection_voltage),
                "collection_series_current_real_a": collection_current.real,
                "collection_series_current_imag_a": collection_current.imag,
                "collection_series_current_magnitude_a": abs(collection_current),
                "collection_series_current_angle_deg": math.degrees(
                    cmath.phase(collection_current)
                ),
                "network_series_current_real_a": network_current.real,
                "network_series_current_imag_a": network_current.imag,
                "network_series_current_magnitude_a": abs(network_current),
                "network_series_current_angle_deg": math.degrees(cmath.phase(network_current)),
                "network_terminal_phase_voltage_real_v": network_voltage.real,
                "network_terminal_phase_voltage_imag_v": network_voltage.imag,
                "network_terminal_phase_voltage_magnitude_v": abs(network_voltage),
                "network_terminal_voltage_line_to_line_rms_v": (
                    abs(network_voltage) * math.sqrt(3.0)
                ),
                "network_terminal_phase_angle_deg": math.degrees(cmath.phase(network_voltage)),
                "p_entering_series_transfer_w": series_power.real,
                "q_entering_series_transfer_var": series_power.imag,
                "p_network_terminal_w": network_power.real,
                "q_network_terminal_var": network_power.imag,
                "s_network_terminal_magnitude_va": abs(network_power),
                "p_no_load_active_sink_w": no_load.no_load_loss_w,
                "p_series_active_loss_w": series_loss.real,
                "q_series_consumption_var": series_loss.imag,
                "p_total_transformer_active_loss_w": (
                    no_load.no_load_loss_w + series_loss.real
                ),
                "active_power_conservation_residual_w": (
                    p_value
                    - network_power.real
                    - no_load.no_load_loss_w
                    - series_loss.real
                ),
                "reactive_power_conservation_residual_var": (
                    q_value - network_power.imag - series_loss.imag
                ),
            }
            finite = all(math.isfinite(value) for value in derived.values())
        except (OverflowError, ZeroDivisionError):
            finite = False
        if not finite:
            primary = _STATES[10]
        else:
            expected.update(derived)
            expected["transformer_terminal_operating_solution_resolved"] = True
            primary = _STATES[11]
    expected["transformer_operating_solution_state"] = primary
    return expected


def _validate_result(
    parents: tuple[Any, ...], result: TopologyTransformerOperatingSolutionResult
) -> None:
    if type(result) is not TopologyTransformerOperatingSolutionResult:
        raise RuntimeError("transformer operating solution result type is invalid")
    s11, static, loss, energisation, network, series = parents
    ids = static.transformer_states.index.tolist()
    timestamps = _timestamps(s11, energisation)
    keys = [(timestamp, transformer_id) for timestamp in timestamps for transformer_id in ids]
    states = result.transformer_operating_states
    if (
        tuple(states.columns) != _COLUMNS
        or states.index.names != ["timestamp", "transformer_id"]
        or states.index.tolist() != keys
        or states.index.has_duplicates
    ):
        raise RuntimeError("transformer operating solution schema/index/order is invalid")
    expected_records = [
        _validator_record(timestamp, transformer_id, parents)
        for timestamp, transformer_id in keys
    ]
    expected_states = _state_frame(keys, expected_records)
    try:
        pd.testing.assert_frame_equal(states, expected_states, check_exact=True)
    except AssertionError as error:
        raise RuntimeError("transformer operating solution states failed exact closure") from error
    expected_diagnostics = _diagnostics(expected_states, len(ids), len(timestamps))
    if result.diagnostics != expected_diagnostics:
        raise RuntimeError("transformer operating solution diagnostics failed exact closure")
    if sum(count for _, count in result.diagnostics.state_counts) != result.diagnostics.row_count:
        raise RuntimeError("transformer operating solution primary states do not partition rows")
    # Exact expected-frame equality above validates every result field. These
    # independent identities additionally protect the accepted transformer
    # equations from synchronized implementation mistakes.
    for key in keys:
        row = expected_states.loc[key]
        if str(row["transformer_operating_solution_state"]) != _STATES[11]:
            continue
        ratio = float(row["network_to_collection_voltage_ratio"])
        if not math.isclose(
            float(row["network_series_current_magnitude_a"]),
            float(row["collection_series_current_magnitude_a"]) / ratio,
            rel_tol=_REL_TOL,
            abs_tol=0.0,
        ):
            raise RuntimeError("ideal transformer current-ratio identity failed closure")
