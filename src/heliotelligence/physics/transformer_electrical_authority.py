"""Explicit positive-sequence transformer electrical-model authority.

S12B admits collection-side-referred per-phase series impedance, a
collection-terminal per-phase shunt admittance, and positive-sequence phase
displacement. It performs no operating, loss, loading, tap, or current solve.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from types import MappingProxyType
from typing import Literal, Protocol, TypeVar

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

TRANSFORMER_ELECTRICAL_AUTHORITY_CONTRACT_ID = (
    "admitted_transformer_static_authority_to_explicit_positive_sequence_"
    "equivalent_circuit_authority_v1"
)
TRANSFORMER_ELECTRICAL_AUTHORITY_MODEL_ID = (
    "balanced_three_phase_two_winding_collection_referred_"
    "series_and_collection_terminal_shunt_equivalent_circuit_v1"
)
TRANSFORMER_ELECTRICAL_AUTHORITY_SCOPE = (
    "static_transformer_positive_sequence_electrical_authority_before_operating_transformer_solve"
)
TRANSFORMER_ELECTRICAL_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_collection_referred_series_impedance_collection_terminal_"
    "shunt_admittance_and_network_side_phase_displacement"
)

Confidence = Literal["high", "medium", "low", "unknown"]
_CONFIDENCES = {"high", "medium", "low", "unknown"}
_COLUMNS = (
    "transformer_static_authority_resolved",
    "transformer_series_impedance_authority_present",
    "transformer_shunt_admittance_authority_present",
    "transformer_phase_displacement_authority_present",
    "transformer_electrical_model_authority_resolved",
    "series_parameter_reference_side",
    "series_impedance_basis",
    "series_resistance_ohm_per_phase",
    "series_reactance_ohm_per_phase",
    "shunt_parameter_reference_side",
    "shunt_admittance_basis",
    "shunt_placement",
    "shunt_conductance_siemens_per_phase",
    "magnetizing_susceptance_siemens_per_phase",
    "phase_displacement_basis",
    "network_side_phase_displacement_deg",
    "series_parameter_source",
    "series_confidence",
    "shunt_parameter_source",
    "shunt_confidence",
    "phase_displacement_parameter_source",
    "phase_displacement_confidence",
    "transformer_electrical_authority_state",
    "transformer_static_authority_contract",
    "transformer_static_authority_model",
    "transformer_electrical_authority_contract",
    "transformer_electrical_authority_model",
    "transformer_electrical_authority_scope",
    "transformer_electrical_authority_coverage_scope",
)
_BOOL_COLUMNS = {
    "transformer_static_authority_resolved",
    "transformer_series_impedance_authority_present",
    "transformer_shunt_admittance_authority_present",
    "transformer_phase_displacement_authority_present",
    "transformer_electrical_model_authority_resolved",
}
_FLOAT_COLUMNS = {
    "series_resistance_ohm_per_phase",
    "series_reactance_ohm_per_phase",
    "shunt_conductance_siemens_per_phase",
    "magnetizing_susceptance_siemens_per_phase",
    "network_side_phase_displacement_deg",
}


class _ElectricalAuthority(Protocol):
    @property
    def transformer_id(self) -> str: ...


_AuthorityT = TypeVar("_AuthorityT", bound=_ElectricalAuthority)


def _identifier(value: object, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be an exact non-empty string without surrounding whitespace")
    return value


def _source(value: object) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(
            "parameter_source must be an exact non-empty string without surrounding whitespace"
        )
    return value


def _confidence(value: object) -> str:
    if type(value) is not str or value not in _CONFIDENCES:
        raise ValueError("confidence is unsupported")
    return value


def _nonnegative_finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real non-Boolean number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return normalized


def _phase(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("network_side_phase_displacement_deg must be a real non-Boolean number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < -180.0 or normalized >= 180.0:
        raise ValueError("network_side_phase_displacement_deg must be in [-180, 180)")
    return normalized


@dataclass(frozen=True)
class TransformerSeriesImpedanceAuthority:
    transformer_id: str
    parameter_reference_side: Literal["collection_side"]
    series_impedance_basis: Literal["per_phase_referred_to_collection_side"]
    series_resistance_ohm_per_phase: float
    series_reactance_ohm_per_phase: float
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _identifier(self.transformer_id, "transformer_id")
        _validate_series(self)
        object.__setattr__(
            self,
            "series_resistance_ohm_per_phase",
            _nonnegative_finite(
                self.series_resistance_ohm_per_phase,
                "series_resistance_ohm_per_phase",
            ),
        )
        object.__setattr__(
            self,
            "series_reactance_ohm_per_phase",
            _nonnegative_finite(
                self.series_reactance_ohm_per_phase,
                "series_reactance_ohm_per_phase",
            ),
        )


@dataclass(frozen=True)
class TransformerShuntAdmittanceAuthority:
    transformer_id: str
    parameter_reference_side: Literal["collection_side"]
    shunt_admittance_basis: Literal["per_phase_referred_to_collection_side"]
    shunt_placement: Literal["transformer_collection_side_terminal"]
    shunt_conductance_siemens_per_phase: float
    magnetizing_susceptance_siemens_per_phase: float
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _identifier(self.transformer_id, "transformer_id")
        _validate_shunt(self)
        object.__setattr__(
            self,
            "shunt_conductance_siemens_per_phase",
            _nonnegative_finite(
                self.shunt_conductance_siemens_per_phase,
                "shunt_conductance_siemens_per_phase",
            ),
        )
        object.__setattr__(
            self,
            "magnetizing_susceptance_siemens_per_phase",
            _nonnegative_finite(
                self.magnetizing_susceptance_siemens_per_phase,
                "magnetizing_susceptance_siemens_per_phase",
            ),
        )


@dataclass(frozen=True)
class TransformerPhaseDisplacementAuthority:
    transformer_id: str
    phase_displacement_basis: Literal[
        "balanced_positive_sequence_network_side_relative_to_collection_side"
    ]
    network_side_phase_displacement_deg: float
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _identifier(self.transformer_id, "transformer_id")
        _validate_phase_authority(self)
        object.__setattr__(
            self,
            "network_side_phase_displacement_deg",
            _phase(self.network_side_phase_displacement_deg),
        )


@dataclass(frozen=True)
class TopologyTransformerElectricalAuthorityDiagnostics:
    transformer_record_count: int
    static_authority_resolved_count: int
    static_authority_unresolved_count: int
    series_impedance_authority_count: int
    shunt_admittance_authority_count: int
    phase_displacement_authority_count: int
    electrical_model_resolved_count: int
    unresolved_upstream_static_count: int
    unresolved_missing_series_count: int
    unresolved_missing_shunt_count: int
    unresolved_missing_phase_displacement_count: int
    model: str


@dataclass(frozen=True)
class TopologyTransformerElectricalAuthorityResult:
    series_impedance_by_id: Mapping[str, TransformerSeriesImpedanceAuthority]
    shunt_admittance_by_id: Mapping[str, TransformerShuntAdmittanceAuthority]
    phase_displacement_by_id: Mapping[str, TransformerPhaseDisplacementAuthority]
    transformer_states: pd.DataFrame
    diagnostics: TopologyTransformerElectricalAuthorityDiagnostics


def resolve_transformer_electrical_authority(
    topology: ElectricalTopologyConfig,
    network_basis: LvAcCollectionNetworkBasisAuthority | None,
    node_authority_by_id: Mapping[str, LvAcCollectionNodeAuthority],
    segment_authority_by_id: Mapping[str, LvAcCollectionSegmentAuthority],
    inverter_terminal_binding_by_inverter_id: Mapping[str, LvAcInverterTerminalBindingAuthority],
    lv_ac_collection_authority: TopologyLvAcCollectionAuthorityResult,
    transformer_equipment_by_id: Mapping[str, TransformerStaticEquipmentAuthority],
    transformer_topology_by_id: Mapping[str, TransformerBoundaryTopologyAuthority],
    transformer_static_authority: TopologyTransformerStaticAuthorityResult,
    transformer_series_impedance_by_id: Mapping[str, TransformerSeriesImpedanceAuthority],
    transformer_shunt_admittance_by_id: Mapping[str, TransformerShuntAdmittanceAuthority],
    transformer_phase_displacement_by_id: Mapping[str, TransformerPhaseDisplacementAuthority],
) -> TopologyTransformerElectricalAuthorityResult:
    """Admit explicit S12B positive-sequence equivalent-circuit authority."""
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
    _validate_parent_replay(transformer_static_authority, canonical_static)
    transformer_ids = canonical_static.transformer_states.index.tolist()
    known_ids = set(transformer_ids)
    series = _admit_mapping(
        transformer_series_impedance_by_id,
        TransformerSeriesImpedanceAuthority,
        known_ids,
        "series impedance",
    )
    shunt = _admit_mapping(
        transformer_shunt_admittance_by_id,
        TransformerShuntAdmittanceAuthority,
        known_ids,
        "shunt admittance",
    )
    phase = _admit_mapping(
        transformer_phase_displacement_by_id,
        TransformerPhaseDisplacementAuthority,
        known_ids,
        "phase displacement",
    )
    for series_authority in series.values():
        _validate_series(series_authority)
    for shunt_authority in shunt.values():
        _validate_shunt(shunt_authority)
    for phase_authority in phase.values():
        _validate_phase_authority(phase_authority)
    records = [
        _record(
            transformer_id,
            bool(
                canonical_static.transformer_states.loc[
                    transformer_id, "transformer_static_authority_resolved"
                ]
            ),
            series.get(transformer_id),
            shunt.get(transformer_id),
            phase.get(transformer_id),
        )
        for transformer_id in transformer_ids
    ]
    states = _state_frame(transformer_ids, records)
    diagnostics = _diagnostics(states, series, shunt, phase)
    result = TopologyTransformerElectricalAuthorityResult(
        series_impedance_by_id=MappingProxyType(dict(series)),
        shunt_admittance_by_id=MappingProxyType(dict(shunt)),
        phase_displacement_by_id=MappingProxyType(dict(phase)),
        transformer_states=states.copy(deep=True),
        diagnostics=diagnostics,
    )
    _validate_result(canonical_static, result)
    return result


def _validate_series(authority: TransformerSeriesImpedanceAuthority) -> None:
    _identifier(authority.transformer_id, "transformer_id")
    if authority.parameter_reference_side != "collection_side":
        raise ValueError("series parameter_reference_side must be collection_side")
    if authority.series_impedance_basis != "per_phase_referred_to_collection_side":
        raise ValueError("series_impedance_basis is unsupported")
    _nonnegative_finite(
        authority.series_resistance_ohm_per_phase,
        "series_resistance_ohm_per_phase",
    )
    _nonnegative_finite(
        authority.series_reactance_ohm_per_phase,
        "series_reactance_ohm_per_phase",
    )
    _source(authority.parameter_source)
    _confidence(authority.confidence)


def _validate_shunt(authority: TransformerShuntAdmittanceAuthority) -> None:
    _identifier(authority.transformer_id, "transformer_id")
    if authority.parameter_reference_side != "collection_side":
        raise ValueError("shunt parameter_reference_side must be collection_side")
    if authority.shunt_admittance_basis != "per_phase_referred_to_collection_side":
        raise ValueError("shunt_admittance_basis is unsupported")
    if authority.shunt_placement != "transformer_collection_side_terminal":
        raise ValueError("shunt_placement must be transformer_collection_side_terminal")
    _nonnegative_finite(
        authority.shunt_conductance_siemens_per_phase,
        "shunt_conductance_siemens_per_phase",
    )
    _nonnegative_finite(
        authority.magnetizing_susceptance_siemens_per_phase,
        "magnetizing_susceptance_siemens_per_phase",
    )
    _source(authority.parameter_source)
    _confidence(authority.confidence)


def _validate_phase_authority(authority: TransformerPhaseDisplacementAuthority) -> None:
    _identifier(authority.transformer_id, "transformer_id")
    if authority.phase_displacement_basis != (
        "balanced_positive_sequence_network_side_relative_to_collection_side"
    ):
        raise ValueError("phase_displacement_basis is unsupported")
    _phase(authority.network_side_phase_displacement_deg)
    _source(authority.parameter_source)
    _confidence(authority.confidence)


def _admit_mapping(
    supplied: Mapping[str, _AuthorityT],
    expected_type: type[_AuthorityT],
    known_ids: set[str],
    label: str,
) -> dict[str, _AuthorityT]:
    if not isinstance(supplied, Mapping):
        raise TypeError(f"transformer {label} authority must be a mapping")
    admitted: dict[str, _AuthorityT] = {}
    for key, authority in supplied.items():
        _identifier(key, "transformer mapping key")
        if type(authority) is not expected_type:
            raise TypeError(f"transformer {label} authority has an invalid value type")
        if key != authority.transformer_id:
            raise ValueError(f"transformer {label} mapping key does not match transformer_id")
        if key not in known_ids:
            raise ValueError(f"transformer {label} authority references unknown S12A transformer")
        admitted[key] = authority
    return dict(sorted(admitted.items()))


def _validate_parent_replay(
    supplied: TopologyTransformerStaticAuthorityResult,
    canonical: TopologyTransformerStaticAuthorityResult,
) -> None:
    if type(supplied) is not TopologyTransformerStaticAuthorityResult:
        raise ValueError("supplied S12A result type is invalid")
    for name in ("equipment_by_id", "topology_by_id"):
        actual = getattr(supplied, name)
        expected = getattr(canonical, name)
        if type(actual).__name__ != "mappingproxy" or dict(actual) != dict(expected):
            raise ValueError(f"supplied S12A {name} does not match immutable canonical replay")
    try:
        pd.testing.assert_frame_equal(
            supplied.transformer_states,
            canonical.transformer_states,
            check_exact=True,
        )
    except AssertionError as error:
        raise ValueError(
            "supplied S12A transformer states do not match canonical replay"
        ) from error
    if supplied.diagnostics != canonical.diagnostics:
        raise ValueError("supplied S12A diagnostics do not match canonical replay")


def _primary_state(
    static_resolved: bool, series_present: bool, shunt_present: bool, phase_present: bool
) -> str:
    return (
        "unresolved_upstream_transformer_static_authority"
        if not static_resolved
        else "unresolved_missing_transformer_series_impedance_authority"
        if not series_present
        else "unresolved_missing_transformer_shunt_admittance_authority"
        if not shunt_present
        else "unresolved_missing_transformer_phase_displacement_authority"
        if not phase_present
        else "resolved_transformer_electrical_model_authority"
    )


def _record(
    transformer_id: str,
    static_resolved: bool,
    series: TransformerSeriesImpedanceAuthority | None,
    shunt: TransformerShuntAdmittanceAuthority | None,
    phase: TransformerPhaseDisplacementAuthority | None,
) -> dict[str, object]:
    series_present = series is not None
    shunt_present = shunt is not None
    phase_present = phase is not None
    resolved = static_resolved and series_present and shunt_present and phase_present
    return {
        "transformer_static_authority_resolved": static_resolved,
        "transformer_series_impedance_authority_present": series_present,
        "transformer_shunt_admittance_authority_present": shunt_present,
        "transformer_phase_displacement_authority_present": phase_present,
        "transformer_electrical_model_authority_resolved": resolved,
        "series_parameter_reference_side": series.parameter_reference_side if series else "",
        "series_impedance_basis": series.series_impedance_basis if series else "",
        "series_resistance_ohm_per_phase": series.series_resistance_ohm_per_phase
        if series
        else math.nan,
        "series_reactance_ohm_per_phase": series.series_reactance_ohm_per_phase
        if series
        else math.nan,
        "shunt_parameter_reference_side": shunt.parameter_reference_side if shunt else "",
        "shunt_admittance_basis": shunt.shunt_admittance_basis if shunt else "",
        "shunt_placement": shunt.shunt_placement if shunt else "",
        "shunt_conductance_siemens_per_phase": shunt.shunt_conductance_siemens_per_phase
        if shunt
        else math.nan,
        "magnetizing_susceptance_siemens_per_phase": (
            shunt.magnetizing_susceptance_siemens_per_phase if shunt else math.nan
        ),
        "phase_displacement_basis": phase.phase_displacement_basis if phase else "",
        "network_side_phase_displacement_deg": phase.network_side_phase_displacement_deg
        if phase
        else math.nan,
        "series_parameter_source": series.parameter_source if series else "",
        "series_confidence": series.confidence if series else "",
        "shunt_parameter_source": shunt.parameter_source if shunt else "",
        "shunt_confidence": shunt.confidence if shunt else "",
        "phase_displacement_parameter_source": phase.parameter_source if phase else "",
        "phase_displacement_confidence": phase.confidence if phase else "",
        "transformer_electrical_authority_state": _primary_state(
            static_resolved, series_present, shunt_present, phase_present
        ),
        "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
        "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
        "transformer_electrical_authority_contract": (TRANSFORMER_ELECTRICAL_AUTHORITY_CONTRACT_ID),
        "transformer_electrical_authority_model": TRANSFORMER_ELECTRICAL_AUTHORITY_MODEL_ID,
        "transformer_electrical_authority_scope": TRANSFORMER_ELECTRICAL_AUTHORITY_SCOPE,
        "transformer_electrical_authority_coverage_scope": (
            TRANSFORMER_ELECTRICAL_AUTHORITY_COVERAGE_SCOPE
        ),
    }


def _state_frame(transformer_ids: list[str], records: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        records,
        index=pd.Index(transformer_ids, name="transformer_id", dtype=object),
    ).reindex(columns=_COLUMNS)
    for column in _BOOL_COLUMNS:
        frame[column] = frame[column].astype(bool)
    for column in _FLOAT_COLUMNS:
        frame[column] = frame[column].astype("float64")
    for column in set(_COLUMNS) - _BOOL_COLUMNS - _FLOAT_COLUMNS:
        frame[column] = frame[column].astype(object)
    return frame


def _diagnostics(
    states: pd.DataFrame,
    series: Mapping[str, TransformerSeriesImpedanceAuthority],
    shunt: Mapping[str, TransformerShuntAdmittanceAuthority],
    phase: Mapping[str, TransformerPhaseDisplacementAuthority],
) -> TopologyTransformerElectricalAuthorityDiagnostics:
    state_counts = states["transformer_electrical_authority_state"].value_counts()
    static_resolved = int(states["transformer_static_authority_resolved"].sum())
    return TopologyTransformerElectricalAuthorityDiagnostics(
        transformer_record_count=len(states),
        static_authority_resolved_count=static_resolved,
        static_authority_unresolved_count=len(states) - static_resolved,
        series_impedance_authority_count=len(series),
        shunt_admittance_authority_count=len(shunt),
        phase_displacement_authority_count=len(phase),
        electrical_model_resolved_count=int(
            state_counts.get("resolved_transformer_electrical_model_authority", 0)
        ),
        unresolved_upstream_static_count=int(
            state_counts.get("unresolved_upstream_transformer_static_authority", 0)
        ),
        unresolved_missing_series_count=int(
            state_counts.get("unresolved_missing_transformer_series_impedance_authority", 0)
        ),
        unresolved_missing_shunt_count=int(
            state_counts.get("unresolved_missing_transformer_shunt_admittance_authority", 0)
        ),
        unresolved_missing_phase_displacement_count=int(
            state_counts.get("unresolved_missing_transformer_phase_displacement_authority", 0)
        ),
        model=TRANSFORMER_ELECTRICAL_AUTHORITY_MODEL_ID,
    )


def _equal(actual: object, expected: object) -> bool:
    if isinstance(expected, float) and math.isnan(expected):
        return bool(pd.isna(actual))
    return bool(actual == expected)


def _validate_result(
    static: TopologyTransformerStaticAuthorityResult,
    result: TopologyTransformerElectricalAuthorityResult,
) -> None:
    if type(result) is not TopologyTransformerElectricalAuthorityResult:
        raise RuntimeError("transformer electrical authority result type is invalid")
    mappings = (
        result.series_impedance_by_id,
        result.shunt_admittance_by_id,
        result.phase_displacement_by_id,
    )
    if any(type(mapping).__name__ != "mappingproxy" for mapping in mappings):
        raise RuntimeError("transformer electrical authority result mappings must be immutable")
    transformer_ids = static.transformer_states.index.tolist()
    known_ids = set(transformer_ids)
    validators = (
        (
            result.series_impedance_by_id,
            TransformerSeriesImpedanceAuthority,
            _validate_series,
        ),
        (
            result.shunt_admittance_by_id,
            TransformerShuntAdmittanceAuthority,
            _validate_shunt,
        ),
        (
            result.phase_displacement_by_id,
            TransformerPhaseDisplacementAuthority,
            _validate_phase_authority,
        ),
    )
    for mapping, expected_type, validator in validators:
        for key, authority in mapping.items():
            if type(authority) is not expected_type or key != authority.transformer_id:
                raise RuntimeError("transformer electrical mapping closure is invalid")
            if key not in known_ids:
                raise RuntimeError("transformer electrical authority contains an unknown ID")
            try:
                validator(authority)  # type: ignore[arg-type]
            except ValueError as error:
                raise RuntimeError("transformer electrical authority domain is invalid") from error
    states = result.transformer_states
    if (
        tuple(states.columns) != _COLUMNS
        or states.index.name != "transformer_id"
        or states.index.has_duplicates
        or states.index.tolist() != transformer_ids
    ):
        raise RuntimeError("transformer electrical state schema/index/order is invalid")
    for column in _COLUMNS:
        expected_dtype = (
            "bool"
            if column in _BOOL_COLUMNS
            else "float64"
            if column in _FLOAT_COLUMNS
            else "object"
        )
        if str(states[column].dtype) != expected_dtype:
            raise RuntimeError(f"transformer electrical dtype is invalid for {column}")
    category_counts = {
        "resolved_transformer_electrical_model_authority": 0,
        "unresolved_upstream_transformer_static_authority": 0,
        "unresolved_missing_transformer_series_impedance_authority": 0,
        "unresolved_missing_transformer_shunt_admittance_authority": 0,
        "unresolved_missing_transformer_phase_displacement_authority": 0,
    }
    static_resolved_count = 0
    for transformer_id, row in states.iterrows():
        static_resolved = bool(
            static.transformer_states.loc[transformer_id, "transformer_static_authority_resolved"]
        )
        series = result.series_impedance_by_id.get(transformer_id)
        shunt = result.shunt_admittance_by_id.get(transformer_id)
        phase = result.phase_displacement_by_id.get(transformer_id)
        series_present = series is not None
        shunt_present = shunt is not None
        phase_present = phase is not None
        resolved = static_resolved and series_present and shunt_present and phase_present
        state = (
            "unresolved_upstream_transformer_static_authority"
            if not static_resolved
            else "unresolved_missing_transformer_series_impedance_authority"
            if not series_present
            else "unresolved_missing_transformer_shunt_admittance_authority"
            if not shunt_present
            else "unresolved_missing_transformer_phase_displacement_authority"
            if not phase_present
            else "resolved_transformer_electrical_model_authority"
        )
        category_counts[state] += 1
        static_resolved_count += int(static_resolved)
        expected: dict[str, object] = {
            "transformer_static_authority_resolved": static_resolved,
            "transformer_series_impedance_authority_present": series_present,
            "transformer_shunt_admittance_authority_present": shunt_present,
            "transformer_phase_displacement_authority_present": phase_present,
            "transformer_electrical_model_authority_resolved": resolved,
            "series_parameter_reference_side": series.parameter_reference_side if series else "",
            "series_impedance_basis": series.series_impedance_basis if series else "",
            "series_resistance_ohm_per_phase": series.series_resistance_ohm_per_phase
            if series
            else math.nan,
            "series_reactance_ohm_per_phase": series.series_reactance_ohm_per_phase
            if series
            else math.nan,
            "shunt_parameter_reference_side": shunt.parameter_reference_side if shunt else "",
            "shunt_admittance_basis": shunt.shunt_admittance_basis if shunt else "",
            "shunt_placement": shunt.shunt_placement if shunt else "",
            "shunt_conductance_siemens_per_phase": (
                shunt.shunt_conductance_siemens_per_phase if shunt else math.nan
            ),
            "magnetizing_susceptance_siemens_per_phase": (
                shunt.magnetizing_susceptance_siemens_per_phase if shunt else math.nan
            ),
            "phase_displacement_basis": phase.phase_displacement_basis if phase else "",
            "network_side_phase_displacement_deg": (
                phase.network_side_phase_displacement_deg if phase else math.nan
            ),
            "series_parameter_source": series.parameter_source if series else "",
            "series_confidence": series.confidence if series else "",
            "shunt_parameter_source": shunt.parameter_source if shunt else "",
            "shunt_confidence": shunt.confidence if shunt else "",
            "phase_displacement_parameter_source": phase.parameter_source if phase else "",
            "phase_displacement_confidence": phase.confidence if phase else "",
            "transformer_electrical_authority_state": state,
            "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
            "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
            "transformer_electrical_authority_contract": (
                TRANSFORMER_ELECTRICAL_AUTHORITY_CONTRACT_ID
            ),
            "transformer_electrical_authority_model": (TRANSFORMER_ELECTRICAL_AUTHORITY_MODEL_ID),
            "transformer_electrical_authority_scope": (TRANSFORMER_ELECTRICAL_AUTHORITY_SCOPE),
            "transformer_electrical_authority_coverage_scope": (
                TRANSFORMER_ELECTRICAL_AUTHORITY_COVERAGE_SCOPE
            ),
        }
        for column, wanted in expected.items():
            if not _equal(row[column], wanted):
                raise RuntimeError(f"transformer electrical state does not close for {column}")
    expected_diagnostics = TopologyTransformerElectricalAuthorityDiagnostics(
        transformer_record_count=len(transformer_ids),
        static_authority_resolved_count=static_resolved_count,
        static_authority_unresolved_count=len(transformer_ids) - static_resolved_count,
        series_impedance_authority_count=len(result.series_impedance_by_id),
        shunt_admittance_authority_count=len(result.shunt_admittance_by_id),
        phase_displacement_authority_count=len(result.phase_displacement_by_id),
        electrical_model_resolved_count=category_counts[
            "resolved_transformer_electrical_model_authority"
        ],
        unresolved_upstream_static_count=category_counts[
            "unresolved_upstream_transformer_static_authority"
        ],
        unresolved_missing_series_count=category_counts[
            "unresolved_missing_transformer_series_impedance_authority"
        ],
        unresolved_missing_shunt_count=category_counts[
            "unresolved_missing_transformer_shunt_admittance_authority"
        ],
        unresolved_missing_phase_displacement_count=category_counts[
            "unresolved_missing_transformer_phase_displacement_authority"
        ],
        model=TRANSFORMER_ELECTRICAL_AUTHORITY_MODEL_ID,
    )
    diagnostics = result.diagnostics
    if diagnostics != expected_diagnostics:
        raise RuntimeError("transformer electrical diagnostics failed exact closure")
    if (
        diagnostics.static_authority_resolved_count + diagnostics.static_authority_unresolved_count
        != diagnostics.transformer_record_count
    ):
        raise RuntimeError("transformer static diagnostics do not close")
    if (
        diagnostics.electrical_model_resolved_count
        + diagnostics.unresolved_upstream_static_count
        + diagnostics.unresolved_missing_series_count
        + diagnostics.unresolved_missing_shunt_count
        + diagnostics.unresolved_missing_phase_displacement_count
        != diagnostics.transformer_record_count
    ):
        raise RuntimeError("transformer electrical state diagnostics do not close")
    if (
        diagnostics.series_impedance_authority_count != len(result.series_impedance_by_id)
        or diagnostics.shunt_admittance_authority_count != len(result.shunt_admittance_by_id)
        or diagnostics.phase_displacement_authority_count != len(result.phase_displacement_by_id)
    ):
        raise RuntimeError("transformer electrical channel diagnostics do not close")
    if (
        diagnostics.electrical_model_resolved_count > diagnostics.static_authority_resolved_count
        or diagnostics.model != TRANSFORMER_ELECTRICAL_AUTHORITY_MODEL_ID
    ):
        raise RuntimeError("transformer electrical diagnostics domain is invalid")
