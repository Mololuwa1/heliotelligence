"""Static MV/HV network, grid-boundary, and revenue-meter authority.

S13A admits topology and reference planes only.  It performs no timestamped
network solve, consumes no S12M operating state, and does not reopen S12 loss
ownership.  A revenue-meter boundary and a grid boundary are distinct objects;
co-location exists only when both explicitly reference the same node.
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

MV_HV_NETWORK_AUTHORITY_CONTRACT_ID = (
    "explicit_mv_hv_network_topology_nominal_pi_and_meter_boundary_authority_v1"
)
MV_HV_NETWORK_AUTHORITY_MODEL_ID = (
    "radial_balanced_three_phase_nominal_pi_network_with_explicit_"
    "transformer_grid_and_revenue_meter_bindings_v1"
)
MV_HV_NETWORK_AUTHORITY_SCOPE = (
    "static_mv_hv_collection_and_meter_reference_plane_authority_before_"
    "boundary_voltage_and_network_solve"
)
MV_HV_NETWORK_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_post_s12_transformer_radial_same_voltage_level_networks_"
    "with_distinct_grid_and_revenue_meter_boundaries"
)

Confidence = Literal["high", "medium", "low", "unknown"]
_CONFIDENCES = {"high", "medium", "low", "unknown"}
_STATES = (
    "unresolved_no_mv_hv_network_basis_authority",
    "unresolved_no_transformer_terminal_binding",
    "unresolved_transformer_terminal_path_to_network_exit",
    "unresolved_no_grid_boundary_at_network_exit",
    "unresolved_no_revenue_meter_boundary_on_path",
    "resolved_mv_hv_network_and_meter_boundary_authority",
)
_COLUMNS = (
    "network_basis_resolved",
    "transformer_static_authority_resolved",
    "transformer_terminal_binding_resolved",
    "path_to_network_exit_resolved",
    "grid_boundary_resolved",
    "revenue_meter_boundary_resolved",
    "revenue_meter_on_transformer_path",
    "revenue_meter_colocated_with_grid_boundary",
    "mv_hv_network_authority_resolved",
    "transformer_network_terminal_id",
    "transformer_terminal_node_id",
    "transformer_voltage_level_id",
    "network_exit_node_id",
    "network_exit_voltage_level_id",
    "grid_boundary_id",
    "revenue_meter_id",
    "revenue_meter_node_id",
    "path_segment_ids",
    "path_segment_count",
    "mv_hv_network_authority_state",
    "transformer_static_authority_contract",
    "transformer_static_authority_model",
    "mv_hv_network_authority_contract",
    "mv_hv_network_authority_model",
    "mv_hv_network_authority_scope",
    "mv_hv_network_authority_coverage_scope",
)
_BOOL_COLUMNS = set(_COLUMNS[:9])


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


def _finite(value: object, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real non-Boolean number")
    number = float(value)
    if not math.isfinite(number) or (number <= 0 if positive else number < 0):
        domain = "strictly positive" if positive else "non-negative"
        raise ValueError(f"{name} must be finite and {domain}")
    return number


@dataclass(frozen=True)
class MvHvNetworkBasisAuthority:
    phase_configuration: Literal["balanced_three_phase"]
    voltage_basis: Literal["line_to_line_rms"]
    series_impedance_basis: Literal["per_phase_series"]
    shunt_admittance_basis: Literal["per_phase_total_nominal_pi"]
    topology_model: Literal["radial"]
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        expected = (
            "balanced_three_phase",
            "line_to_line_rms",
            "per_phase_series",
            "per_phase_total_nominal_pi",
            "radial",
        )
        if (
            self.phase_configuration,
            self.voltage_basis,
            self.series_impedance_basis,
            self.shunt_admittance_basis,
            self.topology_model,
        ) != expected:
            raise ValueError("MV/HV network basis semantics are unsupported")
        _source(self.parameter_source)
        _confidence(self.confidence)


@dataclass(frozen=True)
class MvHvVoltageLevelAuthority:
    voltage_level_id: str
    nominal_line_to_line_rms_v: float
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _identifier(self.voltage_level_id, "voltage_level_id")
        object.__setattr__(
            self,
            "nominal_line_to_line_rms_v",
            _finite(self.nominal_line_to_line_rms_v, "nominal_line_to_line_rms_v", positive=True),
        )
        _source(self.parameter_source)
        _confidence(self.confidence)


@dataclass(frozen=True)
class MvHvNetworkNodeAuthority:
    node_id: str
    node_kind: Literal["transformer_terminal", "junction", "network_exit"]
    voltage_level_id: str
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _identifier(self.node_id, "node_id")
        if self.node_kind not in {"transformer_terminal", "junction", "network_exit"}:
            raise ValueError("node_kind is unsupported")
        _identifier(self.voltage_level_id, "voltage_level_id")
        _source(self.parameter_source)
        _confidence(self.confidence)


@dataclass(frozen=True)
class MvHvNetworkSegmentAuthority:
    segment_id: str
    from_node_id: str
    to_node_id: str
    series_resistance_ohm_per_phase: float
    series_reactance_ohm_per_phase: float
    total_shunt_conductance_siemens_per_phase: float
    total_shunt_susceptance_siemens_per_phase: float
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        for name in ("segment_id", "from_node_id", "to_node_id"):
            _identifier(getattr(self, name), name)
        for name in (
            "series_resistance_ohm_per_phase",
            "series_reactance_ohm_per_phase",
            "total_shunt_conductance_siemens_per_phase",
            "total_shunt_susceptance_siemens_per_phase",
        ):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        _source(self.parameter_source)
        _confidence(self.confidence)


@dataclass(frozen=True)
class MvHvTransformerTerminalBindingAuthority:
    transformer_id: str
    transformer_network_terminal_id: str
    node_id: str
    transformer_reference_plane: Literal["transformer_network_side_terminal"]
    network_reference_plane: Literal["mv_hv_transformer_terminal_node"]
    connection_semantics: Literal["direct_electrical_boundary"]
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        for name in ("transformer_id", "transformer_network_terminal_id", "node_id"):
            _identifier(getattr(self, name), name)
        if self.transformer_reference_plane != "transformer_network_side_terminal":
            raise ValueError("transformer_reference_plane is unsupported")
        if self.network_reference_plane != "mv_hv_transformer_terminal_node":
            raise ValueError("network_reference_plane is unsupported")
        if self.connection_semantics != "direct_electrical_boundary":
            raise ValueError("connection_semantics is unsupported")
        _source(self.parameter_source)
        _confidence(self.confidence)


@dataclass(frozen=True)
class MvHvGridBoundaryAuthority:
    grid_boundary_id: str
    node_id: str
    reference_plane: Literal["grid_interconnection_boundary"]
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _identifier(self.grid_boundary_id, "grid_boundary_id")
        _identifier(self.node_id, "node_id")
        if self.reference_plane != "grid_interconnection_boundary":
            raise ValueError("grid boundary reference_plane is unsupported")
        _source(self.parameter_source)
        _confidence(self.confidence)


@dataclass(frozen=True)
class RevenueMeterBoundaryAuthority:
    revenue_meter_id: str
    node_id: str
    reference_plane: Literal["revenue_meter_boundary"]
    active_power_sign_convention: Literal["positive_plant_to_grid"]
    reactive_power_sign_convention: Literal["positive_plant_to_grid"]
    power_basis: Literal["three_phase_total"]
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _identifier(self.revenue_meter_id, "revenue_meter_id")
        _identifier(self.node_id, "node_id")
        if (
            self.reference_plane,
            self.active_power_sign_convention,
            self.reactive_power_sign_convention,
            self.power_basis,
        ) != (
            "revenue_meter_boundary",
            "positive_plant_to_grid",
            "positive_plant_to_grid",
            "three_phase_total",
        ):
            raise ValueError("revenue-meter boundary semantics are unsupported")
        _source(self.parameter_source)
        _confidence(self.confidence)


@dataclass(frozen=True)
class TopologyMvHvNetworkAuthorityDiagnostics:
    transformer_count: int
    represented_transformer_count: int
    voltage_level_count: int
    node_count: int
    segment_count: int
    transformer_terminal_node_count: int
    junction_node_count: int
    network_exit_node_count: int
    grid_boundary_count: int
    revenue_meter_boundary_count: int
    resolved_transformer_path_count: int
    resolved_transformer_meter_path_count: int
    fully_resolved_transformer_count: int
    unresolved_transformer_count: int
    zero_series_impedance_segment_count: int
    nonzero_series_impedance_segment_count: int
    zero_shunt_admittance_segment_count: int
    nonzero_shunt_admittance_segment_count: int
    colocated_meter_grid_boundary_count: int
    model: str


@dataclass(frozen=True)
class TopologyMvHvNetworkAuthorityResult:
    network_basis: MvHvNetworkBasisAuthority | None
    voltage_levels_by_id: Mapping[str, MvHvVoltageLevelAuthority]
    nodes_by_id: Mapping[str, MvHvNetworkNodeAuthority]
    segments_by_id: Mapping[str, MvHvNetworkSegmentAuthority]
    transformer_terminal_binding_by_transformer_id: Mapping[
        str, MvHvTransformerTerminalBindingAuthority
    ]
    grid_boundary_by_id: Mapping[str, MvHvGridBoundaryAuthority]
    revenue_meter_boundary_by_id: Mapping[str, RevenueMeterBoundaryAuthority]
    transformer_states: pd.DataFrame
    diagnostics: TopologyMvHvNetworkAuthorityDiagnostics


class _Identified(Protocol):
    @property
    def parameter_source(self) -> str: ...


T = TypeVar("T", bound=_Identified)


def _admit(mapping: Mapping[str, T], expected: type[T], id_field: str, label: str) -> dict[str, T]:
    if not isinstance(mapping, Mapping):
        raise TypeError(f"{label} authority must be a mapping")
    admitted: dict[str, T] = {}
    for key, value in mapping.items():
        _identifier(key, f"{label} mapping key")
        if type(value) is not expected:
            raise TypeError(f"{label} authority has an invalid value type")
        if key != getattr(value, id_field):
            raise ValueError(f"{label} mapping key does not match {id_field}")
        admitted[key] = value
    return dict(sorted(admitted.items()))


def _validate_s12a(supplied: object, canonical: TopologyTransformerStaticAuthorityResult) -> None:
    if type(supplied) is not TopologyTransformerStaticAuthorityResult:
        raise ValueError("supplied S12A result type is invalid")
    assert isinstance(supplied, TopologyTransformerStaticAuthorityResult)
    for name in ("equipment_by_id", "topology_by_id"):
        actual = getattr(supplied, name)
        expected = getattr(canonical, name)
        if type(actual) is not MappingProxyType or tuple(actual.items()) != tuple(expected.items()):
            raise ValueError("supplied S12A mapping failed immutable canonical replay")
    try:
        pd.testing.assert_frame_equal(
            supplied.transformer_states, canonical.transformer_states, check_exact=True
        )
    except AssertionError as error:
        raise ValueError("supplied S12A frame failed canonical replay") from error
    if supplied.diagnostics != canonical.diagnostics:
        raise ValueError("supplied S12A diagnostics failed canonical replay")


def _validate_graph(
    levels: Mapping[str, MvHvVoltageLevelAuthority],
    nodes: Mapping[str, MvHvNetworkNodeAuthority],
    segments: Mapping[str, MvHvNetworkSegmentAuthority],
) -> dict[str, MvHvNetworkSegmentAuthority]:
    outgoing: dict[str, MvHvNetworkSegmentAuthority] = {}
    for segment in segments.values():
        if segment.from_node_id == segment.to_node_id:
            raise ValueError("MV/HV segment self loops are not allowed")
        if segment.from_node_id not in nodes or segment.to_node_id not in nodes:
            raise ValueError("MV/HV segment references an unknown node")
        source, target = nodes[segment.from_node_id], nodes[segment.to_node_id]
        if source.node_kind == "network_exit":
            raise ValueError("network_exit cannot originate a segment")
        if target.node_kind == "transformer_terminal":
            raise ValueError("transformer_terminal cannot receive a segment")
        if source.voltage_level_id != target.voltage_level_id:
            raise ValueError("MV/HV segment cannot cross voltage levels")
        if source.node_id in outgoing:
            raise ValueError("MV/HV node may have at most one outgoing segment")
        outgoing[source.node_id] = segment
    for node in nodes.values():
        if node.voltage_level_id not in levels:
            raise ValueError("MV/HV node references an unknown voltage level")
    for start in nodes:
        seen: set[str] = set()
        current = start
        while current in outgoing:
            if current in seen:
                raise ValueError("MV/HV directed cycle is not allowed")
            seen.add(current)
            current = outgoing[current].to_node_id
    return outgoing


def _validate_boundaries(
    canonical: TopologyTransformerStaticAuthorityResult,
    nodes: Mapping[str, MvHvNetworkNodeAuthority],
    bindings: Mapping[str, MvHvTransformerTerminalBindingAuthority],
    grids: Mapping[str, MvHvGridBoundaryAuthority],
    meters: Mapping[str, RevenueMeterBoundaryAuthority],
) -> None:
    bound_nodes: set[str] = set()
    for transformer_id, binding in bindings.items():
        if transformer_id not in canonical.transformer_states.index:
            raise ValueError("transformer terminal binding references an unknown transformer")
        topology = canonical.topology_by_id.get(transformer_id)
        if topology is None:
            raise ValueError("transformer terminal binding requires S12A topology authority")
        if binding.transformer_network_terminal_id != topology.transformer_network_terminal_id:
            raise ValueError("transformer_network_terminal_id does not match canonical S12A")
        node = nodes.get(binding.node_id)
        if node is None or node.node_kind != "transformer_terminal":
            raise ValueError("transformer binding node must be a transformer_terminal")
        if binding.node_id in bound_nodes:
            raise ValueError("transformer_terminal node may bind to only one transformer")
        bound_nodes.add(binding.node_id)
    supplied_terminals = {
        node.node_id for node in nodes.values() if node.node_kind == "transformer_terminal"
    }
    if supplied_terminals != bound_nodes:
        raise ValueError("every supplied transformer_terminal node requires exactly one binding")
    grid_nodes: set[str] = set()
    for grid in grids.values():
        node = nodes.get(grid.node_id)
        if node is None or node.node_kind != "network_exit":
            raise ValueError("grid boundary node must be a network_exit")
        if grid.node_id in grid_nodes:
            raise ValueError("network_exit may have at most one grid boundary")
        grid_nodes.add(grid.node_id)
    for meter in meters.values():
        if meter.node_id not in nodes:
            raise ValueError("revenue meter references an unknown node")


def _trace(
    start: str,
    nodes: Mapping[str, MvHvNetworkNodeAuthority],
    outgoing: Mapping[str, MvHvNetworkSegmentAuthority],
) -> tuple[list[str], list[str], str | None]:
    path_nodes, path_segments = [start], []
    current = start
    while current in outgoing:
        segment = outgoing[current]
        path_segments.append(segment.segment_id)
        current = segment.to_node_id
        path_nodes.append(current)
    exit_id = current if nodes[current].node_kind == "network_exit" else None
    return path_nodes, path_segments, exit_id


def _record(
    transformer_id: str,
    canonical: TopologyTransformerStaticAuthorityResult,
    basis: MvHvNetworkBasisAuthority | None,
    nodes: Mapping[str, MvHvNetworkNodeAuthority],
    outgoing: Mapping[str, MvHvNetworkSegmentAuthority],
    bindings: Mapping[str, MvHvTransformerTerminalBindingAuthority],
    grids: Mapping[str, MvHvGridBoundaryAuthority],
    meters: Mapping[str, RevenueMeterBoundaryAuthority],
) -> dict[str, object]:
    row: dict[str, object] = {name: None for name in _COLUMNS}
    for name in _BOOL_COLUMNS:
        row[name] = False
    static_resolved = bool(
        canonical.transformer_states.loc[transformer_id, "transformer_static_authority_resolved"]
    )
    topology = canonical.topology_by_id.get(transformer_id)
    binding = bindings.get(transformer_id)
    row.update(
        {
            "network_basis_resolved": basis is not None,
            "transformer_static_authority_resolved": static_resolved,
            "transformer_network_terminal_id": (
                topology.transformer_network_terminal_id if topology else None
            ),
            "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
            "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
            "mv_hv_network_authority_contract": MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
            "mv_hv_network_authority_model": MV_HV_NETWORK_AUTHORITY_MODEL_ID,
            "mv_hv_network_authority_scope": MV_HV_NETWORK_AUTHORITY_SCOPE,
            "mv_hv_network_authority_coverage_scope": MV_HV_NETWORK_AUTHORITY_COVERAGE_SCOPE,
            "path_segment_ids": (),
            "path_segment_count": 0,
        }
    )
    if basis is None:
        state = _STATES[0]
    elif binding is None:
        state = _STATES[1]
    else:
        row["transformer_terminal_binding_resolved"] = True
        row["transformer_terminal_node_id"] = binding.node_id
        row["transformer_voltage_level_id"] = nodes[binding.node_id].voltage_level_id
        path_nodes, path_segments, exit_id = _trace(binding.node_id, nodes, outgoing)
        row["path_segment_ids"] = tuple(path_segments)
        row["path_segment_count"] = len(path_segments)
        if exit_id is None:
            state = _STATES[2]
        else:
            row["path_to_network_exit_resolved"] = True
            row["network_exit_node_id"] = exit_id
            row["network_exit_voltage_level_id"] = nodes[exit_id].voltage_level_id
            matching_grids = [grid for grid in grids.values() if grid.node_id == exit_id]
            path_meters = [meter for meter in meters.values() if meter.node_id in path_nodes]
            if len(path_meters) > 1:
                raise ValueError("multiple revenue meters on one transformer path are ambiguous")
            if matching_grids:
                row["grid_boundary_resolved"] = True
                row["grid_boundary_id"] = matching_grids[0].grid_boundary_id
            if path_meters:
                meter = path_meters[0]
                row.update(
                    {
                        "revenue_meter_boundary_resolved": True,
                        "revenue_meter_on_transformer_path": True,
                        "revenue_meter_id": meter.revenue_meter_id,
                        "revenue_meter_node_id": meter.node_id,
                        "revenue_meter_colocated_with_grid_boundary": bool(
                            matching_grids and meter.node_id == matching_grids[0].node_id
                        ),
                    }
                )
            if not matching_grids:
                state = _STATES[3]
            elif not path_meters:
                state = _STATES[4]
            else:
                row["mv_hv_network_authority_resolved"] = True
                state = _STATES[5]
    row["mv_hv_network_authority_state"] = state
    return row


def _frame(ids: list[str], records: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(records, index=pd.Index(ids, name="transformer_id"), columns=_COLUMNS)
    for name in _BOOL_COLUMNS:
        frame[name] = frame[name].astype(bool)
    frame["path_segment_count"] = frame["path_segment_count"].astype("int64")
    for name in set(_COLUMNS) - _BOOL_COLUMNS - {"path_segment_count"}:
        frame[name] = frame[name].astype(object)
    return frame


def _diagnostics(
    frame: pd.DataFrame,
    levels: Mapping[str, MvHvVoltageLevelAuthority],
    nodes: Mapping[str, MvHvNetworkNodeAuthority],
    segments: Mapping[str, MvHvNetworkSegmentAuthority],
    bindings: Mapping[str, MvHvTransformerTerminalBindingAuthority],
    grids: Mapping[str, MvHvGridBoundaryAuthority],
    meters: Mapping[str, RevenueMeterBoundaryAuthority],
) -> TopologyMvHvNetworkAuthorityDiagnostics:
    resolved = frame["mv_hv_network_authority_resolved"]
    zero_z = sum(
        segment.series_resistance_ohm_per_phase == 0
        and segment.series_reactance_ohm_per_phase == 0
        for segment in segments.values()
    )
    zero_y = sum(
        segment.total_shunt_conductance_siemens_per_phase == 0
        and segment.total_shunt_susceptance_siemens_per_phase == 0
        for segment in segments.values()
    )
    grid_nodes = {grid.node_id for grid in grids.values()}
    return TopologyMvHvNetworkAuthorityDiagnostics(
        len(frame),
        len(bindings),
        len(levels),
        len(nodes),
        len(segments),
        sum(node.node_kind == "transformer_terminal" for node in nodes.values()),
        sum(node.node_kind == "junction" for node in nodes.values()),
        sum(node.node_kind == "network_exit" for node in nodes.values()),
        len(grids),
        len(meters),
        int(frame["path_to_network_exit_resolved"].sum()),
        int(frame["revenue_meter_on_transformer_path"].sum()),
        int(resolved.sum()),
        int((~resolved).sum()),
        zero_z,
        len(segments) - zero_z,
        zero_y,
        len(segments) - zero_y,
        sum(meter.node_id in grid_nodes for meter in meters.values()),
        MV_HV_NETWORK_AUTHORITY_MODEL_ID,
    )


def resolve_topology_mv_hv_network_authority(
    topology: ElectricalTopologyConfig,
    network_basis: LvAcCollectionNetworkBasisAuthority | None,
    node_authority_by_id: Mapping[str, LvAcCollectionNodeAuthority],
    segment_authority_by_id: Mapping[str, LvAcCollectionSegmentAuthority],
    inverter_terminal_binding_by_inverter_id: Mapping[str, LvAcInverterTerminalBindingAuthority],
    lv_ac_collection_authority: TopologyLvAcCollectionAuthorityResult,
    transformer_equipment_by_id: Mapping[str, TransformerStaticEquipmentAuthority],
    transformer_topology_by_id: Mapping[str, TransformerBoundaryTopologyAuthority],
    transformer_static_authority: TopologyTransformerStaticAuthorityResult,
    mv_hv_network_basis: MvHvNetworkBasisAuthority | None,
    mv_hv_voltage_level_by_id: Mapping[str, MvHvVoltageLevelAuthority],
    mv_hv_node_by_id: Mapping[str, MvHvNetworkNodeAuthority],
    mv_hv_segment_by_id: Mapping[str, MvHvNetworkSegmentAuthority],
    mv_hv_transformer_terminal_binding_by_transformer_id: Mapping[
        str, MvHvTransformerTerminalBindingAuthority
    ],
    mv_hv_grid_boundary_by_id: Mapping[str, MvHvGridBoundaryAuthority],
    revenue_meter_boundary_by_id: Mapping[str, RevenueMeterBoundaryAuthority],
) -> TopologyMvHvNetworkAuthorityResult:
    canonical = resolve_transformer_static_authority(
        topology,
        network_basis,
        node_authority_by_id,
        segment_authority_by_id,
        inverter_terminal_binding_by_inverter_id,
        lv_ac_collection_authority,
        transformer_equipment_by_id,
        transformer_topology_by_id,
    )
    _validate_s12a(transformer_static_authority, canonical)
    if (
        mv_hv_network_basis is not None
        and type(mv_hv_network_basis) is not MvHvNetworkBasisAuthority
    ):
        raise TypeError("MV/HV network basis has an invalid type")
    levels = _admit(
        mv_hv_voltage_level_by_id, MvHvVoltageLevelAuthority, "voltage_level_id", "voltage level"
    )
    nodes = _admit(mv_hv_node_by_id, MvHvNetworkNodeAuthority, "node_id", "node")
    segments = _admit(
        mv_hv_segment_by_id, MvHvNetworkSegmentAuthority, "segment_id", "segment"
    )
    bindings = _admit(
        mv_hv_transformer_terminal_binding_by_transformer_id,
        MvHvTransformerTerminalBindingAuthority,
        "transformer_id",
        "transformer binding",
    )
    grids = _admit(
        mv_hv_grid_boundary_by_id, MvHvGridBoundaryAuthority, "grid_boundary_id", "grid boundary"
    )
    meters = _admit(
        revenue_meter_boundary_by_id,
        RevenueMeterBoundaryAuthority,
        "revenue_meter_id",
        "revenue meter",
    )
    outgoing = _validate_graph(levels, nodes, segments)
    _validate_boundaries(canonical, nodes, bindings, grids, meters)
    ids = list(canonical.transformer_states.index)
    records = [
        _record(
            identifier,
            canonical,
            mv_hv_network_basis,
            nodes,
            outgoing,
            bindings,
            grids,
            meters,
        )
        for identifier in ids
    ]
    frame = _frame(ids, records)
    diagnostics = _diagnostics(frame, levels, nodes, segments, bindings, grids, meters)
    result = TopologyMvHvNetworkAuthorityResult(
        mv_hv_network_basis,
        MappingProxyType(dict(levels)),
        MappingProxyType(dict(nodes)),
        MappingProxyType(dict(segments)),
        MappingProxyType(dict(bindings)),
        MappingProxyType(dict(grids)),
        MappingProxyType(dict(meters)),
        frame.copy(deep=True),
        diagnostics,
    )
    _validate_result(canonical, result)
    return result


# The validator duplicates path/state/frame/diagnostic construction rather than
# calling or capturing production builders.
def _validator_graph(
    levels: Mapping[str, MvHvVoltageLevelAuthority],
    nodes: Mapping[str, MvHvNetworkNodeAuthority],
    segments: Mapping[str, MvHvNetworkSegmentAuthority],
) -> dict[str, MvHvNetworkSegmentAuthority]:
    outgoing: dict[str, MvHvNetworkSegmentAuthority] = {}
    for segment in segments.values():
        if segment.from_node_id == segment.to_node_id:
            raise ValueError("MV/HV segment self loops are not allowed")
        if segment.from_node_id not in nodes or segment.to_node_id not in nodes:
            raise ValueError("MV/HV segment references an unknown node")
        source = nodes[segment.from_node_id]
        target = nodes[segment.to_node_id]
        if source.node_kind == "network_exit":
            raise ValueError("network_exit cannot originate a segment")
        if target.node_kind == "transformer_terminal":
            raise ValueError("transformer_terminal cannot receive a segment")
        if source.voltage_level_id != target.voltage_level_id:
            raise ValueError("MV/HV segment cannot cross voltage levels")
        if source.node_id in outgoing:
            raise ValueError("MV/HV node may have at most one outgoing segment")
        outgoing[source.node_id] = segment
    for node in nodes.values():
        if node.voltage_level_id not in levels:
            raise ValueError("MV/HV node references an unknown voltage level")
    for start in nodes:
        visited: set[str] = set()
        cursor = start
        while cursor in outgoing:
            if cursor in visited:
                raise ValueError("MV/HV directed cycle is not allowed")
            visited.add(cursor)
            cursor = outgoing[cursor].to_node_id
    return outgoing


def _validator_boundaries(
    canonical: TopologyTransformerStaticAuthorityResult,
    nodes: Mapping[str, MvHvNetworkNodeAuthority],
    bindings: Mapping[str, MvHvTransformerTerminalBindingAuthority],
    grids: Mapping[str, MvHvGridBoundaryAuthority],
    meters: Mapping[str, RevenueMeterBoundaryAuthority],
) -> None:
    bound_nodes: set[str] = set()
    for transformer_id, binding in bindings.items():
        if transformer_id not in canonical.transformer_states.index:
            raise ValueError("transformer terminal binding references an unknown transformer")
        topology = canonical.topology_by_id.get(transformer_id)
        if topology is None:
            raise ValueError("transformer terminal binding requires S12A topology authority")
        if binding.transformer_network_terminal_id != topology.transformer_network_terminal_id:
            raise ValueError("transformer_network_terminal_id does not match canonical S12A")
        node = nodes.get(binding.node_id)
        if node is None or node.node_kind != "transformer_terminal":
            raise ValueError("transformer binding node must be a transformer_terminal")
        if binding.node_id in bound_nodes:
            raise ValueError("transformer_terminal node may bind to only one transformer")
        bound_nodes.add(binding.node_id)
    terminal_nodes = {
        node.node_id for node in nodes.values() if node.node_kind == "transformer_terminal"
    }
    if terminal_nodes != bound_nodes:
        raise ValueError("every supplied transformer_terminal node requires exactly one binding")
    grid_nodes: set[str] = set()
    for grid in grids.values():
        node = nodes.get(grid.node_id)
        if node is None or node.node_kind != "network_exit":
            raise ValueError("grid boundary node must be a network_exit")
        if grid.node_id in grid_nodes:
            raise ValueError("network_exit may have at most one grid boundary")
        grid_nodes.add(grid.node_id)
    for meter in meters.values():
        if meter.node_id not in nodes:
            raise ValueError("revenue meter references an unknown node")


def _validator_trace(
    start: str,
    nodes: Mapping[str, MvHvNetworkNodeAuthority],
    outgoing: Mapping[str, MvHvNetworkSegmentAuthority],
) -> tuple[list[str], list[str], str | None]:
    node_path = [start]
    segment_path: list[str] = []
    cursor = start
    while cursor in outgoing:
        segment = outgoing[cursor]
        segment_path.append(segment.segment_id)
        cursor = segment.to_node_id
        node_path.append(cursor)
    exit_id = cursor if nodes[cursor].node_kind == "network_exit" else None
    return node_path, segment_path, exit_id


def _validator_record(
    transformer_id: str,
    canonical: TopologyTransformerStaticAuthorityResult,
    result: TopologyMvHvNetworkAuthorityResult,
    outgoing: Mapping[str, MvHvNetworkSegmentAuthority],
) -> dict[str, object]:
    row: dict[str, object] = {name: None for name in _COLUMNS}
    for name in _BOOL_COLUMNS:
        row[name] = False
    topology = canonical.topology_by_id.get(transformer_id)
    binding = result.transformer_terminal_binding_by_transformer_id.get(transformer_id)
    row.update(
        {
            "network_basis_resolved": result.network_basis is not None,
            "transformer_static_authority_resolved": bool(
                canonical.transformer_states.loc[
                    transformer_id, "transformer_static_authority_resolved"
                ]
            ),
            "transformer_network_terminal_id": (
                topology.transformer_network_terminal_id if topology else None
            ),
            "path_segment_ids": (),
            "path_segment_count": 0,
            "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
            "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
            "mv_hv_network_authority_contract": MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
            "mv_hv_network_authority_model": MV_HV_NETWORK_AUTHORITY_MODEL_ID,
            "mv_hv_network_authority_scope": MV_HV_NETWORK_AUTHORITY_SCOPE,
            "mv_hv_network_authority_coverage_scope": MV_HV_NETWORK_AUTHORITY_COVERAGE_SCOPE,
        }
    )
    if result.network_basis is None:
        state = _STATES[0]
    elif binding is None:
        state = _STATES[1]
    else:
        row["transformer_terminal_binding_resolved"] = True
        row["transformer_terminal_node_id"] = binding.node_id
        row["transformer_voltage_level_id"] = result.nodes_by_id[binding.node_id].voltage_level_id
        node_path, segment_path, exit_id = _validator_trace(
            binding.node_id, result.nodes_by_id, outgoing
        )
        row["path_segment_ids"] = tuple(segment_path)
        row["path_segment_count"] = len(segment_path)
        if exit_id is None:
            state = _STATES[2]
        else:
            row["path_to_network_exit_resolved"] = True
            row["network_exit_node_id"] = exit_id
            row["network_exit_voltage_level_id"] = result.nodes_by_id[exit_id].voltage_level_id
            grids = [g for g in result.grid_boundary_by_id.values() if g.node_id == exit_id]
            meters = [
                m for m in result.revenue_meter_boundary_by_id.values() if m.node_id in node_path
            ]
            if len(meters) > 1:
                raise ValueError("multiple revenue meters on one transformer path are ambiguous")
            if grids:
                row["grid_boundary_resolved"] = True
                row["grid_boundary_id"] = grids[0].grid_boundary_id
            if meters:
                row.update(
                    {
                        "revenue_meter_boundary_resolved": True,
                        "revenue_meter_on_transformer_path": True,
                        "revenue_meter_id": meters[0].revenue_meter_id,
                        "revenue_meter_node_id": meters[0].node_id,
                        "revenue_meter_colocated_with_grid_boundary": bool(
                            grids and meters[0].node_id == grids[0].node_id
                        ),
                    }
                )
            if not grids:
                state = _STATES[3]
            elif not meters:
                state = _STATES[4]
            else:
                row["mv_hv_network_authority_resolved"] = True
                state = _STATES[5]
    row["mv_hv_network_authority_state"] = state
    return row


def _validator_frame(ids: list[str], records: list[dict[str, object]]) -> pd.DataFrame:
    expected = pd.DataFrame(
        records, index=pd.Index(ids, name="transformer_id"), columns=_COLUMNS
    )
    for name in _BOOL_COLUMNS:
        expected[name] = expected[name].astype(bool)
    expected["path_segment_count"] = expected["path_segment_count"].astype("int64")
    for name in set(_COLUMNS) - _BOOL_COLUMNS - {"path_segment_count"}:
        expected[name] = expected[name].astype(object)
    return expected


def _validator_diagnostics(
    frame: pd.DataFrame, result: TopologyMvHvNetworkAuthorityResult
) -> TopologyMvHvNetworkAuthorityDiagnostics:
    segments = result.segments_by_id
    zero_z = sum(
        s.series_resistance_ohm_per_phase == 0 and s.series_reactance_ohm_per_phase == 0
        for s in segments.values()
    )
    zero_y = sum(
        s.total_shunt_conductance_siemens_per_phase == 0
        and s.total_shunt_susceptance_siemens_per_phase == 0
        for s in segments.values()
    )
    resolved = frame["mv_hv_network_authority_resolved"]
    grid_nodes = {grid.node_id for grid in result.grid_boundary_by_id.values()}
    return TopologyMvHvNetworkAuthorityDiagnostics(
        len(frame),
        len(result.transformer_terminal_binding_by_transformer_id),
        len(result.voltage_levels_by_id),
        len(result.nodes_by_id),
        len(segments),
        sum(n.node_kind == "transformer_terminal" for n in result.nodes_by_id.values()),
        sum(n.node_kind == "junction" for n in result.nodes_by_id.values()),
        sum(n.node_kind == "network_exit" for n in result.nodes_by_id.values()),
        len(result.grid_boundary_by_id),
        len(result.revenue_meter_boundary_by_id),
        int(frame["path_to_network_exit_resolved"].sum()),
        int(frame["revenue_meter_on_transformer_path"].sum()),
        int(resolved.sum()),
        int((~resolved).sum()),
        zero_z,
        len(segments) - zero_z,
        zero_y,
        len(segments) - zero_y,
        sum(meter.node_id in grid_nodes for meter in result.revenue_meter_boundary_by_id.values()),
        MV_HV_NETWORK_AUTHORITY_MODEL_ID,
    )


def _validate_result(
    canonical: TopologyTransformerStaticAuthorityResult,
    result: TopologyMvHvNetworkAuthorityResult,
) -> None:
    if type(result) is not TopologyMvHvNetworkAuthorityResult:
        raise ValueError("S13A result type is invalid")
    for name in (
        "voltage_levels_by_id",
        "nodes_by_id",
        "segments_by_id",
        "transformer_terminal_binding_by_transformer_id",
        "grid_boundary_by_id",
        "revenue_meter_boundary_by_id",
    ):
        mapping = getattr(result, name)
        if type(mapping) is not MappingProxyType:
            raise ValueError("S13A result mappings must be immutable")
    outgoing = _validator_graph(
        result.voltage_levels_by_id, result.nodes_by_id, result.segments_by_id
    )
    _validator_boundaries(
        canonical,
        result.nodes_by_id,
        result.transformer_terminal_binding_by_transformer_id,
        result.grid_boundary_by_id,
        result.revenue_meter_boundary_by_id,
    )
    ids = list(canonical.transformer_states.index)
    expected = _validator_frame(
        ids, [_validator_record(i, canonical, result, outgoing) for i in ids]
    )
    try:
        pd.testing.assert_frame_equal(result.transformer_states, expected, check_exact=True)
    except AssertionError as error:
        raise ValueError("S13A result frame failed independent validation") from error
    if result.diagnostics != _validator_diagnostics(expected, result):
        raise ValueError("S13A diagnostics failed independent validation")
