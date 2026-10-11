"""Factory-reference effective transformer series-equivalent derivation.

S12F combines compatible S12A equipment bases, S12B total rated-load-loss
evidence, and S12E short-circuit impedance evidence.  The derived resistance
is an effective short-circuit equivalent reproducing total rated load loss;
it is not winding, conductor, or copper-only resistance.  No operating or
terminal propagation is performed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from types import MappingProxyType
from typing import Literal

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics.lv_ac_collection_authority import (
    LvAcCollectionNetworkBasisAuthority,
    LvAcCollectionNodeAuthority,
    LvAcCollectionSegmentAuthority,
    LvAcInverterTerminalBindingAuthority,
    TopologyLvAcCollectionAuthorityResult,
)
from heliotelligence.physics.transformer_authority import (
    TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
    TopologyTransformerStaticAuthorityResult,
    TransformerBoundaryTopologyAuthority,
    TransformerStaticEquipmentAuthority,
    resolve_transformer_static_authority,
)
from heliotelligence.physics.transformer_loss_authority import (
    TRANSFORMER_LOSS_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_LOSS_AUTHORITY_MODEL_ID,
    TopologyTransformerLossAuthorityResult,
    TransformerNoLoadLossAuthority,
    TransformerRatedLoadLossAuthority,
    resolve_transformer_loss_authority,
)
from heliotelligence.physics.transformer_network_authority import (
    TRANSFORMER_NETWORK_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_NETWORK_AUTHORITY_MODEL_ID,
    TopologyTransformerNetworkAuthorityResult,
    TransformerShortCircuitImpedanceAuthority,
    TransformerVoltageTransferAuthority,
    resolve_transformer_network_authority,
)

TRANSFORMER_SERIES_EQUIVALENT_CONTRACT_ID = (
    "admitted_transformer_factory_load_loss_and_short_circuit_impedance_"
    "to_effective_series_equivalent_v1"
)
TRANSFORMER_SERIES_EQUIVALENT_MODEL_ID = (
    "balanced_three_phase_factory_short_circuit_effective_series_rx_"
    "reference_condition_decomposition_v1"
)
TRANSFORMER_SERIES_EQUIVALENT_SCOPE = (
    "static_transformer_factory_reference_series_equivalent_before_"
    "transformer_terminal_operating_solve"
)
TRANSFORMER_SERIES_EQUIVALENT_COVERAGE_SCOPE = (
    "compatible_factory_rated_load_loss_and_short_circuit_impedance_"
    "effective_series_resistance_and_reactance"
)

Confidence = Literal["high", "medium", "low", "unknown"]
RatioReferenceCondition = Literal[
    "fixed_non_tapped_transformer_ratio",
    "principal_tapping",
]
_CONFIDENCES = {"high", "medium", "low", "unknown"}
_REFERENCE_CONDITIONS = {"fixed_non_tapped_transformer_ratio", "principal_tapping"}
_R_Z_REL_TOL = 1e-12
_EFFECTIVE_RESISTANCE_SEMANTICS = (
    "effective_factory_short_circuit_series_resistance_reproducing_"
    "total_rated_load_loss_at_reference_condition"
)
_REACTANCE_DERIVATION_SEMANTICS = (
    "nonnegative_effective_series_reactance_from_short_circuit_impedance_"
    "magnitude_and_effective_total_load_loss_resistance"
)

_COLUMNS = (
    "transformer_equipment_authority_present",
    "transformer_factory_rated_load_loss_authority_present",
    "transformer_positive_sequence_network_authority_resolved",
    "transformer_short_circuit_impedance_authority_present",
    "rated_load_loss_reference_condition_authority_present",
    "transformer_series_equivalent_resolved",
    "transformer_boundary_operating_readiness_established",
    "load_loss_test_current_reference_side",
    "short_circuit_impedance_reference_side",
    "reference_side_compatible",
    "load_loss_ratio_reference_condition",
    "short_circuit_impedance_ratio_reference_condition",
    "ratio_reference_condition_compatible",
    "load_loss_reference_temperature_c",
    "short_circuit_reference_temperature_c",
    "reference_temperature_compatible",
    "load_loss_test_frequency_hz",
    "short_circuit_test_frequency_hz",
    "test_frequency_compatible",
    "rated_apparent_power_va",
    "reference_side_rated_line_to_line_rms_v",
    "reference_side_rated_current_a",
    "factory_rated_load_loss_w",
    "short_circuit_impedance_magnitude_pu",
    "effective_series_resistance_pu",
    "effective_series_reactance_pu",
    "short_circuit_impedance_base_ohm_per_phase",
    "effective_series_resistance_ohm_per_phase",
    "effective_series_reactance_ohm_per_phase",
    "short_circuit_impedance_magnitude_ohm_per_phase",
    "effective_series_resistance_semantics",
    "effective_series_reactance_derivation_semantics",
    "series_equivalent_reference_side",
    "rated_load_loss_reference_condition_parameter_source",
    "rated_load_loss_reference_condition_confidence",
    "transformer_series_equivalent_state",
    "transformer_static_authority_contract",
    "transformer_static_authority_model",
    "transformer_loss_authority_contract",
    "transformer_loss_authority_model",
    "transformer_network_authority_contract",
    "transformer_network_authority_model",
    "transformer_series_equivalent_contract",
    "transformer_series_equivalent_model",
    "transformer_series_equivalent_scope",
    "transformer_series_equivalent_coverage_scope",
)
_BOOL_COLUMNS = {
    "transformer_equipment_authority_present",
    "transformer_factory_rated_load_loss_authority_present",
    "transformer_positive_sequence_network_authority_resolved",
    "transformer_short_circuit_impedance_authority_present",
    "rated_load_loss_reference_condition_authority_present",
    "transformer_series_equivalent_resolved",
    "transformer_boundary_operating_readiness_established",
    "reference_side_compatible",
    "ratio_reference_condition_compatible",
    "reference_temperature_compatible",
    "test_frequency_compatible",
}
_FLOAT_COLUMNS = {
    "load_loss_reference_temperature_c",
    "short_circuit_reference_temperature_c",
    "load_loss_test_frequency_hz",
    "short_circuit_test_frequency_hz",
    "rated_apparent_power_va",
    "reference_side_rated_line_to_line_rms_v",
    "reference_side_rated_current_a",
    "factory_rated_load_loss_w",
    "short_circuit_impedance_magnitude_pu",
    "effective_series_resistance_pu",
    "effective_series_reactance_pu",
    "short_circuit_impedance_base_ohm_per_phase",
    "effective_series_resistance_ohm_per_phase",
    "effective_series_reactance_ohm_per_phase",
    "short_circuit_impedance_magnitude_ohm_per_phase",
}


def _identifier(value: object, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be an exact non-empty string without surrounding whitespace")
    return value


def _source(value: object) -> str:
    return _identifier(value, "parameter_source")


def _confidence(value: object) -> str:
    if type(value) is not str or value not in _CONFIDENCES:
        raise ValueError("confidence is unsupported")
    return value


def _reference_condition(value: object) -> str:
    if type(value) is not str or value not in _REFERENCE_CONDITIONS:
        raise ValueError("ratio_reference_condition is unsupported")
    return value


@dataclass(frozen=True)
class TransformerRatedLoadLossReferenceConditionAuthority:
    transformer_id: str
    ratio_reference_condition: RatioReferenceCondition
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _identifier(self.transformer_id, "transformer_id")
        _reference_condition(self.ratio_reference_condition)
        _source(self.parameter_source)
        _confidence(self.confidence)


@dataclass(frozen=True)
class TopologyTransformerSeriesEquivalentDiagnostics:
    transformer_count: int
    equipment_authority_present_count: int
    rated_load_loss_authority_count: int
    positive_sequence_network_authority_resolved_count: int
    short_circuit_impedance_authority_count: int
    load_loss_reference_condition_authority_count: int
    series_equivalent_resolved_count: int
    unresolved_missing_equipment_basis_count: int
    unresolved_missing_rated_load_loss_count: int
    unresolved_missing_network_authority_count: int
    unresolved_missing_impedance_count: int
    unresolved_missing_load_loss_reference_condition_count: int
    unresolved_incompatible_reference_sides_count: int
    unresolved_incompatible_ratio_reference_conditions_count: int
    unresolved_incompatible_reference_temperatures_count: int
    unresolved_incompatible_test_frequencies_count: int
    unresolved_load_loss_exceeds_impedance_count: int
    model: str


@dataclass(frozen=True)
class TopologyTransformerSeriesEquivalentResult:
    rated_load_loss_reference_condition_by_id: Mapping[
        str, TransformerRatedLoadLossReferenceConditionAuthority
    ]
    transformer_states: pd.DataFrame
    diagnostics: TopologyTransformerSeriesEquivalentDiagnostics


def resolve_transformer_series_equivalent(
    topology: ElectricalTopologyConfig,
    network_basis: LvAcCollectionNetworkBasisAuthority | None,
    node_authority_by_id: Mapping[str, LvAcCollectionNodeAuthority],
    segment_authority_by_id: Mapping[str, LvAcCollectionSegmentAuthority],
    inverter_terminal_binding_by_inverter_id: Mapping[str, LvAcInverterTerminalBindingAuthority],
    lv_ac_collection_authority: TopologyLvAcCollectionAuthorityResult,
    transformer_equipment_by_id: Mapping[str, TransformerStaticEquipmentAuthority],
    transformer_topology_by_id: Mapping[str, TransformerBoundaryTopologyAuthority],
    transformer_static_authority: TopologyTransformerStaticAuthorityResult,
    transformer_no_load_loss_by_id: Mapping[str, TransformerNoLoadLossAuthority],
    transformer_rated_load_loss_by_id: Mapping[str, TransformerRatedLoadLossAuthority],
    transformer_loss_authority: TopologyTransformerLossAuthorityResult,
    transformer_voltage_transfer_by_id: Mapping[str, TransformerVoltageTransferAuthority],
    transformer_short_circuit_impedance_by_id: Mapping[
        str, TransformerShortCircuitImpedanceAuthority
    ],
    transformer_network_authority: TopologyTransformerNetworkAuthorityResult,
    transformer_rated_load_loss_reference_condition_by_id: Mapping[
        str, TransformerRatedLoadLossReferenceConditionAuthority
    ],
) -> TopologyTransformerSeriesEquivalentResult:
    """Derive compatible factory-reference effective series R+jX evidence."""
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
    _validate_static_replay(transformer_static_authority, canonical_static)
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
    _validate_loss_replay(transformer_loss_authority, canonical_loss)
    canonical_network = resolve_transformer_network_authority(
        topology,
        network_basis,
        node_authority_by_id,
        segment_authority_by_id,
        inverter_terminal_binding_by_inverter_id,
        lv_ac_collection_authority,
        transformer_equipment_by_id,
        transformer_topology_by_id,
        canonical_static,
        transformer_voltage_transfer_by_id,
        transformer_short_circuit_impedance_by_id,
    )
    _validate_network_replay(transformer_network_authority, canonical_network)
    ids = canonical_static.transformer_states.index.tolist()
    references = _admit_reference_mapping(
        transformer_rated_load_loss_reference_condition_by_id, set(ids)
    )
    records = [
        _build_record(
            canonical_static.transformer_states.loc[transformer_id],
            canonical_static.equipment_by_id.get(transformer_id),
            canonical_loss.rated_load_loss_by_id.get(transformer_id),
            canonical_network.transformer_states.loc[transformer_id],
            canonical_network.short_circuit_impedance_by_id.get(transformer_id),
            references.get(transformer_id),
        )
        for transformer_id in ids
    ]
    states = _state_frame(ids, records)
    diagnostics = _build_diagnostics(states, references)
    result = TopologyTransformerSeriesEquivalentResult(
        MappingProxyType(dict(references)), states.copy(deep=True), diagnostics
    )
    _validate_result(canonical_static, canonical_loss, canonical_network, result)
    return result


def _validate_static_replay(
    supplied: TopologyTransformerStaticAuthorityResult,
    canonical: TopologyTransformerStaticAuthorityResult,
) -> None:
    if type(supplied) is not TopologyTransformerStaticAuthorityResult:
        raise ValueError("supplied S12A result type is invalid")
    for name in ("equipment_by_id", "topology_by_id"):
        actual, expected = getattr(supplied, name), getattr(canonical, name)
        if type(actual).__name__ != "mappingproxy" or dict(actual) != dict(expected):
            raise ValueError(f"supplied S12A {name} does not match immutable canonical replay")
    _require_frame_equal(supplied.transformer_states, canonical.transformer_states, "S12A")
    if supplied.diagnostics != canonical.diagnostics:
        raise ValueError("supplied S12A diagnostics do not match canonical replay")


def _validate_loss_replay(
    supplied: TopologyTransformerLossAuthorityResult,
    canonical: TopologyTransformerLossAuthorityResult,
) -> None:
    if type(supplied) is not TopologyTransformerLossAuthorityResult:
        raise ValueError("supplied S12B result type is invalid")
    for name in ("no_load_loss_by_id", "rated_load_loss_by_id"):
        actual, expected = getattr(supplied, name), getattr(canonical, name)
        if type(actual).__name__ != "mappingproxy" or dict(actual) != dict(expected):
            raise ValueError(f"supplied S12B {name} does not match immutable canonical replay")
    _require_frame_equal(supplied.transformer_states, canonical.transformer_states, "S12B")
    if supplied.diagnostics != canonical.diagnostics:
        raise ValueError("supplied S12B diagnostics do not match canonical replay")


def _validate_network_replay(
    supplied: TopologyTransformerNetworkAuthorityResult,
    canonical: TopologyTransformerNetworkAuthorityResult,
) -> None:
    if type(supplied) is not TopologyTransformerNetworkAuthorityResult:
        raise ValueError("supplied S12E result type is invalid")
    for name in ("voltage_transfer_by_id", "short_circuit_impedance_by_id"):
        actual, expected = getattr(supplied, name), getattr(canonical, name)
        if type(actual).__name__ != "mappingproxy" or dict(actual) != dict(expected):
            raise ValueError(f"supplied S12E {name} does not match immutable canonical replay")
    _require_frame_equal(supplied.transformer_states, canonical.transformer_states, "S12E")
    if supplied.diagnostics != canonical.diagnostics:
        raise ValueError("supplied S12E diagnostics do not match canonical replay")


def _require_frame_equal(actual: pd.DataFrame, expected: pd.DataFrame, label: str) -> None:
    try:
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    except AssertionError as error:
        raise ValueError(f"supplied {label} states do not match canonical replay") from error


def _admit_reference_mapping(
    supplied: Mapping[str, TransformerRatedLoadLossReferenceConditionAuthority],
    known_ids: set[str],
) -> dict[str, TransformerRatedLoadLossReferenceConditionAuthority]:
    if not isinstance(supplied, Mapping):
        raise TypeError("rated load loss reference-condition authority must be a mapping")
    admitted: dict[str, TransformerRatedLoadLossReferenceConditionAuthority] = {}
    for key, authority in supplied.items():
        _identifier(key, "transformer mapping key")
        if type(authority) is not TransformerRatedLoadLossReferenceConditionAuthority:
            raise TypeError("rated load loss reference-condition authority has invalid value type")
        if key != authority.transformer_id:
            raise ValueError("rated load loss reference-condition mapping key mismatch")
        if key not in known_ids:
            raise ValueError("rated load loss reference-condition references unknown transformer")
        admitted[key] = authority
    return dict(sorted(admitted.items()))


def _compatibility(
    rated_load: TransformerRatedLoadLossAuthority | None,
    impedance: TransformerShortCircuitImpedanceAuthority | None,
    reference: TransformerRatedLoadLossReferenceConditionAuthority | None,
) -> tuple[bool, bool, bool, bool]:
    sides = bool(
        rated_load
        and impedance
        and rated_load.test_current_reference_side == impedance.impedance_reference_side
    )
    ratios = bool(
        reference
        and impedance
        and reference.ratio_reference_condition == impedance.ratio_reference_condition
    )
    temperatures = bool(
        rated_load
        and impedance
        and rated_load.reference_temperature_c == impedance.reference_temperature_c
    )
    frequencies = bool(
        rated_load and impedance and rated_load.test_frequency_hz == impedance.test_frequency_hz
    )
    return sides, ratios, temperatures, frequencies


def _state(
    equipment: bool,
    rated_load: bool,
    network: bool,
    impedance: bool,
    reference: bool,
    side_ok: bool,
    ratio_ok: bool,
    temperature_ok: bool,
    frequency_ok: bool,
    math_ok: bool,
) -> str:
    if not equipment:
        return "unresolved_missing_transformer_equipment_basis_authority"
    if not rated_load:
        return "unresolved_missing_transformer_rated_load_loss_authority"
    if not impedance:
        return "unresolved_missing_transformer_short_circuit_impedance_authority"
    if not network:
        return "unresolved_upstream_transformer_positive_sequence_network_authority"
    if not reference:
        return "unresolved_missing_rated_load_loss_reference_condition_authority"
    if not side_ok:
        return "unresolved_incompatible_short_circuit_reference_sides"
    if not ratio_ok:
        return "unresolved_incompatible_short_circuit_ratio_reference_conditions"
    if not temperature_ok:
        return "unresolved_incompatible_short_circuit_reference_temperatures"
    if not frequency_ok:
        return "unresolved_incompatible_short_circuit_test_frequencies"
    if not math_ok:
        return "unresolved_factory_load_loss_exceeds_short_circuit_impedance_capability"
    return "resolved_transformer_factory_series_equivalent"


def _derived_values(
    equipment: TransformerStaticEquipmentAuthority,
    rated_load: TransformerRatedLoadLossAuthority,
    impedance: TransformerShortCircuitImpedanceAuthority,
) -> dict[str, float] | None:
    rated_voltage = (
        equipment.collection_side_rated_line_to_line_rms_v
        if impedance.impedance_reference_side == "collection_side"
        else equipment.network_side_rated_line_to_line_rms_v
    )
    rated_power = equipment.rated_apparent_power_va
    resistance_pu = rated_load.rated_load_loss_w / rated_power
    impedance_pu = impedance.short_circuit_impedance_magnitude_pu
    if resistance_pu > impedance_pu:
        if not math.isclose(resistance_pu, impedance_pu, rel_tol=_R_Z_REL_TOL, abs_tol=0.0):
            return None
        reactance_pu = 0.0
    else:
        resistance_to_impedance_ratio = resistance_pu / impedance_pu
        reactance_pu = impedance_pu * math.sqrt(
            max(0.0, 1.0 - resistance_to_impedance_ratio**2)
        )
    impedance_base = rated_voltage * rated_voltage / rated_power
    rated_current = rated_power / (math.sqrt(3.0) * rated_voltage)
    resistance_ohm = rated_load.rated_load_loss_w / (3.0 * rated_current * rated_current)
    return {
        "rated_apparent_power_va": rated_power,
        "reference_side_rated_line_to_line_rms_v": rated_voltage,
        "reference_side_rated_current_a": rated_current,
        "factory_rated_load_loss_w": rated_load.rated_load_loss_w,
        "short_circuit_impedance_magnitude_pu": impedance_pu,
        "effective_series_resistance_pu": resistance_pu,
        "effective_series_reactance_pu": reactance_pu,
        "short_circuit_impedance_base_ohm_per_phase": impedance_base,
        "effective_series_resistance_ohm_per_phase": resistance_ohm,
        "effective_series_reactance_ohm_per_phase": reactance_pu * impedance_base,
        "short_circuit_impedance_magnitude_ohm_per_phase": impedance_pu * impedance_base,
    }


def _build_record(
    static_row: pd.Series,
    equipment: TransformerStaticEquipmentAuthority | None,
    rated_load: TransformerRatedLoadLossAuthority | None,
    network_row: pd.Series,
    impedance: TransformerShortCircuitImpedanceAuthority | None,
    reference: TransformerRatedLoadLossReferenceConditionAuthority | None,
) -> dict[str, object]:
    equipment_present = bool(static_row["transformer_equipment_authority_present"])
    network_resolved = bool(network_row["transformer_positive_sequence_network_authority_resolved"])
    side_ok, ratio_ok, temperature_ok, frequency_ok = _compatibility(
        rated_load, impedance, reference
    )
    compatible_inputs = bool(
        equipment
        and rated_load
        and impedance
        and reference
        and network_resolved
        and side_ok
        and ratio_ok
        and temperature_ok
        and frequency_ok
    )
    derived = None
    if compatible_inputs:
        assert equipment is not None and rated_load is not None and impedance is not None
        derived = _derived_values(equipment, rated_load, impedance)
    math_ok = derived is not None if compatible_inputs else False
    state = _state(
        equipment_present,
        rated_load is not None,
        network_resolved,
        impedance is not None,
        reference is not None,
        side_ok,
        ratio_ok,
        temperature_ok,
        frequency_ok,
        math_ok,
    )
    nan = math.nan
    unresolved_numerical = {
        name: nan
        for name in _FLOAT_COLUMNS
        if name
        not in {
            "load_loss_reference_temperature_c",
            "short_circuit_reference_temperature_c",
            "load_loss_test_frequency_hz",
            "short_circuit_test_frequency_hz",
        }
    }
    unresolved_numerical["rated_apparent_power_va"] = (
        equipment.rated_apparent_power_va if equipment else nan
    )
    unresolved_numerical["factory_rated_load_loss_w"] = (
        rated_load.rated_load_loss_w if rated_load else nan
    )
    unresolved_numerical["short_circuit_impedance_magnitude_pu"] = (
        impedance.short_circuit_impedance_magnitude_pu if impedance else nan
    )
    return {
        "transformer_equipment_authority_present": equipment_present,
        "transformer_factory_rated_load_loss_authority_present": rated_load is not None,
        "transformer_positive_sequence_network_authority_resolved": network_resolved,
        "transformer_short_circuit_impedance_authority_present": impedance is not None,
        "rated_load_loss_reference_condition_authority_present": reference is not None,
        "transformer_series_equivalent_resolved": state
        == "resolved_transformer_factory_series_equivalent",
        "transformer_boundary_operating_readiness_established": False,
        "load_loss_test_current_reference_side": (
            rated_load.test_current_reference_side if rated_load else ""
        ),
        "short_circuit_impedance_reference_side": (
            impedance.impedance_reference_side if impedance else ""
        ),
        "reference_side_compatible": side_ok,
        "load_loss_ratio_reference_condition": (
            reference.ratio_reference_condition if reference else ""
        ),
        "short_circuit_impedance_ratio_reference_condition": (
            impedance.ratio_reference_condition if impedance else ""
        ),
        "ratio_reference_condition_compatible": ratio_ok,
        "load_loss_reference_temperature_c": rated_load.reference_temperature_c
        if rated_load
        else nan,
        "short_circuit_reference_temperature_c": impedance.reference_temperature_c
        if impedance
        else nan,
        "reference_temperature_compatible": temperature_ok,
        "load_loss_test_frequency_hz": rated_load.test_frequency_hz if rated_load else nan,
        "short_circuit_test_frequency_hz": impedance.test_frequency_hz if impedance else nan,
        "test_frequency_compatible": frequency_ok,
        **(derived if derived is not None else unresolved_numerical),
        "effective_series_resistance_semantics": (
            _EFFECTIVE_RESISTANCE_SEMANTICS if derived is not None else ""
        ),
        "effective_series_reactance_derivation_semantics": (
            _REACTANCE_DERIVATION_SEMANTICS if derived is not None else ""
        ),
        "series_equivalent_reference_side": (
            impedance.impedance_reference_side if derived is not None and impedance else ""
        ),
        "rated_load_loss_reference_condition_parameter_source": (
            reference.parameter_source if reference else ""
        ),
        "rated_load_loss_reference_condition_confidence": (
            reference.confidence if reference else ""
        ),
        "transformer_series_equivalent_state": state,
        "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
        "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
        "transformer_loss_authority_contract": TRANSFORMER_LOSS_AUTHORITY_CONTRACT_ID,
        "transformer_loss_authority_model": TRANSFORMER_LOSS_AUTHORITY_MODEL_ID,
        "transformer_network_authority_contract": TRANSFORMER_NETWORK_AUTHORITY_CONTRACT_ID,
        "transformer_network_authority_model": TRANSFORMER_NETWORK_AUTHORITY_MODEL_ID,
        "transformer_series_equivalent_contract": TRANSFORMER_SERIES_EQUIVALENT_CONTRACT_ID,
        "transformer_series_equivalent_model": TRANSFORMER_SERIES_EQUIVALENT_MODEL_ID,
        "transformer_series_equivalent_scope": TRANSFORMER_SERIES_EQUIVALENT_SCOPE,
        "transformer_series_equivalent_coverage_scope": (
            TRANSFORMER_SERIES_EQUIVALENT_COVERAGE_SCOPE
        ),
    }


def _state_frame(ids: list[str], records: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(records, index=pd.Index(ids, name="transformer_id", dtype=object))
    frame = frame.reindex(columns=_COLUMNS)
    for column in _BOOL_COLUMNS:
        frame[column] = frame[column].astype(bool)
    for column in _FLOAT_COLUMNS:
        frame[column] = frame[column].astype("float64")
    for column in set(_COLUMNS) - _BOOL_COLUMNS - _FLOAT_COLUMNS:
        frame[column] = frame[column].astype(object)
    return frame


def _validator_record(
    static_row: pd.Series,
    equipment: TransformerStaticEquipmentAuthority | None,
    rated_load: TransformerRatedLoadLossAuthority | None,
    network_row: pd.Series,
    impedance: TransformerShortCircuitImpedanceAuthority | None,
    reference: TransformerRatedLoadLossReferenceConditionAuthority | None,
) -> dict[str, object]:
    """Independently reconstruct one expected result row."""
    equipment_present = bool(static_row["transformer_equipment_authority_present"])
    network_resolved = bool(network_row["transformer_positive_sequence_network_authority_resolved"])
    side_ok = bool(
        rated_load is not None
        and impedance is not None
        and rated_load.test_current_reference_side == impedance.impedance_reference_side
    )
    ratio_ok = bool(
        reference is not None
        and impedance is not None
        and reference.ratio_reference_condition == impedance.ratio_reference_condition
    )
    temperature_ok = bool(
        rated_load is not None
        and impedance is not None
        and rated_load.reference_temperature_c == impedance.reference_temperature_c
    )
    frequency_ok = bool(
        rated_load is not None
        and impedance is not None
        and rated_load.test_frequency_hz == impedance.test_frequency_hz
    )
    values: dict[str, float] | None = None
    if (
        equipment is not None
        and rated_load is not None
        and impedance is not None
        and reference is not None
        and network_resolved
        and side_ok
        and ratio_ok
        and temperature_ok
        and frequency_ok
    ):
        voltage = (
            equipment.collection_side_rated_line_to_line_rms_v
            if impedance.impedance_reference_side == "collection_side"
            else equipment.network_side_rated_line_to_line_rms_v
        )
        apparent_power = equipment.rated_apparent_power_va
        resistance_pu = rated_load.rated_load_loss_w / apparent_power
        impedance_pu = impedance.short_circuit_impedance_magnitude_pu
        compatible_math = resistance_pu <= impedance_pu or math.isclose(
            resistance_pu, impedance_pu, rel_tol=_R_Z_REL_TOL, abs_tol=0.0
        )
        if compatible_math:
            if resistance_pu > impedance_pu:
                reactance_pu = 0.0
            else:
                resistance_to_impedance_ratio = resistance_pu / impedance_pu
                reactance_pu = impedance_pu * math.sqrt(
                    max(0.0, 1.0 - resistance_to_impedance_ratio**2)
                )
            base = voltage**2 / apparent_power
            current = apparent_power / (math.sqrt(3.0) * voltage)
            resistance_ohm = rated_load.rated_load_loss_w / (3.0 * current**2)
            values = {
                "rated_apparent_power_va": apparent_power,
                "reference_side_rated_line_to_line_rms_v": voltage,
                "reference_side_rated_current_a": current,
                "factory_rated_load_loss_w": rated_load.rated_load_loss_w,
                "short_circuit_impedance_magnitude_pu": impedance_pu,
                "effective_series_resistance_pu": resistance_pu,
                "effective_series_reactance_pu": reactance_pu,
                "short_circuit_impedance_base_ohm_per_phase": base,
                "effective_series_resistance_ohm_per_phase": resistance_ohm,
                "effective_series_reactance_ohm_per_phase": reactance_pu * base,
                "short_circuit_impedance_magnitude_ohm_per_phase": impedance_pu * base,
            }
    state = _state(
        equipment_present,
        rated_load is not None,
        network_resolved,
        impedance is not None,
        reference is not None,
        side_ok,
        ratio_ok,
        temperature_ok,
        frequency_ok,
        values is not None,
    )
    excluded = {
        "load_loss_reference_temperature_c",
        "short_circuit_reference_temperature_c",
        "load_loss_test_frequency_hz",
        "short_circuit_test_frequency_hz",
    }
    numerical = values or {name: math.nan for name in _FLOAT_COLUMNS if name not in excluded}
    if values is None:
        numerical["rated_apparent_power_va"] = (
            equipment.rated_apparent_power_va if equipment else math.nan
        )
        numerical["factory_rated_load_loss_w"] = (
            rated_load.rated_load_loss_w if rated_load else math.nan
        )
        numerical["short_circuit_impedance_magnitude_pu"] = (
            impedance.short_circuit_impedance_magnitude_pu if impedance else math.nan
        )
    return {
        "transformer_equipment_authority_present": equipment_present,
        "transformer_factory_rated_load_loss_authority_present": rated_load is not None,
        "transformer_positive_sequence_network_authority_resolved": network_resolved,
        "transformer_short_circuit_impedance_authority_present": impedance is not None,
        "rated_load_loss_reference_condition_authority_present": reference is not None,
        "transformer_series_equivalent_resolved": state
        == "resolved_transformer_factory_series_equivalent",
        "transformer_boundary_operating_readiness_established": False,
        "load_loss_test_current_reference_side": (
            rated_load.test_current_reference_side if rated_load else ""
        ),
        "short_circuit_impedance_reference_side": (
            impedance.impedance_reference_side if impedance else ""
        ),
        "reference_side_compatible": side_ok,
        "load_loss_ratio_reference_condition": (
            reference.ratio_reference_condition if reference else ""
        ),
        "short_circuit_impedance_ratio_reference_condition": (
            impedance.ratio_reference_condition if impedance else ""
        ),
        "ratio_reference_condition_compatible": ratio_ok,
        "load_loss_reference_temperature_c": (
            rated_load.reference_temperature_c if rated_load else math.nan
        ),
        "short_circuit_reference_temperature_c": (
            impedance.reference_temperature_c if impedance else math.nan
        ),
        "reference_temperature_compatible": temperature_ok,
        "load_loss_test_frequency_hz": (rated_load.test_frequency_hz if rated_load else math.nan),
        "short_circuit_test_frequency_hz": (impedance.test_frequency_hz if impedance else math.nan),
        "test_frequency_compatible": frequency_ok,
        **numerical,
        "effective_series_resistance_semantics": (
            _EFFECTIVE_RESISTANCE_SEMANTICS if values is not None else ""
        ),
        "effective_series_reactance_derivation_semantics": (
            _REACTANCE_DERIVATION_SEMANTICS if values is not None else ""
        ),
        "series_equivalent_reference_side": (
            impedance.impedance_reference_side if values is not None and impedance else ""
        ),
        "rated_load_loss_reference_condition_parameter_source": (
            reference.parameter_source if reference else ""
        ),
        "rated_load_loss_reference_condition_confidence": (
            reference.confidence if reference else ""
        ),
        "transformer_series_equivalent_state": state,
        "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
        "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
        "transformer_loss_authority_contract": TRANSFORMER_LOSS_AUTHORITY_CONTRACT_ID,
        "transformer_loss_authority_model": TRANSFORMER_LOSS_AUTHORITY_MODEL_ID,
        "transformer_network_authority_contract": TRANSFORMER_NETWORK_AUTHORITY_CONTRACT_ID,
        "transformer_network_authority_model": TRANSFORMER_NETWORK_AUTHORITY_MODEL_ID,
        "transformer_series_equivalent_contract": TRANSFORMER_SERIES_EQUIVALENT_CONTRACT_ID,
        "transformer_series_equivalent_model": TRANSFORMER_SERIES_EQUIVALENT_MODEL_ID,
        "transformer_series_equivalent_scope": TRANSFORMER_SERIES_EQUIVALENT_SCOPE,
        "transformer_series_equivalent_coverage_scope": (
            TRANSFORMER_SERIES_EQUIVALENT_COVERAGE_SCOPE
        ),
    }


_STATES = (
    "resolved_transformer_factory_series_equivalent",
    "unresolved_missing_transformer_equipment_basis_authority",
    "unresolved_missing_transformer_rated_load_loss_authority",
    "unresolved_missing_transformer_short_circuit_impedance_authority",
    "unresolved_upstream_transformer_positive_sequence_network_authority",
    "unresolved_missing_rated_load_loss_reference_condition_authority",
    "unresolved_incompatible_short_circuit_reference_sides",
    "unresolved_incompatible_short_circuit_ratio_reference_conditions",
    "unresolved_incompatible_short_circuit_reference_temperatures",
    "unresolved_incompatible_short_circuit_test_frequencies",
    "unresolved_factory_load_loss_exceeds_short_circuit_impedance_capability",
)


def _build_diagnostics(
    states: pd.DataFrame,
    references: Mapping[str, TransformerRatedLoadLossReferenceConditionAuthority],
) -> TopologyTransformerSeriesEquivalentDiagnostics:
    counts = states["transformer_series_equivalent_state"].value_counts()
    return TopologyTransformerSeriesEquivalentDiagnostics(
        transformer_count=len(states),
        equipment_authority_present_count=int(
            states["transformer_equipment_authority_present"].sum()
        ),
        rated_load_loss_authority_count=int(
            states["transformer_factory_rated_load_loss_authority_present"].sum()
        ),
        positive_sequence_network_authority_resolved_count=int(
            states["transformer_positive_sequence_network_authority_resolved"].sum()
        ),
        short_circuit_impedance_authority_count=int(
            states["transformer_short_circuit_impedance_authority_present"].sum()
        ),
        load_loss_reference_condition_authority_count=len(references),
        series_equivalent_resolved_count=int(counts.get(_STATES[0], 0)),
        unresolved_missing_equipment_basis_count=int(counts.get(_STATES[1], 0)),
        unresolved_missing_rated_load_loss_count=int(counts.get(_STATES[2], 0)),
        unresolved_missing_network_authority_count=int(counts.get(_STATES[4], 0)),
        unresolved_missing_impedance_count=int(counts.get(_STATES[3], 0)),
        unresolved_missing_load_loss_reference_condition_count=int(counts.get(_STATES[5], 0)),
        unresolved_incompatible_reference_sides_count=int(counts.get(_STATES[6], 0)),
        unresolved_incompatible_ratio_reference_conditions_count=int(counts.get(_STATES[7], 0)),
        unresolved_incompatible_reference_temperatures_count=int(counts.get(_STATES[8], 0)),
        unresolved_incompatible_test_frequencies_count=int(counts.get(_STATES[9], 0)),
        unresolved_load_loss_exceeds_impedance_count=int(counts.get(_STATES[10], 0)),
        model=TRANSFORMER_SERIES_EQUIVALENT_MODEL_ID,
    )


def _equal(actual: object, expected: object) -> bool:
    if isinstance(expected, float) and math.isnan(expected):
        return bool(pd.isna(actual))
    if isinstance(expected, float):
        if not isinstance(actual, Real):
            return False
        return math.isclose(float(actual), expected, rel_tol=1e-12, abs_tol=0.0)
    return bool(actual == expected)


def _validate_result(
    static: TopologyTransformerStaticAuthorityResult,
    loss: TopologyTransformerLossAuthorityResult,
    network: TopologyTransformerNetworkAuthorityResult,
    result: TopologyTransformerSeriesEquivalentResult,
) -> None:
    if type(result) is not TopologyTransformerSeriesEquivalentResult:
        raise RuntimeError("transformer series-equivalent result type is invalid")
    if type(result.rated_load_loss_reference_condition_by_id).__name__ != "mappingproxy":
        raise RuntimeError("transformer series-equivalent authority mapping must be immutable")
    ids = static.transformer_states.index.tolist()
    known = set(ids)
    for key, authority in result.rated_load_loss_reference_condition_by_id.items():
        if (
            type(authority) is not TransformerRatedLoadLossReferenceConditionAuthority
            or key != authority.transformer_id
            or key not in known
        ):
            raise RuntimeError("rated load loss reference-condition mapping closure is invalid")
        try:
            _reference_condition(authority.ratio_reference_condition)
            _source(authority.parameter_source)
            _confidence(authority.confidence)
        except ValueError as error:
            raise RuntimeError("rated load loss reference-condition domain is invalid") from error
    states = result.transformer_states
    if (
        tuple(states.columns) != _COLUMNS
        or states.index.name != "transformer_id"
        or states.index.has_duplicates
        or states.index.tolist() != ids
    ):
        raise RuntimeError("transformer series-equivalent schema/index/order is invalid")
    for column in _COLUMNS:
        expected_dtype = (
            "bool"
            if column in _BOOL_COLUMNS
            else "float64"
            if column in _FLOAT_COLUMNS
            else "object"
        )
        if str(states[column].dtype) != expected_dtype:
            raise RuntimeError(f"transformer series-equivalent dtype is invalid for {column}")
    expected_records: list[dict[str, object]] = []
    for transformer_id in ids:
        expected = _validator_record(
            static.transformer_states.loc[transformer_id],
            static.equipment_by_id.get(transformer_id),
            loss.rated_load_loss_by_id.get(transformer_id),
            network.transformer_states.loc[transformer_id],
            network.short_circuit_impedance_by_id.get(transformer_id),
            result.rated_load_loss_reference_condition_by_id.get(transformer_id),
        )
        # Independently close the central equations for resolved rows.
        row = states.loc[transformer_id]
        for column, value in expected.items():
            if not _equal(row[column], value):
                raise RuntimeError(f"transformer series-equivalent row failed closure for {column}")
        if bool(row["transformer_series_equivalent_resolved"]):
            s = float(row["rated_apparent_power_va"])
            v = float(row["reference_side_rated_line_to_line_rms_v"])
            i = float(row["reference_side_rated_current_a"])
            p = float(row["factory_rated_load_loss_w"])
            r_pu = float(row["effective_series_resistance_pu"])
            x_pu = float(row["effective_series_reactance_pu"])
            z_pu = float(row["short_circuit_impedance_magnitude_pu"])
            z_base = float(row["short_circuit_impedance_base_ohm_per_phase"])
            r_ohm = float(row["effective_series_resistance_ohm_per_phase"])
            x_ohm = float(row["effective_series_reactance_ohm_per_phase"])
            z_ohm = float(row["short_circuit_impedance_magnitude_ohm_per_phase"])
            closures = (
                math.isclose(i, s / (math.sqrt(3.0) * v), rel_tol=1e-12, abs_tol=0.0),
                math.isclose(r_pu, p / s, rel_tol=1e-12, abs_tol=0.0),
                math.isclose(z_base, v * v / s, rel_tol=1e-12, abs_tol=0.0),
                math.isclose(z_ohm, z_pu * z_base, rel_tol=1e-12, abs_tol=0.0),
                math.isclose(r_ohm, r_pu * z_base, rel_tol=1e-12, abs_tol=0.0),
                math.isclose(math.hypot(r_pu, x_pu), z_pu, rel_tol=1e-12, abs_tol=0.0),
                math.isclose(math.hypot(r_ohm, x_ohm), z_ohm, rel_tol=1e-12, abs_tol=0.0),
                math.isclose(3.0 * i * i * r_ohm, p, rel_tol=1e-12, abs_tol=0.0),
            )
            if not all(closures):
                raise RuntimeError("transformer series-equivalent physical equations do not close")
        expected_records.append(expected)
    expected_frame = _state_frame(ids, expected_records)
    expected_diagnostics = _build_diagnostics(
        expected_frame, result.rated_load_loss_reference_condition_by_id
    )
    if result.diagnostics != expected_diagnostics:
        raise RuntimeError("transformer series-equivalent diagnostics failed exact closure")
    primary_total = sum(
        getattr(result.diagnostics, field)
        for field in (
            "series_equivalent_resolved_count",
            "unresolved_missing_equipment_basis_count",
            "unresolved_missing_rated_load_loss_count",
            "unresolved_missing_network_authority_count",
            "unresolved_missing_impedance_count",
            "unresolved_missing_load_loss_reference_condition_count",
            "unresolved_incompatible_reference_sides_count",
            "unresolved_incompatible_ratio_reference_conditions_count",
            "unresolved_incompatible_reference_temperatures_count",
            "unresolved_incompatible_test_frequencies_count",
            "unresolved_load_loss_exceeds_impedance_count",
        )
    )
    if primary_total != result.diagnostics.transformer_count:
        raise RuntimeError("transformer series-equivalent diagnostics do not partition rows")
    if result.diagnostics.model != TRANSFORMER_SERIES_EQUIVALENT_MODEL_ID:
        raise RuntimeError("transformer series-equivalent diagnostics model is invalid")
