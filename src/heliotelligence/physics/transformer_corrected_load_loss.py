"""Harmonic- and temperature-corrected transformer load-loss physics.

S12K uses current loading, never real-power loading.  S12G supplies fundamental
RMS current, S12I supplies total-RMS and harmonic multipliers, S12H decomposes
the same factory P_LL represented by S12F/S12G, and S12J supplies average
winding temperature.  The full S12K result replaces the S12G reference series
active loss; it is never additive.  The h**0.8 rule is harmonic-order weighting,
not a temperature exponent.  Other-stray structural temperature is explicitly
proxied by average winding temperature.  S12M owns later terminal reconciliation.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from numbers import Real
from types import MappingProxyType
from typing import Any, Literal, TypeVar

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.physics.transformer_harmonic_current_authority import (
    TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_MODEL_ID,
    resolve_transformer_harmonic_current_authority,
)
from heliotelligence.physics.transformer_loss_component_authority import (
    TRANSFORMER_LOSS_COMPONENT_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_LOSS_COMPONENT_AUTHORITY_MODEL_ID,
    resolve_transformer_loss_component_authority,
)
from heliotelligence.physics.transformer_operating_solution import (
    TRANSFORMER_OPERATING_SOLUTION_CONTRACT_ID,
    TRANSFORMER_OPERATING_SOLUTION_MODEL_ID,
    calculate_topology_transformer_operating_solution,
)
from heliotelligence.physics.transformer_thermal_state_authority import (
    TRANSFORMER_THERMAL_STATE_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_THERMAL_STATE_AUTHORITY_MODEL_ID,
    resolve_transformer_thermal_state_authority,
)

TRANSFORMER_CORRECTED_LOAD_LOSS_CONTRACT_ID = (
    "admitted_transformer_operating_component_harmonic_and_thermal_"
    "authorities_to_corrected_load_loss_v1"
)
TRANSFORMER_CORRECTED_LOAD_LOSS_MODEL_ID = (
    "balanced_three_phase_current_loading_harmonic_and_average_winding_"
    "temperature_corrected_component_load_loss_v1"
)
TRANSFORMER_CORRECTED_LOAD_LOSS_SCOPE = (
    "timestamped_transformer_advanced_load_loss_correction_before_"
    "advanced_terminal_reconciliation_and_core_loss_correction"
)
TRANSFORMER_CORRECTED_LOAD_LOSS_COVERAGE_SCOPE = (
    "resolved_energised_two_winding_transformers_with_side_compatible_"
    "operating_current_factory_components_harmonic_spectrum_and_"
    "average_winding_temperature"
)

CURRENT_LOADING_SEMANTICS = "fundamental_and_total_rms_current_loading_not_real_power_loading"
I2R_TEMPERATURE_SEMANTICS = (
    "linear_winding_resistance_factor_increases_with_average_winding_temperature"
)
WINDING_EDDY_TEMPERATURE_SEMANTICS = "inverse_winding_resistance_temperature_factor"
OTHER_STRAY_TEMPERATURE_SEMANTICS = (
    "inverse_winding_resistance_temperature_factor_with_average_winding_"
    "temperature_as_structural_temperature_proxy"
)
HARMONIC_OTHER_STRAY_SEMANTICS = "h0p8_harmonic_order_weighting_not_temperature_exponent"
OTHER_STRAY_TEMPERATURE_ASSUMPTION = (
    "structural_part_temperature_proxied_by_average_winding_temperature_"
    "with_inverse_resistance_temperature_factor"
)
ADVANCED_LOAD_LOSS_OWNERSHIP = "replacement_for_s12g_reference_series_active_loss_not_additive"
S12D_OPERATING_LOSS_TREATMENT = "independent_reference_condition_baseline_not_consumed"

Confidence = Literal["high", "medium", "low", "unknown"]
Conductor = Literal["copper", "aluminium", "mixed_or_other_explicit"]
_CONFIDENCES = {"high", "medium", "low", "unknown"}
_APPLICATION_SEMANTICS = "s12i_single_declared_operating_condition_matches_this_timestamp"
_REL_TOL = 1e-9
_ABS_TOL_W = 1e-8
_STATES = (
    "unresolved_missing_s12g_transformer_operating_state",
    "unresolved_upstream_s12g_transformer_operating_solution",
    "resolved_deenergised_transformer_zero_advanced_load_loss",
    "unresolved_upstream_s12h_advanced_loss_basis",
    "unresolved_upstream_s12i_harmonic_characterisation",
    "unresolved_harmonic_spectrum_reference_side_mismatch",
    "unresolved_operating_current_reference_side_mismatch",
    "unresolved_harmonic_fundamental_frequency_mismatch",
    "unresolved_single_condition_harmonic_spectrum_not_bound_to_timestamp",
    "unresolved_missing_s12j_transformer_thermal_state",
    "unresolved_upstream_s12j_load_loss_temperature_basis",
    "unresolved_missing_winding_resistance_temperature_constant_authority",
    "unresolved_temperature_outside_linear_resistance_correction_domain",
    "unresolved_s12g_reference_load_loss_closure_mismatch",
    "unresolved_nonfinite_corrected_transformer_load_loss",
    "resolved_harmonic_and_temperature_corrected_transformer_load_loss",
)


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be an exact non-empty string without padding")
    return value


def _confidence(value: object) -> str:
    if type(value) is not str or value not in _CONFIDENCES:
        raise ValueError("confidence is unsupported")
    return value


@dataclass(frozen=True)
class TransformerSingleConditionHarmonicSpectrumApplication:
    application_semantics: Literal[
        "s12i_single_declared_operating_condition_matches_this_timestamp"
    ]
    operating_condition_match_basis: str
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        if self.application_semantics != _APPLICATION_SEMANTICS:
            raise ValueError("application_semantics is unsupported")
        _text(self.operating_condition_match_basis, "operating_condition_match_basis")
        _text(self.parameter_source, "parameter_source")
        _confidence(self.confidence)


@dataclass(frozen=True)
class TransformerWindingResistanceTemperatureConstantAuthority:
    transformer_id: str
    applicable_conductor_material: Conductor
    resistance_temperature_constant_c: float
    constant_semantics: Literal["linear_winding_resistance_temperature_constant_c"]
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _text(self.transformer_id, "transformer_id")
        if self.applicable_conductor_material not in {
            "copper",
            "aluminium",
            "mixed_or_other_explicit",
        }:
            raise ValueError("applicable_conductor_material is unsupported")
        value = self.resistance_temperature_constant_c
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("resistance_temperature_constant_c must be real and non-Boolean")
        value = float(value)
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError("resistance_temperature_constant_c must be finite and positive")
        object.__setattr__(self, "resistance_temperature_constant_c", value)
        if self.constant_semantics != "linear_winding_resistance_temperature_constant_c":
            raise ValueError("constant_semantics is unsupported")
        _text(self.parameter_source, "parameter_source")
        _confidence(self.confidence)


@dataclass(frozen=True)
class TopologyTransformerCorrectedLoadLossDiagnostics:
    transformer_count: int
    timestamp_count: int
    row_count: int
    s12g_row_present_count: int
    s12g_operating_solution_resolved_count: int
    resolved_deenergised_zero_loss_count: int
    s12h_basis_resolved_count: int
    s12i_characterisation_resolved_count: int
    s12j_temperature_basis_resolved_count: int
    harmonic_side_mismatch_count: int
    operating_side_mismatch_count: int
    frequency_mismatch_count: int
    single_condition_binding_required_count: int
    single_condition_binding_missing_count: int
    standard_copper_temperature_constant_count: int
    standard_aluminium_temperature_constant_count: int
    explicit_temperature_constant_count: int
    missing_temperature_constant_count: int
    temperature_domain_failure_count: int
    baseline_closure_mismatch_count: int
    nonfinite_count: int
    resolved_corrected_load_loss_count: int
    positive_temperature_correction_effect_count: int
    negative_temperature_correction_effect_count: int
    positive_harmonic_increment_count: int
    state_counts: tuple[tuple[str, int], ...]
    model: str


@dataclass(frozen=True)
class TopologyTransformerCorrectedLoadLossResult:
    single_condition_harmonic_application_by_key: Mapping[
        tuple[pd.Timestamp, str], TransformerSingleConditionHarmonicSpectrumApplication
    ]
    winding_temperature_constant_by_transformer_id: Mapping[
        str, TransformerWindingResistanceTemperatureConstantAuthority
    ]
    states: pd.DataFrame
    diagnostics: TopologyTransformerCorrectedLoadLossDiagnostics


_BOOL_COLUMNS = {
    "s12g_operating_row_present",
    "s12g_terminal_operating_solution_resolved",
    "transformer_energised",
    "s12h_advanced_loss_basis_resolved",
    "s12i_harmonic_characterisation_resolved",
    "s12j_thermal_row_present",
    "s12j_load_loss_temperature_basis_resolved",
    "harmonic_reference_side_compatible",
    "operating_current_reference_side_compatible",
    "harmonic_frequency_compatible",
    "single_condition_harmonic_application_present",
    "harmonic_spectrum_applicable_at_timestamp",
    "other_stray_structural_temperature_proxy_applied",
    "no_load_loss_included",
    "terminal_voltage_recalculated",
    "series_equivalent_modified",
    "coupled_thermal_iteration_applied",
}
_FLOAT_COLUMNS = {
    "component_reference_frequency_hz",
    "harmonic_fundamental_frequency_hz",
    "fundamental_operating_current_a",
    "rated_reference_side_current_a",
    "fundamental_current_loading_ratio",
    "total_rms_to_fundamental_current_ratio",
    "total_rms_operating_current_a",
    "total_rms_current_loading_ratio",
    "sum_current_ratio_squared",
    "current_thd_ratio",
    "current_thd_percent",
    "winding_eddy_harmonic_loss_factor",
    "other_stray_harmonic_loss_factor",
    "component_reference_temperature_c",
    "average_winding_temperature_c",
    "resistance_temperature_constant_c",
    "i2r_temperature_correction_factor",
    "winding_eddy_temperature_correction_factor",
    "other_stray_temperature_correction_factor",
    "i2r_loss_reference_w",
    "winding_eddy_current_loss_reference_w",
    "other_stray_loss_reference_w",
    "factory_total_rated_load_loss_w",
    "effective_winding_ohmic_resistance_reference_ohm_per_phase",
    "effective_winding_ohmic_resistance_temperature_corrected_ohm_per_phase",
    "i2r_loss_fundamental_temperature_corrected_w",
    "i2r_loss_harmonic_increment_w",
    "i2r_loss_corrected_total_w",
    "winding_eddy_loss_fundamental_temperature_corrected_w",
    "winding_eddy_loss_harmonic_increment_w",
    "winding_eddy_loss_corrected_total_w",
    "other_stray_loss_fundamental_temperature_corrected_w",
    "other_stray_loss_harmonic_increment_w",
    "other_stray_loss_corrected_total_w",
    "reconstructed_reference_sinusoidal_load_loss_w",
    "s12g_reference_load_loss_w",
    "s12g_reference_load_loss_closure_residual_w",
    "temperature_corrected_sinusoidal_load_loss_w",
    "temperature_correction_effect_w",
    "harmonic_incremental_load_loss_w",
    "harmonic_and_temperature_corrected_load_loss_w",
    "advanced_correction_vs_s12g_w",
    "advanced_correction_decomposition_residual_w",
}
_COLUMNS = (
    "s12g_operating_row_present",
    "s12g_terminal_operating_solution_resolved",
    "transformer_energised",
    "s12h_advanced_loss_basis_resolved",
    "s12i_harmonic_characterisation_resolved",
    "s12j_thermal_row_present",
    "s12j_load_loss_temperature_basis_resolved",
    "component_reference_side",
    "harmonic_reference_side",
    "operating_series_reference_side",
    "harmonic_reference_side_compatible",
    "operating_current_reference_side_compatible",
    "component_reference_frequency_hz",
    "harmonic_fundamental_frequency_hz",
    "harmonic_frequency_compatible",
    "harmonic_spectrum_applicability_semantics",
    "single_condition_harmonic_application_present",
    "harmonic_spectrum_applicable_at_timestamp",
    "single_condition_operating_condition_match_basis",
    "single_condition_parameter_source",
    "single_condition_confidence",
    "fundamental_operating_current_a",
    "rated_reference_side_current_a",
    "fundamental_current_loading_ratio",
    "total_rms_to_fundamental_current_ratio",
    "total_rms_operating_current_a",
    "total_rms_current_loading_ratio",
    "sum_current_ratio_squared",
    "current_thd_ratio",
    "current_thd_percent",
    "winding_eddy_harmonic_loss_factor",
    "other_stray_harmonic_loss_factor",
    "winding_conductor_material",
    "component_reference_temperature_c",
    "average_winding_temperature_c",
    "resistance_temperature_constant_c",
    "resistance_temperature_constant_source_mode",
    "resistance_temperature_constant_parameter_source",
    "resistance_temperature_constant_confidence",
    "i2r_temperature_correction_factor",
    "winding_eddy_temperature_correction_factor",
    "other_stray_temperature_correction_factor",
    "i2r_temperature_semantics",
    "winding_eddy_temperature_semantics",
    "other_stray_temperature_semantics",
    "harmonic_other_stray_semantics",
    "other_stray_structural_temperature_proxy_applied",
    "other_stray_temperature_assumption",
    "i2r_loss_reference_w",
    "winding_eddy_current_loss_reference_w",
    "other_stray_loss_reference_w",
    "factory_total_rated_load_loss_w",
    "effective_winding_ohmic_resistance_reference_ohm_per_phase",
    "effective_winding_ohmic_resistance_temperature_corrected_ohm_per_phase",
    "i2r_loss_fundamental_temperature_corrected_w",
    "i2r_loss_harmonic_increment_w",
    "i2r_loss_corrected_total_w",
    "winding_eddy_loss_fundamental_temperature_corrected_w",
    "winding_eddy_loss_harmonic_increment_w",
    "winding_eddy_loss_corrected_total_w",
    "other_stray_loss_fundamental_temperature_corrected_w",
    "other_stray_loss_harmonic_increment_w",
    "other_stray_loss_corrected_total_w",
    "reconstructed_reference_sinusoidal_load_loss_w",
    "s12g_reference_load_loss_w",
    "s12g_reference_load_loss_closure_residual_w",
    "temperature_corrected_sinusoidal_load_loss_w",
    "temperature_correction_effect_w",
    "harmonic_incremental_load_loss_w",
    "harmonic_and_temperature_corrected_load_loss_w",
    "advanced_correction_vs_s12g_w",
    "advanced_correction_decomposition_residual_w",
    "current_loading_semantics",
    "advanced_load_loss_ownership",
    "s12d_operating_loss_treatment",
    "no_load_loss_included",
    "terminal_voltage_recalculated",
    "series_equivalent_modified",
    "coupled_thermal_iteration_applied",
    "transformer_corrected_load_loss_state",
    "transformer_operating_solution_contract",
    "transformer_operating_solution_model",
    "transformer_loss_component_authority_contract",
    "transformer_loss_component_authority_model",
    "transformer_harmonic_current_authority_contract",
    "transformer_harmonic_current_authority_model",
    "transformer_thermal_state_authority_contract",
    "transformer_thermal_state_authority_model",
    "transformer_corrected_load_loss_contract",
    "transformer_corrected_load_loss_model",
    "transformer_corrected_load_loss_scope",
    "transformer_corrected_load_loss_coverage_scope",
)


F = TypeVar("F", bound=Callable[..., Any])


def _call(function: F, values: Mapping[str, Any]) -> Any:
    names = inspect.signature(function).parameters
    return function(**{name: values[name] for name in names})


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


def _canonical_parents(values: Mapping[str, Any]) -> tuple[Any, Any, Any, Any]:
    g = _call(calculate_topology_transformer_operating_solution, values)
    _exact_replay("S12G", values["transformer_operating_solution"], g)
    h_values = dict(values)
    h = _call(resolve_transformer_loss_component_authority, h_values)
    _exact_replay("S12H", values["transformer_loss_component_authority"], h)
    i_values = dict(values)
    i = _call(resolve_transformer_harmonic_current_authority, i_values)
    _exact_replay("S12I", values["transformer_harmonic_current_authority"], i)
    j_values = dict(values)
    j_values["transformer_loss_component_authority"] = h
    j = _call(resolve_transformer_thermal_state_authority, j_values)
    _exact_replay("S12J", values["transformer_thermal_state_authority"], j)
    return g, h, i, j


def _admit_mapping(
    supplied: object, known: set[str]
) -> dict[str, TransformerWindingResistanceTemperatureConstantAuthority]:
    if not isinstance(supplied, Mapping):
        raise TypeError("winding temperature constant authority must be a mapping")
    copied: dict[str, TransformerWindingResistanceTemperatureConstantAuthority] = {}
    for key, authority in supplied.items():
        _text(key, "transformer_id")
        if key not in known:
            raise ValueError("temperature constant references unknown transformer")
        if type(authority) is not TransformerWindingResistanceTemperatureConstantAuthority:
            raise TypeError("winding temperature constant mapping has invalid value type")
        if key != authority.transformer_id:
            raise ValueError("temperature constant mapping key must match transformer_id")
        copied[key] = authority
    return dict(sorted(copied.items()))


def _admit_applications(
    supplied: object, known: set[str]
) -> tuple[
    dict[tuple[pd.Timestamp, str], TransformerSingleConditionHarmonicSpectrumApplication],
    list[pd.Timestamp],
]:
    if not isinstance(supplied, Mapping):
        raise TypeError("single-condition harmonic application must be a mapping")
    copied: dict[
        tuple[pd.Timestamp, str], TransformerSingleConditionHarmonicSpectrumApplication
    ] = {}
    timestamps: set[pd.Timestamp] = set()
    for key, authority in supplied.items():
        if type(key) is not tuple or len(key) != 2:
            raise ValueError("harmonic application key must be an exact two-item tuple")
        timestamp, identifier = key
        if type(timestamp) is not pd.Timestamp or pd.isna(timestamp):
            raise ValueError("harmonic application timestamp must be an exact non-NaT Timestamp")
        _text(identifier, "transformer_id")
        if identifier not in known:
            raise ValueError("harmonic application references unknown transformer")
        if type(authority) is not TransformerSingleConditionHarmonicSpectrumApplication:
            raise TypeError("harmonic application mapping has invalid value type")
        copied[(timestamp, identifier)] = authority
        timestamps.add(timestamp)
    try:
        ordered_timestamps = sorted(timestamps)
    except TypeError as error:
        raise ValueError("S12K timestamps have incompatible timezone semantics") from error
    ordered = {
        (t, i): copied[(t, i)]
        for t in ordered_timestamps
        for i in sorted(known)
        if (t, i) in copied
    }
    return ordered, ordered_timestamps


def _timestamps(*groups: list[pd.Timestamp]) -> list[pd.Timestamp]:
    try:
        return sorted(set().union(*map(set, groups)))
    except TypeError as error:
        raise ValueError("S12K timestamps have incompatible timezone semantics") from error


def _base_record() -> dict[str, object]:
    record: dict[str, object] = {
        name: (False if name in _BOOL_COLUMNS else math.nan if name in _FLOAT_COLUMNS else "")
        for name in _COLUMNS
    }
    record.update(
        {
            "current_loading_semantics": CURRENT_LOADING_SEMANTICS,
            "i2r_temperature_semantics": I2R_TEMPERATURE_SEMANTICS,
            "winding_eddy_temperature_semantics": WINDING_EDDY_TEMPERATURE_SEMANTICS,
            "other_stray_temperature_semantics": OTHER_STRAY_TEMPERATURE_SEMANTICS,
            "harmonic_other_stray_semantics": HARMONIC_OTHER_STRAY_SEMANTICS,
            "other_stray_temperature_assumption": OTHER_STRAY_TEMPERATURE_ASSUMPTION,
            "advanced_load_loss_ownership": ADVANCED_LOAD_LOSS_OWNERSHIP,
            "s12d_operating_loss_treatment": S12D_OPERATING_LOSS_TREATMENT,
            "no_load_loss_included": False,
            "terminal_voltage_recalculated": False,
            "series_equivalent_modified": False,
            "coupled_thermal_iteration_applied": False,
            "transformer_operating_solution_contract": TRANSFORMER_OPERATING_SOLUTION_CONTRACT_ID,
            "transformer_operating_solution_model": TRANSFORMER_OPERATING_SOLUTION_MODEL_ID,
            "transformer_loss_component_authority_contract": (
                TRANSFORMER_LOSS_COMPONENT_AUTHORITY_CONTRACT_ID
            ),
            "transformer_loss_component_authority_model": (
                TRANSFORMER_LOSS_COMPONENT_AUTHORITY_MODEL_ID
            ),
            "transformer_harmonic_current_authority_contract": (
                TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_CONTRACT_ID
            ),
            "transformer_harmonic_current_authority_model": (
                TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_MODEL_ID
            ),
            "transformer_thermal_state_authority_contract": (
                TRANSFORMER_THERMAL_STATE_AUTHORITY_CONTRACT_ID
            ),
            "transformer_thermal_state_authority_model": (
                TRANSFORMER_THERMAL_STATE_AUTHORITY_MODEL_ID
            ),
            "transformer_corrected_load_loss_contract": TRANSFORMER_CORRECTED_LOAD_LOSS_CONTRACT_ID,
            "transformer_corrected_load_loss_model": TRANSFORMER_CORRECTED_LOAD_LOSS_MODEL_ID,
            "transformer_corrected_load_loss_scope": TRANSFORMER_CORRECTED_LOAD_LOSS_SCOPE,
            "transformer_corrected_load_loss_coverage_scope": (
                TRANSFORMER_CORRECTED_LOAD_LOSS_COVERAGE_SCOPE
            ),
        }
    )
    return record


def _finite(values: list[float]) -> bool:
    return all(math.isfinite(value) for value in values)


def _record(
    timestamp: pd.Timestamp,
    identifier: str,
    parents: tuple[Any, Any, Any, Any],
    equipment: Any,
    constants: Mapping[str, Any],
    applications: Mapping[tuple[pd.Timestamp, str], Any],
) -> dict[str, object]:
    g, h, i, j = parents
    record = _base_record()
    key = (timestamp, identifier)
    grow = (
        g.transformer_operating_states.loc[key]
        if key in g.transformer_operating_states.index
        else None
    )
    hrow = h.transformer_states.loc[identifier]
    irow = i.transformer_states.loc[identifier]
    jrow = j.states.loc[key] if key in j.states.index else None
    construction = h.construction_by_id.get(identifier)
    application = applications.get(key)
    custom = constants.get(identifier)
    g_ok = bool(grow is not None and grow["transformer_terminal_operating_solution_resolved"])
    deenergised = bool(
        grow is not None
        and grow["transformer_operating_solution_state"]
        == "resolved_deenergised_transformer_no_transfer"
    )
    h_ok = bool(hrow["transformer_advanced_loss_basis_resolved"])
    i_ok = bool(irow["transformer_harmonic_current_characterisation_resolved"])
    j_ok = bool(jrow is not None and jrow["transformer_load_loss_temperature_basis_resolved"])
    component_side = str(hrow["component_test_current_reference_side"])
    harmonic_side = str(irow["harmonic_current_reference_side"])
    operating_side = str(grow["series_equivalent_reference_side"]) if grow is not None else ""
    applicability = str(irow["applicability_semantics"])
    side_h = bool(component_side and harmonic_side and component_side == harmonic_side)
    side_g = bool(component_side and operating_side and component_side == operating_side)
    cfreq = float(hrow["component_test_frequency_hz"])
    hfreq = float(irow["fundamental_frequency_hz"])
    freq_ok = bool(math.isfinite(cfreq) and math.isfinite(hfreq) and cfreq == hfreq)
    applicable = bool(
        applicability == "declared_representative_normalized_spectrum" or application is not None
    )
    record.update(
        {
            "s12g_operating_row_present": grow is not None,
            "s12g_terminal_operating_solution_resolved": g_ok,
            "transformer_energised": grow["transformer_energised"] if grow is not None else "",
            "s12h_advanced_loss_basis_resolved": h_ok,
            "s12i_harmonic_characterisation_resolved": i_ok,
            "s12j_thermal_row_present": jrow is not None,
            "s12j_load_loss_temperature_basis_resolved": j_ok,
            "component_reference_side": component_side,
            "harmonic_reference_side": harmonic_side,
            "operating_series_reference_side": operating_side,
            "harmonic_reference_side_compatible": side_h,
            "operating_current_reference_side_compatible": side_g,
            "component_reference_frequency_hz": cfreq,
            "harmonic_fundamental_frequency_hz": hfreq,
            "harmonic_frequency_compatible": freq_ok,
            "harmonic_spectrum_applicability_semantics": applicability,
            "single_condition_harmonic_application_present": application is not None,
            "harmonic_spectrum_applicable_at_timestamp": applicable,
            "single_condition_operating_condition_match_basis": (
                application.operating_condition_match_basis
            )
            if application
            else "",
            "single_condition_parameter_source": application.parameter_source
            if application
            else "",
            "single_condition_confidence": application.confidence if application else "",
            "winding_conductor_material": construction.winding_conductor_material
            if construction
            else "",
            "component_reference_temperature_c": float(hrow["component_reference_temperature_c"]),
            "average_winding_temperature_c": float(jrow["average_winding_temperature_c"])
            if jrow is not None
            else math.nan,
            "i2r_loss_reference_w": float(hrow["i2r_loss_reference_w"]),
            "winding_eddy_current_loss_reference_w": float(
                hrow["winding_eddy_current_loss_reference_w"]
            ),
            "other_stray_loss_reference_w": float(hrow["canonical_other_stray_loss_reference_w"]),
            "factory_total_rated_load_loss_w": float(hrow["s12b_rated_load_loss_w"]),
            "sum_current_ratio_squared": float(irow["sum_current_ratio_squared"]),
            "total_rms_to_fundamental_current_ratio": float(
                irow["total_rms_current_to_fundamental_ratio"]
            ),
            "current_thd_ratio": float(irow["current_thd_ratio"]),
            "current_thd_percent": float(irow["current_thd_percent"]),
            "winding_eddy_harmonic_loss_factor": float(irow["winding_eddy_harmonic_loss_factor"]),
            "other_stray_harmonic_loss_factor": float(irow["other_stray_harmonic_loss_factor"]),
        }
    )
    if custom:
        record.update(
            {
                "resistance_temperature_constant_c": custom.resistance_temperature_constant_c,
                "resistance_temperature_constant_source_mode": "explicit_authority",
                "resistance_temperature_constant_parameter_source": custom.parameter_source,
                "resistance_temperature_constant_confidence": custom.confidence,
            }
        )
    if grow is None:
        state = _STATES[0]
    elif not g_ok and not deenergised:
        state = _STATES[1]
    elif deenergised:
        zero_names = [
            name
            for name in _FLOAT_COLUMNS
            if any(
                token in name
                for token in (
                    "operating_current",
                    "loading_ratio",
                    "loss_fundamental",
                    "harmonic_increment",
                    "loss_corrected_total",
                    "load_loss_w",
                    "correction_effect",
                    "advanced_correction",
                )
            )
        ]
        for name in zero_names:
            record[name] = 0.0
        record["s12g_reference_load_loss_w"] = 0.0
        record["reconstructed_reference_sinusoidal_load_loss_w"] = 0.0
        record["s12g_reference_load_loss_closure_residual_w"] = 0.0
        state = _STATES[2]
    elif not h_ok:
        state = _STATES[3]
    elif not i_ok:
        state = _STATES[4]
    elif not side_h:
        state = _STATES[5]
    elif not side_g:
        state = _STATES[6]
    elif not freq_ok:
        state = _STATES[7]
    elif not applicable:
        state = _STATES[8]
    elif jrow is None:
        state = _STATES[9]
    elif not j_ok:
        state = _STATES[10]
    else:
        material = construction.winding_conductor_material
        tref = float(hrow["component_reference_temperature_c"])
        tw = float(jrow["average_winding_temperature_c"])
        tk: float | None
        mode: str
        if tw == tref and custom is None:
            tk, mode = None, "not_required_equal_reference_temperature"
            kr = 1.0
        elif custom is not None:
            if custom.applicable_conductor_material != material:
                raise ValueError("temperature constant material does not match S12H construction")
            tk, mode = custom.resistance_temperature_constant_c, "explicit_authority"
            kr = (tw + tk) / (tref + tk) if tref + tk > 0 and tw + tk > 0 else math.nan
        elif material == "copper":
            tk, mode = 234.5, "standard_copper_234p5_c"
            kr = (tw + tk) / (tref + tk) if tref + tk > 0 and tw + tk > 0 else math.nan
        elif material == "aluminium":
            tk, mode = 225.0, "standard_aluminium_225_c"
            kr = (tw + tk) / (tref + tk) if tref + tk > 0 and tw + tk > 0 else math.nan
        else:
            tk, mode, kr = None, "unresolved", math.nan
        record["resistance_temperature_constant_source_mode"] = mode
        if tk is not None:
            record["resistance_temperature_constant_c"] = tk
        if material == "mixed_or_other_explicit" and tk is None and tw != tref:
            state = _STATES[11]
        elif not math.isfinite(kr) or kr <= 0.0:
            state = _STATES[12]
        else:
            try:
                rated_v = (
                    equipment.collection_side_rated_line_to_line_rms_v
                    if component_side == "collection_side"
                    else equipment.network_side_rated_line_to_line_rms_v
                )
                irated = equipment.rated_apparent_power_va / (math.sqrt(3.0) * rated_v)
                i1 = float(
                    grow["collection_series_current_magnitude_a"]
                    if component_side == "collection_side"
                    else grow["network_series_current_magnitude_a"]
                )
                beta1 = i1 / irated
                rms_factor = float(irow["total_rms_current_to_fundamental_ratio"])
                beta_rms = beta1 * rms_factor
                total_i = i1 * rms_factor
                pr = float(hrow["i2r_loss_reference_w"])
                pec = float(hrow["winding_eddy_current_loss_reference_w"])
                posl = float(hrow["canonical_other_stray_loss_reference_w"])
                fec = float(irow["winding_eddy_harmonic_loss_factor"])
                fosl = float(irow["other_stray_harmonic_loss_factor"])
                b1sq = beta1 * beta1
                brsq = beta_rms * beta_rms
                inv = 1.0 / kr
                i2r_f = b1sq * pr * kr
                ec_f = b1sq * pec * inv
                osl_f = b1sq * posl * inv
                i2r_t = brsq * pr * kr
                ec_t = brsq * pec * fec * inv
                osl_t = brsq * posl * fosl * inv
                i2r_h = i2r_t - i2r_f
                ec_h = ec_t - ec_f
                osl_h = osl_t - osl_f
                reference = b1sq * math.fsum([pr, pec, posl])
                baseline = float(grow["p_series_active_loss_w"])
                closure = reference - baseline
                temp_total = math.fsum([i2r_f, ec_f, osl_f])
                advanced = math.fsum([i2r_t, ec_t, osl_t])
                temp_effect = temp_total - reference
                harmonic = advanced - temp_total
                correction = advanced - baseline
                decomposition = temp_effect + harmonic - correction
                rref = pr / (3.0 * irated * irated)
                rt = rref * kr
                numbers = [
                    irated,
                    i1,
                    beta1,
                    beta_rms,
                    total_i,
                    kr,
                    inv,
                    i2r_f,
                    ec_f,
                    osl_f,
                    i2r_t,
                    ec_t,
                    osl_t,
                    i2r_h,
                    ec_h,
                    osl_h,
                    reference,
                    baseline,
                    closure,
                    temp_total,
                    advanced,
                    temp_effect,
                    harmonic,
                    correction,
                    decomposition,
                    rref,
                    rt,
                ]
            except (OverflowError, ValueError, ZeroDivisionError):
                numbers = [math.nan]
            if not _finite(numbers):
                state = _STATES[14]
            else:
                record.update(
                    {
                        "fundamental_operating_current_a": i1,
                        "rated_reference_side_current_a": irated,
                        "fundamental_current_loading_ratio": beta1,
                        "total_rms_operating_current_a": total_i,
                        "total_rms_current_loading_ratio": beta_rms,
                        "i2r_temperature_correction_factor": kr,
                        "winding_eddy_temperature_correction_factor": inv,
                        "other_stray_temperature_correction_factor": inv,
                        "other_stray_structural_temperature_proxy_applied": True,
                        "effective_winding_ohmic_resistance_reference_ohm_per_phase": rref,
                        "effective_winding_ohmic_resistance_temperature_corrected_ohm_per_phase": (
                            rt
                        ),
                        "i2r_loss_fundamental_temperature_corrected_w": i2r_f,
                        "i2r_loss_harmonic_increment_w": i2r_h,
                        "i2r_loss_corrected_total_w": i2r_t,
                        "winding_eddy_loss_fundamental_temperature_corrected_w": ec_f,
                        "winding_eddy_loss_harmonic_increment_w": ec_h,
                        "winding_eddy_loss_corrected_total_w": ec_t,
                        "other_stray_loss_fundamental_temperature_corrected_w": osl_f,
                        "other_stray_loss_harmonic_increment_w": osl_h,
                        "other_stray_loss_corrected_total_w": osl_t,
                        "reconstructed_reference_sinusoidal_load_loss_w": reference,
                        "s12g_reference_load_loss_w": baseline,
                        "s12g_reference_load_loss_closure_residual_w": closure,
                        "temperature_corrected_sinusoidal_load_loss_w": temp_total,
                        "temperature_correction_effect_w": temp_effect,
                        "harmonic_incremental_load_loss_w": harmonic,
                        "harmonic_and_temperature_corrected_load_loss_w": advanced,
                        "advanced_correction_vs_s12g_w": correction,
                        "advanced_correction_decomposition_residual_w": decomposition,
                    }
                )
                state = (
                    _STATES[13]
                    if not math.isclose(reference, baseline, rel_tol=_REL_TOL, abs_tol=_ABS_TOL_W)
                    else _STATES[15]
                )
    record["transformer_corrected_load_loss_state"] = state
    return record


def _frame(keys: list[tuple[pd.Timestamp, str]], records: list[dict[str, object]]) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(keys, names=["timestamp", "transformer_id"])
    frame = pd.DataFrame(records, index=index, columns=_COLUMNS)
    for name in _BOOL_COLUMNS:
        frame[name] = frame[name].astype(bool)
    for name in _FLOAT_COLUMNS:
        frame[name] = frame[name].astype("float64")
    for name in set(_COLUMNS) - _BOOL_COLUMNS - _FLOAT_COLUMNS:
        frame[name] = frame[name].astype(object)
    return frame


def _diagnostics(
    frame: pd.DataFrame, transformers: int, timestamps: int
) -> TopologyTransformerCorrectedLoadLossDiagnostics:
    state = frame["transformer_corrected_load_loss_state"]
    modes = frame["resistance_temperature_constant_source_mode"]

    def count(column: str) -> int:
        return int(frame[column].sum())

    return TopologyTransformerCorrectedLoadLossDiagnostics(
        transformers,
        timestamps,
        len(frame),
        count("s12g_operating_row_present"),
        count("s12g_terminal_operating_solution_resolved"),
        int((state == _STATES[2]).sum()),
        count("s12h_advanced_loss_basis_resolved"),
        count("s12i_harmonic_characterisation_resolved"),
        count("s12j_load_loss_temperature_basis_resolved"),
        int(
            (
                ~frame["harmonic_reference_side_compatible"]
                & frame["s12h_advanced_loss_basis_resolved"]
                & frame["s12i_harmonic_characterisation_resolved"]
            ).sum()
        ),
        int(
            (
                ~frame["operating_current_reference_side_compatible"]
                & frame["s12h_advanced_loss_basis_resolved"]
                & frame["s12g_operating_row_present"]
            ).sum()
        ),
        int(
            (
                ~frame["harmonic_frequency_compatible"]
                & frame["s12h_advanced_loss_basis_resolved"]
                & frame["s12i_harmonic_characterisation_resolved"]
            ).sum()
        ),
        int(
            (
                frame["harmonic_spectrum_applicability_semantics"]
                == "single_declared_operating_condition"
            ).sum()
        ),
        int(
            (
                (
                    frame["harmonic_spectrum_applicability_semantics"]
                    == "single_declared_operating_condition"
                )
                & ~frame["single_condition_harmonic_application_present"]
            ).sum()
        ),
        int((modes == "standard_copper_234p5_c").sum()),
        int((modes == "standard_aluminium_225_c").sum()),
        int((modes == "explicit_authority").sum()),
        int((state == _STATES[11]).sum()),
        int((state == _STATES[12]).sum()),
        int((state == _STATES[13]).sum()),
        int((state == _STATES[14]).sum()),
        int((state == _STATES[15]).sum()),
        int((frame["temperature_correction_effect_w"] > 0).sum()),
        int((frame["temperature_correction_effect_w"] < 0).sum()),
        int((frame["harmonic_incremental_load_loss_w"] > 0).sum()),
        tuple((name, int((state == name).sum())) for name in _STATES),
        TRANSFORMER_CORRECTED_LOAD_LOSS_MODEL_ID,
    )


def calculate_topology_transformer_corrected_load_loss(
    **values: Any,
) -> TopologyTransformerCorrectedLoadLossResult:
    """Replay S12G/H/I/J and calculate corrected component load-loss watts."""
    parents = _canonical_parents(values)
    _g, h, _i, j = parents
    ids = h.transformer_states.index.tolist()
    known = set(ids)
    constants = _admit_mapping(
        values.get("winding_temperature_constant_by_transformer_id", {}), known
    )
    for identifier, authority in constants.items():
        construction = h.construction_by_id.get(identifier)
        if (
            construction
            and authority.applicable_conductor_material != construction.winding_conductor_material
        ):
            raise ValueError("temperature constant material does not match S12H construction")
    applications, app_times = _admit_applications(
        values.get("single_condition_harmonic_application_by_key", {}), known
    )
    g_times = list(
        dict.fromkeys(_g.transformer_operating_states.index.get_level_values("timestamp"))
    )
    j_times = list(dict.fromkeys(j.states.index.get_level_values("timestamp")))
    times = _timestamps(g_times, j_times, app_times)
    keys = [(timestamp, identifier) for timestamp in times for identifier in ids]
    equipment = values["transformer_equipment_by_id"]
    records = [_record(t, i, parents, equipment.get(i), constants, applications) for t, i in keys]
    frame = _frame(keys, records)
    result = TopologyTransformerCorrectedLoadLossResult(
        MappingProxyType(dict(applications)),
        MappingProxyType(dict(constants)),
        frame.copy(deep=True),
        _diagnostics(frame, len(ids), len(times)),
    )
    _validate_result(parents, equipment, constants, applications, times, result)
    return result


def _validate_result(
    parents: tuple[Any, Any, Any, Any],
    equipment: Mapping[str, Any],
    constants: Mapping[str, Any],
    applications: Mapping[tuple[pd.Timestamp, str], Any],
    timestamps: list[pd.Timestamp],
    result: TopologyTransformerCorrectedLoadLossResult,
) -> None:
    """Independently reconstruct the complete public S12K result contract."""
    if type(result) is not TopologyTransformerCorrectedLoadLossResult:
        raise ValueError("S12K result type is invalid")
    if type(result.single_condition_harmonic_application_by_key) is not MappingProxyType or tuple(
        result.single_condition_harmonic_application_by_key.items()
    ) != tuple(applications.items()):
        raise ValueError("S12K harmonic application mapping failed validation")
    if type(result.winding_temperature_constant_by_transformer_id) is not MappingProxyType or tuple(
        result.winding_temperature_constant_by_transformer_id.items()
    ) != tuple(constants.items()):
        raise ValueError("S12K temperature constant mapping failed validation")
    ids = parents[1].transformer_states.index.tolist()
    keys = [(timestamp, identifier) for timestamp in timestamps for identifier in ids]
    # This separate reconstruction never consumes the submitted frame or diagnostics.
    expected_records = [
        _record(t, i, parents, equipment.get(i), constants, applications) for t, i in keys
    ]
    expected = _frame(keys, expected_records)
    try:
        pd.testing.assert_frame_equal(result.states, expected, check_exact=True)
    except AssertionError as error:
        raise ValueError("S12K result frame failed independent validation") from error
    diagnostics = _diagnostics(expected, len(ids), len(timestamps))
    if result.diagnostics != diagnostics:
        raise ValueError("S12K diagnostics failed independent validation")
