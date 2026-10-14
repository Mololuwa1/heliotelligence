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
from typing import Literal, TypeVar

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
    state_counts: tuple[tuple[str, int], ...]
    model: str


@dataclass(frozen=True)
class TopologyTransformerLossComponentAuthorityResult:
    construction_by_id: Mapping[str, TransformerAdvancedConstructionAuthority]
    rated_load_loss_component_by_id: Mapping[str, TransformerRatedLoadLossComponentAuthority]
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
        str, TransformerRatedLoadLossComponentAuthority
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
    construction = _admit_mapping(
        transformer_construction_by_id,
        set(ids),
        TransformerAdvancedConstructionAuthority,
        "construction",
    )
    components = _admit_mapping(
        transformer_rated_load_loss_component_by_id,
        set(ids),
        TransformerRatedLoadLossComponentAuthority,
        "rated load loss component",
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
    supplied: Mapping[str, AuthorityT],
    known: set[str],
    expected_type: type[AuthorityT],
    label: str,
) -> dict[str, AuthorityT]:
    if not isinstance(supplied, Mapping):
        raise TypeError(f"{label} authority must be a mapping")
    admitted: dict[str, AuthorityT] = {}
    for key, value in supplied.items():
        _exact_text(key, "transformer mapping key")
        if type(value) is not expected_type:
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
    for condition, state in zip(conditions, _STATES[:-1], strict=True):
        if not condition:
            return state
    return _STATES[-1]


def _build_record(
    static_row: pd.Series,
    rated: TransformerRatedLoadLossAuthority | None,
    construction: TransformerAdvancedConstructionAuthority | None,
    component: TransformerRatedLoadLossComponentAuthority | None,
) -> dict[str, object]:
    return _record_values(static_row, rated, construction, component)


def _record_values(
    static_row: pd.Series,
    rated: TransformerRatedLoadLossAuthority | None,
    construction: TransformerAdvancedConstructionAuthority | None,
    component: TransformerRatedLoadLossComponentAuthority | None,
) -> dict[str, object]:
    static = bool(static_row["transformer_static_authority_resolved"])
    closure = _closure(rated, component)
    side, temperature, frequency, math_ok, reported_ok, residual, total, delta, adjusted = closure
    component_resolved = bool(
        rated and component and side and temperature and frequency and math_ok and reported_ok
    )
    construction_resolved = construction is not None
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
            component.winding_eddy_current_loss_w if component else nan
        ),
        "reported_other_stray_loss_w": (
            component.reported_other_stray_loss_w
            if component and component.reported_other_stray_loss_w is not None
            else nan
        ),
        "canonical_other_stray_loss_reference_w": residual,
        "canonical_component_sum_w": total,
        "component_closure_residual_w": delta,
        "reported_other_stray_loss_present": bool(
            component and component.reported_other_stray_loss_w is not None
        ),
        "other_stray_loss_residual_derived": bool(
            component and component.reported_other_stray_loss_w is None and math_ok
        ),
        "component_closure_roundoff_adjusted": adjusted,
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
        "component_basis_semantics": component.component_basis_semantics if component else "",
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
        states,
        TRANSFORMER_LOSS_COMPONENT_AUTHORITY_MODEL_ID,
    )


def _validate_result(
    static: TopologyTransformerStaticAuthorityResult,
    loss: TopologyTransformerLossAuthorityResult,
    expected_construction: Mapping[str, TransformerAdvancedConstructionAuthority],
    expected_components: Mapping[str, TransformerRatedLoadLossComponentAuthority],
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


def _validator_record(
    static_row: pd.Series,
    rated: TransformerRatedLoadLossAuthority | None,
    construction: TransformerAdvancedConstructionAuthority | None,
    component: TransformerRatedLoadLossComponentAuthority | None,
) -> dict[str, object]:
    """Independently reconstruct expected S12H evidence and component closure."""
    # The independent path reimplements the numerical closure and state choice.
    static_ok = bool(static_row["transformer_static_authority_resolved"])
    if rated is not None and component is not None:
        side_ok = rated.test_current_reference_side == component.test_current_reference_side
        temperature_ok = rated.reference_temperature_c == component.reference_temperature_c
        frequency_ok = rated.test_frequency_hz == component.test_frequency_hz
        try:
            known = math.fsum((component.i2r_loss_w, component.winding_eddy_current_loss_w))
        except OverflowError:
            known = math.inf
        adjusted = known > rated.rated_load_loss_w and math.isclose(
            known, rated.rated_load_loss_w, rel_tol=_REL_TOL, abs_tol=0.0
        )
        math_ok = math.isfinite(known) and (known <= rated.rated_load_loss_w or adjusted)
        residual = max(0.0, rated.rated_load_loss_w - known) if math_ok else math.nan
        total = math.fsum((known, residual)) if math_ok else math.nan
        delta = rated.rated_load_loss_w - total if math_ok else math.nan
        reported_ok = component.reported_other_stray_loss_w is None or (
            math_ok
            and math.isclose(
                component.reported_other_stray_loss_w,
                residual,
                rel_tol=_REL_TOL,
                abs_tol=0.0,
            )
        )
    else:
        side_ok = temperature_ok = frequency_ok = math_ok = reported_ok = adjusted = False
        residual = total = delta = math.nan
    component_ok = bool(
        rated
        and component
        and side_ok
        and temperature_ok
        and frequency_ok
        and math_ok
        and reported_ok
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
    state = _STATES[-1]
    for position, condition in enumerate(conditions):
        if not condition:
            state = _STATES[position]
            break
    nan = math.nan
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
            component.winding_eddy_current_loss_w if component else nan
        ),
        "reported_other_stray_loss_w": (
            component.reported_other_stray_loss_w
            if component and component.reported_other_stray_loss_w is not None
            else nan
        ),
        "canonical_other_stray_loss_reference_w": residual,
        "canonical_component_sum_w": total,
        "component_closure_residual_w": delta,
        "reported_other_stray_loss_present": bool(
            component and component.reported_other_stray_loss_w is not None
        ),
        "other_stray_loss_residual_derived": bool(
            component and component.reported_other_stray_loss_w is None and math_ok
        ),
        "component_closure_roundoff_adjusted": adjusted,
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
        "component_basis_semantics": component.component_basis_semantics if component else "",
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
        residual_other_stray_derived_count=int(
            frame["other_stray_loss_residual_derived"].sum()
        ),
        roundoff_adjusted_count=int(frame["component_closure_roundoff_adjusted"].sum()),
        state_counts=state_counts,
        model=TRANSFORMER_LOSS_COMPONENT_AUTHORITY_MODEL_ID,
    )
