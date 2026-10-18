"""Timestamped voltage authority at explicit MV/HV grid boundaries.

S13B admits line-to-line RMS voltage magnitude at S13A's named
``grid_interconnection_boundary`` reference planes.  Nominal voltage is
static network context, not an inferred operating value or a compliance
limit.  This stage performs no network solve, consumes no S12M operating
power, and consumes no revenue-meter telemetry.
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
from heliotelligence.physics.mv_hv_network_authority import (
    MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
    MV_HV_NETWORK_AUTHORITY_MODEL_ID,
    MvHvGridBoundaryAuthority,
    MvHvNetworkBasisAuthority,
    MvHvNetworkNodeAuthority,
    MvHvNetworkSegmentAuthority,
    MvHvTransformerTerminalBindingAuthority,
    MvHvVoltageLevelAuthority,
    RevenueMeterBoundaryAuthority,
    TopologyMvHvNetworkAuthorityResult,
    resolve_topology_mv_hv_network_authority,
)
from heliotelligence.physics.transformer_authority import (
    TopologyTransformerStaticAuthorityResult,
    TransformerBoundaryTopologyAuthority,
    TransformerStaticEquipmentAuthority,
)

MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_CONTRACT_ID = (
    "admitted_mv_hv_network_authority_to_timestamped_grid_boundary_voltage_state_v1"
)
MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_MODEL_ID = (
    "explicit_balanced_three_phase_grid_interconnection_boundary_"
    "line_to_line_rms_voltage_state_v1"
)
MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_SCOPE = (
    "timestamped_grid_interconnection_boundary_voltage_authority_before_"
    "mv_hv_network_operating_solve"
)
MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_grid_boundary_line_to_line_rms_voltage_states_for_"
    "admitted_mv_hv_network_authority"
)

Confidence = Literal["high", "medium", "low", "unknown"]
_CONFIDENCES = {"high", "medium", "low", "unknown"}
_COLUMNS = (
    "network_basis_resolved",
    "grid_boundary_voltage_state_present",
    "grid_boundary_voltage_authority_resolved",
    "grid_boundary_node_id",
    "grid_boundary_voltage_level_id",
    "nominal_line_to_line_rms_v",
    "voltage_line_to_line_rms_v",
    "voltage_is_zero",
    "voltage_basis",
    "voltage_reference_plane",
    "parameter_source",
    "confidence",
    "grid_boundary_voltage_authority_state",
    "mv_hv_network_authority_contract",
    "mv_hv_network_authority_model",
    "mv_hv_grid_boundary_voltage_authority_contract",
    "mv_hv_grid_boundary_voltage_authority_model",
    "mv_hv_grid_boundary_voltage_authority_scope",
    "mv_hv_grid_boundary_voltage_authority_coverage_scope",
)
_BOOL_COLUMNS = {
    "network_basis_resolved",
    "grid_boundary_voltage_state_present",
    "grid_boundary_voltage_authority_resolved",
}
_FLOAT_COLUMNS = {"nominal_line_to_line_rms_v", "voltage_line_to_line_rms_v"}
_NULLABLE_BOOL_COLUMNS = {"voltage_is_zero"}


def _identifier(value: object) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(
            "grid_boundary_id must be an exact non-empty string without surrounding whitespace"
        )
    return value


def _source(value: object) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(
            "parameter_source must be an exact non-empty string without surrounding whitespace"
        )
    return value


@dataclass(frozen=True)
class MvHvGridBoundaryVoltageState:
    """Explicit LL RMS magnitude at one named grid boundary and timestamp."""

    voltage_line_to_line_rms_v: float
    voltage_basis: Literal["line_to_line_rms"]
    reference_plane: Literal["grid_interconnection_boundary"]
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        value = self.voltage_line_to_line_rms_v
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("voltage_line_to_line_rms_v must be a real non-Boolean number")
        normalized = float(value)
        if not math.isfinite(normalized) or normalized < 0.0:
            raise ValueError("voltage_line_to_line_rms_v must be finite and non-negative")
        if self.voltage_basis != "line_to_line_rms":
            raise ValueError("voltage_basis must be line_to_line_rms")
        if self.reference_plane != "grid_interconnection_boundary":
            raise ValueError("reference_plane must be grid_interconnection_boundary")
        _source(self.parameter_source)
        if type(self.confidence) is not str or self.confidence not in _CONFIDENCES:
            raise ValueError("confidence is unsupported")
        object.__setattr__(self, "voltage_line_to_line_rms_v", normalized)


@dataclass(frozen=True)
class TopologyMvHvGridBoundaryVoltageAuthorityDiagnostics:
    grid_boundary_count: int
    represented_grid_boundary_count: int
    timestamp_count: int
    row_count: int
    voltage_state_present_count: int
    voltage_state_missing_count: int
    voltage_authority_resolved_count: int
    voltage_authority_unresolved_count: int
    explicit_zero_voltage_count: int
    positive_voltage_count: int
    missing_network_basis_row_count: int
    model: str


@dataclass(frozen=True)
class TopologyMvHvGridBoundaryVoltageAuthorityResult:
    voltage_states_by_key: Mapping[
        tuple[pd.Timestamp, str], MvHvGridBoundaryVoltageState
    ]
    states: pd.DataFrame
    diagnostics: TopologyMvHvGridBoundaryVoltageAuthorityDiagnostics


def _validate_parent_replay(
    supplied: object, canonical: TopologyMvHvNetworkAuthorityResult
) -> None:
    if type(supplied) is not TopologyMvHvNetworkAuthorityResult:
        raise RuntimeError("supplied S13A authority result type is invalid")
    assert isinstance(supplied, TopologyMvHvNetworkAuthorityResult)
    if supplied.network_basis != canonical.network_basis:
        raise RuntimeError("supplied S13A network basis failed exact replay")
    for label in (
        "voltage_levels_by_id",
        "nodes_by_id",
        "segments_by_id",
        "transformer_terminal_binding_by_transformer_id",
        "grid_boundary_by_id",
        "revenue_meter_boundary_by_id",
    ):
        actual = getattr(supplied, label)
        expected = getattr(canonical, label)
        if type(actual) is not MappingProxyType or tuple(actual.items()) != tuple(
            expected.items()
        ):
            raise RuntimeError(f"supplied S13A {label} failed immutable canonical replay")
    try:
        pd.testing.assert_frame_equal(
            supplied.transformer_states, canonical.transformer_states, check_exact=True
        )
    except AssertionError as error:
        raise RuntimeError("supplied S13A transformer states failed exact replay") from error
    if supplied.diagnostics != canonical.diagnostics:
        raise RuntimeError("supplied S13A diagnostics failed exact replay")


def _admit_voltage_mapping(
    supplied: object, parent: TopologyMvHvNetworkAuthorityResult
) -> dict[tuple[pd.Timestamp, str], MvHvGridBoundaryVoltageState]:
    if not isinstance(supplied, Mapping):
        raise TypeError("grid_boundary_voltage_by_key must be a mapping")
    admitted: dict[tuple[pd.Timestamp, str], MvHvGridBoundaryVoltageState] = {}
    for key, state in supplied.items():
        if type(key) is not tuple or len(key) != 2:
            raise TypeError("voltage-state keys must be exact two-item tuples")
        timestamp, boundary_id = key
        if type(timestamp) is not pd.Timestamp or pd.isna(timestamp):
            raise TypeError("voltage-state timestamp must be an exact non-NaT pd.Timestamp")
        _identifier(boundary_id)
        if boundary_id not in parent.grid_boundary_by_id:
            raise ValueError("voltage-state key references an unknown grid boundary")
        if type(state) is not MvHvGridBoundaryVoltageState:
            raise TypeError("voltage-state values must use the exact authority type")
        admitted[(timestamp, boundary_id)] = state
    return admitted


def _canonical_timestamps(
    admitted: Mapping[tuple[pd.Timestamp, str], MvHvGridBoundaryVoltageState],
) -> tuple[pd.Timestamp, ...]:
    try:
        return tuple(sorted({timestamp for timestamp, _ in admitted}))
    except TypeError as error:
        raise ValueError("voltage-state timestamps have incompatible timezone semantics") from error


def _record(
    parent: TopologyMvHvNetworkAuthorityResult,
    boundary_id: str,
    state: MvHvGridBoundaryVoltageState | None,
) -> dict[str, object]:
    boundary = parent.grid_boundary_by_id[boundary_id]
    node = parent.nodes_by_id[boundary.node_id]
    level = parent.voltage_levels_by_id[node.voltage_level_id]
    basis = parent.network_basis is not None
    present = state is not None
    resolved = basis and present
    primary = (
        "unresolved_no_mv_hv_network_basis_authority"
        if not basis
        else "unresolved_missing_grid_boundary_voltage_state"
        if not present
        else "resolved_explicit_grid_interconnection_boundary_voltage_state"
    )
    return {
        "network_basis_resolved": basis,
        "grid_boundary_voltage_state_present": present,
        "grid_boundary_voltage_authority_resolved": resolved,
        "grid_boundary_node_id": boundary.node_id,
        "grid_boundary_voltage_level_id": node.voltage_level_id,
        "nominal_line_to_line_rms_v": level.nominal_line_to_line_rms_v,
        "voltage_line_to_line_rms_v": (
            state.voltage_line_to_line_rms_v if state is not None else float("nan")
        ),
        "voltage_is_zero": (
            state.voltage_line_to_line_rms_v == 0.0 if state is not None else pd.NA
        ),
        "voltage_basis": state.voltage_basis if state is not None else "",
        "voltage_reference_plane": state.reference_plane if state is not None else "",
        "parameter_source": state.parameter_source if state is not None else "",
        "confidence": state.confidence if state is not None else "",
        "grid_boundary_voltage_authority_state": primary,
        "mv_hv_network_authority_contract": MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
        "mv_hv_network_authority_model": MV_HV_NETWORK_AUTHORITY_MODEL_ID,
        "mv_hv_grid_boundary_voltage_authority_contract": (
            MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_CONTRACT_ID
        ),
        "mv_hv_grid_boundary_voltage_authority_model": (
            MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_MODEL_ID
        ),
        "mv_hv_grid_boundary_voltage_authority_scope": (
            MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_SCOPE
        ),
        "mv_hv_grid_boundary_voltage_authority_coverage_scope": (
            MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_COVERAGE_SCOPE
        ),
    }


def _frame(
    keys: tuple[tuple[pd.Timestamp, str], ...], records: list[dict[str, object]]
) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(keys, names=["timestamp", "grid_boundary_id"])
    frame = pd.DataFrame.from_records(records, columns=_COLUMNS, index=index)
    frame.index = index
    _apply_dtypes(frame)
    return frame


def _apply_dtypes(frame: pd.DataFrame) -> None:
    for column in _BOOL_COLUMNS:
        frame[column] = frame[column].astype("bool")
    for column in _FLOAT_COLUMNS:
        frame[column] = frame[column].astype("float64")
    for column in _NULLABLE_BOOL_COLUMNS:
        frame[column] = frame[column].astype("boolean")
    for column in set(_COLUMNS) - _BOOL_COLUMNS - _FLOAT_COLUMNS - _NULLABLE_BOOL_COLUMNS:
        frame[column] = frame[column].astype("object")


def _diagnostics(
    boundary_ids: tuple[str, ...],
    timestamps: tuple[pd.Timestamp, ...],
    admitted: Mapping[tuple[pd.Timestamp, str], MvHvGridBoundaryVoltageState],
    basis: bool,
) -> TopologyMvHvGridBoundaryVoltageAuthorityDiagnostics:
    rows = len(boundary_ids) * len(timestamps)
    present = len(admitted)
    zero = sum(state.voltage_line_to_line_rms_v == 0.0 for state in admitted.values())
    resolved = present if basis else 0
    return TopologyMvHvGridBoundaryVoltageAuthorityDiagnostics(
        grid_boundary_count=len(boundary_ids),
        represented_grid_boundary_count=len({identifier for _, identifier in admitted}),
        timestamp_count=len(timestamps),
        row_count=rows,
        voltage_state_present_count=present,
        voltage_state_missing_count=rows - present,
        voltage_authority_resolved_count=resolved,
        voltage_authority_unresolved_count=rows - resolved,
        explicit_zero_voltage_count=zero,
        positive_voltage_count=present - zero,
        missing_network_basis_row_count=0 if basis else rows,
        model=MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_MODEL_ID,
    )


def resolve_topology_mv_hv_grid_boundary_voltage_authority(
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
    mv_hv_network_authority: TopologyMvHvNetworkAuthorityResult,
    grid_boundary_voltage_by_key: Mapping[
        tuple[pd.Timestamp, str], MvHvGridBoundaryVoltageState
    ],
) -> TopologyMvHvGridBoundaryVoltageAuthorityResult:
    """Resolve explicit timestamped grid-boundary voltage evidence only."""

    canonical = resolve_topology_mv_hv_network_authority(
        topology,
        network_basis,
        node_authority_by_id,
        segment_authority_by_id,
        inverter_terminal_binding_by_inverter_id,
        lv_ac_collection_authority,
        transformer_equipment_by_id,
        transformer_topology_by_id,
        transformer_static_authority,
        mv_hv_network_basis,
        mv_hv_voltage_level_by_id,
        mv_hv_node_by_id,
        mv_hv_segment_by_id,
        mv_hv_transformer_terminal_binding_by_transformer_id,
        mv_hv_grid_boundary_by_id,
        revenue_meter_boundary_by_id,
    )
    _validate_parent_replay(mv_hv_network_authority, canonical)
    admitted = _admit_voltage_mapping(grid_boundary_voltage_by_key, canonical)
    boundary_ids = tuple(canonical.grid_boundary_by_id)
    timestamps = _canonical_timestamps(admitted)
    keys = tuple(
        (timestamp, boundary_id)
        for timestamp in timestamps
        for boundary_id in boundary_ids
    )
    canonical_states = {key: admitted[key] for key in keys if key in admitted}
    records = [
        _record(canonical, boundary_id, canonical_states.get((timestamp, boundary_id)))
        for timestamp, boundary_id in keys
    ]
    frame = _frame(keys, records)
    diagnostics = _diagnostics(
        boundary_ids, timestamps, canonical_states, canonical.network_basis is not None
    )
    result = TopologyMvHvGridBoundaryVoltageAuthorityResult(
        MappingProxyType(dict(canonical_states)), frame.copy(deep=True), diagnostics
    )
    _validate_result(canonical, result)
    return result


# The validator deliberately duplicates S13B construction and never calls or
# captures the production record, frame, or diagnostics builders.
def _validator_record(
    parent: TopologyMvHvNetworkAuthorityResult,
    boundary_id: str,
    state: MvHvGridBoundaryVoltageState | None,
) -> dict[str, object]:
    boundary = parent.grid_boundary_by_id[boundary_id]
    node = parent.nodes_by_id[boundary.node_id]
    nominal = parent.voltage_levels_by_id[node.voltage_level_id].nominal_line_to_line_rms_v
    basis = parent.network_basis is not None
    present = state is not None
    primary = (
        "unresolved_no_mv_hv_network_basis_authority"
        if not basis
        else "unresolved_missing_grid_boundary_voltage_state"
        if not present
        else "resolved_explicit_grid_interconnection_boundary_voltage_state"
    )
    return {
        "network_basis_resolved": basis,
        "grid_boundary_voltage_state_present": present,
        "grid_boundary_voltage_authority_resolved": basis and present,
        "grid_boundary_node_id": boundary.node_id,
        "grid_boundary_voltage_level_id": node.voltage_level_id,
        "nominal_line_to_line_rms_v": nominal,
        "voltage_line_to_line_rms_v": (
            state.voltage_line_to_line_rms_v if state is not None else float("nan")
        ),
        "voltage_is_zero": (
            state.voltage_line_to_line_rms_v == 0.0 if state is not None else pd.NA
        ),
        "voltage_basis": state.voltage_basis if state is not None else "",
        "voltage_reference_plane": state.reference_plane if state is not None else "",
        "parameter_source": state.parameter_source if state is not None else "",
        "confidence": state.confidence if state is not None else "",
        "grid_boundary_voltage_authority_state": primary,
        "mv_hv_network_authority_contract": MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
        "mv_hv_network_authority_model": MV_HV_NETWORK_AUTHORITY_MODEL_ID,
        "mv_hv_grid_boundary_voltage_authority_contract": (
            MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_CONTRACT_ID
        ),
        "mv_hv_grid_boundary_voltage_authority_model": (
            MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_MODEL_ID
        ),
        "mv_hv_grid_boundary_voltage_authority_scope": (
            MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_SCOPE
        ),
        "mv_hv_grid_boundary_voltage_authority_coverage_scope": (
            MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_COVERAGE_SCOPE
        ),
    }


def _validator_frame(
    keys: tuple[tuple[pd.Timestamp, str], ...], records: list[dict[str, object]]
) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(keys, names=["timestamp", "grid_boundary_id"])
    frame = pd.DataFrame.from_records(records, columns=_COLUMNS, index=index)
    frame.index = index
    for column in _BOOL_COLUMNS:
        frame[column] = frame[column].astype("bool")
    for column in _FLOAT_COLUMNS:
        frame[column] = frame[column].astype("float64")
    for column in _NULLABLE_BOOL_COLUMNS:
        frame[column] = frame[column].astype("boolean")
    for column in set(_COLUMNS) - _BOOL_COLUMNS - _FLOAT_COLUMNS - _NULLABLE_BOOL_COLUMNS:
        frame[column] = frame[column].astype("object")
    return frame


def _validator_diagnostics(
    boundary_ids: tuple[str, ...],
    timestamps: tuple[pd.Timestamp, ...],
    admitted: Mapping[tuple[pd.Timestamp, str], MvHvGridBoundaryVoltageState],
    basis: bool,
) -> TopologyMvHvGridBoundaryVoltageAuthorityDiagnostics:
    row_count = len(boundary_ids) * len(timestamps)
    present = len(admitted)
    zero = sum(value.voltage_line_to_line_rms_v == 0.0 for value in admitted.values())
    resolved = present if basis else 0
    return TopologyMvHvGridBoundaryVoltageAuthorityDiagnostics(
        len(boundary_ids),
        len({identifier for _, identifier in admitted}),
        len(timestamps),
        row_count,
        present,
        row_count - present,
        resolved,
        row_count - resolved,
        zero,
        present - zero,
        0 if basis else row_count,
        MV_HV_GRID_BOUNDARY_VOLTAGE_AUTHORITY_MODEL_ID,
    )


def _validate_result(
    canonical: TopologyMvHvNetworkAuthorityResult,
    result: TopologyMvHvGridBoundaryVoltageAuthorityResult,
) -> None:
    """Independently reconstruct and close the complete S13B result."""

    if type(result) is not TopologyMvHvGridBoundaryVoltageAuthorityResult:
        raise RuntimeError("S13B result type is invalid")
    if type(result.voltage_states_by_key) is not MappingProxyType:
        raise RuntimeError("S13B voltage-state mapping must be immutable")
    boundary_ids = tuple(canonical.grid_boundary_by_id)
    for key, state in result.voltage_states_by_key.items():
        if type(key) is not tuple or len(key) != 2:
            raise RuntimeError("S13B result mapping key is invalid")
        timestamp, boundary_id = key
        if type(timestamp) is not pd.Timestamp or pd.isna(timestamp):
            raise RuntimeError("S13B result timestamp is invalid")
        if type(boundary_id) is not str or boundary_id not in boundary_ids:
            raise RuntimeError("S13B result boundary identity is invalid")
        if type(state) is not MvHvGridBoundaryVoltageState:
            raise RuntimeError("S13B result authority type is invalid")
    timestamps = _canonical_timestamps(result.voltage_states_by_key)
    keys = tuple(
        (timestamp, boundary_id)
        for timestamp in timestamps
        for boundary_id in boundary_ids
    )
    expected = _validator_frame(
        keys,
        [
            _validator_record(
                canonical,
                boundary_id,
                result.voltage_states_by_key.get((timestamp, boundary_id)),
            )
            for timestamp, boundary_id in keys
        ],
    )
    try:
        pd.testing.assert_frame_equal(result.states, expected, check_exact=True)
    except AssertionError as error:
        raise RuntimeError("S13B state frame failed independent exact closure") from error
    diagnostics = _validator_diagnostics(
        boundary_ids,
        timestamps,
        result.voltage_states_by_key,
        canonical.network_basis is not None,
    )
    if result.diagnostics != diagnostics:
        raise RuntimeError("S13B diagnostics failed independent exact closure")
