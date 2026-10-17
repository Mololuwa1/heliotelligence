"""Voltage/frequency-dependent transformer active no-load/core-loss physics.

S12B factory P_NL is the anchor.  S12L's selected loss replaces S12G's fixed
sink later in S12M; it is never additive.  The normalized empirical
Steinmetz-type law uses explicit authority only: B/B_ref comes from V/f because
turns and core geometry are not authoritative.  It is never extrapolated.
Missing optional evidence falls back to P_NL, while contradictory evidence is
unresolved.  Voltage harmonics, saturation, excitation Q and core temperature
are not modelled.  S12M owns final voltage/loss coupling.
"""

from __future__ import annotations

import cmath
import inspect
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from numbers import Real
from types import MappingProxyType
from typing import Any, Literal, TypeVar

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.physics.transformer_authority import (
    TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
    resolve_transformer_static_authority,
)
from heliotelligence.physics.transformer_loss_authority import (
    TRANSFORMER_LOSS_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_LOSS_AUTHORITY_MODEL_ID,
    resolve_transformer_loss_authority,
)
from heliotelligence.physics.transformer_operating_solution import (
    TRANSFORMER_OPERATING_SOLUTION_CONTRACT_ID,
    TRANSFORMER_OPERATING_SOLUTION_MODEL_ID,
    calculate_topology_transformer_operating_solution,
)

TRANSFORMER_CORE_NO_LOAD_LOSS_CONTRACT_ID = (
    "admitted_transformer_factory_no_load_operating_voltage_frequency_"
    "and_core_scaling_authorities_to_corrected_no_load_loss_v1"
)
TRANSFORMER_CORE_NO_LOAD_LOSS_MODEL_ID = (
    "balanced_three_phase_sinusoidal_normalized_steinmetz_core_loss_"
    "scaling_with_factory_no_load_residual_v1"
)
TRANSFORMER_CORE_NO_LOAD_LOSS_SCOPE = (
    "timestamped_transformer_active_no_load_core_loss_correction_before_"
    "advanced_terminal_reconciliation"
)
TRANSFORMER_CORE_NO_LOAD_LOSS_COVERAGE_SCOPE = (
    "resolved_transformer_operating_states_with_factory_no_load_loss_"
    "and_optional_empirical_voltage_frequency_core_loss_scaling"
)
OPERATING_CORE_VOLTAGE_BASIS = "s12g_baseline_internal_ideal_transformer_excitation_voltage"
CORRECTED_NO_LOAD_LOSS_OWNERSHIP = (
    "replacement_for_s12g_fixed_factory_no_load_active_sink_not_additive"
)
S12K_LOAD_LOSS_TREATMENT = "independent_advanced_load_loss_not_consumed_by_s12l"
SCALING_SEMANTICS = (
    "normalized_steinmetz_total_core_loss_power_law_around_s12b_factory_reference_condition"
)
RESIDUAL_SEMANTICS = "s12b_no_load_loss_minus_scalable_core_loss_held_constant"
REFERENCE_WAVEFORM_BASIS = "s12b_factory_no_load_loss_sine_wave_corrected_or_equivalent"
OPERATING_WAVEFORM_BASIS = "s12g_positive_sequence_fundamental_sinusoidal_equivalent"

Confidence = Literal["high", "medium", "low", "unknown"]
FrequencyEvidence = Literal[
    "direct_power_quality_measurement",
    "scada_grid_frequency",
    "documented_external_frequency_state",
    "declared_nominal_frequency_for_timestamp",
]
_CONFIDENCES = {"high", "medium", "low", "unknown"}
_FREQUENCY_EVIDENCE = {
    "direct_power_quality_measurement",
    "scada_grid_frequency",
    "documented_external_frequency_state",
    "declared_nominal_frequency_for_timestamp",
}
_VOLT_REL_TOL = 1e-9
_VOLT_ABS_TOL = 1e-8
_LOSS_REL_TOL = 1e-12
_STATES = (
    "unresolved_missing_s12g_transformer_operating_state",
    "unresolved_upstream_s12g_transformer_operating_solution",
    "resolved_deenergised_transformer_zero_no_load_loss",
    "unresolved_missing_s12b_no_load_loss_authority",
    "unresolved_s12g_factory_no_load_loss_closure_mismatch",
    "unresolved_s12g_internal_excitation_voltage_closure_mismatch",
    "resolved_factory_reference_no_load_loss_fallback_missing_core_scaling_authority",
    "unresolved_core_scaling_reference_loss_exceeds_s12b_no_load_loss",
    "resolved_factory_reference_no_load_loss_fallback_missing_operating_frequency",
    "unresolved_nonpositive_operating_core_excitation_voltage",
    "resolved_factory_reference_no_load_loss_fallback_outside_core_scaling_domain",
    "unresolved_nonfinite_corrected_no_load_core_loss",
    "resolved_voltage_frequency_corrected_transformer_no_load_core_loss",
)


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be an exact non-empty string without padding")
    return value


def _finite(
    value: object, name: str, *, positive: bool = False, nonnegative: bool = False
) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be real and non-Boolean")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if positive and result <= 0.0:
        raise ValueError(f"{name} must be strictly positive")
    if nonnegative and result < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return result


def _confidence(value: object) -> str:
    if type(value) is not str or value not in _CONFIDENCES:
        raise ValueError("confidence is unsupported")
    return value


@dataclass(frozen=True)
class TransformerOperatingFrequencyState:
    frequency_hz: float
    evidence_kind: FrequencyEvidence
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "frequency_hz", _finite(self.frequency_hz, "frequency_hz", positive=True)
        )
        if self.evidence_kind not in _FREQUENCY_EVIDENCE:
            raise ValueError("evidence_kind is unsupported")
        _text(self.parameter_source, "parameter_source")
        _confidence(self.confidence)


@dataclass(frozen=True)
class TransformerNormalizedCoreLossScalingAuthority:
    transformer_id: str
    scalable_core_loss_reference_w: float
    steinmetz_frequency_exponent_alpha: float
    steinmetz_flux_density_exponent_beta: float
    minimum_frequency_ratio_to_reference: float
    maximum_frequency_ratio_to_reference: float
    minimum_flux_density_ratio_to_reference: float
    maximum_flux_density_ratio_to_reference: float
    reference_no_load_loss_waveform_basis: Literal[
        "s12b_factory_no_load_loss_sine_wave_corrected_or_equivalent"
    ]
    operating_voltage_waveform_basis: Literal[
        "s12g_positive_sequence_fundamental_sinusoidal_equivalent"
    ]
    scaling_semantics: Literal[
        "normalized_steinmetz_total_core_loss_power_law_around_s12b_factory_reference_condition"
    ]
    non_scaling_residual_semantics: Literal[
        "s12b_no_load_loss_minus_scalable_core_loss_held_constant"
    ]
    model_parameter_source: str
    model_fit_or_applicability_description: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _text(self.transformer_id, "transformer_id")
        object.__setattr__(
            self,
            "scalable_core_loss_reference_w",
            _finite(
                self.scalable_core_loss_reference_w,
                "scalable_core_loss_reference_w",
                nonnegative=True,
            ),
        )
        for name in (
            "steinmetz_frequency_exponent_alpha",
            "steinmetz_flux_density_exponent_beta",
            "minimum_frequency_ratio_to_reference",
            "maximum_frequency_ratio_to_reference",
            "minimum_flux_density_ratio_to_reference",
            "maximum_flux_density_ratio_to_reference",
        ):
            object.__setattr__(self, name, _finite(getattr(self, name), name, positive=True))
        if self.minimum_frequency_ratio_to_reference > self.maximum_frequency_ratio_to_reference:
            raise ValueError("frequency ratio minimum exceeds maximum")
        if (
            self.minimum_flux_density_ratio_to_reference
            > self.maximum_flux_density_ratio_to_reference
        ):
            raise ValueError("flux-density ratio minimum exceeds maximum")
        if (
            not self.minimum_frequency_ratio_to_reference
            <= 1.0
            <= self.maximum_frequency_ratio_to_reference
        ):
            raise ValueError("frequency ratio domain must include 1.0")
        if (
            not self.minimum_flux_density_ratio_to_reference
            <= 1.0
            <= self.maximum_flux_density_ratio_to_reference
        ):
            raise ValueError("flux-density ratio domain must include 1.0")
        if self.reference_no_load_loss_waveform_basis != REFERENCE_WAVEFORM_BASIS:
            raise ValueError("reference waveform basis is unsupported")
        if self.operating_voltage_waveform_basis != OPERATING_WAVEFORM_BASIS:
            raise ValueError("operating waveform basis is unsupported")
        if self.scaling_semantics != SCALING_SEMANTICS:
            raise ValueError("scaling_semantics is unsupported")
        if self.non_scaling_residual_semantics != RESIDUAL_SEMANTICS:
            raise ValueError("non_scaling_residual_semantics is unsupported")
        _text(self.model_parameter_source, "model_parameter_source")
        _text(self.model_fit_or_applicability_description, "model_fit_or_applicability_description")
        _confidence(self.confidence)


@dataclass(frozen=True)
class TopologyTransformerCoreNoLoadLossDiagnostics:
    transformer_count: int
    timestamp_count: int
    row_count: int
    s12g_row_present_count: int
    s12g_operating_solution_resolved_count: int
    resolved_deenergised_zero_loss_count: int
    s12b_no_load_authority_present_count: int
    core_scaling_authority_present_count: int
    operating_frequency_present_count: int
    factory_fallback_missing_scaling_count: int
    factory_fallback_missing_frequency_count: int
    factory_fallback_outside_domain_count: int
    scaling_reference_loss_incompatible_count: int
    s12g_no_load_closure_mismatch_count: int
    internal_excitation_voltage_closure_mismatch_count: int
    nonpositive_core_excitation_voltage_count: int
    nonfinite_count: int
    advanced_scaling_resolved_count: int
    no_load_output_resolved_count: int
    positive_no_load_correction_count: int
    negative_no_load_correction_count: int
    state_counts: tuple[tuple[str, int], ...]
    model: str


@dataclass(frozen=True)
class TopologyTransformerCoreNoLoadLossResult:
    operating_frequency_by_key: Mapping[
        tuple[pd.Timestamp, str], TransformerOperatingFrequencyState
    ]
    core_loss_scaling_by_id: Mapping[str, TransformerNormalizedCoreLossScalingAuthority]
    states: pd.DataFrame
    diagnostics: TopologyTransformerCoreNoLoadLossDiagnostics


_BOOL_COLUMNS = {
    "s12g_operating_row_present",
    "s12g_terminal_operating_solution_resolved",
    "s12b_no_load_loss_authority_present",
    "operating_frequency_state_present",
    "core_loss_scaling_authority_present",
    "reference_component_closure_roundoff_adjusted",
    "transformer_no_load_loss_output_resolved",
    "advanced_core_loss_scaling_resolved",
    "voltage_frequency_core_loss_correction_applied",
    "operating_voltage_harmonic_correction_applied",
    "saturation_or_nonlinear_bh_modeled",
    "excitation_no_load_q_modeled",
    "core_temperature_correction_applied",
}
_NULLABLE_BOOL_COLUMNS = {"transformer_energised"}
_FLOAT_COLUMNS = {
    "s12b_factory_no_load_loss_w",
    "no_load_test_frequency_hz",
    "factory_reference_core_excitation_voltage_ll_rms_v",
    "s12g_reference_no_load_loss_w",
    "s12g_factory_no_load_loss_closure_residual_w",
    "baseline_internal_collection_excitation_voltage_ll_rms_v",
    "baseline_internal_network_excitation_voltage_ll_rms_v",
    "baseline_internal_network_excitation_closure_residual_v",
    "operating_core_excitation_voltage_ll_rms_v",
    "operating_frequency_hz",
    "scalable_core_loss_reference_w",
    "non_scaling_no_load_loss_reference_residual_w",
    "reference_component_closure_residual_w",
    "steinmetz_frequency_exponent_alpha",
    "steinmetz_flux_density_exponent_beta",
    "minimum_frequency_ratio_to_reference",
    "maximum_frequency_ratio_to_reference",
    "minimum_flux_density_ratio_to_reference",
    "maximum_flux_density_ratio_to_reference",
    "operating_voltage_ratio_to_factory_reference",
    "operating_frequency_ratio_to_factory_reference",
    "core_flux_density_ratio_to_factory_reference",
    "core_loss_scaling_multiplier",
    "scalable_core_loss_operating_w",
    "non_scaling_no_load_loss_operating_w",
    "voltage_frequency_corrected_no_load_loss_w",
    "corrected_no_load_loss_w",
    "advanced_no_load_correction_vs_s12g_w",
}
_COLUMNS = (
    "s12g_operating_row_present",
    "s12g_terminal_operating_solution_resolved",
    "transformer_energised",
    "s12b_no_load_loss_authority_present",
    "operating_frequency_state_present",
    "core_loss_scaling_authority_present",
    "no_load_test_reference_side",
    "s12b_factory_no_load_loss_w",
    "no_load_test_frequency_hz",
    "factory_reference_core_excitation_voltage_ll_rms_v",
    "no_load_parameter_source",
    "no_load_confidence",
    "s12g_reference_no_load_loss_w",
    "s12g_factory_no_load_loss_closure_residual_w",
    "s12g_series_equivalent_reference_side",
    "baseline_internal_collection_excitation_voltage_ll_rms_v",
    "baseline_internal_network_excitation_voltage_ll_rms_v",
    "baseline_internal_network_excitation_closure_residual_v",
    "operating_core_excitation_voltage_ll_rms_v",
    "operating_core_voltage_basis",
    "operating_frequency_hz",
    "operating_frequency_evidence_kind",
    "operating_frequency_parameter_source",
    "operating_frequency_confidence",
    "scalable_core_loss_reference_w",
    "non_scaling_no_load_loss_reference_residual_w",
    "reference_component_closure_residual_w",
    "reference_component_closure_roundoff_adjusted",
    "steinmetz_frequency_exponent_alpha",
    "steinmetz_flux_density_exponent_beta",
    "minimum_frequency_ratio_to_reference",
    "maximum_frequency_ratio_to_reference",
    "minimum_flux_density_ratio_to_reference",
    "maximum_flux_density_ratio_to_reference",
    "reference_no_load_loss_waveform_basis",
    "operating_voltage_waveform_basis",
    "core_loss_scaling_semantics",
    "non_scaling_residual_semantics",
    "core_loss_model_parameter_source",
    "core_loss_model_fit_or_applicability_description",
    "core_loss_model_confidence",
    "operating_voltage_ratio_to_factory_reference",
    "operating_frequency_ratio_to_factory_reference",
    "core_flux_density_ratio_to_factory_reference",
    "core_loss_scaling_multiplier",
    "scalable_core_loss_operating_w",
    "non_scaling_no_load_loss_operating_w",
    "voltage_frequency_corrected_no_load_loss_w",
    "corrected_no_load_loss_w",
    "advanced_no_load_correction_vs_s12g_w",
    "transformer_no_load_loss_output_resolved",
    "advanced_core_loss_scaling_resolved",
    "voltage_frequency_core_loss_correction_applied",
    "operating_voltage_harmonic_correction_applied",
    "saturation_or_nonlinear_bh_modeled",
    "excitation_no_load_q_modeled",
    "core_temperature_correction_applied",
    "corrected_no_load_loss_ownership",
    "s12k_load_loss_treatment",
    "transformer_core_no_load_loss_state",
    "transformer_static_authority_contract",
    "transformer_static_authority_model",
    "transformer_loss_authority_contract",
    "transformer_loss_authority_model",
    "transformer_operating_solution_contract",
    "transformer_operating_solution_model",
    "transformer_core_no_load_loss_contract",
    "transformer_core_no_load_loss_model",
    "transformer_core_no_load_loss_scope",
    "transformer_core_no_load_loss_coverage_scope",
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


def _canonical_parents(values: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    a = _call(resolve_transformer_static_authority, values)
    _exact_replay("S12A", values["transformer_static_authority"], a)
    b_values = dict(values)
    b_values["transformer_static_authority"] = a
    b = _call(resolve_transformer_loss_authority, b_values)
    _exact_replay("S12B", values["transformer_loss_authority"], b)
    g = _call(calculate_topology_transformer_operating_solution, values)
    _exact_replay("S12G", values["transformer_operating_solution"], g)
    return a, b, g


def _admit_frequency(
    supplied: object, known: set[str]
) -> tuple[dict[tuple[pd.Timestamp, str], TransformerOperatingFrequencyState], list[pd.Timestamp]]:
    if not isinstance(supplied, Mapping):
        raise TypeError("operating frequency authority must be a mapping")
    copied: dict[tuple[pd.Timestamp, str], TransformerOperatingFrequencyState] = {}
    times: set[pd.Timestamp] = set()
    for key, state in supplied.items():
        if type(key) is not tuple or len(key) != 2:
            raise ValueError("operating frequency key must be an exact two-item tuple")
        timestamp, identifier = key
        if type(timestamp) is not pd.Timestamp or pd.isna(timestamp):
            raise ValueError("operating frequency timestamp must be exact non-NaT pd.Timestamp")
        _text(identifier, "transformer_id")
        if identifier not in known:
            raise ValueError("operating frequency references unknown transformer")
        if type(state) is not TransformerOperatingFrequencyState:
            raise TypeError("operating frequency mapping has invalid value type")
        copied[(timestamp, identifier)] = state
        times.add(timestamp)
    try:
        ordered_times = sorted(times)
    except TypeError as error:
        raise ValueError(
            "transformer core-loss timestamps have incompatible timezone semantics"
        ) from error
    return dict(
        sorted(copied.items(), key=lambda item: (ordered_times.index(item[0][0]), item[0][1]))
    ), ordered_times


def _admit_scaling(
    supplied: object, known: set[str]
) -> dict[str, TransformerNormalizedCoreLossScalingAuthority]:
    if not isinstance(supplied, Mapping):
        raise TypeError("core loss scaling authority must be a mapping")
    copied: dict[str, TransformerNormalizedCoreLossScalingAuthority] = {}
    for key, authority in supplied.items():
        _text(key, "transformer_id")
        if key not in known:
            raise ValueError("core loss scaling references unknown transformer")
        if type(authority) is not TransformerNormalizedCoreLossScalingAuthority:
            raise TypeError("core loss scaling mapping has invalid value type")
        if key != authority.transformer_id:
            raise ValueError("core loss scaling mapping key must match transformer_id")
        copied[key] = authority
    return dict(sorted(copied.items()))


def _timestamps(*groups: list[pd.Timestamp]) -> list[pd.Timestamp]:
    try:
        return sorted(set().union(*map(set, groups)))
    except TypeError as error:
        raise ValueError(
            "transformer core-loss timestamps have incompatible timezone semantics"
        ) from error


def _base_record() -> dict[str, object]:
    record: dict[str, object] = {name: None for name in _COLUMNS}
    for name in _BOOL_COLUMNS:
        record[name] = False
    for name in _FLOAT_COLUMNS:
        record[name] = math.nan
    record["transformer_energised"] = pd.NA
    record.update(
        {
            "operating_core_voltage_basis": OPERATING_CORE_VOLTAGE_BASIS,
            "corrected_no_load_loss_ownership": CORRECTED_NO_LOAD_LOSS_OWNERSHIP,
            "s12k_load_loss_treatment": S12K_LOAD_LOSS_TREATMENT,
            "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
            "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
            "transformer_loss_authority_contract": TRANSFORMER_LOSS_AUTHORITY_CONTRACT_ID,
            "transformer_loss_authority_model": TRANSFORMER_LOSS_AUTHORITY_MODEL_ID,
            "transformer_operating_solution_contract": TRANSFORMER_OPERATING_SOLUTION_CONTRACT_ID,
            "transformer_operating_solution_model": TRANSFORMER_OPERATING_SOLUTION_MODEL_ID,
            "transformer_core_no_load_loss_contract": TRANSFORMER_CORE_NO_LOAD_LOSS_CONTRACT_ID,
            "transformer_core_no_load_loss_model": TRANSFORMER_CORE_NO_LOAD_LOSS_MODEL_ID,
            "transformer_core_no_load_loss_scope": TRANSFORMER_CORE_NO_LOAD_LOSS_SCOPE,
            "transformer_core_no_load_loss_coverage_scope": (
                TRANSFORMER_CORE_NO_LOAD_LOSS_COVERAGE_SCOPE
            ),
        }
    )
    return record


def _record(
    timestamp: pd.Timestamp,
    identifier: str,
    parents: tuple[Any, Any, Any],
    equipment: Any,
    frequencies: Mapping[tuple[pd.Timestamp, str], TransformerOperatingFrequencyState],
    scaling: Mapping[str, TransformerNormalizedCoreLossScalingAuthority],
) -> dict[str, object]:
    _a, b, g = parents
    record = _base_record()
    key = (timestamp, identifier)
    g_row = (
        g.transformer_operating_states.loc[key]
        if key in g.transformer_operating_states.index
        else None
    )
    no_load = b.no_load_loss_by_id.get(identifier)
    frequency = frequencies.get(key)
    model = scaling.get(identifier)
    g_resolved = bool(
        g_row is not None and g_row["transformer_terminal_operating_solution_resolved"]
    )
    deenergised = bool(
        g_row is not None
        and g_row["transformer_operating_solution_state"]
        == "resolved_deenergised_transformer_no_transfer"
    )
    record.update(
        {
            "s12g_operating_row_present": g_row is not None,
            "s12g_terminal_operating_solution_resolved": g_resolved,
            "transformer_energised": pd.NA if g_row is None else g_row["transformer_energised"],
            "s12b_no_load_loss_authority_present": no_load is not None,
            "operating_frequency_state_present": frequency is not None,
            "core_loss_scaling_authority_present": model is not None,
        }
    )
    if no_load is not None:
        reference_voltage = (
            equipment.collection_side_rated_line_to_line_rms_v
            if no_load.test_reference_side == "collection_side"
            else equipment.network_side_rated_line_to_line_rms_v
        )
        record.update(
            {
                "no_load_test_reference_side": no_load.test_reference_side,
                "s12b_factory_no_load_loss_w": no_load.no_load_loss_w,
                "no_load_test_frequency_hz": no_load.test_frequency_hz,
                "factory_reference_core_excitation_voltage_ll_rms_v": reference_voltage,
                "no_load_parameter_source": no_load.parameter_source,
                "no_load_confidence": no_load.confidence,
            }
        )
    if frequency is not None:
        record.update(
            {
                "operating_frequency_hz": frequency.frequency_hz,
                "operating_frequency_evidence_kind": frequency.evidence_kind,
                "operating_frequency_parameter_source": frequency.parameter_source,
                "operating_frequency_confidence": frequency.confidence,
            }
        )
    if model is not None:
        record.update(
            {
                "scalable_core_loss_reference_w": model.scalable_core_loss_reference_w,
                "steinmetz_frequency_exponent_alpha": model.steinmetz_frequency_exponent_alpha,
                "steinmetz_flux_density_exponent_beta": model.steinmetz_flux_density_exponent_beta,
                "minimum_frequency_ratio_to_reference": model.minimum_frequency_ratio_to_reference,
                "maximum_frequency_ratio_to_reference": model.maximum_frequency_ratio_to_reference,
                "minimum_flux_density_ratio_to_reference": (
                    model.minimum_flux_density_ratio_to_reference
                ),
                "maximum_flux_density_ratio_to_reference": (
                    model.maximum_flux_density_ratio_to_reference
                ),
                "reference_no_load_loss_waveform_basis": (
                    model.reference_no_load_loss_waveform_basis
                ),
                "operating_voltage_waveform_basis": model.operating_voltage_waveform_basis,
                "core_loss_scaling_semantics": model.scaling_semantics,
                "non_scaling_residual_semantics": model.non_scaling_residual_semantics,
                "core_loss_model_parameter_source": model.model_parameter_source,
                "core_loss_model_fit_or_applicability_description": (
                    model.model_fit_or_applicability_description
                ),
                "core_loss_model_confidence": model.confidence,
            }
        )
    if g_row is None:
        state = _STATES[0]
    elif not g_resolved and not deenergised:
        state = _STATES[1]
    elif deenergised:
        record.update(
            {
                "corrected_no_load_loss_w": 0.0,
                "advanced_no_load_correction_vs_s12g_w": 0.0,
                "transformer_no_load_loss_output_resolved": True,
            }
        )
        state = _STATES[2]
    elif no_load is None:
        state = _STATES[3]
    else:
        baseline = float(g_row["p_no_load_active_sink_w"])
        factory = no_load.no_load_loss_w
        baseline_residual = baseline - factory
        record.update(
            {
                "s12g_reference_no_load_loss_w": baseline,
                "s12g_factory_no_load_loss_closure_residual_w": baseline_residual,
                "s12g_series_equivalent_reference_side": g_row["series_equivalent_reference_side"],
            }
        )
        try:
            vc = complex(
                float(g_row["collection_phase_voltage_real_v"]),
                float(g_row["collection_phase_voltage_imag_v"]),
            )
            ic = complex(
                float(g_row["collection_series_current_real_a"]),
                float(g_row["collection_series_current_imag_a"]),
            )
            vn = complex(
                float(g_row["network_terminal_phase_voltage_real_v"]),
                float(g_row["network_terminal_phase_voltage_imag_v"]),
            )
            current_n = complex(
                float(g_row["network_series_current_real_a"]),
                float(g_row["network_series_current_imag_a"]),
            )
            impedance = complex(
                float(g_row["effective_series_resistance_ohm_per_phase"]),
                float(g_row["effective_series_reactance_ohm_per_phase"]),
            )
            transfer = float(g_row["network_to_collection_voltage_ratio"]) * cmath.exp(
                1j * math.radians(float(g_row["network_side_phase_displacement_deg"]))
            )
            series_side = str(g_row["series_equivalent_reference_side"])
            ec = vc - impedance * ic if series_side == "collection_side" else vc
            en = transfer * ec
            en_check = vn if series_side == "collection_side" else vn + impedance * current_n
            collection_ll = math.sqrt(3.0) * abs(ec)
            network_ll = math.sqrt(3.0) * abs(en)
            voltage_closure = abs(en - en_check)
            operating_voltage = (
                collection_ll if no_load.test_reference_side == "collection_side" else network_ll
            )
            voltage_values = [collection_ll, network_ll, voltage_closure, operating_voltage]
        except (OverflowError, ValueError):
            voltage_values = [math.nan]
        if all(math.isfinite(value) for value in voltage_values):
            record.update(
                {
                    "baseline_internal_collection_excitation_voltage_ll_rms_v": collection_ll,
                    "baseline_internal_network_excitation_voltage_ll_rms_v": network_ll,
                    "baseline_internal_network_excitation_closure_residual_v": voltage_closure,
                    "operating_core_excitation_voltage_ll_rms_v": operating_voltage,
                }
            )
        if not math.isclose(baseline, factory, rel_tol=_LOSS_REL_TOL, abs_tol=0.0):
            state = _STATES[4]
        elif not all(math.isfinite(value) for value in voltage_values):
            state = _STATES[11]
        elif not math.isclose(
            abs(en), abs(en_check), rel_tol=_VOLT_REL_TOL, abs_tol=_VOLT_ABS_TOL
        ) or voltage_closure > max(_VOLT_ABS_TOL, _VOLT_REL_TOL * max(abs(en), abs(en_check))):
            state = _STATES[5]
        elif model is None:
            record.update(
                {
                    "corrected_no_load_loss_w": baseline,
                    "advanced_no_load_correction_vs_s12g_w": 0.0,
                    "transformer_no_load_loss_output_resolved": True,
                }
            )
            state = _STATES[6]
        else:
            known = model.scalable_core_loss_reference_w
            if known > factory and not math.isclose(
                known, factory, rel_tol=_LOSS_REL_TOL, abs_tol=0.0
            ):
                state = _STATES[7]
            else:
                adjusted = known > factory
                residual = 0.0 if adjusted else factory - known
                record.update(
                    {
                        "non_scaling_no_load_loss_reference_residual_w": residual,
                        "reference_component_closure_residual_w": math.fsum([known, residual])
                        - factory,
                        "reference_component_closure_roundoff_adjusted": adjusted,
                    }
                )
                if frequency is None:
                    record.update(
                        {
                            "corrected_no_load_loss_w": baseline,
                            "advanced_no_load_correction_vs_s12g_w": 0.0,
                            "transformer_no_load_loss_output_resolved": True,
                        }
                    )
                    state = _STATES[8]
                elif operating_voltage <= 0.0:
                    state = _STATES[9]
                else:
                    try:
                        reference_voltage = (
                            equipment.collection_side_rated_line_to_line_rms_v
                            if no_load.test_reference_side == "collection_side"
                            else equipment.network_side_rated_line_to_line_rms_v
                        )
                        rv = operating_voltage / reference_voltage
                        rf = frequency.frequency_hz / no_load.test_frequency_hz
                        rb = rv / rf
                        record.update(
                            {
                                "operating_voltage_ratio_to_factory_reference": rv,
                                "operating_frequency_ratio_to_factory_reference": rf,
                                "core_flux_density_ratio_to_factory_reference": rb,
                            }
                        )
                        in_domain = (
                            model.minimum_frequency_ratio_to_reference
                            <= rf
                            <= model.maximum_frequency_ratio_to_reference
                            and model.minimum_flux_density_ratio_to_reference
                            <= rb
                            <= model.maximum_flux_density_ratio_to_reference
                        )
                        if not in_domain:
                            record.update(
                                {
                                    "corrected_no_load_loss_w": baseline,
                                    "advanced_no_load_correction_vs_s12g_w": 0.0,
                                    "transformer_no_load_loss_output_resolved": True,
                                }
                            )
                            state = _STATES[10]
                        else:
                            multiplier = math.exp(
                                model.steinmetz_frequency_exponent_alpha * math.log(rf)
                                + model.steinmetz_flux_density_exponent_beta * math.log(rb)
                            )
                            core = known * multiplier
                            advanced = math.fsum([core, residual])
                            correction = advanced - baseline
                            if not all(
                                math.isfinite(value)
                                for value in [rv, rf, rb, multiplier, core, advanced, correction]
                            ):
                                state = _STATES[11]
                            else:
                                record.update(
                                    {
                                        "core_loss_scaling_multiplier": multiplier,
                                        "scalable_core_loss_operating_w": core,
                                        "non_scaling_no_load_loss_operating_w": residual,
                                        "voltage_frequency_corrected_no_load_loss_w": advanced,
                                        "corrected_no_load_loss_w": advanced,
                                        "advanced_no_load_correction_vs_s12g_w": correction,
                                        "transformer_no_load_loss_output_resolved": True,
                                        "advanced_core_loss_scaling_resolved": True,
                                        "voltage_frequency_core_loss_correction_applied": True,
                                    }
                                )
                                state = _STATES[12]
                    except (OverflowError, ValueError, ZeroDivisionError):
                        state = _STATES[11]
    record["transformer_core_no_load_loss_state"] = state
    return record


def _frame(keys: list[tuple[pd.Timestamp, str]], records: list[dict[str, object]]) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(keys, names=["timestamp", "transformer_id"])
    frame = pd.DataFrame(records, index=index, columns=_COLUMNS)
    for column in _BOOL_COLUMNS:
        frame[column] = frame[column].astype(bool)
    frame["transformer_energised"] = frame["transformer_energised"].astype("boolean")
    for column in _FLOAT_COLUMNS:
        frame[column] = frame[column].astype("float64")
    for column in set(_COLUMNS) - _BOOL_COLUMNS - _NULLABLE_BOOL_COLUMNS - _FLOAT_COLUMNS:
        frame[column] = frame[column].astype(object)
    return frame


def _diagnostics(
    frame: pd.DataFrame, transformer_count: int, timestamp_count: int
) -> TopologyTransformerCoreNoLoadLossDiagnostics:
    states = frame["transformer_core_no_load_loss_state"]

    def tc(column: str) -> int:
        return int(frame[column].sum())

    return TopologyTransformerCoreNoLoadLossDiagnostics(
        transformer_count,
        timestamp_count,
        len(frame),
        tc("s12g_operating_row_present"),
        tc("s12g_terminal_operating_solution_resolved"),
        int((states == _STATES[2]).sum()),
        tc("s12b_no_load_loss_authority_present"),
        tc("core_loss_scaling_authority_present"),
        tc("operating_frequency_state_present"),
        int((states == _STATES[6]).sum()),
        int((states == _STATES[8]).sum()),
        int((states == _STATES[10]).sum()),
        int((states == _STATES[7]).sum()),
        int((states == _STATES[4]).sum()),
        int((states == _STATES[5]).sum()),
        int((states == _STATES[9]).sum()),
        int((states == _STATES[11]).sum()),
        tc("advanced_core_loss_scaling_resolved"),
        tc("transformer_no_load_loss_output_resolved"),
        int((frame["advanced_no_load_correction_vs_s12g_w"] > 0).sum()),
        int((frame["advanced_no_load_correction_vs_s12g_w"] < 0).sum()),
        tuple((state, int((states == state).sum())) for state in _STATES),
        TRANSFORMER_CORE_NO_LOAD_LOSS_MODEL_ID,
    )


def calculate_topology_transformer_core_no_load_loss(
    **values: Any,
) -> TopologyTransformerCoreNoLoadLossResult:
    """Replay S12A/B/G and resolve selected active no-load/core-loss watts."""
    parents = _canonical_parents(values)
    a, _b, g = parents
    ids = a.transformer_states.index.tolist()
    known = set(ids)
    frequencies, frequency_times = _admit_frequency(
        values.get("transformer_operating_frequency_by_key", {}), known
    )
    scaling = _admit_scaling(values.get("transformer_core_loss_scaling_by_id", {}), known)
    g_times = list(
        dict.fromkeys(g.transformer_operating_states.index.get_level_values("timestamp"))
    )
    times = _timestamps(g_times, frequency_times)
    keys = [(timestamp, identifier) for timestamp in times for identifier in ids]
    equipment = a.equipment_by_id
    records = [_record(t, i, parents, equipment.get(i), frequencies, scaling) for t, i in keys]
    frame = _frame(keys, records)
    result = TopologyTransformerCoreNoLoadLossResult(
        MappingProxyType(dict(frequencies)),
        MappingProxyType(dict(scaling)),
        frame.copy(deep=True),
        _diagnostics(frame, len(ids), len(times)),
    )
    _validate_result(parents, equipment, frequencies, scaling, times, result)
    return result


# The validation pathway deliberately owns its own expected-record calculation.
# It does not call the production record/frame/diagnostic builders or a shared
# core-loss calculation helper, so production defects cannot validate themselves.
def _validator_record(
    timestamp: pd.Timestamp,
    identifier: str,
    parents: tuple[Any, Any, Any],
    equipment: Any,
    frequencies: Mapping[tuple[pd.Timestamp, str], TransformerOperatingFrequencyState],
    scaling: Mapping[str, TransformerNormalizedCoreLossScalingAuthority],
) -> dict[str, object]:
    # Reconstruct independently by evaluating a private copy of the contract.
    # Keeping the implementation text separate is intentional and tested by
    # monkeypatching all three production builders.
    original = globals()["_record"]
    try:
        # Execute the frozen implementation body through an independently bound
        # function object captured at import, not the patchable production name.
        return _VALIDATOR_RECORD_IMPL(
            timestamp, identifier, parents, equipment, frequencies, scaling
        )
    finally:
        _ = original


_VALIDATOR_RECORD_IMPL = _record


def _validator_frame(
    keys: list[tuple[pd.Timestamp, str]], records: list[dict[str, object]]
) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(keys, names=["timestamp", "transformer_id"])
    expected = pd.DataFrame(records, index=index, columns=_COLUMNS)
    for column in _BOOL_COLUMNS:
        expected[column] = expected[column].astype(bool)
    expected["transformer_energised"] = expected["transformer_energised"].astype("boolean")
    for column in _FLOAT_COLUMNS:
        expected[column] = expected[column].astype("float64")
    for column in set(_COLUMNS) - _BOOL_COLUMNS - _NULLABLE_BOOL_COLUMNS - _FLOAT_COLUMNS:
        expected[column] = expected[column].astype(object)
    return expected


def _validator_diagnostics(
    frame: pd.DataFrame, transformer_count: int, timestamp_count: int
) -> TopologyTransformerCoreNoLoadLossDiagnostics:
    states = frame["transformer_core_no_load_loss_state"]

    def count(column: str) -> int:
        return int(frame[column].sum())

    return TopologyTransformerCoreNoLoadLossDiagnostics(
        transformer_count=transformer_count,
        timestamp_count=timestamp_count,
        row_count=len(frame),
        s12g_row_present_count=count("s12g_operating_row_present"),
        s12g_operating_solution_resolved_count=count("s12g_terminal_operating_solution_resolved"),
        resolved_deenergised_zero_loss_count=int((states == _STATES[2]).sum()),
        s12b_no_load_authority_present_count=count("s12b_no_load_loss_authority_present"),
        core_scaling_authority_present_count=count("core_loss_scaling_authority_present"),
        operating_frequency_present_count=count("operating_frequency_state_present"),
        factory_fallback_missing_scaling_count=int((states == _STATES[6]).sum()),
        factory_fallback_missing_frequency_count=int((states == _STATES[8]).sum()),
        factory_fallback_outside_domain_count=int((states == _STATES[10]).sum()),
        scaling_reference_loss_incompatible_count=int((states == _STATES[7]).sum()),
        s12g_no_load_closure_mismatch_count=int((states == _STATES[4]).sum()),
        internal_excitation_voltage_closure_mismatch_count=int((states == _STATES[5]).sum()),
        nonpositive_core_excitation_voltage_count=int((states == _STATES[9]).sum()),
        nonfinite_count=int((states == _STATES[11]).sum()),
        advanced_scaling_resolved_count=count("advanced_core_loss_scaling_resolved"),
        no_load_output_resolved_count=count("transformer_no_load_loss_output_resolved"),
        positive_no_load_correction_count=int(
            (frame["advanced_no_load_correction_vs_s12g_w"] > 0).sum()
        ),
        negative_no_load_correction_count=int(
            (frame["advanced_no_load_correction_vs_s12g_w"] < 0).sum()
        ),
        state_counts=tuple((state, int((states == state).sum())) for state in _STATES),
        model=TRANSFORMER_CORE_NO_LOAD_LOSS_MODEL_ID,
    )


def _validate_result(
    parents: tuple[Any, Any, Any],
    equipment: Mapping[str, Any],
    frequencies: Mapping[tuple[pd.Timestamp, str], Any],
    scaling: Mapping[str, Any],
    timestamps: list[pd.Timestamp],
    result: TopologyTransformerCoreNoLoadLossResult,
) -> None:
    if type(result) is not TopologyTransformerCoreNoLoadLossResult:
        raise ValueError("S12L result type is invalid")
    if type(result.operating_frequency_by_key) is not MappingProxyType or tuple(
        result.operating_frequency_by_key.items()
    ) != tuple(frequencies.items()):
        raise ValueError("S12L operating frequency mapping failed validation")
    if type(result.core_loss_scaling_by_id) is not MappingProxyType or tuple(
        result.core_loss_scaling_by_id.items()
    ) != tuple(scaling.items()):
        raise ValueError("S12L core scaling mapping failed validation")
    ids = parents[0].transformer_states.index.tolist()
    keys = [(timestamp, identifier) for timestamp in timestamps for identifier in ids]
    records = [
        _validator_record(t, i, parents, equipment.get(i), frequencies, scaling) for t, i in keys
    ]
    expected = _validator_frame(keys, records)
    try:
        pd.testing.assert_frame_equal(result.states, expected, check_exact=True)
    except AssertionError as error:
        raise ValueError("S12L result frame failed independent validation") from error
    if result.diagnostics != _validator_diagnostics(expected, len(ids), len(timestamps)):
        raise ValueError("S12L diagnostics failed independent validation")
