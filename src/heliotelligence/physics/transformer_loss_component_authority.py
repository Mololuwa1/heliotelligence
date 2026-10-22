"""Static transformer construction and factory load-loss component authority.

S12H decomposes the S12B total rated load loss into factory-reference I2R,
winding-eddy, and canonical residual other-stray components.  The components
are the same loss already represented by S12B and S12F, not additional loss.
No operating, harmonic, thermal, core-loss, or terminal calculation occurs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from types import MappingProxyType
from typing import Any, Literal, TypeVar, cast

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

TRANSFORMER_LOSS_COMPONENT_AUTHORITY_CONTRACT_ID = (
    "admitted_transformer_static_and_factory_loss_authority_to_advanced_"
    "construction_and_load_loss_component_basis_v1"
)
TRANSFORMER_LOSS_COMPONENT_AUTHORITY_MODEL_ID = (
    "explicit_transformer_construction_and_factory_reference_i2r_"
    "winding_eddy_other_stray_loss_component_basis_v1"
)
TRANSFORMER_LOSS_COMPONENT_AUTHORITY_SCOPE = (
    "static_transformer_advanced_loss_basis_before_harmonic_thermal_and_core_loss_correction"
)
TRANSFORMER_LOSS_COMPONENT_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_transformer_construction_metadata_and_three_component_"
    "rated_load_loss_decomposition_closing_to_s12b_total_rated_load_loss"
)
REFERENCE_LOAD_LOSS_OWNERSHIP = "decomposition_of_s12b_total_rated_load_loss_not_additional_loss"

Confidence = Literal["high", "medium", "low", "unknown"]
ThermalConstructionFamily = Literal["mineral_oil_immersed", "dry_type", "other_explicit"]
WindingConductorMaterial = Literal["copper", "aluminium", "mixed_or_other_explicit"]
CoreMaterialFamily = Literal[
    "conventional_silicon_steel",
    "crgo_silicon_steel",
    "high_permeability_crgo",
    "amorphous_metal",
    "nanocrystalline",
    "other_explicit",
]
ReferenceSide = Literal["collection_side", "network_side"]
DecompositionMethod = Literal[
    "factory_test_report",
    "manufacturer_design_data",
    "certified_test_plus_resistance_calculation",
    "other_documented",
]

_CONFIDENCES = {"high", "medium", "low", "unknown"}
_THERMAL_FAMILIES = {"mineral_oil_immersed", "dry_type", "other_explicit"}
_CONDUCTORS = {"copper", "aluminium", "mixed_or_other_explicit"}
_CORE_FAMILIES = {
    "conventional_silicon_steel",
    "crgo_silicon_steel",
    "high_permeability_crgo",
    "amorphous_metal",
    "nanocrystalline",
    "other_explicit",
}
_SIDES = {"collection_side", "network_side"}
_METHODS = {
    "factory_test_report",
    "manufacturer_design_data",
    "certified_test_plus_resistance_calculation",
    "other_documented",
}
_COMPONENT_SEMANTICS = (
    "rated_total_load_loss_three_component_decomposition_at_factory_reference_condition"
)
_REL_TOL = 1e-12
_ABSOLUTE_ZERO_C = -273.15

AuthorityT = TypeVar(
    "AuthorityT",
    "TransformerAdvancedConstructionAuthority",
    "TransformerRatedLoadLossComponentAuthority",
    "TransformerRatedLoadLossAggregateStrayAuthority",
)

_STATES = (
    "unresolved_upstream_transformer_static_authority",
    "unresolved_missing_s12b_rated_load_loss_authority",
    "unresolved_missing_transformer_advanced_construction_authority",
    "unresolved_missing_transformer_rated_load_loss_component_authority",
    "unresolved_incompatible_load_loss_component_reference_side",
    "unresolved_incompatible_load_loss_component_reference_temperature",
    "unresolved_incompatible_load_loss_component_test_frequency",
    "unresolved_component_i2r_plus_winding_eddy_exceeds_s12b_rated_load_loss",
    "unresolved_reported_other_stray_loss_inconsistent_with_s12b_residual",
    "resolved_transformer_factory_load_loss_explicit_components_resolution_bounded",
    "resolved_transformer_factory_load_loss_aggregate_stray_basis",
    "resolved_transformer_factory_load_loss_aggregate_stray_resolution_bounded",
    "resolved_transformer_advanced_loss_basis",
)

_BOOL_COLUMNS = {
    "transformer_static_authority_resolved",
    "s12b_rated_load_loss_authority_present",
    "transformer_advanced_construction_authority_present",
    "transformer_rated_load_loss_component_authority_present",
    "transformer_construction_basis_resolved",
    "transformer_load_loss_component_basis_resolved",
    "transformer_advanced_loss_basis_resolved",
    "component_reference_side_compatible",
    "component_reference_temperature_compatible",
    "component_test_frequency_compatible",
    "component_math_compatible",
    "reported_other_stray_loss_compatible",
    "reported_other_stray_loss_present",
    "other_stray_loss_residual_derived",
    "component_closure_roundoff_adjusted",
    "transformer_factory_load_loss_evidence_resolved",
    "source_resolution_authority_present",
    "source_resolution_applied",
    "strict_point_component_closure_resolved",
    "resolution_bounded_closure_resolved",
    "aggregate_stray_basis_resolved",
    "advanced_component_correction_eligible",
}
_FLOAT_COLUMNS = {
    "s12b_rated_load_loss_w",
    "s12b_load_loss_reference_temperature_c",
    "s12b_load_loss_test_frequency_hz",
    "i2r_loss_reference_w",
    "winding_eddy_current_loss_reference_w",
    "reported_other_stray_loss_w",
    "canonical_other_stray_loss_reference_w",
    "canonical_component_sum_w",
    "component_closure_residual_w",
    "component_reference_temperature_c",
    "component_test_frequency_hz",
    "rated_load_loss_reported_resolution_w",
    "i2r_loss_reported_resolution_w",
    "winding_eddy_current_loss_reported_resolution_w",
    "reported_other_stray_loss_reported_resolution_w",
    "reported_total_stray_loss_w",
    "reported_total_stray_loss_reported_resolution_w",
    "rated_load_loss_lower_bound_w",
    "rated_load_loss_upper_bound_w",
    "i2r_loss_lower_bound_w",
    "i2r_loss_upper_bound_w",
    "winding_eddy_loss_lower_bound_w",
    "winding_eddy_loss_upper_bound_w",
    "derived_aggregate_stray_loss_nominal_w",
    "derived_aggregate_stray_loss_lower_bound_w",
    "derived_aggregate_stray_loss_upper_bound_w",
    "derived_other_stray_loss_lower_bound_w",
    "derived_other_stray_loss_upper_bound_w",
}
_COLUMNS = (
    "transformer_static_authority_resolved",
    "s12b_rated_load_loss_authority_present",
    "transformer_advanced_construction_authority_present",
    "transformer_rated_load_loss_component_authority_present",
    "transformer_construction_basis_resolved",
    "transformer_load_loss_component_basis_resolved",
    "transformer_advanced_loss_basis_resolved",
    "component_reference_side_compatible",
    "component_reference_temperature_compatible",
    "component_test_frequency_compatible",
    "component_math_compatible",
    "reported_other_stray_loss_compatible",
    "s12b_rated_load_loss_w",
    "s12b_load_loss_test_current_reference_side",
    "s12b_load_loss_reference_temperature_c",
    "s12b_load_loss_test_frequency_hz",
    "i2r_loss_reference_w",
    "winding_eddy_current_loss_reference_w",
    "reported_other_stray_loss_w",
    "canonical_other_stray_loss_reference_w",
    "canonical_component_sum_w",
    "component_closure_residual_w",
    "reported_other_stray_loss_present",
    "other_stray_loss_residual_derived",
    "component_closure_roundoff_adjusted",
    "transformer_factory_load_loss_evidence_resolved",
    "source_resolution_authority_present",
    "source_resolution_applied",
    "strict_point_component_closure_resolved",
    "resolution_bounded_closure_resolved",
    "aggregate_stray_basis_resolved",
    "advanced_component_correction_eligible",
    "factory_load_loss_evidence_fidelity",
    "source_rounding_semantics",
    "rated_load_loss_reported_resolution_w",
    "i2r_loss_reported_resolution_w",
    "winding_eddy_current_loss_reported_resolution_w",
    "reported_other_stray_loss_reported_resolution_w",
    "reported_total_stray_loss_w",
    "reported_total_stray_loss_reported_resolution_w",
    "rated_load_loss_lower_bound_w",
    "rated_load_loss_upper_bound_w",
    "i2r_loss_lower_bound_w",
    "i2r_loss_upper_bound_w",
    "winding_eddy_loss_lower_bound_w",
    "winding_eddy_loss_upper_bound_w",
    "derived_aggregate_stray_loss_nominal_w",
    "derived_aggregate_stray_loss_lower_bound_w",
    "derived_aggregate_stray_loss_upper_bound_w",
    "derived_other_stray_loss_lower_bound_w",
    "derived_other_stray_loss_upper_bound_w",
    "thermal_construction_family",
    "winding_conductor_material",
    "conductor_material_description",
    "cooling_method_code",
    "core_material_family",
    "core_material_description",
    "component_test_current_reference_side",
    "component_reference_temperature_c",
    "component_test_frequency_hz",
    "component_basis_semantics",
    "decomposition_method",
    "construction_parameter_source",
    "construction_confidence",
    "component_parameter_source",
    "component_confidence",
    "reference_load_loss_ownership",
    "transformer_static_authority_contract",
    "transformer_static_authority_model",
    "transformer_loss_authority_contract",
    "transformer_loss_authority_model",
    "transformer_loss_component_authority_contract",
    "transformer_loss_component_authority_model",
    "transformer_loss_component_authority_scope",
    "transformer_loss_component_authority_coverage_scope",
    "transformer_loss_component_authority_state",
)


def _exact_text(value: object, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be an exact non-empty string without whitespace padding")
    return value


def _literal(value: object, allowed: set[str], name: str) -> str:
    if type(value) is not str or value not in allowed:
        raise ValueError(f"{name} is unsupported")
    return value


def _number(value: object, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a non-Boolean real number")
    result = float(value)
    if not math.isfinite(result) or (result <= 0.0 if positive else result < 0.0):
        qualifier = "strictly positive" if positive else "non-negative"
        raise ValueError(f"{name} must be finite and {qualifier}")
    return result


@dataclass(frozen=True)
class TransformerAdvancedConstructionAuthority:
    transformer_id: str
    thermal_construction_family: ThermalConstructionFamily
    winding_conductor_material: WindingConductorMaterial
    conductor_material_description: str
    cooling_method_code: str
    core_material_family: CoreMaterialFamily
    core_material_description: str
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _exact_text(self.transformer_id, "transformer_id")
        _literal(self.thermal_construction_family, _THERMAL_FAMILIES, "thermal family")
        _literal(self.winding_conductor_material, _CONDUCTORS, "conductor material")
        _exact_text(self.conductor_material_description, "conductor material description")
        _exact_text(self.cooling_method_code, "cooling method code")
        _literal(self.core_material_family, _CORE_FAMILIES, "core material family")
        _exact_text(self.core_material_description, "core material description")
        _exact_text(self.parameter_source, "parameter_source")
        _literal(self.confidence, _CONFIDENCES, "confidence")


@dataclass(frozen=True)
class TransformerRatedLoadLossComponentAuthority:
    transformer_id: str
    i2r_loss_w: float
    winding_eddy_current_loss_w: float
    reported_other_stray_loss_w: float | None
    test_current_reference_side: ReferenceSide
    test_current_condition: Literal["rated_current"]
    reference_temperature_c: float
    test_frequency_hz: float
    component_basis_semantics: Literal[
        "rated_total_load_loss_three_component_decomposition_at_factory_reference_condition"
    ]
    decomposition_method: DecompositionMethod
    parameter_source: str
    confidence: Confidence
    i2r_loss_reported_resolution_w: float | None = None
    winding_eddy_current_loss_reported_resolution_w: float | None = None
    reported_other_stray_loss_reported_resolution_w: float | None = None
    rounding_semantics: Literal["nearest_increment"] | None = None

    def __post_init__(self) -> None:
        _exact_text(self.transformer_id, "transformer_id")
        _number(self.i2r_loss_w, "i2r_loss_w")
        _number(self.winding_eddy_current_loss_w, "winding_eddy_current_loss_w")
        if self.reported_other_stray_loss_w is not None:
            _number(self.reported_other_stray_loss_w, "reported_other_stray_loss_w")
        _literal(self.test_current_reference_side, _SIDES, "test current reference side")
        _literal(self.test_current_condition, {"rated_current"}, "test current condition")
        if isinstance(self.reference_temperature_c, bool) or not isinstance(
            self.reference_temperature_c, Real
        ):
            raise ValueError("reference_temperature_c must be a non-Boolean real number")
        temperature = float(self.reference_temperature_c)
        if not math.isfinite(temperature) or temperature <= _ABSOLUTE_ZERO_C:
            raise ValueError("reference_temperature_c must be finite and above absolute zero")
        _number(self.test_frequency_hz, "test_frequency_hz", positive=True)
        _literal(
            self.component_basis_semantics,
            {_COMPONENT_SEMANTICS},
            "component basis semantics",
        )
        _literal(self.decomposition_method, _METHODS, "decomposition method")
        _exact_text(self.parameter_source, "parameter_source")
        _literal(self.confidence, _CONFIDENCES, "confidence")
        _validate_resolutions(
            (
                self.i2r_loss_reported_resolution_w,
                self.winding_eddy_current_loss_reported_resolution_w,
                self.reported_other_stray_loss_reported_resolution_w,
            ),
            self.rounding_semantics,
        )
        if (
            self.reported_other_stray_loss_reported_resolution_w is not None
            and self.reported_other_stray_loss_w is None
        ):
            raise ValueError("other-stray resolution requires a reported other-stray value")


@dataclass(frozen=True)
class TransformerRatedLoadLossAggregateStrayAuthority:
    transformer_id: str
    i2r_loss_w: float
    reported_total_stray_loss_w: float | None
    test_current_reference_side: ReferenceSide
    test_current_condition: Literal["rated_current"]
    reference_temperature_c: float
    test_frequency_hz: float
    evidence_basis_semantics: Literal[
        "rated_total_load_loss_i2r_and_aggregate_stray_at_factory_reference_condition"
    ]
    decomposition_method: DecompositionMethod
    parameter_source: str
    confidence: Confidence
    i2r_loss_reported_resolution_w: float | None = None
    reported_total_stray_loss_reported_resolution_w: float | None = None
    rounding_semantics: Literal["nearest_increment"] | None = None

    def __post_init__(self) -> None:
        _exact_text(self.transformer_id, "transformer_id")
        _number(self.i2r_loss_w, "i2r_loss_w")
        if self.reported_total_stray_loss_w is not None:
            _number(self.reported_total_stray_loss_w, "reported_total_stray_loss_w")
        _literal(self.test_current_reference_side, _SIDES, "test current reference side")
        _literal(self.test_current_condition, {"rated_current"}, "test current condition")
        temperature = float(self.reference_temperature_c)
        if (
            isinstance(self.reference_temperature_c, bool)
            or not isinstance(self.reference_temperature_c, Real)
            or not math.isfinite(temperature)
            or temperature <= _ABSOLUTE_ZERO_C
        ):
            raise ValueError("reference_temperature_c must be finite and above absolute zero")
        _number(self.test_frequency_hz, "test_frequency_hz", positive=True)
        _literal(
            self.evidence_basis_semantics,
            {"rated_total_load_loss_i2r_and_aggregate_stray_at_factory_reference_condition"},
            "evidence basis semantics",
        )
        _literal(self.decomposition_method, _METHODS, "decomposition method")
        _exact_text(self.parameter_source, "parameter_source")
        _literal(self.confidence, _CONFIDENCES, "confidence")
        _validate_resolutions(
            (
                self.i2r_loss_reported_resolution_w,
                self.reported_total_stray_loss_reported_resolution_w,
            ),
            self.rounding_semantics,
        )
        if (
            self.reported_total_stray_loss_reported_resolution_w is not None
            and self.reported_total_stray_loss_w is None
        ):
            raise ValueError("aggregate-stray resolution requires a reported aggregate value")


def _validate_resolutions(resolutions: tuple[float | None, ...], semantics: object) -> None:
    present = [resolution for resolution in resolutions if resolution is not None]
    if not present:
        if semantics is not None:
            raise ValueError("rounding semantics requires source resolution authority")
        return
    if semantics != "nearest_increment":
        raise ValueError("rounding semantics must be nearest_increment")
    for resolution in present:
        _number(resolution, "reported resolution", positive=True)


@dataclass(frozen=True)
class TopologyTransformerLossComponentAuthorityDiagnostics:
    transformer_count: int
    construction_authority_count: int
    component_authority_count: int
    construction_basis_resolved_count: int
    load_loss_component_basis_resolved_count: int
    advanced_loss_basis_resolved_count: int
    missing_s12b_rated_load_count: int
    missing_construction_count: int
    missing_component_count: int
    incompatible_side_count: int
    incompatible_temperature_count: int
    incompatible_frequency_count: int
    component_math_incompatible_count: int
    reported_other_stray_incompatible_count: int
    residual_other_stray_derived_count: int
    roundoff_adjusted_count: int
    explicit_three_component_exact_count: int
    explicit_three_component_resolution_bounded_count: int
    aggregate_stray_exact_count: int
    aggregate_stray_resolution_bounded_count: int
    unresolved_factory_evidence_count: int
    state_counts: tuple[tuple[str, int], ...]
    model: str


@dataclass(frozen=True)
class TopologyTransformerLossComponentAuthorityResult:
    construction_by_id: Mapping[str, TransformerAdvancedConstructionAuthority]
    rated_load_loss_component_by_id: Mapping[
        str,
        TransformerRatedLoadLossComponentAuthority
        | TransformerRatedLoadLossAggregateStrayAuthority,
    ]
    transformer_states: pd.DataFrame
    diagnostics: TopologyTransformerLossComponentAuthorityDiagnostics


def resolve_transformer_loss_component_authority(
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
    transformer_construction_by_id: Mapping[str, TransformerAdvancedConstructionAuthority],
    transformer_rated_load_loss_component_by_id: Mapping[
        str,
        TransformerRatedLoadLossComponentAuthority
        | TransformerRatedLoadLossAggregateStrayAuthority,
    ],
) -> TopologyTransformerLossComponentAuthorityResult:
    """Resolve explicit construction and factory rated-load component evidence."""
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
    ids = canonical_static.transformer_states.index.tolist()
    construction = cast(
        dict[str, TransformerAdvancedConstructionAuthority],
        _admit_mapping(
            transformer_construction_by_id,
            set(ids),
            TransformerAdvancedConstructionAuthority,
            "construction",
        ),
    )
    components = cast(
        dict[
            str,
            TransformerRatedLoadLossComponentAuthority
            | TransformerRatedLoadLossAggregateStrayAuthority,
        ],
        _admit_mapping(
            transformer_rated_load_loss_component_by_id,
            set(ids),
            (
                TransformerRatedLoadLossComponentAuthority,
                TransformerRatedLoadLossAggregateStrayAuthority,
            ),
            "rated load loss component",
        ),
    )
    records = [
        _build_record(
            canonical_static.transformer_states.loc[identifier],
            canonical_loss.rated_load_loss_by_id.get(identifier),
            construction.get(identifier),
            components.get(identifier),
        )
        for identifier in ids
    ]
    states = _frame(ids, records)
    diagnostics = _diagnostics(states)
    result = TopologyTransformerLossComponentAuthorityResult(
        MappingProxyType(dict(construction)),
        MappingProxyType(dict(components)),
        states.copy(deep=True),
        diagnostics,
    )
    _validate_result(canonical_static, canonical_loss, construction, components, result)
    return result


def _validate_static_replay(
    supplied: TopologyTransformerStaticAuthorityResult,
    canonical: TopologyTransformerStaticAuthorityResult,
) -> None:
    if type(supplied) is not TopologyTransformerStaticAuthorityResult:
        raise ValueError("supplied S12A result type is invalid")
    for name in ("equipment_by_id", "topology_by_id"):
        actual = getattr(supplied, name)
        if type(actual) is not MappingProxyType or dict(actual) != dict(getattr(canonical, name)):
            raise ValueError(f"supplied S12A {name} failed immutable canonical replay")
    _frame_equal(supplied.transformer_states, canonical.transformer_states, "S12A")
    if supplied.diagnostics != canonical.diagnostics:
        raise ValueError("supplied S12A diagnostics failed canonical replay")


def _validate_loss_replay(
    supplied: TopologyTransformerLossAuthorityResult,
    canonical: TopologyTransformerLossAuthorityResult,
) -> None:
    if type(supplied) is not TopologyTransformerLossAuthorityResult:
        raise ValueError("supplied S12B result type is invalid")
    for name in ("no_load_loss_by_id", "rated_load_loss_by_id"):
        actual = getattr(supplied, name)
        if type(actual) is not MappingProxyType or dict(actual) != dict(getattr(canonical, name)):
            raise ValueError(f"supplied S12B {name} failed immutable canonical replay")
    _frame_equal(supplied.transformer_states, canonical.transformer_states, "S12B")
    if supplied.diagnostics != canonical.diagnostics:
        raise ValueError("supplied S12B diagnostics failed canonical replay")


def _frame_equal(actual: pd.DataFrame, expected: pd.DataFrame, label: str) -> None:
    try:
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    except AssertionError as error:
        raise ValueError(f"supplied {label} frame failed canonical replay") from error


def _admit_mapping(
    supplied: Mapping[str, Any],
    known: set[str],
    expected_type: type[Any] | tuple[type[Any], ...],
    label: str,
) -> dict[str, Any]:
    if not isinstance(supplied, Mapping):
        raise TypeError(f"{label} authority must be a mapping")
    admitted: dict[str, Any] = {}
    for key, value in supplied.items():
        _exact_text(key, "transformer mapping key")
        expected_types = expected_type if isinstance(expected_type, tuple) else (expected_type,)
        if type(value) not in expected_types:
            raise TypeError(f"{label} authority has invalid value type")
        if key != value.transformer_id:
            raise ValueError(f"{label} mapping key mismatch")
        if key not in known:
            raise ValueError(f"{label} references unknown transformer")
        admitted[key] = value
    return dict(sorted(admitted.items()))


def _closure(
    rated: TransformerRatedLoadLossAuthority | None,
    component: TransformerRatedLoadLossComponentAuthority | None,
) -> tuple[bool, bool, bool, bool, bool, float, float, float, bool]:
    if rated is None or component is None:
        return False, False, False, False, False, math.nan, math.nan, math.nan, False
    side_ok = rated.test_current_reference_side == component.test_current_reference_side
    temperature_ok = rated.reference_temperature_c == component.reference_temperature_c
    frequency_ok = rated.test_frequency_hz == component.test_frequency_hz
    try:
        known = math.fsum([component.i2r_loss_w, component.winding_eddy_current_loss_w])
    except OverflowError:
        known = math.inf
    roundoff = False
    math_ok = math.isfinite(known) and known <= rated.rated_load_loss_w
    if not math_ok and math.isclose(known, rated.rated_load_loss_w, rel_tol=_REL_TOL, abs_tol=0.0):
        math_ok = True
        roundoff = True
    residual = max(0.0, rated.rated_load_loss_w - known) if math_ok else math.nan
    total = math.fsum([known, residual]) if math_ok else math.nan
    closure_residual = rated.rated_load_loss_w - total if math_ok else math.nan
    reported_ok = component.reported_other_stray_loss_w is None or (
        math_ok
        and math.isclose(
            component.reported_other_stray_loss_w,
            residual,
            rel_tol=_REL_TOL,
            abs_tol=0.0,
        )
    )
    return (
        side_ok,
        temperature_ok,
        frequency_ok,
        math_ok,
        reported_ok,
        residual,
        total,
        closure_residual,
        roundoff,
    )


def _primary_state(
    static: bool,
    rated: bool,
    construction: bool,
    component: bool,
    side: bool,
    temperature: bool,
    frequency: bool,
    math_ok: bool,
    reported_ok: bool,
    fidelity: str,
) -> str:
    conditions = (
        static,
        rated,
        construction,
        component,
        side,
        temperature,
        frequency,
        math_ok,
        reported_ok,
    )
    for condition, state in zip(conditions, _STATES[:9], strict=True):
        if not condition:
            return state
    return {
        "explicit_three_component_exact": "resolved_transformer_advanced_loss_basis",
        "explicit_three_component_resolution_bounded": (
            "resolved_transformer_factory_load_loss_explicit_components_resolution_bounded"
        ),
        "aggregate_stray_exact": "resolved_transformer_factory_load_loss_aggregate_stray_basis",
        "aggregate_stray_resolution_bounded": (
            "resolved_transformer_factory_load_loss_aggregate_stray_resolution_bounded"
        ),
    }.get(fidelity, "unresolved_component_i2r_plus_winding_eddy_exceeds_s12b_rated_load_loss")


def _source_interval(value: float, resolution: float | None) -> tuple[float, float]:
    if resolution is None:
        return value, value
    lower = max(0.0, value - resolution / 2.0)
    upper = value + resolution / 2.0
    if not math.isfinite(lower) or not math.isfinite(upper) or lower > upper:
        raise ValueError("source-resolution interval is nonfinite or inverted")
    return lower, upper


def _evidence(
    rated: TransformerRatedLoadLossAuthority | None,
    component: TransformerRatedLoadLossComponentAuthority
    | TransformerRatedLoadLossAggregateStrayAuthority
    | None,
) -> dict[str, object]:
    nan = math.nan
    result: dict[str, object] = {
        "strict": False,
        "bounded": False,
        "resolved": False,
        "fidelity": "unresolved",
        "resolution_present": False,
        "resolution_applied": False,
        "aggregate": False,
        "total_bounds": (nan, nan),
        "i2r_bounds": (nan, nan),
        "eddy_bounds": (nan, nan),
        "aggregate_bounds": (nan, nan),
        "other_bounds": (nan, nan),
        "aggregate_nominal": nan,
    }
    if rated is None or component is None:
        return result
    total_resolution = rated.reported_resolution_w
    i2r_resolution = component.i2r_loss_reported_resolution_w
    resolution_present = total_resolution is not None or i2r_resolution is not None
    try:
        total_bounds = _source_interval(rated.rated_load_loss_w, total_resolution)
        i2r_bounds = _source_interval(component.i2r_loss_w, i2r_resolution)
        result.update(
            resolution_present=resolution_present,
            total_bounds=total_bounds,
            i2r_bounds=i2r_bounds,
        )
        if type(component) is TransformerRatedLoadLossAggregateStrayAuthority:
            resolution_present = resolution_present or (
                component.reported_total_stray_loss_reported_resolution_w is not None
            )
            strict_math = component.i2r_loss_w <= rated.rated_load_loss_w
            nominal = max(0.0, rated.rated_load_loss_w - component.i2r_loss_w)
            strict_report = component.reported_total_stray_loss_w is None or (
                strict_math
                and math.isclose(
                    component.reported_total_stray_loss_w,
                    nominal,
                    rel_tol=_REL_TOL,
                    abs_tol=0.0,
                )
            )
            lower = max(0.0, total_bounds[0] - i2r_bounds[1])
            upper = max(0.0, total_bounds[1] - i2r_bounds[0])
            bounded = i2r_bounds[0] <= total_bounds[1] and lower <= upper
            if component.reported_total_stray_loss_w is not None:
                reported_bounds = _source_interval(
                    component.reported_total_stray_loss_w,
                    component.reported_total_stray_loss_reported_resolution_w,
                )
                bounded = bounded and max(lower, reported_bounds[0]) <= min(
                    upper, reported_bounds[1]
                )
            strict = strict_math and strict_report
            resolved = strict or (resolution_present and bounded)
            fidelity = (
                "aggregate_stray_exact"
                if strict
                else "aggregate_stray_resolution_bounded"
                if resolved
                else "unresolved"
            )
            result.update(
                strict=strict,
                bounded=bounded,
                resolved=resolved,
                fidelity=fidelity,
                resolution_present=resolution_present,
                resolution_applied=resolved and not strict,
                aggregate=resolved,
                aggregate_bounds=(lower, upper),
                aggregate_nominal=nominal if resolved else nan,
            )
            return result
        explicit_component = cast(TransformerRatedLoadLossComponentAuthority, component)
        resolution_present = resolution_present or any(
            value is not None
            for value in (
                explicit_component.winding_eddy_current_loss_reported_resolution_w,
                explicit_component.reported_other_stray_loss_reported_resolution_w,
            )
        )
        eddy_bounds = _source_interval(
            explicit_component.winding_eddy_current_loss_w,
            explicit_component.winding_eddy_current_loss_reported_resolution_w,
        )
        known_lower = math.fsum((i2r_bounds[0], eddy_bounds[0]))
        known_upper = math.fsum((i2r_bounds[1], eddy_bounds[1]))
        other_lower = max(0.0, total_bounds[0] - known_upper)
        other_upper = max(0.0, total_bounds[1] - known_lower)
        bounded = known_lower <= total_bounds[1] and other_lower <= other_upper
        if explicit_component.reported_other_stray_loss_w is not None:
            reported_bounds = _source_interval(
                explicit_component.reported_other_stray_loss_w,
                explicit_component.reported_other_stray_loss_reported_resolution_w,
            )
            bounded = bounded and max(other_lower, reported_bounds[0]) <= min(
                other_upper, reported_bounds[1]
            )
        closure = _closure(rated, explicit_component)
        strict = all(closure[index] for index in (3, 4))
        resolved = strict or (resolution_present and bounded)
        fidelity = (
            "explicit_three_component_exact"
            if strict
            else "explicit_three_component_resolution_bounded"
            if resolved
            else "unresolved"
        )
        result.update(
            strict=strict,
            bounded=bounded,
            resolved=resolved,
            fidelity=fidelity,
            resolution_present=resolution_present,
            resolution_applied=resolved and not strict,
            eddy_bounds=eddy_bounds,
            other_bounds=(other_lower, other_upper),
        )
    except (OverflowError, ValueError):
        return result
    return result


def _build_record(
    static_row: pd.Series,
    rated: TransformerRatedLoadLossAuthority | None,
    construction: TransformerAdvancedConstructionAuthority | None,
    component: TransformerRatedLoadLossComponentAuthority
    | TransformerRatedLoadLossAggregateStrayAuthority
    | None,
) -> dict[str, object]:
    return _record_values(static_row, rated, construction, component)


def _record_values(
    static_row: pd.Series,
    rated: TransformerRatedLoadLossAuthority | None,
    construction: TransformerAdvancedConstructionAuthority | None,
    component: TransformerRatedLoadLossComponentAuthority
    | TransformerRatedLoadLossAggregateStrayAuthority
    | None,
) -> dict[str, object]:
    static = bool(static_row["transformer_static_authority_resolved"])
    explicit = component if type(component) is TransformerRatedLoadLossComponentAuthority else None
    closure = _closure(rated, explicit)
    side, temperature, frequency, math_ok, reported_ok, residual, total, delta, adjusted = closure
    if rated is not None and component is not None:
        side = rated.test_current_reference_side == component.test_current_reference_side
        temperature = rated.reference_temperature_c == component.reference_temperature_c
        frequency = rated.test_frequency_hz == component.test_frequency_hz
    evidence = _evidence(rated, component)
    strict = bool(evidence["strict"])
    evidence_resolved = bool(evidence["resolved"]) and side and temperature and frequency
    if bool(evidence["resolved"]) and not strict:
        math_ok = True
        reported_ok = True
    elif type(component) is TransformerRatedLoadLossAggregateStrayAuthority:
        math_ok = bool(evidence["strict"] or evidence["bounded"])
        reported_ok = bool(evidence["resolved"])
    component_resolved = bool(explicit and strict and side and temperature and frequency)
    construction_resolved = construction is not None
    factory_resolved = bool(static and construction_resolved and evidence_resolved)
    state = _primary_state(
        static,
        rated is not None,
        construction_resolved,
        component is not None,
        side,
        temperature,
        frequency,
        math_ok,
        reported_ok,
        str(evidence["fidelity"]) if evidence_resolved else "unresolved",
    )
    nan = math.nan
    return {
        "transformer_static_authority_resolved": static,
        "s12b_rated_load_loss_authority_present": rated is not None,
        "transformer_advanced_construction_authority_present": construction is not None,
        "transformer_rated_load_loss_component_authority_present": component is not None,
        "transformer_construction_basis_resolved": construction_resolved,
        "transformer_load_loss_component_basis_resolved": component_resolved,
        "transformer_advanced_loss_basis_resolved": construction_resolved
        and component_resolved
        and static,
        "component_reference_side_compatible": side,
        "component_reference_temperature_compatible": temperature,
        "component_test_frequency_compatible": frequency,
        "component_math_compatible": math_ok,
        "reported_other_stray_loss_compatible": reported_ok,
        "s12b_rated_load_loss_w": rated.rated_load_loss_w if rated else nan,
        "s12b_load_loss_test_current_reference_side": (
            rated.test_current_reference_side if rated else ""
        ),
        "s12b_load_loss_reference_temperature_c": rated.reference_temperature_c if rated else nan,
        "s12b_load_loss_test_frequency_hz": rated.test_frequency_hz if rated else nan,
        "i2r_loss_reference_w": component.i2r_loss_w if component else nan,
        "winding_eddy_current_loss_reference_w": (
            explicit.winding_eddy_current_loss_w if explicit else nan
        ),
        "reported_other_stray_loss_w": (
            explicit.reported_other_stray_loss_w
            if explicit and explicit.reported_other_stray_loss_w is not None
            else nan
        ),
        "canonical_other_stray_loss_reference_w": residual if component_resolved else nan,
        "canonical_component_sum_w": total if component_resolved else nan,
        "component_closure_residual_w": delta if component_resolved else nan,
        "reported_other_stray_loss_present": bool(
            explicit and explicit.reported_other_stray_loss_w is not None
        ),
        "other_stray_loss_residual_derived": bool(
            explicit and explicit.reported_other_stray_loss_w is None and component_resolved
        ),
        "component_closure_roundoff_adjusted": adjusted,
        "transformer_factory_load_loss_evidence_resolved": factory_resolved,
        "source_resolution_authority_present": bool(evidence["resolution_present"]),
        "source_resolution_applied": bool(factory_resolved and evidence["resolution_applied"]),
        "strict_point_component_closure_resolved": bool(factory_resolved and strict),
        "resolution_bounded_closure_resolved": bool(
            factory_resolved and evidence["resolution_applied"]
        ),
        "aggregate_stray_basis_resolved": bool(factory_resolved and evidence["aggregate"]),
        "advanced_component_correction_eligible": bool(
            construction_resolved and component_resolved and static
        ),
        "factory_load_loss_evidence_fidelity": (
            evidence["fidelity"] if factory_resolved else "unresolved"
        ),
        "source_rounding_semantics": (
            component.rounding_semantics
            if component and component.rounding_semantics is not None
            else rated.rounding_semantics
            if rated and rated.rounding_semantics is not None
            else ""
        ),
        "rated_load_loss_reported_resolution_w": (
            rated.reported_resolution_w
            if rated and rated.reported_resolution_w is not None
            else nan
        ),
        "i2r_loss_reported_resolution_w": (
            component.i2r_loss_reported_resolution_w
            if component and component.i2r_loss_reported_resolution_w is not None
            else nan
        ),
        "winding_eddy_current_loss_reported_resolution_w": (
            explicit.winding_eddy_current_loss_reported_resolution_w
            if explicit and explicit.winding_eddy_current_loss_reported_resolution_w is not None
            else nan
        ),
        "reported_other_stray_loss_reported_resolution_w": (
            explicit.reported_other_stray_loss_reported_resolution_w
            if explicit and explicit.reported_other_stray_loss_reported_resolution_w is not None
            else nan
        ),
        "reported_total_stray_loss_w": (
            component.reported_total_stray_loss_w
            if type(component) is TransformerRatedLoadLossAggregateStrayAuthority
            and component.reported_total_stray_loss_w is not None
            else nan
        ),
        "reported_total_stray_loss_reported_resolution_w": (
            component.reported_total_stray_loss_reported_resolution_w
            if type(component) is TransformerRatedLoadLossAggregateStrayAuthority
            and component.reported_total_stray_loss_reported_resolution_w is not None
            else nan
        ),
        "rated_load_loss_lower_bound_w": cast(tuple[float, float], evidence["total_bounds"])[0],
        "rated_load_loss_upper_bound_w": cast(tuple[float, float], evidence["total_bounds"])[1],
        "i2r_loss_lower_bound_w": cast(tuple[float, float], evidence["i2r_bounds"])[0],
        "i2r_loss_upper_bound_w": cast(tuple[float, float], evidence["i2r_bounds"])[1],
        "winding_eddy_loss_lower_bound_w": cast(tuple[float, float], evidence["eddy_bounds"])[0],
        "winding_eddy_loss_upper_bound_w": cast(tuple[float, float], evidence["eddy_bounds"])[1],
        "derived_aggregate_stray_loss_nominal_w": evidence["aggregate_nominal"],
        "derived_aggregate_stray_loss_lower_bound_w": cast(
            tuple[float, float], evidence["aggregate_bounds"]
        )[0],
        "derived_aggregate_stray_loss_upper_bound_w": cast(
            tuple[float, float], evidence["aggregate_bounds"]
        )[1],
        "derived_other_stray_loss_lower_bound_w": cast(
            tuple[float, float], evidence["other_bounds"]
        )[0],
        "derived_other_stray_loss_upper_bound_w": cast(
            tuple[float, float], evidence["other_bounds"]
        )[1],
        "thermal_construction_family": (
            construction.thermal_construction_family if construction else ""
        ),
        "winding_conductor_material": (
            construction.winding_conductor_material if construction else ""
        ),
        "conductor_material_description": (
            construction.conductor_material_description if construction else ""
        ),
        "cooling_method_code": construction.cooling_method_code if construction else "",
        "core_material_family": construction.core_material_family if construction else "",
        "core_material_description": (
            construction.core_material_description if construction else ""
        ),
        "component_test_current_reference_side": (
            component.test_current_reference_side if component else ""
        ),
        "component_reference_temperature_c": (
            component.reference_temperature_c if component else nan
        ),
        "component_test_frequency_hz": component.test_frequency_hz if component else nan,
        "component_basis_semantics": (
            explicit.component_basis_semantics
            if explicit
            else component.evidence_basis_semantics
            if type(component) is TransformerRatedLoadLossAggregateStrayAuthority
            else ""
        ),
        "decomposition_method": component.decomposition_method if component else "",
        "construction_parameter_source": construction.parameter_source if construction else "",
        "construction_confidence": construction.confidence if construction else "",
        "component_parameter_source": component.parameter_source if component else "",
        "component_confidence": component.confidence if component else "",
        "reference_load_loss_ownership": REFERENCE_LOAD_LOSS_OWNERSHIP,
        "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
        "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
        "transformer_loss_authority_contract": TRANSFORMER_LOSS_AUTHORITY_CONTRACT_ID,
        "transformer_loss_authority_model": TRANSFORMER_LOSS_AUTHORITY_MODEL_ID,
        "transformer_loss_component_authority_contract": (
            TRANSFORMER_LOSS_COMPONENT_AUTHORITY_CONTRACT_ID
        ),
        "transformer_loss_component_authority_model": (
            TRANSFORMER_LOSS_COMPONENT_AUTHORITY_MODEL_ID
        ),
        "transformer_loss_component_authority_scope": (TRANSFORMER_LOSS_COMPONENT_AUTHORITY_SCOPE),
        "transformer_loss_component_authority_coverage_scope": (
            TRANSFORMER_LOSS_COMPONENT_AUTHORITY_COVERAGE_SCOPE
        ),
        "transformer_loss_component_authority_state": state,
    }


def _frame(ids: list[str], records: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(records, index=pd.Index(ids, name="transformer_id", dtype=object))
    frame = frame.reindex(columns=_COLUMNS)
    for column in _BOOL_COLUMNS:
        frame[column] = frame[column].astype(bool)
    for column in _FLOAT_COLUMNS:
        frame[column] = frame[column].astype("float64")
    for column in set(_COLUMNS) - _BOOL_COLUMNS - _FLOAT_COLUMNS:
        frame[column] = frame[column].astype(object)
    return frame


def _diagnostics(frame: pd.DataFrame) -> TopologyTransformerLossComponentAuthorityDiagnostics:
    states = tuple(
        (state, int((frame["transformer_loss_component_authority_state"] == state).sum()))
        for state in _STATES
    )
    return TopologyTransformerLossComponentAuthorityDiagnostics(
        len(frame),
        int(frame["transformer_advanced_construction_authority_present"].sum()),
        int(frame["transformer_rated_load_loss_component_authority_present"].sum()),
        int(frame["transformer_construction_basis_resolved"].sum()),
        int(frame["transformer_load_loss_component_basis_resolved"].sum()),
        int(frame["transformer_advanced_loss_basis_resolved"].sum()),
        int((~frame["s12b_rated_load_loss_authority_present"]).sum()),
        int((~frame["transformer_advanced_construction_authority_present"]).sum()),
        int((~frame["transformer_rated_load_loss_component_authority_present"]).sum()),
        int(
            (
                frame["s12b_rated_load_loss_authority_present"]
                & frame["transformer_rated_load_loss_component_authority_present"]
                & ~frame["component_reference_side_compatible"]
            ).sum()
        ),
        int(
            (
                frame["s12b_rated_load_loss_authority_present"]
                & frame["transformer_rated_load_loss_component_authority_present"]
                & ~frame["component_reference_temperature_compatible"]
            ).sum()
        ),
        int(
            (
                frame["s12b_rated_load_loss_authority_present"]
                & frame["transformer_rated_load_loss_component_authority_present"]
                & ~frame["component_test_frequency_compatible"]
            ).sum()
        ),
        int(
            (
                frame["s12b_rated_load_loss_authority_present"]
                & frame["transformer_rated_load_loss_component_authority_present"]
                & ~frame["component_math_compatible"]
            ).sum()
        ),
        int(
            (
                frame["s12b_rated_load_loss_authority_present"]
                & frame["transformer_rated_load_loss_component_authority_present"]
                & ~frame["reported_other_stray_loss_compatible"]
            ).sum()
        ),
        int(frame["other_stray_loss_residual_derived"].sum()),
        int(frame["component_closure_roundoff_adjusted"].sum()),
        int(
            (frame["factory_load_loss_evidence_fidelity"] == "explicit_three_component_exact").sum()
        ),
        int(
            (
                frame["factory_load_loss_evidence_fidelity"]
                == "explicit_three_component_resolution_bounded"
            ).sum()
        ),
        int((frame["factory_load_loss_evidence_fidelity"] == "aggregate_stray_exact").sum()),
        int(
            (
                frame["factory_load_loss_evidence_fidelity"] == "aggregate_stray_resolution_bounded"
            ).sum()
        ),
        int((frame["factory_load_loss_evidence_fidelity"] == "unresolved").sum()),
        states,
        TRANSFORMER_LOSS_COMPONENT_AUTHORITY_MODEL_ID,
    )


def _validate_result(
    static: TopologyTransformerStaticAuthorityResult,
    loss: TopologyTransformerLossAuthorityResult,
    expected_construction: Mapping[str, TransformerAdvancedConstructionAuthority],
    expected_components: Mapping[
        str,
        TransformerRatedLoadLossComponentAuthority
        | TransformerRatedLoadLossAggregateStrayAuthority,
    ],
    result: TopologyTransformerLossComponentAuthorityResult,
) -> None:
    if type(result) is not TopologyTransformerLossComponentAuthorityResult:
        raise RuntimeError("S12H result type is invalid")
    for name in ("construction_by_id", "rated_load_loss_component_by_id"):
        if type(getattr(result, name)) is not MappingProxyType:
            raise RuntimeError(f"S12H {name} must be immutable")
    if tuple(result.construction_by_id.items()) != tuple(expected_construction.items()):
        raise RuntimeError("S12H construction mapping failed independent closure")
    if tuple(result.rated_load_loss_component_by_id.items()) != tuple(expected_components.items()):
        raise RuntimeError("S12H component mapping failed independent closure")
    ids = static.transformer_states.index.tolist()
    expected_records = [
        _validator_record(
            static.transformer_states.loc[identifier],
            loss.rated_load_loss_by_id.get(identifier),
            expected_construction.get(identifier),
            expected_components.get(identifier),
        )
        for identifier in ids
    ]
    expected = _validator_frame(ids, expected_records)
    try:
        pd.testing.assert_frame_equal(result.transformer_states, expected, check_exact=True)
    except AssertionError as error:
        raise RuntimeError("S12H result frame failed independent closure") from error
    expected_diagnostics = _validator_diagnostics(expected)
    if result.diagnostics != expected_diagnostics:
        raise RuntimeError("S12H diagnostics failed independent closure")
    if sum(count for _, count in expected_diagnostics.state_counts) != len(expected):
        raise RuntimeError("S12H primary states do not partition transformers")


def _validator_interval(value: float, resolution: float | None) -> tuple[float, float]:
    if resolution is None:
        return value, value
    lower, upper = max(0.0, value - resolution / 2.0), value + resolution / 2.0
    if not math.isfinite(lower) or not math.isfinite(upper) or lower > upper:
        raise ValueError
    return lower, upper


def _validator_record(
    static_row: pd.Series,
    rated: TransformerRatedLoadLossAuthority | None,
    construction: TransformerAdvancedConstructionAuthority | None,
    component: TransformerRatedLoadLossComponentAuthority
    | TransformerRatedLoadLossAggregateStrayAuthority
    | None,
) -> dict[str, object]:
    """Independently reconstruct expected S12H evidence and component closure."""
    # The independent path reimplements the numerical closure and state choice.
    static_ok = bool(static_row["transformer_static_authority_resolved"])
    explicit = component if type(component) is TransformerRatedLoadLossComponentAuthority else None
    if rated is not None and explicit is not None:
        side_ok = rated.test_current_reference_side == explicit.test_current_reference_side
        temperature_ok = rated.reference_temperature_c == explicit.reference_temperature_c
        frequency_ok = rated.test_frequency_hz == explicit.test_frequency_hz
        try:
            known = math.fsum((explicit.i2r_loss_w, explicit.winding_eddy_current_loss_w))
        except OverflowError:
            known = math.inf
        adjusted = known > rated.rated_load_loss_w and math.isclose(
            known, rated.rated_load_loss_w, rel_tol=_REL_TOL, abs_tol=0.0
        )
        math_ok = math.isfinite(known) and (known <= rated.rated_load_loss_w or adjusted)
        residual = max(0.0, rated.rated_load_loss_w - known) if math_ok else math.nan
        total = math.fsum((known, residual)) if math_ok else math.nan
        delta = rated.rated_load_loss_w - total if math_ok else math.nan
        reported_ok = explicit.reported_other_stray_loss_w is None or (
            math_ok
            and math.isclose(
                explicit.reported_other_stray_loss_w,
                residual,
                rel_tol=_REL_TOL,
                abs_tol=0.0,
            )
        )
    else:
        side_ok = temperature_ok = frequency_ok = math_ok = reported_ok = adjusted = False
        residual = total = delta = math.nan
    nan = math.nan
    total_bounds = i2r_bounds = eddy_bounds = aggregate_bounds = other_bounds = (nan, nan)
    aggregate_nominal = nan
    resolution_present = resolution_applied = aggregate = False
    strict = bool(explicit and math_ok and reported_ok)
    bounded = False
    fidelity = "unresolved"
    if rated is not None and component is not None:
        side_ok = rated.test_current_reference_side == component.test_current_reference_side
        temperature_ok = rated.reference_temperature_c == component.reference_temperature_c
        frequency_ok = rated.test_frequency_hz == component.test_frequency_hz
        try:
            total_bounds = _validator_interval(rated.rated_load_loss_w, rated.reported_resolution_w)
            i2r_bounds = _validator_interval(
                component.i2r_loss_w, component.i2r_loss_reported_resolution_w
            )
            resolution_present = (
                rated.reported_resolution_w is not None
                or component.i2r_loss_reported_resolution_w is not None
            )
            if type(component) is TransformerRatedLoadLossAggregateStrayAuthority:
                resolution_present = resolution_present or (
                    component.reported_total_stray_loss_reported_resolution_w is not None
                )
                aggregate_nominal = max(0.0, rated.rated_load_loss_w - component.i2r_loss_w)
                strict_math = component.i2r_loss_w <= rated.rated_load_loss_w
                reported_ok = component.reported_total_stray_loss_w is None or (
                    strict_math
                    and math.isclose(
                        component.reported_total_stray_loss_w,
                        aggregate_nominal,
                        rel_tol=_REL_TOL,
                        abs_tol=0.0,
                    )
                )
                strict = strict_math and reported_ok
                aggregate_bounds = (
                    max(0.0, total_bounds[0] - i2r_bounds[1]),
                    max(0.0, total_bounds[1] - i2r_bounds[0]),
                )
                bounded = i2r_bounds[0] <= total_bounds[1]
                if component.reported_total_stray_loss_w is not None:
                    reported_bounds = _validator_interval(
                        component.reported_total_stray_loss_w,
                        component.reported_total_stray_loss_reported_resolution_w,
                    )
                    bounded = bounded and max(aggregate_bounds[0], reported_bounds[0]) <= min(
                        aggregate_bounds[1], reported_bounds[1]
                    )
                resolved = strict or (resolution_present and bounded)
                resolution_applied, aggregate = resolved and not strict, resolved
                math_ok, reported_ok = strict or bounded, resolved
                fidelity = (
                    "aggregate_stray_exact"
                    if strict
                    else "aggregate_stray_resolution_bounded"
                    if resolved
                    else "unresolved"
                )
            elif explicit is not None:
                resolution_present = resolution_present or any(
                    value is not None
                    for value in (
                        explicit.winding_eddy_current_loss_reported_resolution_w,
                        explicit.reported_other_stray_loss_reported_resolution_w,
                    )
                )
                eddy_bounds = _validator_interval(
                    explicit.winding_eddy_current_loss_w,
                    explicit.winding_eddy_current_loss_reported_resolution_w,
                )
                known_lower = math.fsum((i2r_bounds[0], eddy_bounds[0]))
                known_upper = math.fsum((i2r_bounds[1], eddy_bounds[1]))
                other_bounds = (
                    max(0.0, total_bounds[0] - known_upper),
                    max(0.0, total_bounds[1] - known_lower),
                )
                bounded = known_lower <= total_bounds[1]
                if explicit.reported_other_stray_loss_w is not None:
                    reported_bounds = _validator_interval(
                        explicit.reported_other_stray_loss_w,
                        explicit.reported_other_stray_loss_reported_resolution_w,
                    )
                    bounded = bounded and max(other_bounds[0], reported_bounds[0]) <= min(
                        other_bounds[1], reported_bounds[1]
                    )
                resolved = strict or (resolution_present and bounded)
                resolution_applied = resolved and not strict
                fidelity = (
                    "explicit_three_component_exact"
                    if strict
                    else "explicit_three_component_resolution_bounded"
                    if resolved
                    else "unresolved"
                )
        except (OverflowError, ValueError):
            fidelity = "unresolved"
            eddy_bounds = aggregate_bounds = other_bounds = (nan, nan)
            aggregate_nominal = nan
    if fidelity.endswith("resolution_bounded"):
        math_ok = True
        reported_ok = True
    if fidelity == "unresolved":
        aggregate_nominal = nan
    component_ok = bool(
        rated and explicit and side_ok and temperature_ok and frequency_ok and strict
    )
    factory_ok = bool(
        static_ok
        and construction
        and side_ok
        and temperature_ok
        and frequency_ok
        and fidelity != "unresolved"
    )
    conditions = (
        static_ok,
        rated is not None,
        construction is not None,
        component is not None,
        side_ok,
        temperature_ok,
        frequency_ok,
        math_ok,
        reported_ok,
    )
    state = {
        "explicit_three_component_exact": "resolved_transformer_advanced_loss_basis",
        "explicit_three_component_resolution_bounded": (
            "resolved_transformer_factory_load_loss_explicit_components_resolution_bounded"
        ),
        "aggregate_stray_exact": "resolved_transformer_factory_load_loss_aggregate_stray_basis",
        "aggregate_stray_resolution_bounded": (
            "resolved_transformer_factory_load_loss_aggregate_stray_resolution_bounded"
        ),
    }.get(fidelity if factory_ok else "unresolved", _STATES[7])
    for position, condition in enumerate(conditions):
        if not condition:
            state = _STATES[position]
            break
    return {
        "transformer_static_authority_resolved": static_ok,
        "s12b_rated_load_loss_authority_present": rated is not None,
        "transformer_advanced_construction_authority_present": construction is not None,
        "transformer_rated_load_loss_component_authority_present": component is not None,
        "transformer_construction_basis_resolved": construction is not None,
        "transformer_load_loss_component_basis_resolved": component_ok,
        "transformer_advanced_loss_basis_resolved": bool(
            static_ok and construction is not None and component_ok
        ),
        "component_reference_side_compatible": side_ok,
        "component_reference_temperature_compatible": temperature_ok,
        "component_test_frequency_compatible": frequency_ok,
        "component_math_compatible": math_ok,
        "reported_other_stray_loss_compatible": reported_ok,
        "s12b_rated_load_loss_w": rated.rated_load_loss_w if rated else nan,
        "s12b_load_loss_test_current_reference_side": (
            rated.test_current_reference_side if rated else ""
        ),
        "s12b_load_loss_reference_temperature_c": rated.reference_temperature_c if rated else nan,
        "s12b_load_loss_test_frequency_hz": rated.test_frequency_hz if rated else nan,
        "i2r_loss_reference_w": component.i2r_loss_w if component else nan,
        "winding_eddy_current_loss_reference_w": (
            explicit.winding_eddy_current_loss_w if explicit else nan
        ),
        "reported_other_stray_loss_w": (
            explicit.reported_other_stray_loss_w
            if explicit and explicit.reported_other_stray_loss_w is not None
            else nan
        ),
        "canonical_other_stray_loss_reference_w": residual if component_ok else nan,
        "canonical_component_sum_w": total if component_ok else nan,
        "component_closure_residual_w": delta if component_ok else nan,
        "reported_other_stray_loss_present": bool(
            explicit and explicit.reported_other_stray_loss_w is not None
        ),
        "other_stray_loss_residual_derived": bool(
            explicit and explicit.reported_other_stray_loss_w is None and component_ok
        ),
        "component_closure_roundoff_adjusted": adjusted,
        "transformer_factory_load_loss_evidence_resolved": factory_ok,
        "source_resolution_authority_present": resolution_present,
        "source_resolution_applied": factory_ok and resolution_applied,
        "strict_point_component_closure_resolved": factory_ok and strict,
        "resolution_bounded_closure_resolved": factory_ok and resolution_applied,
        "aggregate_stray_basis_resolved": factory_ok and aggregate,
        "advanced_component_correction_eligible": bool(
            static_ok and construction is not None and component_ok
        ),
        "factory_load_loss_evidence_fidelity": fidelity if factory_ok else "unresolved",
        "source_rounding_semantics": (
            component.rounding_semantics
            if component and component.rounding_semantics is not None
            else rated.rounding_semantics
            if rated and rated.rounding_semantics is not None
            else ""
        ),
        "rated_load_loss_reported_resolution_w": (
            rated.reported_resolution_w
            if rated and rated.reported_resolution_w is not None
            else nan
        ),
        "i2r_loss_reported_resolution_w": (
            component.i2r_loss_reported_resolution_w
            if component and component.i2r_loss_reported_resolution_w is not None
            else nan
        ),
        "winding_eddy_current_loss_reported_resolution_w": (
            explicit.winding_eddy_current_loss_reported_resolution_w
            if explicit and explicit.winding_eddy_current_loss_reported_resolution_w is not None
            else nan
        ),
        "reported_other_stray_loss_reported_resolution_w": (
            explicit.reported_other_stray_loss_reported_resolution_w
            if explicit and explicit.reported_other_stray_loss_reported_resolution_w is not None
            else nan
        ),
        "reported_total_stray_loss_w": (
            component.reported_total_stray_loss_w
            if type(component) is TransformerRatedLoadLossAggregateStrayAuthority
            and component.reported_total_stray_loss_w is not None
            else nan
        ),
        "reported_total_stray_loss_reported_resolution_w": (
            component.reported_total_stray_loss_reported_resolution_w
            if type(component) is TransformerRatedLoadLossAggregateStrayAuthority
            and component.reported_total_stray_loss_reported_resolution_w is not None
            else nan
        ),
        "rated_load_loss_lower_bound_w": total_bounds[0],
        "rated_load_loss_upper_bound_w": total_bounds[1],
        "i2r_loss_lower_bound_w": i2r_bounds[0],
        "i2r_loss_upper_bound_w": i2r_bounds[1],
        "winding_eddy_loss_lower_bound_w": eddy_bounds[0],
        "winding_eddy_loss_upper_bound_w": eddy_bounds[1],
        "derived_aggregate_stray_loss_nominal_w": aggregate_nominal,
        "derived_aggregate_stray_loss_lower_bound_w": aggregate_bounds[0],
        "derived_aggregate_stray_loss_upper_bound_w": aggregate_bounds[1],
        "derived_other_stray_loss_lower_bound_w": other_bounds[0],
        "derived_other_stray_loss_upper_bound_w": other_bounds[1],
        "thermal_construction_family": (
            construction.thermal_construction_family if construction else ""
        ),
        "winding_conductor_material": (
            construction.winding_conductor_material if construction else ""
        ),
        "conductor_material_description": (
            construction.conductor_material_description if construction else ""
        ),
        "cooling_method_code": construction.cooling_method_code if construction else "",
        "core_material_family": construction.core_material_family if construction else "",
        "core_material_description": construction.core_material_description if construction else "",
        "component_test_current_reference_side": (
            component.test_current_reference_side if component else ""
        ),
        "component_reference_temperature_c": (
            component.reference_temperature_c if component else nan
        ),
        "component_test_frequency_hz": component.test_frequency_hz if component else nan,
        "component_basis_semantics": (
            explicit.component_basis_semantics
            if explicit
            else component.evidence_basis_semantics
            if type(component) is TransformerRatedLoadLossAggregateStrayAuthority
            else ""
        ),
        "decomposition_method": component.decomposition_method if component else "",
        "construction_parameter_source": construction.parameter_source if construction else "",
        "construction_confidence": construction.confidence if construction else "",
        "component_parameter_source": component.parameter_source if component else "",
        "component_confidence": component.confidence if component else "",
        "reference_load_loss_ownership": REFERENCE_LOAD_LOSS_OWNERSHIP,
        "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
        "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
        "transformer_loss_authority_contract": TRANSFORMER_LOSS_AUTHORITY_CONTRACT_ID,
        "transformer_loss_authority_model": TRANSFORMER_LOSS_AUTHORITY_MODEL_ID,
        "transformer_loss_component_authority_contract": (
            TRANSFORMER_LOSS_COMPONENT_AUTHORITY_CONTRACT_ID
        ),
        "transformer_loss_component_authority_model": (
            TRANSFORMER_LOSS_COMPONENT_AUTHORITY_MODEL_ID
        ),
        "transformer_loss_component_authority_scope": TRANSFORMER_LOSS_COMPONENT_AUTHORITY_SCOPE,
        "transformer_loss_component_authority_coverage_scope": (
            TRANSFORMER_LOSS_COMPONENT_AUTHORITY_COVERAGE_SCOPE
        ),
        "transformer_loss_component_authority_state": state,
    }


def _validator_frame(ids: list[str], records: list[dict[str, object]]) -> pd.DataFrame:
    """Build the expected frame without using the production frame builder."""
    expected = pd.DataFrame(records, index=pd.Index(ids, name="transformer_id", dtype=object))
    expected = expected.loc[:, list(_COLUMNS)]
    for column in _COLUMNS:
        if column in _BOOL_COLUMNS:
            expected[column] = expected[column].astype(bool)
        elif column in _FLOAT_COLUMNS:
            expected[column] = expected[column].astype("float64")
        else:
            expected[column] = expected[column].astype(object)
    return expected


def _validator_diagnostics(
    frame: pd.DataFrame,
) -> TopologyTransformerLossComponentAuthorityDiagnostics:
    """Independently derive every expected diagnostic from expected evidence."""
    state_counts = tuple(
        (state, int(frame["transformer_loss_component_authority_state"].eq(state).sum()))
        for state in _STATES
    )
    rated_present = frame["s12b_rated_load_loss_authority_present"]
    component_present = frame["transformer_rated_load_loss_component_authority_present"]
    comparable = rated_present & component_present
    return TopologyTransformerLossComponentAuthorityDiagnostics(
        transformer_count=len(frame),
        construction_authority_count=int(
            frame["transformer_advanced_construction_authority_present"].sum()
        ),
        component_authority_count=int(component_present.sum()),
        construction_basis_resolved_count=int(
            frame["transformer_construction_basis_resolved"].sum()
        ),
        load_loss_component_basis_resolved_count=int(
            frame["transformer_load_loss_component_basis_resolved"].sum()
        ),
        advanced_loss_basis_resolved_count=int(
            frame["transformer_advanced_loss_basis_resolved"].sum()
        ),
        missing_s12b_rated_load_count=int((~rated_present).sum()),
        missing_construction_count=int(
            (~frame["transformer_advanced_construction_authority_present"]).sum()
        ),
        missing_component_count=int((~component_present).sum()),
        incompatible_side_count=int(
            (comparable & ~frame["component_reference_side_compatible"]).sum()
        ),
        incompatible_temperature_count=int(
            (comparable & ~frame["component_reference_temperature_compatible"]).sum()
        ),
        incompatible_frequency_count=int(
            (comparable & ~frame["component_test_frequency_compatible"]).sum()
        ),
        component_math_incompatible_count=int(
            (comparable & ~frame["component_math_compatible"]).sum()
        ),
        reported_other_stray_incompatible_count=int(
            (comparable & ~frame["reported_other_stray_loss_compatible"]).sum()
        ),
        residual_other_stray_derived_count=int(frame["other_stray_loss_residual_derived"].sum()),
        roundoff_adjusted_count=int(frame["component_closure_roundoff_adjusted"].sum()),
        explicit_three_component_exact_count=int(
            frame["factory_load_loss_evidence_fidelity"].eq("explicit_three_component_exact").sum()
        ),
        explicit_three_component_resolution_bounded_count=int(
            frame["factory_load_loss_evidence_fidelity"]
            .eq("explicit_three_component_resolution_bounded")
            .sum()
        ),
        aggregate_stray_exact_count=int(
            frame["factory_load_loss_evidence_fidelity"].eq("aggregate_stray_exact").sum()
        ),
        aggregate_stray_resolution_bounded_count=int(
            frame["factory_load_loss_evidence_fidelity"]
            .eq("aggregate_stray_resolution_bounded")
            .sum()
        ),
        unresolved_factory_evidence_count=int(
            frame["factory_load_loss_evidence_fidelity"].eq("unresolved").sum()
        ),
        state_counts=state_counts,
        model=TRANSFORMER_LOSS_COMPONENT_AUTHORITY_MODEL_ID,
    )
