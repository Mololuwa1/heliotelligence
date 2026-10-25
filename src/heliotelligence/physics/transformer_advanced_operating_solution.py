"""Coupled transformer terminal and explicit load-loss-fidelity solution.

S12M replaces (never adds to) S12G's baseline load and no-load losses.  S12K
supplies corrected load-loss physics; S12L supplies selected no-load physics.
S12K may instead select S12G's positive-sequence series-loss baseline without
inventing harmonic or temperature correction; that lower fidelity remains explicit.
Fundamental eddy/stray loss is represented in an effective positive-sequence
R, while harmonic increment remains a separate active sink.  Leakage X is
retained.  Temperature is fixed timestamp evidence: no thermal iteration,
harmonic-voltage solve, excitation Q, saturation, or S13 network physics.
"""

from __future__ import annotations

import cmath
import inspect
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, TypeVar

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.physics.transformer_core_no_load_loss import (
    TRANSFORMER_CORE_NO_LOAD_LOSS_CONTRACT_ID,
    TRANSFORMER_CORE_NO_LOAD_LOSS_MODEL_ID,
    calculate_topology_transformer_core_no_load_loss,
)
from heliotelligence.physics.transformer_corrected_load_loss import (
    TRANSFORMER_CORRECTED_LOAD_LOSS_CONTRACT_ID,
    TRANSFORMER_CORRECTED_LOAD_LOSS_MODEL_ID,
    calculate_topology_transformer_corrected_load_loss,
)
from heliotelligence.physics.transformer_operating_solution import (
    TRANSFORMER_OPERATING_SOLUTION_CONTRACT_ID,
    TRANSFORMER_OPERATING_SOLUTION_MODEL_ID,
    calculate_topology_transformer_operating_solution,
)

TRANSFORMER_ADVANCED_OPERATING_SOLUTION_CONTRACT_ID = (
    "admitted_s12g_terminal_s12k_corrected_load_and_s12l_corrected_no_load_"
    "to_coupled_advanced_transformer_terminal_solution_v1"
)
TRANSFORMER_ADVANCED_OPERATING_SOLUTION_MODEL_ID = (
    "balanced_three_phase_positive_sequence_advanced_loss_coupled_"
    "transformer_terminal_fixed_point_v1"
)
TRANSFORMER_ADVANCED_OPERATING_SOLUTION_SCOPE = (
    "timestamped_advanced_transformer_terminal_reconciliation_before_mv_hv_collection_network"
)
TRANSFORMER_ADVANCED_OPERATING_SOLUTION_COVERAGE_SCOPE = (
    "resolved_energised_transformers_with_s12k_selected_advanced_or_s12g_baseline_"
    "load_loss_and_s12l_selected_no_load_loss"
)
ADVANCED_FUNDAMENTAL_SERIES_RESISTANCE_SEMANTICS = (
    "effective_positive_sequence_series_resistance_reproducing_"
    "s12k_temperature_corrected_sinusoidal_load_loss"
)
ADVANCED_SERIES_REACTANCE_TREATMENT = "s12f_factory_reference_effective_series_reactance_retained"
HARMONIC_INCREMENT_TREATMENT = (
    "separate_active_power_sink_scaled_by_fundamental_reference_side_"
    "current_squared_not_applied_to_positive_sequence_voltage_drop"
)
ADVANCED_LOAD_LOSS_OWNERSHIP = "s12k_replaces_s12g_reference_load_loss_not_additive"
ADVANCED_NO_LOAD_LOSS_OWNERSHIP = "s12l_replaces_s12g_factory_no_load_sink_not_additive"
S12D_TREATMENT = "independent_reference_condition_baseline_not_consumed"
MAXIMUM_ITERATIONS = 100
DAMPING_FACTOR = 0.5
FIXED_POINT_RELATIVE_TOLERANCE = 1e-10
FIXED_POINT_ABSOLUTE_TOLERANCE_W = 1e-6
_CLOSURE_REL_TOL = 1e-9
_CLOSURE_ABS_TOL_W = 1e-8
_CONSERVATION_ABS_TOL = 1e-6
_STATES = (
    "unresolved_missing_s12g_transformer_operating_state",
    "unresolved_upstream_s12g_transformer_operating_solution",
    "resolved_deenergised_transformer_zero_advanced_transfer",
    "unresolved_missing_s12k_corrected_load_loss_state",
    "unresolved_upstream_s12k_corrected_load_loss",
    "unresolved_missing_s12l_core_no_load_loss_state",
    "unresolved_upstream_s12l_no_load_loss_output",
    "unresolved_s12k_fundamental_load_loss_coefficient_closure_mismatch",
    "unresolved_s12k_harmonic_increment_coefficient_closure_mismatch",
    "unresolved_negative_harmonic_increment_accounting_coefficient",
    "unresolved_coupled_core_loss_outside_s12l_scaling_domain",
    "unresolved_nonfinite_advanced_transformer_operating_state",
    "unresolved_advanced_transformer_fixed_point_nonconvergence",
    "unresolved_advanced_transformer_power_conservation_mismatch",
    "resolved_coupled_advanced_transformer_terminal_solution",
    "resolved_coupled_transformer_terminal_solution_with_s12g_load_loss_fallback",
)


@dataclass(frozen=True)
class TopologyTransformerAdvancedOperatingSolutionDiagnostics:
    transformer_count: int
    timestamp_count: int
    row_count: int
    resolved_count: int
    deenergised_count: int
    nonconverged_count: int
    terminal_output_resolved_count: int
    advanced_load_loss_terminal_count: int
    s12g_load_loss_fallback_terminal_count: int
    state_counts: tuple[tuple[str, int], ...]
    model: str


@dataclass(frozen=True)
class TopologyTransformerAdvancedOperatingSolutionResult:
    states: pd.DataFrame
    diagnostics: TopologyTransformerAdvancedOperatingSolutionDiagnostics


_BOOL = {
    "s12g_operating_row_present",
    "s12g_terminal_operating_solution_resolved",
    "s12k_corrected_load_loss_row_present",
    "s12k_corrected_load_loss_resolved",
    "s12l_core_no_load_loss_row_present",
    "s12l_no_load_loss_output_resolved",
    "s12l_advanced_core_loss_scaling_resolved",
    "harmonic_increment_roundoff_adjusted",
    "fixed_point_converged",
    "s12l_core_loss_re_evaluated_in_coupled_iteration",
    "harmonic_voltage_drop_modeled",
    "excitation_no_load_q_modeled",
    "coupled_thermal_iteration_applied",
    "upstream_collection_recalculated",
    "s12k_load_loss_output_resolved",
    "s12k_advanced_load_loss_correction_resolved",
    "s12k_load_loss_fallback_applied",
    "transformer_terminal_output_resolved",
    "load_loss_fallback_applied",
}
_NULLABLE = {"transformer_energised"}
_FLOAT = {
    "collection_voltage_line_to_line_rms_v",
    "collection_p_w",
    "collection_q_var",
    "network_to_collection_voltage_ratio",
    "network_side_phase_displacement_deg",
    "s12g_reference_effective_series_resistance_ohm_per_phase",
    "advanced_fundamental_effective_series_resistance_ohm_per_phase",
    "advanced_fundamental_series_resistance_delta_ohm_per_phase",
    "retained_series_reactance_ohm_per_phase",
    "harmonic_increment_accounting_resistance_ohm_per_phase",
    "collection_series_current_real_a",
    "collection_series_current_imag_a",
    "collection_series_current_magnitude_a",
    "collection_series_current_angle_deg",
    "network_series_current_real_a",
    "network_series_current_imag_a",
    "network_series_current_magnitude_a",
    "network_series_current_angle_deg",
    "internal_collection_excitation_voltage_line_to_line_rms_v",
    "internal_network_excitation_voltage_line_to_line_rms_v",
    "network_terminal_phase_voltage_real_v",
    "network_terminal_phase_voltage_imag_v",
    "network_terminal_phase_voltage_magnitude_v",
    "network_terminal_voltage_line_to_line_rms_v",
    "network_terminal_phase_angle_deg",
    "p_network_terminal_w",
    "q_network_terminal_var",
    "s_network_terminal_magnitude_va",
    "p_no_load_active_loss_w",
    "p_harmonic_incremental_load_loss_w",
    "p_fundamental_series_active_loss_w",
    "q_fundamental_series_consumption_var",
    "p_advanced_load_loss_w",
    "coupled_advanced_load_loss_w",
    "p_total_transformer_active_loss_w",
    "coupled_no_load_loss_w",
    "coupled_total_transformer_active_loss_w",
    "s12g_baseline_load_loss_w",
    "s12k_baseline_advanced_load_loss_w",
    "coupled_load_loss_adjustment_vs_s12k_w",
    "s12g_baseline_no_load_loss_w",
    "s12l_selected_no_load_loss_w",
    "coupled_no_load_adjustment_vs_s12l_w",
    "s12g_baseline_total_transformer_active_loss_w",
    "advanced_total_loss_correction_vs_s12g_w",
    "fixed_point_damping_factor",
    "fixed_point_relative_tolerance",
    "fixed_point_absolute_tolerance_w",
    "no_load_fixed_point_residual_w",
    "harmonic_fixed_point_residual_w",
    "coupled_core_voltage_ratio_to_factory_reference",
    "coupled_core_frequency_ratio_to_factory_reference",
    "coupled_core_flux_density_ratio_to_factory_reference",
    "coupled_core_loss_scaling_multiplier",
    "active_power_conservation_residual_w",
    "reactive_power_conservation_residual_var",
    "s12k_selected_load_loss_w",
    "p_selected_load_loss_w",
    "coupled_selected_load_loss_w",
    "coupled_load_loss_adjustment_vs_s12k_selected_w",
}
_INT = {"fixed_point_iterations", "fixed_point_maximum_iterations"}
_COLUMNS = (
    "s12g_operating_row_present",
    "s12g_terminal_operating_solution_resolved",
    "s12k_corrected_load_loss_row_present",
    "s12k_corrected_load_loss_resolved",
    "s12k_load_loss_output_resolved",
    "s12k_advanced_load_loss_correction_resolved",
    "s12k_load_loss_fallback_applied",
    "s12l_core_no_load_loss_row_present",
    "s12l_no_load_loss_output_resolved",
    "s12l_advanced_core_loss_scaling_resolved",
    "transformer_energised",
    "collection_voltage_line_to_line_rms_v",
    "collection_p_w",
    "collection_q_var",
    "network_to_collection_voltage_ratio",
    "network_side_phase_displacement_deg",
    "series_reference_side",
    "s12g_reference_effective_series_resistance_ohm_per_phase",
    "advanced_fundamental_effective_series_resistance_ohm_per_phase",
    "advanced_fundamental_series_resistance_delta_ohm_per_phase",
    "retained_series_reactance_ohm_per_phase",
    "harmonic_increment_accounting_resistance_ohm_per_phase",
    "harmonic_increment_roundoff_adjusted",
    "collection_series_current_real_a",
    "collection_series_current_imag_a",
    "collection_series_current_magnitude_a",
    "collection_series_current_angle_deg",
    "network_series_current_real_a",
    "network_series_current_imag_a",
    "network_series_current_magnitude_a",
    "network_series_current_angle_deg",
    "internal_collection_excitation_voltage_line_to_line_rms_v",
    "internal_network_excitation_voltage_line_to_line_rms_v",
    "network_terminal_phase_voltage_real_v",
    "network_terminal_phase_voltage_imag_v",
    "network_terminal_phase_voltage_magnitude_v",
    "network_terminal_voltage_line_to_line_rms_v",
    "network_terminal_phase_angle_deg",
    "p_network_terminal_w",
    "q_network_terminal_var",
    "s_network_terminal_magnitude_va",
    "p_no_load_active_loss_w",
    "p_harmonic_incremental_load_loss_w",
    "p_fundamental_series_active_loss_w",
    "q_fundamental_series_consumption_var",
    "p_advanced_load_loss_w",
    "coupled_advanced_load_loss_w",
    "p_total_transformer_active_loss_w",
    "coupled_no_load_loss_w",
    "coupled_total_transformer_active_loss_w",
    "s12g_baseline_load_loss_w",
    "s12k_baseline_advanced_load_loss_w",
    "s12k_selected_load_loss_w",
    "p_selected_load_loss_w",
    "coupled_selected_load_loss_w",
    "coupled_load_loss_adjustment_vs_s12k_selected_w",
    "coupled_load_loss_adjustment_vs_s12k_w",
    "s12g_baseline_no_load_loss_w",
    "s12l_selected_no_load_loss_w",
    "coupled_no_load_adjustment_vs_s12l_w",
    "s12g_baseline_total_transformer_active_loss_w",
    "advanced_total_loss_correction_vs_s12g_w",
    "fixed_point_iterations",
    "fixed_point_converged",
    "fixed_point_maximum_iterations",
    "fixed_point_damping_factor",
    "fixed_point_relative_tolerance",
    "fixed_point_absolute_tolerance_w",
    "no_load_fixed_point_residual_w",
    "harmonic_fixed_point_residual_w",
    "coupled_core_voltage_ratio_to_factory_reference",
    "coupled_core_frequency_ratio_to_factory_reference",
    "coupled_core_flux_density_ratio_to_factory_reference",
    "coupled_core_loss_scaling_multiplier",
    "active_power_conservation_residual_w",
    "reactive_power_conservation_residual_var",
    "s12l_core_loss_re_evaluated_in_coupled_iteration",
    "harmonic_voltage_drop_modeled",
    "excitation_no_load_q_modeled",
    "coupled_thermal_iteration_applied",
    "upstream_collection_recalculated",
    "transformer_terminal_output_resolved",
    "load_loss_fallback_applied",
    "s12k_load_loss_output_fidelity",
    "terminal_solution_fidelity",
    "advanced_fundamental_series_resistance_semantics",
    "advanced_series_reactance_treatment",
    "harmonic_increment_treatment",
    "advanced_load_loss_ownership",
    "advanced_no_load_loss_ownership",
    "s12d_operating_loss_treatment",
    "transformer_advanced_operating_solution_state",
    "transformer_operating_solution_contract",
    "transformer_operating_solution_model",
    "transformer_corrected_load_loss_contract",
    "transformer_corrected_load_loss_model",
    "transformer_core_no_load_loss_contract",
    "transformer_core_no_load_loss_model",
    "transformer_advanced_operating_solution_contract",
    "transformer_advanced_operating_solution_model",
    "transformer_advanced_operating_solution_scope",
    "transformer_advanced_operating_solution_coverage_scope",
)
F = TypeVar("F", bound=Callable[..., Any])


def _call(function: F, values: Mapping[str, Any]) -> Any:
    parameters = inspect.signature(function).parameters
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return function(**values)
    return function(**{name: values[name] for name in parameters})


def _exact_replay(label: str, supplied: object, canonical: object) -> None:
    if type(supplied) is not type(canonical):
        raise ValueError(f"supplied {label} result type is invalid")
    for name, expected in vars(canonical).items():
        actual = getattr(supplied, name)
        if isinstance(expected, pd.DataFrame):
            try:
                pd.testing.assert_frame_equal(actual, expected, check_exact=True)
            except AssertionError as error:
                raise ValueError(f"supplied {label} frame failed canonical replay") from error
        elif isinstance(expected, Mapping):
            if type(actual) is not MappingProxyType or tuple(actual.items()) != tuple(
                expected.items()
            ):
                raise ValueError(f"supplied {label} mapping failed immutable canonical replay")
        elif actual != expected:
            raise ValueError(f"supplied {label} diagnostics failed canonical replay")


def _parents(values: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    g = _call(calculate_topology_transformer_operating_solution, values)
    _exact_replay("S12G", values["transformer_operating_solution"], g)
    k = _call(calculate_topology_transformer_corrected_load_loss, values)
    _exact_replay("S12K", values["transformer_corrected_load_loss"], k)
    core = _call(calculate_topology_transformer_core_no_load_loss, values)
    _exact_replay("S12L", values["transformer_core_no_load_loss"], core)
    return g, k, core


def _base() -> dict[str, object]:
    r: dict[str, object] = {name: None for name in _COLUMNS}
    for name in _BOOL:
        r[name] = False
    for name in _FLOAT:
        r[name] = math.nan
    for name in _INT:
        r[name] = 0
    r["transformer_energised"] = pd.NA
    r.update(
        {
            "fixed_point_maximum_iterations": MAXIMUM_ITERATIONS,
            "fixed_point_damping_factor": DAMPING_FACTOR,
            "fixed_point_relative_tolerance": FIXED_POINT_RELATIVE_TOLERANCE,
            "fixed_point_absolute_tolerance_w": FIXED_POINT_ABSOLUTE_TOLERANCE_W,
            "advanced_fundamental_series_resistance_semantics": (
                ADVANCED_FUNDAMENTAL_SERIES_RESISTANCE_SEMANTICS
            ),
            "advanced_series_reactance_treatment": ADVANCED_SERIES_REACTANCE_TREATMENT,
            "harmonic_increment_treatment": HARMONIC_INCREMENT_TREATMENT,
            "advanced_load_loss_ownership": ADVANCED_LOAD_LOSS_OWNERSHIP,
            "advanced_no_load_loss_ownership": ADVANCED_NO_LOAD_LOSS_OWNERSHIP,
            "s12d_operating_loss_treatment": S12D_TREATMENT,
            "transformer_operating_solution_contract": TRANSFORMER_OPERATING_SOLUTION_CONTRACT_ID,
            "transformer_operating_solution_model": TRANSFORMER_OPERATING_SOLUTION_MODEL_ID,
            "transformer_corrected_load_loss_contract": TRANSFORMER_CORRECTED_LOAD_LOSS_CONTRACT_ID,
            "transformer_corrected_load_loss_model": TRANSFORMER_CORRECTED_LOAD_LOSS_MODEL_ID,
            "transformer_core_no_load_loss_contract": TRANSFORMER_CORE_NO_LOAD_LOSS_CONTRACT_ID,
            "transformer_core_no_load_loss_model": TRANSFORMER_CORE_NO_LOAD_LOSS_MODEL_ID,
            "transformer_advanced_operating_solution_contract": (
                TRANSFORMER_ADVANCED_OPERATING_SOLUTION_CONTRACT_ID
            ),
            "transformer_advanced_operating_solution_model": (
                TRANSFORMER_ADVANCED_OPERATING_SOLUTION_MODEL_ID
            ),
            "transformer_advanced_operating_solution_scope": (
                TRANSFORMER_ADVANCED_OPERATING_SOLUTION_SCOPE
            ),
            "transformer_advanced_operating_solution_coverage_scope": (
                TRANSFORMER_ADVANCED_OPERATING_SOLUTION_COVERAGE_SCOPE
            ),
        }
    )
    return r


def _propose(
    g: pd.Series, core: pd.Series, rf: float, rh: float, x: float, pnl: float, ph: float
) -> tuple[dict[str, Any], bool]:
    vc = complex(float(g["collection_voltage_line_to_line_rms_v"]) / math.sqrt(3.0), 0.0)
    s = complex(float(g["collection_p_w"]) - pnl - ph, float(g["collection_q_var"]))
    ic = (s / (3.0 * vc)).conjugate()
    k = float(g["network_to_collection_voltage_ratio"]) * cmath.exp(
        1j * math.radians(float(g["network_side_phase_displacement_deg"]))
    )
    current_n = ic / k.conjugate()
    z = complex(rf, x)
    side = str(g["series_equivalent_reference_side"])
    ec = vc - z * ic if side == "collection_side" else vc
    en = k * ec
    vn = en if side == "collection_side" else en - z * current_n
    iref = ic if side == "collection_side" else current_n
    ph_new = 3.0 * rh * abs(iref) ** 2
    core_ll = math.sqrt(3.0) * abs(
        ec if core["no_load_test_reference_side"] == "collection_side" else en
    )
    pnl_new = float(core["corrected_no_load_loss_w"])
    domain = True
    rv = rfq = rb = mult = math.nan
    if bool(core["advanced_core_loss_scaling_resolved"]):
        rv = core_ll / float(core["factory_reference_core_excitation_voltage_ll_rms_v"])
        rfq = float(core["operating_frequency_hz"]) / float(core["no_load_test_frequency_hz"])
        rb = rv / rfq
        domain = float(core["minimum_frequency_ratio_to_reference"]) <= rfq <= float(
            core["maximum_frequency_ratio_to_reference"]
        ) and float(core["minimum_flux_density_ratio_to_reference"]) <= rb <= float(
            core["maximum_flux_density_ratio_to_reference"]
        )
        if domain:
            mult = math.exp(
                float(core["steinmetz_frequency_exponent_alpha"]) * math.log(rfq)
                + float(core["steinmetz_flux_density_exponent_beta"]) * math.log(rb)
            )
            pnl_new = float(core["scalable_core_loss_reference_w"]) * mult + float(
                core["non_scaling_no_load_loss_reference_residual_w"]
            )
    sn = 3.0 * vn * current_n.conjugate()
    return {
        "ic": ic,
        "in": current_n,
        "ec": ec,
        "en": en,
        "vn": vn,
        "sn": sn,
        "iref": abs(iref),
        "ph": ph_new,
        "pnl": pnl_new,
        "rv": rv,
        "rfq": rfq,
        "rb": rb,
        "mult": mult,
    }, domain


def _record(
    timestamp: pd.Timestamp, identifier: str, parents: tuple[Any, Any, Any]
) -> dict[str, object]:
    g, k, core = parents
    r = _base()
    key = (timestamp, identifier)
    gr = (
        g.transformer_operating_states.loc[key]
        if key in g.transformer_operating_states.index
        else None
    )
    kr = k.states.loc[key] if key in k.states.index else None
    lr = core.states.loc[key] if key in core.states.index else None
    gres = bool(gr is not None and gr["transformer_terminal_operating_solution_resolved"])
    kres = bool(
        kr is not None
        and kr["transformer_corrected_load_loss_state"]
        == "resolved_harmonic_and_temperature_corrected_transformer_load_loss"
    )
    kout = bool(kr is not None and kr["transformer_load_loss_output_resolved"])
    kfallback = bool(kr is not None and kr["s12g_load_loss_fallback_applied"])
    lres = bool(lr is not None and lr["transformer_no_load_loss_output_resolved"])
    de = bool(
        gr is not None
        and gr["transformer_operating_solution_state"]
        == "resolved_deenergised_transformer_no_transfer"
    )
    r.update(
        {
            "s12g_operating_row_present": gr is not None,
            "s12g_terminal_operating_solution_resolved": gres,
            "s12k_corrected_load_loss_row_present": kr is not None,
            "s12k_corrected_load_loss_resolved": kres,
            "s12k_load_loss_output_resolved": kout,
            "s12k_advanced_load_loss_correction_resolved": kres,
            "s12k_load_loss_fallback_applied": kfallback,
            "s12k_load_loss_output_fidelity": (
                str(kr["load_loss_output_fidelity"]) if kr is not None else ""
            ),
            "s12l_core_no_load_loss_row_present": lr is not None,
            "s12l_no_load_loss_output_resolved": lres,
            "s12l_advanced_core_loss_scaling_resolved": bool(
                lr is not None and lr["advanced_core_loss_scaling_resolved"]
            ),
            "transformer_energised": pd.NA if gr is None else gr["transformer_energised"],
        }
    )
    if gr is not None:
        r.update(
            {
                "collection_voltage_line_to_line_rms_v": float(
                    gr["collection_voltage_line_to_line_rms_v"]
                ),
                "collection_p_w": float(gr["collection_p_w"]),
                "collection_q_var": float(gr["collection_q_var"]),
                "network_to_collection_voltage_ratio": float(
                    gr["network_to_collection_voltage_ratio"]
                ),
                "network_side_phase_displacement_deg": float(
                    gr["network_side_phase_displacement_deg"]
                ),
                "s12g_reference_effective_series_resistance_ohm_per_phase": float(
                    gr["effective_series_resistance_ohm_per_phase"]
                ),
                "retained_series_reactance_ohm_per_phase": float(
                    gr["effective_series_reactance_ohm_per_phase"]
                ),
                "series_reference_side": gr["series_equivalent_reference_side"],
                "s12g_baseline_load_loss_w": float(gr["p_series_active_loss_w"]),
                "s12g_baseline_no_load_loss_w": float(gr["p_no_load_active_sink_w"]),
                "s12g_baseline_total_transformer_active_loss_w": float(
                    gr["p_total_transformer_active_loss_w"]
                ),
            }
        )
    if kr is not None:
        r["s12k_baseline_advanced_load_loss_w"] = float(
            kr["harmonic_and_temperature_corrected_load_loss_w"]
        )
        r["s12k_selected_load_loss_w"] = float(kr["selected_total_load_loss_w"])
    if lr is not None:
        r["s12l_selected_no_load_loss_w"] = float(lr["corrected_no_load_loss_w"])
    if gr is None:
        state = _STATES[0]
    elif not gres and not de:
        state = _STATES[1]
    elif de:
        for name in (
            "collection_series_current_real_a",
            "collection_series_current_imag_a",
            "collection_series_current_magnitude_a",
            "collection_series_current_angle_deg",
            "network_series_current_real_a",
            "network_series_current_imag_a",
            "network_series_current_magnitude_a",
            "network_series_current_angle_deg",
            "p_network_terminal_w",
            "q_network_terminal_var",
            "s_network_terminal_magnitude_va",
            "p_no_load_active_loss_w",
            "p_harmonic_incremental_load_loss_w",
            "p_fundamental_series_active_loss_w",
            "q_fundamental_series_consumption_var",
            "p_advanced_load_loss_w",
            "coupled_advanced_load_loss_w",
            "p_total_transformer_active_loss_w",
            "coupled_no_load_loss_w",
            "coupled_total_transformer_active_loss_w",
            "coupled_load_loss_adjustment_vs_s12k_w",
            "coupled_no_load_adjustment_vs_s12l_w",
            "advanced_total_loss_correction_vs_s12g_w",
            "no_load_fixed_point_residual_w",
            "harmonic_fixed_point_residual_w",
            "active_power_conservation_residual_w",
            "reactive_power_conservation_residual_var",
            "p_selected_load_loss_w",
            "coupled_selected_load_loss_w",
            "coupled_load_loss_adjustment_vs_s12k_selected_w",
        ):
            r[name] = 0.0
        r["fixed_point_converged"] = True
        r["transformer_terminal_output_resolved"] = True
        r["terminal_solution_fidelity"] = "deenergised_zero"
        state = _STATES[2]
    elif kr is None:
        state = _STATES[3]
    elif not kout:
        state = _STATES[4]
    elif lr is None:
        state = _STATES[5]
    elif not lres:
        state = _STATES[6]
    else:
        try:
            x = float(gr["effective_series_reactance_ohm_per_phase"])
            if kfallback:
                rf = float(gr["effective_series_resistance_ohm_per_phase"])
                rh = 0.0
                side = str(gr["series_equivalent_reference_side"])
                i0 = float(
                    gr["collection_series_current_magnitude_a"]
                    if side == "collection_side"
                    else gr["network_series_current_magnitude_a"]
                )
                pf = float(kr["selected_fundamental_load_loss_w"])
                phb = float(kr["selected_harmonic_incremental_load_loss_w"])
                selected = float(kr["selected_total_load_loss_w"])
                fundamental_target = pf
                harmonic_target = phb
                adjusted = False
            else:
                ir = float(kr["rated_reference_side_current_a"])
                i0 = float(kr["fundamental_operating_current_a"])
                pr = float(kr["i2r_loss_reference_w"])
                pec = float(kr["winding_eddy_current_loss_reference_w"])
                posl = float(kr["other_stray_loss_reference_w"])
                kt = float(kr["i2r_temperature_correction_factor"])
                kec = float(kr["winding_eddy_temperature_correction_factor"])
                kosl = float(kr["other_stray_temperature_correction_factor"])
                s2 = float(kr["sum_current_ratio_squared"])
                fec = float(kr["winding_eddy_harmonic_loss_factor"])
                fosl = float(kr["other_stray_harmonic_loss_factor"])
                pf = math.fsum([pr * kt, pec * kec, posl * kosl])
                phb = math.fsum(
                    [
                        pr * kt * (s2 - 1.0),
                        pec * kec * (s2 * fec - 1.0),
                        posl * kosl * (s2 * fosl - 1.0),
                    ]
                )
                adjusted = phb < 0 and math.isclose(
                    phb, 0.0, rel_tol=0.0, abs_tol=1e-12 * max(1.0, pf)
                )
                phb = 0.0 if adjusted else phb
                rf = pf / (3 * ir * ir)
                rh = phb / (3 * ir * ir)
                selected = float(kr["harmonic_and_temperature_corrected_load_loss_w"])
                fundamental_target = float(kr["temperature_corrected_sinusoidal_load_loss_w"])
                harmonic_target = float(kr["harmonic_incremental_load_loss_w"])
            fclosure = 3 * rf * i0 * i0 - fundamental_target
            hclosure = 3 * rh * i0 * i0 - harmonic_target
            total_closure = 3 * (rf + rh) * i0 * i0 - selected
            r.update(
                {
                    "s12g_reference_effective_series_resistance_ohm_per_phase": float(
                        gr["effective_series_resistance_ohm_per_phase"]
                    ),
                    "advanced_fundamental_effective_series_resistance_ohm_per_phase": rf,
                    "advanced_fundamental_series_resistance_delta_ohm_per_phase": rf
                    - float(gr["effective_series_resistance_ohm_per_phase"]),
                    "retained_series_reactance_ohm_per_phase": x,
                    "harmonic_increment_accounting_resistance_ohm_per_phase": rh,
                    "harmonic_increment_roundoff_adjusted": adjusted,
                    "series_reference_side": gr["series_equivalent_reference_side"],
                }
            )
            if not math.isclose(fclosure, 0, rel_tol=_CLOSURE_REL_TOL, abs_tol=_CLOSURE_ABS_TOL_W):
                state = _STATES[7]
            elif not math.isclose(
                hclosure, 0, rel_tol=_CLOSURE_REL_TOL, abs_tol=_CLOSURE_ABS_TOL_W
            ) or not math.isclose(
                total_closure, 0, rel_tol=_CLOSURE_REL_TOL, abs_tol=_CLOSURE_ABS_TOL_W
            ):
                state = _STATES[8]
            elif phb < 0:
                state = _STATES[9]
            else:
                pnl = float(lr["corrected_no_load_loss_w"])
                ph = phb
                solved = None
                domain = True
                converged = False
                nonfinite = False
                final_no_load_residual = math.nan
                final_harmonic_residual = math.nan
                final_pnl = math.nan
                final_ph = math.nan
                iteration_count = 0
                proposed: dict[str, Any] = {}
                for iteration in range(1, MAXIMUM_ITERATIONS + 1):
                    iteration_count = iteration
                    proposed, domain = _propose(gr, lr, rf, rh, x, pnl, ph)
                    complex_values = tuple(
                        complex(proposed[name]) for name in ("ic", "in", "ec", "en", "vn", "sn")
                    )
                    finite_values = [float(proposed[name]) for name in ("iref", "ph")]
                    if bool(lr["advanced_core_loss_scaling_resolved"]):
                        finite_values.extend(float(proposed[name]) for name in ("rv", "rfq", "rb"))
                        if domain:
                            finite_values.extend(float(proposed[name]) for name in ("mult", "pnl"))
                    else:
                        finite_values.append(float(proposed["pnl"]))
                    nonfinite = not all(
                        math.isfinite(value.real) and math.isfinite(value.imag)
                        for value in complex_values
                    ) or not all(math.isfinite(value) for value in finite_values)
                    if nonfinite:
                        break
                    if not domain:
                        break
                    rn = float(proposed["pnl"]) - pnl
                    rhres = float(proposed["ph"]) - ph
                    final_no_load_residual = rn
                    final_harmonic_residual = rhres
                    if math.isclose(
                        rn,
                        0,
                        rel_tol=FIXED_POINT_RELATIVE_TOLERANCE,
                        abs_tol=FIXED_POINT_ABSOLUTE_TOLERANCE_W,
                    ) and math.isclose(
                        rhres,
                        0,
                        rel_tol=FIXED_POINT_RELATIVE_TOLERANCE,
                        abs_tol=FIXED_POINT_ABSOLUTE_TOLERANCE_W,
                    ):
                        converged = True
                        solved = proposed
                        final_pnl = pnl
                        final_ph = ph
                        break
                    pnl += DAMPING_FACTOR * rn
                    ph += DAMPING_FACTOR * rhres
                r["fixed_point_iterations"] = iteration_count
                if math.isfinite(final_no_load_residual):
                    r["no_load_fixed_point_residual_w"] = final_no_load_residual
                if math.isfinite(final_harmonic_residual):
                    r["harmonic_fixed_point_residual_w"] = final_harmonic_residual
                if nonfinite:
                    state = _STATES[11]
                elif not domain:
                    r.update(
                        {
                            "coupled_core_voltage_ratio_to_factory_reference": float(
                                proposed["rv"]
                            ),
                            "coupled_core_frequency_ratio_to_factory_reference": float(
                                proposed["rfq"]
                            ),
                            "coupled_core_flux_density_ratio_to_factory_reference": float(
                                proposed["rb"]
                            ),
                        }
                    )
                    state = _STATES[10]
                elif solved is None and not converged:
                    state = _STATES[12]
                else:
                    assert solved is not None
                    numeric_keys: tuple[str, ...] = ("iref", "ph", "pnl")
                    if bool(lr["advanced_core_loss_scaling_resolved"]):
                        numeric_keys += ("rv", "rfq", "rb", "mult")
                    vals = [float(solved[name]) for name in numeric_keys]
                    if not all(math.isfinite(v) for v in vals):
                        state = _STATES[11]
                    else:
                        ic = complex(solved["ic"])
                        inn = complex(solved["in"])
                        ec = complex(solved["ec"])
                        en = complex(solved["en"])
                        vn = complex(solved["vn"])
                        sn = complex(solved["sn"])
                        iref = float(solved["iref"])
                        pnl = final_pnl
                        ph = final_ph
                        pfs = 3 * rf * iref**2
                        qfs = 3 * x * iref**2
                        pl = pfs + ph
                        total = pnl + pl
                        ar = float(gr["collection_p_w"]) - sn.real - pnl - ph - pfs
                        qr = float(gr["collection_q_var"]) - sn.imag - qfs
                        r.update(
                            {
                                "collection_voltage_line_to_line_rms_v": float(
                                    gr["collection_voltage_line_to_line_rms_v"]
                                ),
                                "collection_p_w": float(gr["collection_p_w"]),
                                "collection_q_var": float(gr["collection_q_var"]),
                                "network_to_collection_voltage_ratio": float(
                                    gr["network_to_collection_voltage_ratio"]
                                ),
                                "network_side_phase_displacement_deg": float(
                                    gr["network_side_phase_displacement_deg"]
                                ),
                                "collection_series_current_real_a": ic.real,
                                "collection_series_current_imag_a": ic.imag,
                                "collection_series_current_magnitude_a": abs(ic),
                                "collection_series_current_angle_deg": math.degrees(
                                    cmath.phase(ic)
                                ),
                                "network_series_current_real_a": inn.real,
                                "network_series_current_imag_a": inn.imag,
                                "network_series_current_magnitude_a": abs(inn),
                                "network_series_current_angle_deg": math.degrees(cmath.phase(inn)),
                                "internal_collection_excitation_voltage_line_to_line_rms_v": (
                                    math.sqrt(3) * abs(ec)
                                ),
                                "internal_network_excitation_voltage_line_to_line_rms_v": math.sqrt(
                                    3
                                )
                                * abs(en),
                                "network_terminal_phase_voltage_real_v": vn.real,
                                "network_terminal_phase_voltage_imag_v": vn.imag,
                                "network_terminal_phase_voltage_magnitude_v": abs(vn),
                                "network_terminal_voltage_line_to_line_rms_v": math.sqrt(3)
                                * abs(vn),
                                "network_terminal_phase_angle_deg": math.degrees(cmath.phase(vn)),
                                "p_network_terminal_w": sn.real,
                                "q_network_terminal_var": sn.imag,
                                "s_network_terminal_magnitude_va": abs(sn),
                                "p_no_load_active_loss_w": pnl,
                                "p_harmonic_incremental_load_loss_w": ph,
                                "p_fundamental_series_active_loss_w": pfs,
                                "q_fundamental_series_consumption_var": qfs,
                                "p_advanced_load_loss_w": pl,
                                "coupled_advanced_load_loss_w": pl,
                                "p_selected_load_loss_w": pl,
                                "coupled_selected_load_loss_w": pl,
                                "p_total_transformer_active_loss_w": total,
                                "coupled_no_load_loss_w": pnl,
                                "coupled_total_transformer_active_loss_w": total,
                                "s12g_baseline_load_loss_w": float(gr["p_series_active_loss_w"]),
                                "s12k_baseline_advanced_load_loss_w": float(
                                    kr["harmonic_and_temperature_corrected_load_loss_w"]
                                ),
                                "coupled_load_loss_adjustment_vs_s12k_w": pl
                                - float(kr["harmonic_and_temperature_corrected_load_loss_w"]),
                                "coupled_load_loss_adjustment_vs_s12k_selected_w": pl
                                - float(kr["selected_total_load_loss_w"]),
                                "s12g_baseline_no_load_loss_w": float(
                                    gr["p_no_load_active_sink_w"]
                                ),
                                "s12l_selected_no_load_loss_w": float(
                                    lr["corrected_no_load_loss_w"]
                                ),
                                "coupled_no_load_adjustment_vs_s12l_w": pnl
                                - float(lr["corrected_no_load_loss_w"]),
                                "s12g_baseline_total_transformer_active_loss_w": float(
                                    gr["p_total_transformer_active_loss_w"]
                                ),
                                "advanced_total_loss_correction_vs_s12g_w": total
                                - float(gr["p_total_transformer_active_loss_w"]),
                                "fixed_point_iterations": iteration_count,
                                "fixed_point_converged": True,
                                "no_load_fixed_point_residual_w": final_no_load_residual,
                                "harmonic_fixed_point_residual_w": final_harmonic_residual,
                                "coupled_core_voltage_ratio_to_factory_reference": float(
                                    solved["rv"]
                                ),
                                "coupled_core_frequency_ratio_to_factory_reference": float(
                                    solved["rfq"]
                                ),
                                "coupled_core_flux_density_ratio_to_factory_reference": float(
                                    solved["rb"]
                                ),
                                "coupled_core_loss_scaling_multiplier": float(solved["mult"]),
                                "active_power_conservation_residual_w": ar,
                                "reactive_power_conservation_residual_var": qr,
                                "s12l_core_loss_re_evaluated_in_coupled_iteration": bool(
                                    lr["advanced_core_loss_scaling_resolved"]
                                ),
                                "transformer_terminal_output_resolved": True,
                                "load_loss_fallback_applied": kfallback,
                                "terminal_solution_fidelity": (
                                    "coupled_s12g_load_loss_fallback"
                                    if kfallback
                                    else "coupled_advanced_load_loss"
                                ),
                            }
                        )
                        state = (
                            (_STATES[15] if kfallback else _STATES[14])
                            if math.isclose(
                                ar, 0, rel_tol=_CLOSURE_REL_TOL, abs_tol=_CONSERVATION_ABS_TOL
                            )
                            and math.isclose(
                                qr, 0, rel_tol=_CLOSURE_REL_TOL, abs_tol=_CONSERVATION_ABS_TOL
                            )
                            else _STATES[13]
                        )
        except (OverflowError, ValueError, ZeroDivisionError):
            state = _STATES[11]
    r["transformer_advanced_operating_solution_state"] = state
    return r


def _frame(keys: list[tuple[pd.Timestamp, str]], records: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        records,
        index=pd.MultiIndex.from_tuples(keys, names=["timestamp", "transformer_id"]),
        columns=_COLUMNS,
    )
    for c in _BOOL:
        frame[c] = frame[c].astype(bool)
    frame["transformer_energised"] = frame["transformer_energised"].astype("boolean")
    for c in _FLOAT:
        frame[c] = frame[c].astype("float64")
    for c in _INT:
        frame[c] = frame[c].astype("int64")
    for c in set(_COLUMNS) - _BOOL - _NULLABLE - _FLOAT - _INT:
        frame[c] = frame[c].astype(object)
    return frame


def _diagnostics(
    frame: pd.DataFrame, nids: int, ntimes: int
) -> TopologyTransformerAdvancedOperatingSolutionDiagnostics:
    s = frame["transformer_advanced_operating_solution_state"]
    return TopologyTransformerAdvancedOperatingSolutionDiagnostics(
        nids,
        ntimes,
        len(frame),
        int((s == _STATES[14]).sum()),
        int((s == _STATES[2]).sum()),
        int((s == _STATES[12]).sum()),
        int(frame["transformer_terminal_output_resolved"].sum()),
        int((s == _STATES[14]).sum()),
        int((s == _STATES[15]).sum()),
        tuple((x, int((s == x).sum())) for x in _STATES),
        TRANSFORMER_ADVANCED_OPERATING_SOLUTION_MODEL_ID,
    )


def calculate_topology_transformer_advanced_operating_solution(
    **values: Any,
) -> TopologyTransformerAdvancedOperatingSolutionResult:
    parents = _parents(values)
    g, k, core = parents
    ids = list(
        dict.fromkeys(g.transformer_operating_states.index.get_level_values("transformer_id"))
    )
    groups = [
        list(x.index.get_level_values("timestamp"))
        for x in (g.transformer_operating_states, k.states, core.states)
    ]
    try:
        times = sorted(set().union(*map(set, groups)))
    except TypeError as error:
        raise ValueError(
            "advanced transformer timestamps have incompatible timezone semantics"
        ) from error
    keys = [(t, i) for t in times for i in ids]
    records = [_record(t, i, parents) for t, i in keys]
    frame = _frame(keys, records)
    result = TopologyTransformerAdvancedOperatingSolutionResult(
        frame.copy(deep=True), _diagnostics(frame, len(ids), len(times))
    )
    _validate_result(parents, times, result)
    return result


# Independent validation deliberately duplicates the bounded S12M equations.
# It does not call or capture any production builder, coefficient path, or
# fixed-point solver, so a production defect cannot validate itself.
def _validator_base() -> dict[str, object]:
    r: dict[str, object] = {name: None for name in _COLUMNS}
    for name in _BOOL:
        r[name] = False
    for name in _FLOAT:
        r[name] = math.nan
    for name in _INT:
        r[name] = 0
    r["transformer_energised"] = pd.NA
    r.update(
        {
            "fixed_point_maximum_iterations": MAXIMUM_ITERATIONS,
            "fixed_point_damping_factor": DAMPING_FACTOR,
            "fixed_point_relative_tolerance": FIXED_POINT_RELATIVE_TOLERANCE,
            "fixed_point_absolute_tolerance_w": FIXED_POINT_ABSOLUTE_TOLERANCE_W,
            "advanced_fundamental_series_resistance_semantics": (
                ADVANCED_FUNDAMENTAL_SERIES_RESISTANCE_SEMANTICS
            ),
            "advanced_series_reactance_treatment": ADVANCED_SERIES_REACTANCE_TREATMENT,
            "harmonic_increment_treatment": HARMONIC_INCREMENT_TREATMENT,
            "advanced_load_loss_ownership": ADVANCED_LOAD_LOSS_OWNERSHIP,
            "advanced_no_load_loss_ownership": ADVANCED_NO_LOAD_LOSS_OWNERSHIP,
            "s12d_operating_loss_treatment": S12D_TREATMENT,
            "transformer_operating_solution_contract": TRANSFORMER_OPERATING_SOLUTION_CONTRACT_ID,
            "transformer_operating_solution_model": TRANSFORMER_OPERATING_SOLUTION_MODEL_ID,
            "transformer_corrected_load_loss_contract": TRANSFORMER_CORRECTED_LOAD_LOSS_CONTRACT_ID,
            "transformer_corrected_load_loss_model": TRANSFORMER_CORRECTED_LOAD_LOSS_MODEL_ID,
            "transformer_core_no_load_loss_contract": TRANSFORMER_CORE_NO_LOAD_LOSS_CONTRACT_ID,
            "transformer_core_no_load_loss_model": TRANSFORMER_CORE_NO_LOAD_LOSS_MODEL_ID,
            "transformer_advanced_operating_solution_contract": (
                TRANSFORMER_ADVANCED_OPERATING_SOLUTION_CONTRACT_ID
            ),
            "transformer_advanced_operating_solution_model": (
                TRANSFORMER_ADVANCED_OPERATING_SOLUTION_MODEL_ID
            ),
            "transformer_advanced_operating_solution_scope": (
                TRANSFORMER_ADVANCED_OPERATING_SOLUTION_SCOPE
            ),
            "transformer_advanced_operating_solution_coverage_scope": (
                TRANSFORMER_ADVANCED_OPERATING_SOLUTION_COVERAGE_SCOPE
            ),
        }
    )
    return r


def _validator_propose(
    g: pd.Series, core: pd.Series, rf: float, rh: float, x: float, pnl: float, ph: float
) -> tuple[dict[str, Any], bool]:
    vc = complex(float(g["collection_voltage_line_to_line_rms_v"]) / math.sqrt(3.0), 0.0)
    s = complex(float(g["collection_p_w"]) - pnl - ph, float(g["collection_q_var"]))
    ic = (s / (3.0 * vc)).conjugate()
    k = float(g["network_to_collection_voltage_ratio"]) * cmath.exp(
        1j * math.radians(float(g["network_side_phase_displacement_deg"]))
    )
    current_n = ic / k.conjugate()
    z = complex(rf, x)
    side = str(g["series_equivalent_reference_side"])
    ec = vc - z * ic if side == "collection_side" else vc
    en = k * ec
    vn = en if side == "collection_side" else en - z * current_n
    iref = ic if side == "collection_side" else current_n
    ph_new = 3.0 * rh * abs(iref) ** 2
    core_ll = math.sqrt(3.0) * abs(
        ec if core["no_load_test_reference_side"] == "collection_side" else en
    )
    pnl_new = float(core["corrected_no_load_loss_w"])
    domain = True
    rv = rfq = rb = mult = math.nan
    if bool(core["advanced_core_loss_scaling_resolved"]):
        rv = core_ll / float(core["factory_reference_core_excitation_voltage_ll_rms_v"])
        rfq = float(core["operating_frequency_hz"]) / float(core["no_load_test_frequency_hz"])
        rb = rv / rfq
        domain = float(core["minimum_frequency_ratio_to_reference"]) <= rfq <= float(
            core["maximum_frequency_ratio_to_reference"]
        ) and float(core["minimum_flux_density_ratio_to_reference"]) <= rb <= float(
            core["maximum_flux_density_ratio_to_reference"]
        )
        if domain:
            mult = math.exp(
                float(core["steinmetz_frequency_exponent_alpha"]) * math.log(rfq)
                + float(core["steinmetz_flux_density_exponent_beta"]) * math.log(rb)
            )
            pnl_new = float(core["scalable_core_loss_reference_w"]) * mult + float(
                core["non_scaling_no_load_loss_reference_residual_w"]
            )
    sn = 3.0 * vn * current_n.conjugate()
    return {
        "ic": ic,
        "in": current_n,
        "ec": ec,
        "en": en,
        "vn": vn,
        "sn": sn,
        "iref": abs(iref),
        "ph": ph_new,
        "pnl": pnl_new,
        "rv": rv,
        "rfq": rfq,
        "rb": rb,
        "mult": mult,
    }, domain


def _validator_record(
    timestamp: pd.Timestamp, identifier: str, parents: tuple[Any, Any, Any]
) -> dict[str, object]:
    g, k, core = parents
    r = _validator_base()
    key = (timestamp, identifier)
    gr = (
        g.transformer_operating_states.loc[key]
        if key in g.transformer_operating_states.index
        else None
    )
    kr = k.states.loc[key] if key in k.states.index else None
    lr = core.states.loc[key] if key in core.states.index else None
    gres = bool(gr is not None and gr["transformer_terminal_operating_solution_resolved"])
    kres = bool(
        kr is not None
        and kr["transformer_corrected_load_loss_state"]
        == "resolved_harmonic_and_temperature_corrected_transformer_load_loss"
    )
    kout = bool(kr is not None and kr["transformer_load_loss_output_resolved"])
    kfallback = bool(kr is not None and kr["s12g_load_loss_fallback_applied"])
    lres = bool(lr is not None and lr["transformer_no_load_loss_output_resolved"])
    de = bool(
        gr is not None
        and gr["transformer_operating_solution_state"]
        == "resolved_deenergised_transformer_no_transfer"
    )
    r.update(
        {
            "s12g_operating_row_present": gr is not None,
            "s12g_terminal_operating_solution_resolved": gres,
            "s12k_corrected_load_loss_row_present": kr is not None,
            "s12k_corrected_load_loss_resolved": kres,
            "s12k_load_loss_output_resolved": kout,
            "s12k_advanced_load_loss_correction_resolved": kres,
            "s12k_load_loss_fallback_applied": kfallback,
            "s12k_load_loss_output_fidelity": (
                str(kr["load_loss_output_fidelity"]) if kr is not None else ""
            ),
            "s12l_core_no_load_loss_row_present": lr is not None,
            "s12l_no_load_loss_output_resolved": lres,
            "s12l_advanced_core_loss_scaling_resolved": bool(
                lr is not None and lr["advanced_core_loss_scaling_resolved"]
            ),
            "transformer_energised": pd.NA if gr is None else gr["transformer_energised"],
        }
    )
    if gr is not None:
        r.update(
            {
                "collection_voltage_line_to_line_rms_v": float(
                    gr["collection_voltage_line_to_line_rms_v"]
                ),
                "collection_p_w": float(gr["collection_p_w"]),
                "collection_q_var": float(gr["collection_q_var"]),
                "network_to_collection_voltage_ratio": float(
                    gr["network_to_collection_voltage_ratio"]
                ),
                "network_side_phase_displacement_deg": float(
                    gr["network_side_phase_displacement_deg"]
                ),
                "s12g_reference_effective_series_resistance_ohm_per_phase": float(
                    gr["effective_series_resistance_ohm_per_phase"]
                ),
                "retained_series_reactance_ohm_per_phase": float(
                    gr["effective_series_reactance_ohm_per_phase"]
                ),
                "series_reference_side": gr["series_equivalent_reference_side"],
                "s12g_baseline_load_loss_w": float(gr["p_series_active_loss_w"]),
                "s12g_baseline_no_load_loss_w": float(gr["p_no_load_active_sink_w"]),
                "s12g_baseline_total_transformer_active_loss_w": float(
                    gr["p_total_transformer_active_loss_w"]
                ),
            }
        )
    if kr is not None:
        r["s12k_baseline_advanced_load_loss_w"] = float(
            kr["harmonic_and_temperature_corrected_load_loss_w"]
        )
        r["s12k_selected_load_loss_w"] = float(kr["selected_total_load_loss_w"])
    if lr is not None:
        r["s12l_selected_no_load_loss_w"] = float(lr["corrected_no_load_loss_w"])
    if gr is None:
        state = _STATES[0]
    elif not gres and not de:
        state = _STATES[1]
    elif de:
        for name in (
            "collection_series_current_real_a",
            "collection_series_current_imag_a",
            "collection_series_current_magnitude_a",
            "collection_series_current_angle_deg",
            "network_series_current_real_a",
            "network_series_current_imag_a",
            "network_series_current_magnitude_a",
            "network_series_current_angle_deg",
            "p_network_terminal_w",
            "q_network_terminal_var",
            "s_network_terminal_magnitude_va",
            "p_no_load_active_loss_w",
            "p_harmonic_incremental_load_loss_w",
            "p_fundamental_series_active_loss_w",
            "q_fundamental_series_consumption_var",
            "p_advanced_load_loss_w",
            "coupled_advanced_load_loss_w",
            "p_total_transformer_active_loss_w",
            "coupled_no_load_loss_w",
            "coupled_total_transformer_active_loss_w",
            "coupled_load_loss_adjustment_vs_s12k_w",
            "coupled_no_load_adjustment_vs_s12l_w",
            "advanced_total_loss_correction_vs_s12g_w",
            "no_load_fixed_point_residual_w",
            "harmonic_fixed_point_residual_w",
            "active_power_conservation_residual_w",
            "reactive_power_conservation_residual_var",
            "p_selected_load_loss_w",
            "coupled_selected_load_loss_w",
            "coupled_load_loss_adjustment_vs_s12k_selected_w",
        ):
            r[name] = 0.0
        r["fixed_point_converged"] = True
        r["transformer_terminal_output_resolved"] = True
        r["terminal_solution_fidelity"] = "deenergised_zero"
        state = _STATES[2]
    elif kr is None:
        state = _STATES[3]
    elif not kout:
        state = _STATES[4]
    elif lr is None:
        state = _STATES[5]
    elif not lres:
        state = _STATES[6]
    else:
        try:
            x = float(gr["effective_series_reactance_ohm_per_phase"])
            if kfallback:
                rf = float(gr["effective_series_resistance_ohm_per_phase"])
                rh = 0.0
                side = str(gr["series_equivalent_reference_side"])
                i0 = float(
                    gr["collection_series_current_magnitude_a"]
                    if side == "collection_side"
                    else gr["network_series_current_magnitude_a"]
                )
                pf = float(kr["selected_fundamental_load_loss_w"])
                phb = float(kr["selected_harmonic_incremental_load_loss_w"])
                selected = float(kr["selected_total_load_loss_w"])
                fundamental_target = pf
                harmonic_target = phb
                adjusted = False
            else:
                ir = float(kr["rated_reference_side_current_a"])
                i0 = float(kr["fundamental_operating_current_a"])
                pr = float(kr["i2r_loss_reference_w"])
                pec = float(kr["winding_eddy_current_loss_reference_w"])
                posl = float(kr["other_stray_loss_reference_w"])
                kt = float(kr["i2r_temperature_correction_factor"])
                kec = float(kr["winding_eddy_temperature_correction_factor"])
                kosl = float(kr["other_stray_temperature_correction_factor"])
                s2 = float(kr["sum_current_ratio_squared"])
                fec = float(kr["winding_eddy_harmonic_loss_factor"])
                fosl = float(kr["other_stray_harmonic_loss_factor"])
                pf = math.fsum([pr * kt, pec * kec, posl * kosl])
                phb = math.fsum(
                    [
                        pr * kt * (s2 - 1.0),
                        pec * kec * (s2 * fec - 1.0),
                        posl * kosl * (s2 * fosl - 1.0),
                    ]
                )
                adjusted = phb < 0 and math.isclose(
                    phb, 0.0, rel_tol=0.0, abs_tol=1e-12 * max(1.0, pf)
                )
                phb = 0.0 if adjusted else phb
                rf = pf / (3 * ir * ir)
                rh = phb / (3 * ir * ir)
                selected = float(kr["harmonic_and_temperature_corrected_load_loss_w"])
                fundamental_target = float(kr["temperature_corrected_sinusoidal_load_loss_w"])
                harmonic_target = float(kr["harmonic_incremental_load_loss_w"])
            fclosure = 3 * rf * i0 * i0 - fundamental_target
            hclosure = 3 * rh * i0 * i0 - harmonic_target
            total_closure = 3 * (rf + rh) * i0 * i0 - selected
            r.update(
                {
                    "s12g_reference_effective_series_resistance_ohm_per_phase": float(
                        gr["effective_series_resistance_ohm_per_phase"]
                    ),
                    "advanced_fundamental_effective_series_resistance_ohm_per_phase": rf,
                    "advanced_fundamental_series_resistance_delta_ohm_per_phase": rf
                    - float(gr["effective_series_resistance_ohm_per_phase"]),
                    "retained_series_reactance_ohm_per_phase": x,
                    "harmonic_increment_accounting_resistance_ohm_per_phase": rh,
                    "harmonic_increment_roundoff_adjusted": adjusted,
                    "series_reference_side": gr["series_equivalent_reference_side"],
                }
            )
            if not math.isclose(fclosure, 0, rel_tol=_CLOSURE_REL_TOL, abs_tol=_CLOSURE_ABS_TOL_W):
                state = _STATES[7]
            elif not math.isclose(
                hclosure, 0, rel_tol=_CLOSURE_REL_TOL, abs_tol=_CLOSURE_ABS_TOL_W
            ) or not math.isclose(
                total_closure, 0, rel_tol=_CLOSURE_REL_TOL, abs_tol=_CLOSURE_ABS_TOL_W
            ):
                state = _STATES[8]
            elif phb < 0:
                state = _STATES[9]
            else:
                pnl = float(lr["corrected_no_load_loss_w"])
                ph = phb
                solved = None
                domain = True
                converged = False
                nonfinite = False
                final_no_load_residual = math.nan
                final_harmonic_residual = math.nan
                final_pnl = math.nan
                final_ph = math.nan
                iteration_count = 0
                proposed: dict[str, Any] = {}
                for iteration in range(1, MAXIMUM_ITERATIONS + 1):
                    iteration_count = iteration
                    proposed, domain = _validator_propose(gr, lr, rf, rh, x, pnl, ph)
                    complex_values = tuple(
                        complex(proposed[name]) for name in ("ic", "in", "ec", "en", "vn", "sn")
                    )
                    finite_values = [float(proposed[name]) for name in ("iref", "ph")]
                    if bool(lr["advanced_core_loss_scaling_resolved"]):
                        finite_values.extend(float(proposed[name]) for name in ("rv", "rfq", "rb"))
                        if domain:
                            finite_values.extend(float(proposed[name]) for name in ("mult", "pnl"))
                    else:
                        finite_values.append(float(proposed["pnl"]))
                    nonfinite = not all(
                        math.isfinite(value.real) and math.isfinite(value.imag)
                        for value in complex_values
                    ) or not all(math.isfinite(value) for value in finite_values)
                    if nonfinite:
                        break
                    if not domain:
                        break
                    rn = float(proposed["pnl"]) - pnl
                    rhres = float(proposed["ph"]) - ph
                    final_no_load_residual = rn
                    final_harmonic_residual = rhres
                    if math.isclose(
                        rn,
                        0,
                        rel_tol=FIXED_POINT_RELATIVE_TOLERANCE,
                        abs_tol=FIXED_POINT_ABSOLUTE_TOLERANCE_W,
                    ) and math.isclose(
                        rhres,
                        0,
                        rel_tol=FIXED_POINT_RELATIVE_TOLERANCE,
                        abs_tol=FIXED_POINT_ABSOLUTE_TOLERANCE_W,
                    ):
                        converged = True
                        solved = proposed
                        final_pnl = pnl
                        final_ph = ph
                        break
                    pnl += DAMPING_FACTOR * rn
                    ph += DAMPING_FACTOR * rhres
                r["fixed_point_iterations"] = iteration_count
                if math.isfinite(final_no_load_residual):
                    r["no_load_fixed_point_residual_w"] = final_no_load_residual
                if math.isfinite(final_harmonic_residual):
                    r["harmonic_fixed_point_residual_w"] = final_harmonic_residual
                if nonfinite:
                    state = _STATES[11]
                elif not domain:
                    r.update(
                        {
                            "coupled_core_voltage_ratio_to_factory_reference": float(
                                proposed["rv"]
                            ),
                            "coupled_core_frequency_ratio_to_factory_reference": float(
                                proposed["rfq"]
                            ),
                            "coupled_core_flux_density_ratio_to_factory_reference": float(
                                proposed["rb"]
                            ),
                        }
                    )
                    state = _STATES[10]
                elif solved is None and not converged:
                    state = _STATES[12]
                else:
                    assert solved is not None
                    numeric_keys: tuple[str, ...] = ("iref", "ph", "pnl")
                    if bool(lr["advanced_core_loss_scaling_resolved"]):
                        numeric_keys += ("rv", "rfq", "rb", "mult")
                    vals = [float(solved[name]) for name in numeric_keys]
                    if not all(math.isfinite(v) for v in vals):
                        state = _STATES[11]
                    else:
                        ic = complex(solved["ic"])
                        inn = complex(solved["in"])
                        ec = complex(solved["ec"])
                        en = complex(solved["en"])
                        vn = complex(solved["vn"])
                        sn = complex(solved["sn"])
                        iref = float(solved["iref"])
                        pnl = final_pnl
                        ph = final_ph
                        pfs = 3 * rf * iref**2
                        qfs = 3 * x * iref**2
                        pl = pfs + ph
                        total = pnl + pl
                        ar = float(gr["collection_p_w"]) - sn.real - pnl - ph - pfs
                        qr = float(gr["collection_q_var"]) - sn.imag - qfs
                        r.update(
                            {
                                "collection_voltage_line_to_line_rms_v": float(
                                    gr["collection_voltage_line_to_line_rms_v"]
                                ),
                                "collection_p_w": float(gr["collection_p_w"]),
                                "collection_q_var": float(gr["collection_q_var"]),
                                "network_to_collection_voltage_ratio": float(
                                    gr["network_to_collection_voltage_ratio"]
                                ),
                                "network_side_phase_displacement_deg": float(
                                    gr["network_side_phase_displacement_deg"]
                                ),
                                "collection_series_current_real_a": ic.real,
                                "collection_series_current_imag_a": ic.imag,
                                "collection_series_current_magnitude_a": abs(ic),
                                "collection_series_current_angle_deg": math.degrees(
                                    cmath.phase(ic)
                                ),
                                "network_series_current_real_a": inn.real,
                                "network_series_current_imag_a": inn.imag,
                                "network_series_current_magnitude_a": abs(inn),
                                "network_series_current_angle_deg": math.degrees(cmath.phase(inn)),
                                "internal_collection_excitation_voltage_line_to_line_rms_v": (
                                    math.sqrt(3) * abs(ec)
                                ),
                                "internal_network_excitation_voltage_line_to_line_rms_v": math.sqrt(
                                    3
                                )
                                * abs(en),
                                "network_terminal_phase_voltage_real_v": vn.real,
                                "network_terminal_phase_voltage_imag_v": vn.imag,
                                "network_terminal_phase_voltage_magnitude_v": abs(vn),
                                "network_terminal_voltage_line_to_line_rms_v": math.sqrt(3)
                                * abs(vn),
                                "network_terminal_phase_angle_deg": math.degrees(cmath.phase(vn)),
                                "p_network_terminal_w": sn.real,
                                "q_network_terminal_var": sn.imag,
                                "s_network_terminal_magnitude_va": abs(sn),
                                "p_no_load_active_loss_w": pnl,
                                "p_harmonic_incremental_load_loss_w": ph,
                                "p_fundamental_series_active_loss_w": pfs,
                                "q_fundamental_series_consumption_var": qfs,
                                "p_advanced_load_loss_w": pl,
                                "coupled_advanced_load_loss_w": pl,
                                "p_selected_load_loss_w": pl,
                                "coupled_selected_load_loss_w": pl,
                                "p_total_transformer_active_loss_w": total,
                                "coupled_no_load_loss_w": pnl,
                                "coupled_total_transformer_active_loss_w": total,
                                "s12g_baseline_load_loss_w": float(gr["p_series_active_loss_w"]),
                                "s12k_baseline_advanced_load_loss_w": float(
                                    kr["harmonic_and_temperature_corrected_load_loss_w"]
                                ),
                                "coupled_load_loss_adjustment_vs_s12k_w": pl
                                - float(kr["harmonic_and_temperature_corrected_load_loss_w"]),
                                "coupled_load_loss_adjustment_vs_s12k_selected_w": pl
                                - float(kr["selected_total_load_loss_w"]),
                                "s12g_baseline_no_load_loss_w": float(
                                    gr["p_no_load_active_sink_w"]
                                ),
                                "s12l_selected_no_load_loss_w": float(
                                    lr["corrected_no_load_loss_w"]
                                ),
                                "coupled_no_load_adjustment_vs_s12l_w": pnl
                                - float(lr["corrected_no_load_loss_w"]),
                                "s12g_baseline_total_transformer_active_loss_w": float(
                                    gr["p_total_transformer_active_loss_w"]
                                ),
                                "advanced_total_loss_correction_vs_s12g_w": total
                                - float(gr["p_total_transformer_active_loss_w"]),
                                "fixed_point_iterations": iteration_count,
                                "fixed_point_converged": True,
                                "no_load_fixed_point_residual_w": final_no_load_residual,
                                "harmonic_fixed_point_residual_w": final_harmonic_residual,
                                "coupled_core_voltage_ratio_to_factory_reference": float(
                                    solved["rv"]
                                ),
                                "coupled_core_frequency_ratio_to_factory_reference": float(
                                    solved["rfq"]
                                ),
                                "coupled_core_flux_density_ratio_to_factory_reference": float(
                                    solved["rb"]
                                ),
                                "coupled_core_loss_scaling_multiplier": float(solved["mult"]),
                                "active_power_conservation_residual_w": ar,
                                "reactive_power_conservation_residual_var": qr,
                                "s12l_core_loss_re_evaluated_in_coupled_iteration": bool(
                                    lr["advanced_core_loss_scaling_resolved"]
                                ),
                                "transformer_terminal_output_resolved": True,
                                "load_loss_fallback_applied": kfallback,
                                "terminal_solution_fidelity": (
                                    "coupled_s12g_load_loss_fallback"
                                    if kfallback
                                    else "coupled_advanced_load_loss"
                                ),
                            }
                        )
                        state = (
                            (_STATES[15] if kfallback else _STATES[14])
                            if math.isclose(
                                ar, 0, rel_tol=_CLOSURE_REL_TOL, abs_tol=_CONSERVATION_ABS_TOL
                            )
                            and math.isclose(
                                qr, 0, rel_tol=_CLOSURE_REL_TOL, abs_tol=_CONSERVATION_ABS_TOL
                            )
                            else _STATES[13]
                        )
        except (OverflowError, ValueError, ZeroDivisionError):
            state = _STATES[11]
    r["transformer_advanced_operating_solution_state"] = state
    return r


def _validator_frame(
    keys: list[tuple[pd.Timestamp, str]], records: list[dict[str, object]]
) -> pd.DataFrame:
    frame = pd.DataFrame(
        records,
        index=pd.MultiIndex.from_tuples(keys, names=["timestamp", "transformer_id"]),
        columns=_COLUMNS,
    )
    for c in _BOOL:
        frame[c] = frame[c].astype(bool)
    frame["transformer_energised"] = frame["transformer_energised"].astype("boolean")
    for c in _FLOAT:
        frame[c] = frame[c].astype("float64")
    for c in _INT:
        frame[c] = frame[c].astype("int64")
    for c in set(_COLUMNS) - _BOOL - _NULLABLE - _FLOAT - _INT:
        frame[c] = frame[c].astype(object)
    return frame


def _validator_diagnostics(
    frame: pd.DataFrame, nids: int, ntimes: int
) -> TopologyTransformerAdvancedOperatingSolutionDiagnostics:
    s = frame["transformer_advanced_operating_solution_state"]
    return TopologyTransformerAdvancedOperatingSolutionDiagnostics(
        nids,
        ntimes,
        len(frame),
        int((s == _STATES[14]).sum()),
        int((s == _STATES[2]).sum()),
        int((s == _STATES[12]).sum()),
        int(frame["transformer_terminal_output_resolved"].sum()),
        int((s == _STATES[14]).sum()),
        int((s == _STATES[15]).sum()),
        tuple((x, int((s == x).sum())) for x in _STATES),
        TRANSFORMER_ADVANCED_OPERATING_SOLUTION_MODEL_ID,
    )


def _validate_result(
    parents: tuple[Any, Any, Any],
    times: list[pd.Timestamp],
    result: TopologyTransformerAdvancedOperatingSolutionResult,
) -> None:
    ids = list(
        dict.fromkeys(
            parents[0].transformer_operating_states.index.get_level_values("transformer_id")
        )
    )
    keys = [(t, i) for t in times for i in ids]
    expected = _validator_frame(keys, [_validator_record(t, i, parents) for t, i in keys])
    try:
        pd.testing.assert_frame_equal(result.states, expected, check_exact=True)
    except AssertionError as error:
        raise ValueError("S12M result frame failed independent validation") from error
    if result.diagnostics != _validator_diagnostics(expected, len(ids), len(times)):
        raise ValueError("S12M diagnostics failed independent validation")
