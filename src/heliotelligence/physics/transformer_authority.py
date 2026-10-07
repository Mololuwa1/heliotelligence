"""Static transformer equipment and S11 boundary-topology authority.

S12A admits explicit two-winding transformer ratings and direct bindings from
S11 collection exits to transformer terminals. It performs no operating,
equivalent-circuit, loss, tap, thermal, or transformer power-flow calculation.
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
    resolve_topology_lv_ac_collection_authority,
)

TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID = (
    "explicit_transformer_static_ratings_and_s11_boundary_topology_authority_v1"
)
TRANSFORMER_STATIC_AUTHORITY_MODEL_ID = (
    "balanced_three_phase_two_winding_transformer_rated_terminal_authority_v1"
)
TRANSFORMER_STATIC_AUTHORITY_SCOPE = (
    "static_transformer_identity_rated_terminal_and_s11_boundary_authority_"
    "before_equivalent_circuit_and_operating_solve"
)
TRANSFORMER_STATIC_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_transformer_rated_apparent_power_rated_terminal_voltages_"
    "and_direct_s11_collection_exit_binding"
)

Confidence = Literal["high", "medium", "low", "unknown"]
_CONFIDENCES = {"high", "medium", "low", "unknown"}


class _TransformerAuthority(Protocol):
    @property
    def transformer_id(self) -> str: ...


_AuthorityT = TypeVar("_AuthorityT", bound=_TransformerAuthority)
_COLUMNS = (
    "transformer_equipment_authority_present",
    "transformer_topology_authority_present",
    "s11_collection_exit_binding_resolved",
    "transformer_static_authority_resolved",
    "transformer_type",
    "phase_configuration",
    "voltage_basis",
    "rated_apparent_power_va",
    "collection_side_rated_line_to_line_rms_v",
    "network_side_rated_line_to_line_rms_v",
    "s11_collection_exit_node_id",
    "s11_reference_plane",
    "transformer_collection_terminal_id",
    "transformer_collection_reference_plane",
    "transformer_network_terminal_id",
    "transformer_network_reference_plane",
    "connection_semantics",
    "equipment_parameter_source",
    "equipment_confidence",
    "topology_parameter_source",
    "topology_confidence",
    "transformer_static_authority_state",
    "transformer_static_authority_contract",
    "transformer_static_authority_model",
    "transformer_static_authority_scope",
    "transformer_static_authority_coverage_scope",
)
_BOOL_COLUMNS = {
    "transformer_equipment_authority_present",
    "transformer_topology_authority_present",
    "s11_collection_exit_binding_resolved",
    "transformer_static_authority_resolved",
}
_FLOAT_COLUMNS = {
    "rated_apparent_power_va",
    "collection_side_rated_line_to_line_rms_v",
    "network_side_rated_line_to_line_rms_v",
}


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


def _positive_finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real non-Boolean number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0.0:
        raise ValueError(f"{name} must be finite and strictly positive")
    return normalized


@dataclass(frozen=True)
class TransformerStaticEquipmentAuthority:
    transformer_id: str
    transformer_type: Literal["two_winding"]
    phase_configuration: Literal["balanced_three_phase"]
    voltage_basis: Literal["line_to_line_rms"]
    rated_apparent_power_va: float
    collection_side_rated_line_to_line_rms_v: float
    network_side_rated_line_to_line_rms_v: float
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _identifier(self.transformer_id, "transformer_id")
        if self.transformer_type != "two_winding":
            raise ValueError("transformer_type must be two_winding")
        if self.phase_configuration != "balanced_three_phase":
            raise ValueError("phase_configuration must be balanced_three_phase")
        if self.voltage_basis != "line_to_line_rms":
            raise ValueError("voltage_basis must be line_to_line_rms")
        for field_name in (
            "rated_apparent_power_va",
            "collection_side_rated_line_to_line_rms_v",
            "network_side_rated_line_to_line_rms_v",
        ):
            object.__setattr__(
                self, field_name, _positive_finite(getattr(self, field_name), field_name)
            )
        _source(self.parameter_source)
        _confidence(self.confidence)


@dataclass(frozen=True)
class TransformerBoundaryTopologyAuthority:
    transformer_id: str
    s11_collection_exit_node_id: str
    s11_reference_plane: Literal["lv_ac_collection_exit"]
    transformer_collection_terminal_id: str
    transformer_collection_reference_plane: Literal["transformer_collection_side_terminal"]
    transformer_network_terminal_id: str
    transformer_network_reference_plane: Literal["transformer_network_side_terminal"]
    connection_semantics: Literal["direct_electrical_boundary"]
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _identifier(self.transformer_id, "transformer_id")
        _identifier(self.s11_collection_exit_node_id, "s11_collection_exit_node_id")
        _identifier(self.transformer_collection_terminal_id, "transformer_collection_terminal_id")
        _identifier(self.transformer_network_terminal_id, "transformer_network_terminal_id")
        if self.s11_reference_plane != "lv_ac_collection_exit":
            raise ValueError("s11_reference_plane must be lv_ac_collection_exit")
        if self.transformer_collection_reference_plane != "transformer_collection_side_terminal":
            raise ValueError(
                "transformer_collection_reference_plane must be "
                "transformer_collection_side_terminal"
            )
        if self.transformer_network_reference_plane != "transformer_network_side_terminal":
            raise ValueError(
                "transformer_network_reference_plane must be transformer_network_side_terminal"
            )
        if self.connection_semantics != "direct_electrical_boundary":
            raise ValueError("connection_semantics must be direct_electrical_boundary")
        if self.transformer_collection_terminal_id == self.transformer_network_terminal_id:
            raise ValueError("transformer collection and network terminal IDs must differ")
        _source(self.parameter_source)
        _confidence(self.confidence)


@dataclass(frozen=True)
class TopologyTransformerStaticAuthorityDiagnostics:
    transformer_record_count: int
    equipment_authority_count: int
    topology_authority_count: int
    resolved_transformer_count: int
    equipment_only_transformer_count: int
    topology_only_transformer_count: int
    s11_collection_exit_count: int
    bound_s11_collection_exit_count: int
    transformer_terminal_count: int
    model: str


@dataclass(frozen=True)
class TopologyTransformerStaticAuthorityResult:
    equipment_by_id: Mapping[str, TransformerStaticEquipmentAuthority]
    topology_by_id: Mapping[str, TransformerBoundaryTopologyAuthority]
    transformer_states: pd.DataFrame
    diagnostics: TopologyTransformerStaticAuthorityDiagnostics


def resolve_transformer_static_authority(
    topology: ElectricalTopologyConfig,
    network_basis: LvAcCollectionNetworkBasisAuthority | None,
    node_authority_by_id: Mapping[str, LvAcCollectionNodeAuthority],
    segment_authority_by_id: Mapping[str, LvAcCollectionSegmentAuthority],
    inverter_terminal_binding_by_inverter_id: Mapping[str, LvAcInverterTerminalBindingAuthority],
    lv_ac_collection_authority: TopologyLvAcCollectionAuthorityResult,
    transformer_equipment_by_id: Mapping[str, TransformerStaticEquipmentAuthority],
    transformer_topology_by_id: Mapping[str, TransformerBoundaryTopologyAuthority],
) -> TopologyTransformerStaticAuthorityResult:
    """Admit explicit transformer ratings and direct S11 exit bindings."""
    canonical_s11a = resolve_topology_lv_ac_collection_authority(
        topology,
        network_basis,
        node_authority_by_id,
        segment_authority_by_id,
        inverter_terminal_binding_by_inverter_id,
    )
    _validate_parent_replay(lv_ac_collection_authority, canonical_s11a)
    equipment = _admit_mapping(
        transformer_equipment_by_id,
        TransformerStaticEquipmentAuthority,
        "transformer equipment",
    )
    transformer_topology = _admit_mapping(
        transformer_topology_by_id,
        TransformerBoundaryTopologyAuthority,
        "transformer topology",
    )
    for equipment_authority in equipment.values():
        _validate_equipment_authority(equipment_authority)
    for boundary_authority in transformer_topology.values():
        _validate_boundary_authority(boundary_authority)
    _validate_topology_authority(canonical_s11a, transformer_topology)
    transformer_ids = sorted(set(equipment) | set(transformer_topology))
    records = [
        _transformer_record(
            transformer_id, equipment.get(transformer_id), transformer_topology.get(transformer_id)
        )
        for transformer_id in transformer_ids
    ]
    states = _state_frame(transformer_ids, records)
    diagnostics = _diagnostics(canonical_s11a, equipment, transformer_topology, states)
    result = TopologyTransformerStaticAuthorityResult(
        equipment_by_id=MappingProxyType(dict(equipment)),
        topology_by_id=MappingProxyType(dict(transformer_topology)),
        transformer_states=states.copy(deep=True),
        diagnostics=diagnostics,
    )
    _validate_result(canonical_s11a, result)
    return result


def _admit_mapping(
    supplied: Mapping[str, _AuthorityT], expected_type: type[_AuthorityT], label: str
) -> dict[str, _AuthorityT]:
    if not isinstance(supplied, Mapping):
        raise TypeError(f"{label} authority must be a mapping")
    admitted: dict[str, _AuthorityT] = {}
    for key, authority in supplied.items():
        _identifier(key, "transformer mapping key")
        if type(authority) is not expected_type:
            raise TypeError(f"{label} authority has an invalid value type")
        if key != authority.transformer_id:
            raise ValueError(f"{label} mapping key does not match transformer_id")
        admitted[key] = authority
    return dict(sorted(admitted.items()))


def _validate_parent_replay(
    supplied: TopologyLvAcCollectionAuthorityResult,
    canonical: TopologyLvAcCollectionAuthorityResult,
) -> None:
    if type(supplied) is not TopologyLvAcCollectionAuthorityResult:
        raise ValueError("supplied S11A result type is invalid")
    if supplied.network_basis != canonical.network_basis:
        raise ValueError("supplied S11A network basis does not match canonical replay")
    for name in (
        "nodes_by_id",
        "segments_by_id",
        "inverter_terminal_binding_by_inverter_id",
    ):
        actual = getattr(supplied, name)
        expected = getattr(canonical, name)
        if type(actual).__name__ != "mappingproxy" or dict(actual) != dict(expected):
            raise ValueError(f"supplied S11A {name} does not match immutable canonical replay")
    try:
        pd.testing.assert_frame_equal(
            supplied.inverter_states, canonical.inverter_states, check_exact=True
        )
    except AssertionError as error:
        raise ValueError("supplied S11A inverter states do not match canonical replay") from error
    if supplied.diagnostics != canonical.diagnostics:
        raise ValueError("supplied S11A diagnostics do not match canonical replay")


def _validate_topology_authority(
    s11a: TopologyLvAcCollectionAuthorityResult,
    transformer_topology: Mapping[str, TransformerBoundaryTopologyAuthority],
) -> None:
    exits: set[str] = set()
    terminals: set[str] = set()
    for authority in transformer_topology.values():
        node = s11a.nodes_by_id.get(authority.s11_collection_exit_node_id)
        if node is None or node.node_kind != "collection_exit":
            raise ValueError("transformer topology must bind an admitted S11 collection_exit")
        if authority.s11_collection_exit_node_id in exits:
            raise ValueError("an S11 collection exit may bind to at most one transformer")
        exits.add(authority.s11_collection_exit_node_id)
        for terminal_id in (
            authority.transformer_collection_terminal_id,
            authority.transformer_network_terminal_id,
        ):
            if terminal_id in terminals:
                raise ValueError("transformer terminal IDs must be globally unique")
            terminals.add(terminal_id)


def _validate_equipment_authority(authority: TransformerStaticEquipmentAuthority) -> None:
    _identifier(authority.transformer_id, "transformer_id")
    if authority.transformer_type != "two_winding":
        raise ValueError("transformer_type must be two_winding")
    if authority.phase_configuration != "balanced_three_phase":
        raise ValueError("phase_configuration must be balanced_three_phase")
    if authority.voltage_basis != "line_to_line_rms":
        raise ValueError("voltage_basis must be line_to_line_rms")
    _positive_finite(authority.rated_apparent_power_va, "rated_apparent_power_va")
    _positive_finite(
        authority.collection_side_rated_line_to_line_rms_v,
        "collection_side_rated_line_to_line_rms_v",
    )
    _positive_finite(
        authority.network_side_rated_line_to_line_rms_v,
        "network_side_rated_line_to_line_rms_v",
    )
    _source(authority.parameter_source)
    _confidence(authority.confidence)


def _validate_boundary_authority(authority: TransformerBoundaryTopologyAuthority) -> None:
    _identifier(authority.transformer_id, "transformer_id")
    _identifier(authority.s11_collection_exit_node_id, "s11_collection_exit_node_id")
    _identifier(authority.transformer_collection_terminal_id, "transformer_collection_terminal_id")
    _identifier(authority.transformer_network_terminal_id, "transformer_network_terminal_id")
    if authority.s11_reference_plane != "lv_ac_collection_exit":
        raise ValueError("s11_reference_plane must be lv_ac_collection_exit")
    if authority.transformer_collection_reference_plane != "transformer_collection_side_terminal":
        raise ValueError("transformer collection reference plane is invalid")
    if authority.transformer_network_reference_plane != "transformer_network_side_terminal":
        raise ValueError("transformer network reference plane is invalid")
    if authority.connection_semantics != "direct_electrical_boundary":
        raise ValueError("connection_semantics must be direct_electrical_boundary")
    if authority.transformer_collection_terminal_id == authority.transformer_network_terminal_id:
        raise ValueError("transformer collection and network terminal IDs must differ")
    _source(authority.parameter_source)
    _confidence(authority.confidence)


def _transformer_record(
    transformer_id: str,
    equipment: TransformerStaticEquipmentAuthority | None,
    topology: TransformerBoundaryTopologyAuthority | None,
) -> dict[str, object]:
    equipment_present = equipment is not None
    topology_present = topology is not None
    resolved = equipment_present and topology_present
    state = (
        "unresolved_missing_transformer_equipment_authority"
        if not equipment_present
        else "unresolved_missing_transformer_topology_authority"
        if not topology_present
        else "resolved_transformer_static_authority"
    )
    collection_voltage = (
        equipment.collection_side_rated_line_to_line_rms_v if equipment else math.nan
    )
    return {
        "transformer_equipment_authority_present": equipment_present,
        "transformer_topology_authority_present": topology_present,
        "s11_collection_exit_binding_resolved": topology_present,
        "transformer_static_authority_resolved": resolved,
        "transformer_type": equipment.transformer_type if equipment else "",
        "phase_configuration": equipment.phase_configuration if equipment else "",
        "voltage_basis": equipment.voltage_basis if equipment else "",
        "rated_apparent_power_va": equipment.rated_apparent_power_va if equipment else math.nan,
        "collection_side_rated_line_to_line_rms_v": collection_voltage,
        "network_side_rated_line_to_line_rms_v": equipment.network_side_rated_line_to_line_rms_v
        if equipment
        else math.nan,
        "s11_collection_exit_node_id": topology.s11_collection_exit_node_id if topology else "",
        "s11_reference_plane": topology.s11_reference_plane if topology else "",
        "transformer_collection_terminal_id": topology.transformer_collection_terminal_id
        if topology
        else "",
        "transformer_collection_reference_plane": topology.transformer_collection_reference_plane
        if topology
        else "",
        "transformer_network_terminal_id": topology.transformer_network_terminal_id
        if topology
        else "",
        "transformer_network_reference_plane": topology.transformer_network_reference_plane
        if topology
        else "",
        "connection_semantics": topology.connection_semantics if topology else "",
        "equipment_parameter_source": equipment.parameter_source if equipment else "",
        "equipment_confidence": equipment.confidence if equipment else "",
        "topology_parameter_source": topology.parameter_source if topology else "",
        "topology_confidence": topology.confidence if topology else "",
        "transformer_static_authority_state": state,
        "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
        "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
        "transformer_static_authority_scope": TRANSFORMER_STATIC_AUTHORITY_SCOPE,
        "transformer_static_authority_coverage_scope": TRANSFORMER_STATIC_AUTHORITY_COVERAGE_SCOPE,
    }


def _state_frame(transformer_ids: list[str], records: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        records, index=pd.Index(transformer_ids, name="transformer_id", dtype=object)
    )
    frame = frame.reindex(columns=_COLUMNS)
    for column in _BOOL_COLUMNS:
        frame[column] = frame[column].astype(bool)
    for column in _FLOAT_COLUMNS:
        frame[column] = frame[column].astype("float64")
    for column in set(_COLUMNS) - _BOOL_COLUMNS - _FLOAT_COLUMNS:
        frame[column] = frame[column].astype(object)
    return frame


def _diagnostics(
    s11a: TopologyLvAcCollectionAuthorityResult,
    equipment: Mapping[str, TransformerStaticEquipmentAuthority],
    transformer_topology: Mapping[str, TransformerBoundaryTopologyAuthority],
    states: pd.DataFrame,
) -> TopologyTransformerStaticAuthorityDiagnostics:
    resolved = int(states["transformer_static_authority_resolved"].sum())
    return TopologyTransformerStaticAuthorityDiagnostics(
        transformer_record_count=len(states),
        equipment_authority_count=len(equipment),
        topology_authority_count=len(transformer_topology),
        resolved_transformer_count=resolved,
        equipment_only_transformer_count=len(equipment) - resolved,
        topology_only_transformer_count=len(transformer_topology) - resolved,
        s11_collection_exit_count=sum(
            node.node_kind == "collection_exit" for node in s11a.nodes_by_id.values()
        ),
        bound_s11_collection_exit_count=len(transformer_topology),
        transformer_terminal_count=2 * len(transformer_topology),
        model=TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
    )


def _same(actual: object, expected: object) -> bool:
    return (
        bool(pd.isna(actual) and pd.isna(expected))
        if isinstance(expected, float) and math.isnan(expected)
        else actual == expected
    )


def _validate_result(
    s11a: TopologyLvAcCollectionAuthorityResult,
    result: TopologyTransformerStaticAuthorityResult,
) -> None:
    if type(result) is not TopologyTransformerStaticAuthorityResult:
        raise RuntimeError("transformer static authority result type is invalid")
    if (
        type(result.equipment_by_id).__name__ != "mappingproxy"
        or type(result.topology_by_id).__name__ != "mappingproxy"
    ):
        raise RuntimeError("transformer static authority result mappings must be immutable copies")
    equipment = result.equipment_by_id
    transformer_topology = result.topology_by_id
    for key, mapped_equipment in equipment.items():
        if (
            type(mapped_equipment) is not TransformerStaticEquipmentAuthority
            or key != mapped_equipment.transformer_id
        ):
            raise RuntimeError("transformer equipment mapping closure is invalid")
        try:
            _validate_equipment_authority(mapped_equipment)
        except ValueError as error:
            raise RuntimeError("transformer equipment result domain is invalid") from error
    for key, mapped_topology in transformer_topology.items():
        if (
            type(mapped_topology) is not TransformerBoundaryTopologyAuthority
            or key != mapped_topology.transformer_id
        ):
            raise RuntimeError("transformer topology mapping closure is invalid")
        try:
            _validate_boundary_authority(mapped_topology)
        except ValueError as error:
            raise RuntimeError("transformer topology result domain is invalid") from error
    try:
        _validate_topology_authority(s11a, transformer_topology)
    except ValueError as error:
        raise RuntimeError("transformer topology result structure is invalid") from error
    transformer_ids = sorted(set(equipment) | set(transformer_topology))
    states = result.transformer_states
    if (
        tuple(states.columns) != _COLUMNS
        or states.index.name != "transformer_id"
        or states.index.has_duplicates
    ):
        raise RuntimeError("transformer static authority state schema/index is invalid")
    if states.index.tolist() != transformer_ids:
        raise RuntimeError("transformer static authority canonical ordering is invalid")
    for column in _COLUMNS:
        expected_dtype = (
            "bool"
            if column in _BOOL_COLUMNS
            else "float64"
            if column in _FLOAT_COLUMNS
            else "object"
        )
        if str(states[column].dtype) != expected_dtype:
            raise RuntimeError(f"transformer static authority dtype is invalid for {column}")
    resolved_count = equipment_only = topology_only = 0
    for transformer_id, row in states.iterrows():
        equipment_authority = equipment.get(transformer_id)
        topology_authority = transformer_topology.get(transformer_id)
        equipment_present = equipment_authority is not None
        topology_present = topology_authority is not None
        resolved = equipment_present and topology_present
        resolved_count += int(resolved)
        equipment_only += int(equipment_present and not topology_present)
        topology_only += int(topology_present and not equipment_present)
        expected_state = (
            "unresolved_missing_transformer_equipment_authority"
            if not equipment_present
            else "unresolved_missing_transformer_topology_authority"
            if not topology_present
            else "resolved_transformer_static_authority"
        )
        collection_voltage = (
            equipment_authority.collection_side_rated_line_to_line_rms_v
            if equipment_authority
            else math.nan
        )
        network_voltage = (
            equipment_authority.network_side_rated_line_to_line_rms_v
            if equipment_authority
            else math.nan
        )
        collection_terminal = (
            topology_authority.transformer_collection_terminal_id if topology_authority else ""
        )
        collection_plane = (
            topology_authority.transformer_collection_reference_plane if topology_authority else ""
        )
        network_plane = (
            topology_authority.transformer_network_reference_plane if topology_authority else ""
        )
        expected: dict[str, object] = {
            "transformer_equipment_authority_present": equipment_present,
            "transformer_topology_authority_present": topology_present,
            "s11_collection_exit_binding_resolved": topology_present,
            "transformer_static_authority_resolved": resolved,
            "transformer_type": equipment_authority.transformer_type if equipment_authority else "",
            "phase_configuration": equipment_authority.phase_configuration
            if equipment_authority
            else "",
            "voltage_basis": equipment_authority.voltage_basis if equipment_authority else "",
            "rated_apparent_power_va": equipment_authority.rated_apparent_power_va
            if equipment_authority
            else math.nan,
            "collection_side_rated_line_to_line_rms_v": collection_voltage,
            "network_side_rated_line_to_line_rms_v": network_voltage,
            "s11_collection_exit_node_id": topology_authority.s11_collection_exit_node_id
            if topology_authority
            else "",
            "s11_reference_plane": topology_authority.s11_reference_plane
            if topology_authority
            else "",
            "transformer_collection_terminal_id": collection_terminal,
            "transformer_collection_reference_plane": collection_plane,
            "transformer_network_terminal_id": topology_authority.transformer_network_terminal_id
            if topology_authority
            else "",
            "transformer_network_reference_plane": network_plane,
            "connection_semantics": topology_authority.connection_semantics
            if topology_authority
            else "",
            "equipment_parameter_source": equipment_authority.parameter_source
            if equipment_authority
            else "",
            "equipment_confidence": equipment_authority.confidence if equipment_authority else "",
            "topology_parameter_source": topology_authority.parameter_source
            if topology_authority
            else "",
            "topology_confidence": topology_authority.confidence if topology_authority else "",
            "transformer_static_authority_state": expected_state,
            "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
            "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
            "transformer_static_authority_scope": TRANSFORMER_STATIC_AUTHORITY_SCOPE,
            "transformer_static_authority_coverage_scope": (
                TRANSFORMER_STATIC_AUTHORITY_COVERAGE_SCOPE
            ),
        }
        for column, wanted in expected.items():
            if not _same(row[column], wanted):
                raise RuntimeError(
                    f"transformer static authority state does not close for {column}"
                )
    exit_count = sum(node.node_kind == "collection_exit" for node in s11a.nodes_by_id.values())
    expected_diagnostics = TopologyTransformerStaticAuthorityDiagnostics(
        transformer_record_count=len(transformer_ids),
        equipment_authority_count=len(equipment),
        topology_authority_count=len(transformer_topology),
        resolved_transformer_count=resolved_count,
        equipment_only_transformer_count=equipment_only,
        topology_only_transformer_count=topology_only,
        s11_collection_exit_count=exit_count,
        bound_s11_collection_exit_count=len(
            {authority.s11_collection_exit_node_id for authority in transformer_topology.values()}
        ),
        transformer_terminal_count=sum(2 for _ in transformer_topology.values()),
        model=TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
    )
    diagnostics = result.diagnostics
    if diagnostics != expected_diagnostics:
        raise RuntimeError("transformer static authority diagnostics failed exact closure")
    if (
        diagnostics.resolved_transformer_count
        + diagnostics.equipment_only_transformer_count
        + diagnostics.topology_only_transformer_count
        != diagnostics.transformer_record_count
    ):
        raise RuntimeError("transformer record diagnostics do not close")
    if (
        diagnostics.equipment_authority_count
        != diagnostics.resolved_transformer_count + diagnostics.equipment_only_transformer_count
    ):
        raise RuntimeError("transformer equipment diagnostics do not close")
    if (
        diagnostics.topology_authority_count
        != diagnostics.resolved_transformer_count + diagnostics.topology_only_transformer_count
    ):
        raise RuntimeError("transformer topology diagnostics do not close")
    if (
        diagnostics.bound_s11_collection_exit_count != diagnostics.topology_authority_count
        or diagnostics.transformer_terminal_count != 2 * diagnostics.topology_authority_count
    ):
        raise RuntimeError("transformer binding diagnostics do not close")
    if (
        diagnostics.bound_s11_collection_exit_count > diagnostics.s11_collection_exit_count
        or diagnostics.model != TRANSFORMER_STATIC_AUTHORITY_MODEL_ID
    ):
        raise RuntimeError("transformer diagnostics domain is invalid")
