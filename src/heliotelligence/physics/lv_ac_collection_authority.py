"""Static LV AC collection topology and direct series-impedance authority.

S11A records a balanced three-phase directed radial collection forest. It
does not consume selected dispatch, establish operating voltage, calculate
current or voltage drop, solve power flow, or account for network losses.
Segment direction is from inverter terminals toward collection exits.
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

TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_CONTRACT_ID = (
    "explicit_lv_ac_collection_topology_and_series_impedance_authority_v1"
)
TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_MODEL_ID = (
    "radial_balanced_three_phase_direct_series_impedance_authority_v1"
)
TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_SCOPE = (
    "static_lv_ac_collection_authority_before_operating_voltage_current_and_network_solve"
)
TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_inverter_terminal_junction_collection_exit_and_segment_series_impedance_authority"
)

Confidence = Literal["high", "medium", "low", "unknown"]
NodeKind = Literal["inverter_terminal", "junction", "collection_exit"]

_CONFIDENCES = {"high", "medium", "low", "unknown"}
_NODE_KINDS = {"inverter_terminal", "junction", "collection_exit"}
_COLUMNS = (
    "network_basis_resolved",
    "inverter_terminal_binding_resolved",
    "path_to_collection_exit_resolved",
    "lv_ac_collection_authority_resolved",
    "terminal_node_id",
    "collection_exit_node_id",
    "path_segment_ids",
    "path_segment_count",
    "lv_ac_collection_authority_state",
    "topology_lv_ac_collection_authority_contract",
    "topology_lv_ac_collection_authority_model",
    "topology_lv_ac_collection_authority_scope",
    "topology_lv_ac_collection_authority_coverage_scope",
)
_BOOL_COLUMNS = {
    "network_basis_resolved",
    "inverter_terminal_binding_resolved",
    "path_to_collection_exit_resolved",
    "lv_ac_collection_authority_resolved",
}
_AuthorityT = TypeVar("_AuthorityT")


def _identifier(value: object, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be an exact non-empty string without surrounding whitespace")
    return value


def _source(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("parameter_source must be a non-empty string")
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


@dataclass(frozen=True)
class LvAcCollectionNetworkBasisAuthority:
    phase_configuration: Literal["balanced_three_phase"]
    voltage_basis: Literal["line_to_line_rms"]
    series_impedance_basis: Literal["per_phase_series"]
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        if self.phase_configuration != "balanced_three_phase":
            raise ValueError("phase_configuration must be balanced_three_phase")
        if self.voltage_basis != "line_to_line_rms":
            raise ValueError("voltage_basis must be line_to_line_rms")
        if self.series_impedance_basis != "per_phase_series":
            raise ValueError("series_impedance_basis must be per_phase_series")
        _source(self.parameter_source)
        _confidence(self.confidence)


@dataclass(frozen=True)
class LvAcCollectionNodeAuthority:
    node_id: str
    node_kind: NodeKind
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _identifier(self.node_id, "node_id")
        if type(self.node_kind) is not str or self.node_kind not in _NODE_KINDS:
            raise ValueError("node_kind is unsupported")
        _source(self.parameter_source)
        _confidence(self.confidence)


@dataclass(frozen=True)
class LvAcCollectionSegmentAuthority:
    segment_id: str
    from_node_id: str
    to_node_id: str
    series_resistance_ohm_per_phase: float
    series_reactance_ohm_per_phase: float
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _identifier(self.segment_id, "segment_id")
        _identifier(self.from_node_id, "from_node_id")
        _identifier(self.to_node_id, "to_node_id")
        resistance = _nonnegative_finite(
            self.series_resistance_ohm_per_phase,
            "series_resistance_ohm_per_phase",
        )
        reactance = _nonnegative_finite(
            self.series_reactance_ohm_per_phase,
            "series_reactance_ohm_per_phase",
        )
        _source(self.parameter_source)
        _confidence(self.confidence)
        object.__setattr__(self, "series_resistance_ohm_per_phase", resistance)
        object.__setattr__(self, "series_reactance_ohm_per_phase", reactance)


@dataclass(frozen=True)
class LvAcInverterTerminalBindingAuthority:
    inverter_id: str
    node_id: str
    reference_plane: Literal["inverter_ac_output"]
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _identifier(self.inverter_id, "inverter_id")
        _identifier(self.node_id, "node_id")
        if self.reference_plane != "inverter_ac_output":
            raise ValueError("reference_plane must be inverter_ac_output")
        _source(self.parameter_source)
        _confidence(self.confidence)


@dataclass(frozen=True)
class TopologyLvAcCollectionAuthorityDiagnostics:
    inverter_count: int
    represented_inverter_count: int
    node_count: int
    segment_count: int
    inverter_terminal_node_count: int
    junction_node_count: int
    collection_exit_node_count: int
    resolved_inverter_path_count: int
    unresolved_inverter_count: int
    zero_impedance_segment_count: int
    nonzero_impedance_segment_count: int
    model: str


@dataclass(frozen=True)
class TopologyLvAcCollectionAuthorityResult:
    network_basis: LvAcCollectionNetworkBasisAuthority | None
    nodes_by_id: Mapping[str, LvAcCollectionNodeAuthority]
    segments_by_id: Mapping[str, LvAcCollectionSegmentAuthority]
    inverter_terminal_binding_by_inverter_id: Mapping[str, LvAcInverterTerminalBindingAuthority]
    inverter_states: pd.DataFrame
    diagnostics: TopologyLvAcCollectionAuthorityDiagnostics


def resolve_topology_lv_ac_collection_authority(
    topology: ElectricalTopologyConfig,
    network_basis: LvAcCollectionNetworkBasisAuthority | None,
    node_authority_by_id: Mapping[str, LvAcCollectionNodeAuthority],
    segment_authority_by_id: Mapping[str, LvAcCollectionSegmentAuthority],
    inverter_terminal_binding_by_inverter_id: Mapping[str, LvAcInverterTerminalBindingAuthority],
) -> TopologyLvAcCollectionAuthorityResult:
    """Resolve explicit static LV collection authority without an operating solve."""

    if type(topology) is not ElectricalTopologyConfig:
        raise TypeError("topology must be exactly ElectricalTopologyConfig")
    if network_basis is not None and type(network_basis) is not LvAcCollectionNetworkBasisAuthority:
        raise TypeError("network_basis must use the exact authority type or be None")
    nodes = _admit_mapping(
        node_authority_by_id, LvAcCollectionNodeAuthority, "node_id", "node authority"
    )
    segments = _admit_mapping(
        segment_authority_by_id,
        LvAcCollectionSegmentAuthority,
        "segment_id",
        "segment authority",
    )
    bindings = _admit_mapping(
        inverter_terminal_binding_by_inverter_id,
        LvAcInverterTerminalBindingAuthority,
        "inverter_id",
        "inverter terminal binding",
    )
    inverter_ids = [inverter.id for inverter in topology.inverters]
    _validate_graph(inverter_ids, nodes, segments, bindings)

    canonical_nodes = {key: nodes[key] for key in sorted(nodes)}
    canonical_segments = {key: segments[key] for key in sorted(segments)}
    canonical_bindings = {key: bindings[key] for key in inverter_ids if key in bindings}
    outgoing = _outgoing(canonical_segments)
    records = [
        _inverter_record(
            inverter_id,
            network_basis,
            canonical_nodes,
            outgoing,
            canonical_bindings,
        )
        for inverter_id in inverter_ids
    ]
    states = pd.DataFrame.from_records(
        records,
        columns=_COLUMNS,
        index=pd.Index(inverter_ids, name="inverter_id", dtype=object),
    )
    states.index = pd.Index(inverter_ids, name="inverter_id", dtype=object)
    for column in _BOOL_COLUMNS:
        states[column] = states[column].astype("bool")
    states["path_segment_count"] = states["path_segment_count"].astype("Int64")
    for column in set(_COLUMNS) - _BOOL_COLUMNS - {"path_segment_count"}:
        states[column] = states[column].astype("object")

    diagnostics = _diagnostics(topology, canonical_nodes, canonical_segments, states)
    result = TopologyLvAcCollectionAuthorityResult(
        network_basis=network_basis,
        nodes_by_id=MappingProxyType(canonical_nodes.copy()),
        segments_by_id=MappingProxyType(canonical_segments.copy()),
        inverter_terminal_binding_by_inverter_id=MappingProxyType(canonical_bindings.copy()),
        inverter_states=states.copy(deep=True),
        diagnostics=diagnostics,
    )
    _validate_result(topology, result)
    return result


def _admit_mapping(
    supplied: object,
    authority_type: type[_AuthorityT],
    identity_field: str,
    label: str,
) -> dict[str, _AuthorityT]:
    if not isinstance(supplied, Mapping):
        raise TypeError(f"{label} input must be a mapping")
    admitted: dict[str, _AuthorityT] = {}
    for key, authority in supplied.items():
        if type(key) is not str:
            raise TypeError(f"{label} keys must be strings")
        if type(authority) is not authority_type:
            raise TypeError(f"{label} values must use the exact authority type")
        if key != getattr(authority, identity_field):
            raise ValueError(f"{label} mapping key does not match {identity_field}")
        admitted[key] = authority
    return admitted


def _outgoing(
    segments: Mapping[str, LvAcCollectionSegmentAuthority],
) -> dict[str, LvAcCollectionSegmentAuthority]:
    return {segment.from_node_id: segment for segment in segments.values()}


def _validate_graph(
    inverter_ids: list[str],
    nodes: Mapping[str, object],
    segments: Mapping[str, object],
    bindings: Mapping[str, object],
) -> None:
    typed_nodes = {
        key: value for key, value in nodes.items() if type(value) is LvAcCollectionNodeAuthority
    }
    typed_segments = {
        key: value
        for key, value in segments.items()
        if type(value) is LvAcCollectionSegmentAuthority
    }
    typed_bindings = {
        key: value
        for key, value in bindings.items()
        if type(value) is LvAcInverterTerminalBindingAuthority
    }
    known_inverters = set(inverter_ids)
    unexpected = set(typed_bindings) - known_inverters
    if unexpected:
        raise ValueError(f"unknown inverter terminal bindings: {sorted(unexpected)!r}")
    terminal_users: dict[str, str] = {}
    for inverter_id, binding in typed_bindings.items():
        node = typed_nodes.get(binding.node_id)
        if node is None:
            raise ValueError("inverter terminal binding references an unknown node")
        if node.node_kind != "inverter_terminal":
            raise ValueError("inverter terminal binding must reference an inverter_terminal node")
        if binding.node_id in terminal_users:
            raise ValueError("an inverter_terminal node may bind to only one inverter")
        terminal_users[binding.node_id] = inverter_id
    supplied_terminals = {
        node_id for node_id, node in typed_nodes.items() if node.node_kind == "inverter_terminal"
    }
    if supplied_terminals != set(terminal_users):
        raise ValueError("every supplied inverter_terminal node must have exactly one binding")

    outgoing: dict[str, LvAcCollectionSegmentAuthority] = {}
    for segment in typed_segments.values():
        if segment.from_node_id == segment.to_node_id:
            raise ValueError("LV AC collection segments must not be self loops")
        source = typed_nodes.get(segment.from_node_id)
        destination = typed_nodes.get(segment.to_node_id)
        if source is None or destination is None:
            raise ValueError("LV AC collection segment references an unknown node")
        if source.node_kind == "collection_exit":
            raise ValueError("collection_exit nodes must not originate segments")
        if destination.node_kind == "inverter_terminal":
            raise ValueError("inverter_terminal nodes must not receive segments")
        if segment.from_node_id in outgoing:
            raise ValueError("LV AC collection nodes may have at most one outgoing segment")
        outgoing[segment.from_node_id] = segment

    colors: dict[str, int] = {}

    def visit(node_id: str) -> None:
        color = colors.get(node_id, 0)
        if color == 1:
            raise ValueError("LV AC collection graph contains a directed cycle")
        if color == 2:
            return
        colors[node_id] = 1
        segment = outgoing.get(node_id)
        if segment is not None:
            visit(segment.to_node_id)
        colors[node_id] = 2

    for node_id in typed_nodes:
        visit(node_id)


def _trace_path(
    terminal_node_id: str,
    nodes: Mapping[str, LvAcCollectionNodeAuthority],
    outgoing: Mapping[str, LvAcCollectionSegmentAuthority],
) -> tuple[bool, str, tuple[str, ...]]:
    node_id = terminal_node_id
    path: list[str] = []
    while True:
        node = nodes[node_id]
        if node.node_kind == "collection_exit":
            return True, node_id, tuple(path)
        segment = outgoing.get(node_id)
        if segment is None:
            return False, "", ()
        path.append(segment.segment_id)
        node_id = segment.to_node_id


def _inverter_record(
    inverter_id: str,
    network_basis: LvAcCollectionNetworkBasisAuthority | None,
    nodes: Mapping[str, LvAcCollectionNodeAuthority],
    outgoing: Mapping[str, LvAcCollectionSegmentAuthority],
    bindings: Mapping[str, LvAcInverterTerminalBindingAuthority],
) -> dict[str, object]:
    basis_resolved = network_basis is not None
    binding = bindings.get(inverter_id)
    binding_resolved = binding is not None
    terminal_node_id = binding.node_id if binding is not None else ""
    path_resolved, exit_node_id, path = (
        _trace_path(terminal_node_id, nodes, outgoing) if binding is not None else (False, "", ())
    )
    resolved = basis_resolved and binding_resolved and path_resolved
    state = (
        "unresolved_no_lv_ac_network_basis_authority"
        if not basis_resolved
        else "unresolved_no_inverter_terminal_binding"
        if not binding_resolved
        else "unresolved_inverter_terminal_path_to_collection_exit"
        if not path_resolved
        else "resolved_lv_ac_collection_path_authority"
    )
    return {
        "network_basis_resolved": basis_resolved,
        "inverter_terminal_binding_resolved": binding_resolved,
        "path_to_collection_exit_resolved": path_resolved,
        "lv_ac_collection_authority_resolved": resolved,
        "terminal_node_id": terminal_node_id,
        "collection_exit_node_id": exit_node_id,
        "path_segment_ids": path,
        "path_segment_count": len(path) if path_resolved else pd.NA,
        "lv_ac_collection_authority_state": state,
        "topology_lv_ac_collection_authority_contract": (
            TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_CONTRACT_ID
        ),
        "topology_lv_ac_collection_authority_model": (TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_MODEL_ID),
        "topology_lv_ac_collection_authority_scope": (TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_SCOPE),
        "topology_lv_ac_collection_authority_coverage_scope": (
            TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_COVERAGE_SCOPE
        ),
    }


def _diagnostics(
    topology: ElectricalTopologyConfig,
    nodes: Mapping[str, LvAcCollectionNodeAuthority],
    segments: Mapping[str, LvAcCollectionSegmentAuthority],
    states: pd.DataFrame,
) -> TopologyLvAcCollectionAuthorityDiagnostics:
    zero = sum(
        segment.series_resistance_ohm_per_phase == 0.0
        and segment.series_reactance_ohm_per_phase == 0.0
        for segment in segments.values()
    )
    resolved_paths = int(states["path_to_collection_exit_resolved"].sum())
    return TopologyLvAcCollectionAuthorityDiagnostics(
        inverter_count=topology.inverter_count,
        represented_inverter_count=int(states["inverter_terminal_binding_resolved"].sum()),
        node_count=len(nodes),
        segment_count=len(segments),
        inverter_terminal_node_count=sum(
            node.node_kind == "inverter_terminal" for node in nodes.values()
        ),
        junction_node_count=sum(node.node_kind == "junction" for node in nodes.values()),
        collection_exit_node_count=sum(
            node.node_kind == "collection_exit" for node in nodes.values()
        ),
        resolved_inverter_path_count=resolved_paths,
        unresolved_inverter_count=topology.inverter_count - resolved_paths,
        zero_impedance_segment_count=zero,
        nonzero_impedance_segment_count=len(segments) - zero,
        model=TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_MODEL_ID,
    )


def _validate_result(
    topology: ElectricalTopologyConfig,
    result: TopologyLvAcCollectionAuthorityResult,
) -> None:
    if type(result) is not TopologyLvAcCollectionAuthorityResult:
        raise RuntimeError("LV AC collection result type is invalid")
    if any(
        type(mapping).__name__ != "mappingproxy"
        for mapping in (
            result.nodes_by_id,
            result.segments_by_id,
            result.inverter_terminal_binding_by_inverter_id,
        )
    ):
        raise RuntimeError("LV AC collection result mappings must be immutable copies")
    if result.network_basis is not None and type(result.network_basis) is not (
        LvAcCollectionNetworkBasisAuthority
    ):
        raise RuntimeError("LV AC collection network basis type is invalid")
    for key, node_authority in result.nodes_by_id.items():
        if type(node_authority) is not LvAcCollectionNodeAuthority or key != node_authority.node_id:
            raise RuntimeError("LV AC collection node mapping closure is invalid")
    for key, segment_authority in result.segments_by_id.items():
        if (
            type(segment_authority) is not LvAcCollectionSegmentAuthority
            or key != segment_authority.segment_id
        ):
            raise RuntimeError("LV AC collection segment mapping closure is invalid")
        if not (
            math.isfinite(segment_authority.series_resistance_ohm_per_phase)
            and segment_authority.series_resistance_ohm_per_phase >= 0.0
            and math.isfinite(segment_authority.series_reactance_ohm_per_phase)
            and segment_authority.series_reactance_ohm_per_phase >= 0.0
        ):
            raise RuntimeError("LV AC collection segment impedance domain is invalid")
    for key, binding_authority in result.inverter_terminal_binding_by_inverter_id.items():
        if (
            type(binding_authority) is not LvAcInverterTerminalBindingAuthority
            or key != binding_authority.inverter_id
        ):
            raise RuntimeError("LV AC collection binding mapping closure is invalid")
    inverter_ids = [inverter.id for inverter in topology.inverters]
    states = result.inverter_states
    if tuple(states.columns) != _COLUMNS:
        raise RuntimeError("LV AC collection state schema is invalid")
    if states.index.name != "inverter_id" or states.index.has_duplicates:
        raise RuntimeError("LV AC collection state index is invalid")
    if states.index.tolist() != inverter_ids:
        raise RuntimeError("LV AC collection canonical inverter ordering is invalid")
    for column in _COLUMNS:
        expected_dtype = (
            "bool"
            if column in _BOOL_COLUMNS
            else "Int64"
            if column == "path_segment_count"
            else "object"
        )
        if str(states[column].dtype) != expected_dtype:
            raise RuntimeError(f"LV AC collection dtype is invalid for {column}")

    _validate_graph(
        inverter_ids,
        result.nodes_by_id,
        result.segments_by_id,
        result.inverter_terminal_binding_by_inverter_id,
    )
    outgoing = _outgoing(result.segments_by_id)
    for inverter_id, row in states.iterrows():
        expected = _inverter_record(
            inverter_id,
            result.network_basis,
            result.nodes_by_id,
            outgoing,
            result.inverter_terminal_binding_by_inverter_id,
        )
        for column in _COLUMNS:
            actual = row[column]
            wanted = expected[column]
            if wanted is pd.NA:
                if not pd.isna(actual):
                    raise RuntimeError("LV AC collection unresolved path count is invalid")
            elif actual != wanted:
                raise RuntimeError(f"LV AC collection state does not close for {column}")

    diagnostics = result.diagnostics
    expected_diagnostics = _diagnostics(topology, result.nodes_by_id, result.segments_by_id, states)
    if diagnostics != expected_diagnostics:
        raise RuntimeError("LV AC collection diagnostics failed exact closure")
    if (
        diagnostics.inverter_terminal_node_count
        + diagnostics.junction_node_count
        + diagnostics.collection_exit_node_count
        != diagnostics.node_count
    ):
        raise RuntimeError("LV AC collection node diagnostics do not close")
    if (
        diagnostics.resolved_inverter_path_count + diagnostics.unresolved_inverter_count
        != diagnostics.inverter_count
    ):
        raise RuntimeError("LV AC collection inverter diagnostics do not close")
    if (
        diagnostics.zero_impedance_segment_count + diagnostics.nonzero_impedance_segment_count
        != diagnostics.segment_count
    ):
        raise RuntimeError("LV AC collection segment diagnostics do not close")
    if diagnostics.represented_inverter_count != len(
        result.inverter_terminal_binding_by_inverter_id
    ):
        raise RuntimeError("LV AC collection represented-inverter count is invalid")
    if diagnostics.model != TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_MODEL_ID:
        raise RuntimeError("LV AC collection diagnostics model is invalid")
