"""Timestamped LV collection-exit operating-voltage authority.

S11B records explicit line-to-line RMS voltage magnitude at admitted S11A
collection exits. It does not infer voltage, consume dispatch, convert phase
voltage, calculate current or losses, or solve the LV collection network.
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
    TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_CONTRACT_ID,
    TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_MODEL_ID,
    LvAcCollectionNetworkBasisAuthority,
    LvAcCollectionNodeAuthority,
    LvAcCollectionSegmentAuthority,
    LvAcInverterTerminalBindingAuthority,
    TopologyLvAcCollectionAuthorityResult,
    resolve_topology_lv_ac_collection_authority,
)

TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_CONTRACT_ID = (
    "admitted_lv_ac_collection_authority_to_timestamped_collection_exit_voltage_state_v1"
)
TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_MODEL_ID = (
    "explicit_balanced_three_phase_collection_exit_line_to_line_rms_voltage_state_v1"
)
TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_SCOPE = (
    "timestamped_lv_ac_collection_exit_voltage_boundary_authority_before_network_solve"
)
TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_collection_exit_line_to_line_rms_voltage_states_for_admitted_lv_ac_collection_topology"
)

Confidence = Literal["high", "medium", "low", "unknown"]
_CONFIDENCES = {"high", "medium", "low", "unknown"}
_COLUMNS = (
    "network_basis_resolved",
    "collection_exit_voltage_state_present",
    "collection_exit_voltage_boundary_authority_resolved",
    "voltage_line_to_line_rms_v",
    "voltage_is_zero",
    "voltage_basis",
    "voltage_reference_plane",
    "parameter_source",
    "confidence",
    "collection_exit_voltage_authority_state",
    "topology_lv_ac_collection_authority_contract",
    "topology_lv_ac_collection_authority_model",
    "topology_lv_ac_collection_exit_voltage_authority_contract",
    "topology_lv_ac_collection_exit_voltage_authority_model",
    "topology_lv_ac_collection_exit_voltage_authority_scope",
    "topology_lv_ac_collection_exit_voltage_authority_coverage_scope",
)
_BOOL_COLUMNS = {
    "network_basis_resolved",
    "collection_exit_voltage_state_present",
    "collection_exit_voltage_boundary_authority_resolved",
}
_FLOAT_COLUMNS = {"voltage_line_to_line_rms_v"}
_NULLABLE_BOOL_COLUMNS = {"voltage_is_zero"}


def _source(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("parameter_source must be an exact non-empty string")
    return value


def _confidence(value: object) -> str:
    if type(value) is not str or value not in _CONFIDENCES:
        raise ValueError("confidence is unsupported")
    return value


def _exit_identifier(value: object) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(
            "collection_exit_node_id must be an exact non-empty string "
            "without surrounding whitespace"
        )
    return value


@dataclass(frozen=True)
class LvAcCollectionExitVoltageState:
    """Explicit operating voltage magnitude at one LV collection exit and timestamp."""

    voltage_line_to_line_rms_v: float
    voltage_basis: Literal["line_to_line_rms"]
    reference_plane: Literal["lv_ac_collection_exit"]
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
        if self.reference_plane != "lv_ac_collection_exit":
            raise ValueError("reference_plane must be lv_ac_collection_exit")
        _source(self.parameter_source)
        _confidence(self.confidence)
        object.__setattr__(self, "voltage_line_to_line_rms_v", normalized)


@dataclass(frozen=True)
class TopologyLvAcCollectionExitVoltageAuthorityDiagnostics:
    collection_exit_count: int
    represented_collection_exit_count: int
    timestamp_count: int
    row_count: int
    voltage_state_present_count: int
    voltage_state_missing_count: int
    voltage_boundary_authority_resolved_count: int
    voltage_boundary_authority_unresolved_count: int
    explicit_zero_voltage_count: int
    positive_voltage_count: int
    missing_network_basis_row_count: int
    model: str


@dataclass(frozen=True)
class TopologyLvAcCollectionExitVoltageAuthorityResult:
    voltage_states_by_key: Mapping[
        tuple[pd.Timestamp, str], LvAcCollectionExitVoltageState
    ]
    states: pd.DataFrame
    diagnostics: TopologyLvAcCollectionExitVoltageAuthorityDiagnostics


def resolve_topology_lv_ac_collection_exit_voltage_authority(
    topology: ElectricalTopologyConfig,
    network_basis: LvAcCollectionNetworkBasisAuthority | None,
    node_authority_by_id: Mapping[str, LvAcCollectionNodeAuthority],
    segment_authority_by_id: Mapping[str, LvAcCollectionSegmentAuthority],
    inverter_terminal_binding_by_inverter_id: Mapping[
        str, LvAcInverterTerminalBindingAuthority
    ],
    lv_ac_collection_authority: TopologyLvAcCollectionAuthorityResult,
    collection_exit_voltage_by_key: Mapping[
        tuple[pd.Timestamp, str], LvAcCollectionExitVoltageState
    ],
) -> TopologyLvAcCollectionExitVoltageAuthorityResult:
    """Resolve explicit timestamped collection-exit voltage authority only."""

    canonical_parent = resolve_topology_lv_ac_collection_authority(
        topology,
        network_basis,
        node_authority_by_id,
        segment_authority_by_id,
        inverter_terminal_binding_by_inverter_id,
    )
    _validate_parent_replay(lv_ac_collection_authority, canonical_parent)
    admitted = _admit_voltage_mapping(collection_exit_voltage_by_key, canonical_parent)
    exit_ids = tuple(
        node_id
        for node_id, node in canonical_parent.nodes_by_id.items()
        if node.node_kind == "collection_exit"
    )
    timestamps = _canonical_timestamps(admitted)
    canonical_keys = tuple((timestamp, exit_id) for timestamp in timestamps for exit_id in exit_ids)
    canonical_voltage_states = {
        key: admitted[key] for key in canonical_keys if key in admitted
    }
    basis_resolved = canonical_parent.network_basis is not None
    records = [
        _state_record(basis_resolved, canonical_voltage_states.get(key))
        for key in canonical_keys
    ]
    index = pd.MultiIndex.from_tuples(
        canonical_keys, names=["timestamp", "collection_exit_node_id"]
    )
    states = pd.DataFrame.from_records(records, columns=_COLUMNS, index=index)
    states.index = index
    _apply_dtypes(states)
    diagnostics = _build_diagnostics(
        exit_ids, timestamps, canonical_voltage_states, basis_resolved
    )
    result = TopologyLvAcCollectionExitVoltageAuthorityResult(
        voltage_states_by_key=MappingProxyType(canonical_voltage_states.copy()),
        states=states.copy(deep=True),
        diagnostics=diagnostics,
    )
    _validate_result(topology, canonical_parent, result)
    return result


def _validate_parent_replay(
    supplied: object, canonical: TopologyLvAcCollectionAuthorityResult
) -> None:
    if type(supplied) is not TopologyLvAcCollectionAuthorityResult:
        raise RuntimeError("supplied S11A authority result type is invalid")
    if supplied.network_basis != canonical.network_basis:
        raise RuntimeError("supplied S11A network basis failed exact replay")
    for label, actual, expected in (
        ("nodes", supplied.nodes_by_id, canonical.nodes_by_id),
        ("segments", supplied.segments_by_id, canonical.segments_by_id),
        (
            "bindings",
            supplied.inverter_terminal_binding_by_inverter_id,
            canonical.inverter_terminal_binding_by_inverter_id,
        ),
    ):
        if type(actual).__name__ != "mappingproxy" or dict(actual) != dict(expected):
            raise RuntimeError(f"supplied S11A {label} failed exact replay")
    try:
        pd.testing.assert_frame_equal(
            supplied.inverter_states, canonical.inverter_states, check_exact=True
        )
    except AssertionError as exc:
        raise RuntimeError("supplied S11A inverter states failed exact replay") from exc
    if supplied.diagnostics != canonical.diagnostics:
        raise RuntimeError("supplied S11A diagnostics failed exact replay")


def _admit_voltage_mapping(
    supplied: object,
    parent: TopologyLvAcCollectionAuthorityResult,
) -> dict[tuple[pd.Timestamp, str], LvAcCollectionExitVoltageState]:
    if not isinstance(supplied, Mapping):
        raise TypeError("collection_exit_voltage_by_key must be a mapping")
    admitted: dict[tuple[pd.Timestamp, str], LvAcCollectionExitVoltageState] = {}
    for key, state in supplied.items():
        if type(key) is not tuple or len(key) != 2:
            raise TypeError("voltage-state keys must be exact two-item tuples")
        timestamp, exit_id = key
        if type(timestamp) is not pd.Timestamp or pd.isna(timestamp):
            raise TypeError("voltage-state timestamp must be an exact non-NaT pd.Timestamp")
        _exit_identifier(exit_id)
        node = parent.nodes_by_id.get(exit_id)
        if node is None:
            raise ValueError("voltage-state key references an unknown node")
        if node.node_kind != "collection_exit":
            raise ValueError("voltage-state key must reference a collection_exit node")
        if type(state) is not LvAcCollectionExitVoltageState:
            raise TypeError("voltage-state values must use the exact authority type")
        admitted[(timestamp, exit_id)] = state
    return admitted


def _canonical_timestamps(
    admitted: Mapping[tuple[pd.Timestamp, str], LvAcCollectionExitVoltageState],
) -> tuple[pd.Timestamp, ...]:
    try:
        return tuple(sorted({timestamp for timestamp, _ in admitted}))
    except TypeError as exc:
        raise ValueError("voltage-state timestamps have incompatible timezone semantics") from exc


def _state_record(
    basis_resolved: bool,
    state: LvAcCollectionExitVoltageState | None,
) -> dict[str, object]:
    present = state is not None
    resolved = basis_resolved and present
    primary_state = (
        "unresolved_no_lv_ac_network_basis_authority"
        if not basis_resolved
        else "unresolved_missing_collection_exit_voltage_state"
        if not present
        else "resolved_explicit_collection_exit_voltage_state"
    )
    return {
        "network_basis_resolved": basis_resolved,
        "collection_exit_voltage_state_present": present,
        "collection_exit_voltage_boundary_authority_resolved": resolved,
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
        "collection_exit_voltage_authority_state": primary_state,
        "topology_lv_ac_collection_authority_contract": (
            TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_CONTRACT_ID
        ),
        "topology_lv_ac_collection_authority_model": (
            TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_MODEL_ID
        ),
        "topology_lv_ac_collection_exit_voltage_authority_contract": (
            TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_CONTRACT_ID
        ),
        "topology_lv_ac_collection_exit_voltage_authority_model": (
            TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_MODEL_ID
        ),
        "topology_lv_ac_collection_exit_voltage_authority_scope": (
            TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_SCOPE
        ),
        "topology_lv_ac_collection_exit_voltage_authority_coverage_scope": (
            TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_COVERAGE_SCOPE
        ),
    }


def _apply_dtypes(states: pd.DataFrame) -> None:
    for column in _BOOL_COLUMNS:
        states[column] = states[column].astype("bool")
    for column in _FLOAT_COLUMNS:
        states[column] = states[column].astype("float64")
    for column in _NULLABLE_BOOL_COLUMNS:
        states[column] = states[column].astype("boolean")
    for column in set(_COLUMNS) - _BOOL_COLUMNS - _FLOAT_COLUMNS - _NULLABLE_BOOL_COLUMNS:
        states[column] = states[column].astype("object")


def _build_diagnostics(
    exit_ids: tuple[str, ...],
    timestamps: tuple[pd.Timestamp, ...],
    voltage_states: Mapping[tuple[pd.Timestamp, str], LvAcCollectionExitVoltageState],
    basis_resolved: bool,
) -> TopologyLvAcCollectionExitVoltageAuthorityDiagnostics:
    rows = len(exit_ids) * len(timestamps)
    present = len(voltage_states)
    zero = sum(state.voltage_line_to_line_rms_v == 0.0 for state in voltage_states.values())
    resolved = present if basis_resolved else 0
    return TopologyLvAcCollectionExitVoltageAuthorityDiagnostics(
        collection_exit_count=len(exit_ids),
        represented_collection_exit_count=len({exit_id for _, exit_id in voltage_states}),
        timestamp_count=len(timestamps),
        row_count=rows,
        voltage_state_present_count=present,
        voltage_state_missing_count=rows - present,
        voltage_boundary_authority_resolved_count=resolved,
        voltage_boundary_authority_unresolved_count=rows - resolved,
        explicit_zero_voltage_count=zero,
        positive_voltage_count=present - zero,
        missing_network_basis_row_count=0 if basis_resolved else rows,
        model=TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_MODEL_ID,
    )


def _validate_result(
    topology: ElectricalTopologyConfig,
    canonical_parent: TopologyLvAcCollectionAuthorityResult,
    result: TopologyLvAcCollectionExitVoltageAuthorityResult,
) -> None:
    """Independently close S11B output against canonical S11A and admitted states."""

    if type(topology) is not ElectricalTopologyConfig:
        raise RuntimeError("S11B validation topology type is invalid")
    if type(result) is not TopologyLvAcCollectionExitVoltageAuthorityResult:
        raise RuntimeError("S11B result type is invalid")
    if type(result.voltage_states_by_key).__name__ != "mappingproxy":
        raise RuntimeError("S11B voltage-state mapping must be immutable")
    exit_ids = tuple(
        node_id
        for node_id, node in canonical_parent.nodes_by_id.items()
        if node.node_kind == "collection_exit"
    )
    for key, state in result.voltage_states_by_key.items():
        if type(key) is not tuple or len(key) != 2:
            raise RuntimeError("S11B result mapping key is invalid")
        timestamp, exit_id = key
        if type(timestamp) is not pd.Timestamp or pd.isna(timestamp):
            raise RuntimeError("S11B result timestamp is invalid")
        if type(exit_id) is not str or exit_id not in exit_ids:
            raise RuntimeError("S11B result exit identity is invalid")
        if type(state) is not LvAcCollectionExitVoltageState:
            raise RuntimeError("S11B result authority type is invalid")
        if canonical_parent.network_basis is not None and (
            state.voltage_basis != canonical_parent.network_basis.voltage_basis
        ):
            raise RuntimeError("S11B voltage basis is incompatible with S11A")
    timestamps = _canonical_timestamps(result.voltage_states_by_key)
    expected_keys = tuple((timestamp, exit_id) for timestamp in timestamps for exit_id in exit_ids)
    states = result.states
    if tuple(states.columns) != _COLUMNS:
        raise RuntimeError("S11B schema is invalid")
    if not isinstance(states.index, pd.MultiIndex):
        raise RuntimeError("S11B index must be a MultiIndex")
    if list(states.index.names) != ["timestamp", "collection_exit_node_id"]:
        raise RuntimeError("S11B index names are invalid")
    if states.index.has_duplicates or tuple(states.index.tolist()) != expected_keys:
        raise RuntimeError("S11B canonical index/order is invalid")
    for column in _COLUMNS:
        expected_dtype = (
            "bool"
            if column in _BOOL_COLUMNS
            else "float64"
            if column in _FLOAT_COLUMNS
            else "boolean"
            if column in _NULLABLE_BOOL_COLUMNS
            else "object"
        )
        if str(states[column].dtype) != expected_dtype:
            raise RuntimeError(f"S11B dtype is invalid for {column}")

    basis_resolved = canonical_parent.network_basis is not None
    independently_present = 0
    independently_resolved = 0
    independently_zero = 0
    represented_exits: set[str] = set()
    for key, row in states.iterrows():
        authority = result.voltage_states_by_key.get(key)
        present = authority is not None
        resolved = basis_resolved and present
        expected_state = (
            "unresolved_no_lv_ac_network_basis_authority"
            if not basis_resolved
            else "unresolved_missing_collection_exit_voltage_state"
            if not present
            else "resolved_explicit_collection_exit_voltage_state"
        )
        expected_values: dict[str, object] = {
            "network_basis_resolved": basis_resolved,
            "collection_exit_voltage_state_present": present,
            "collection_exit_voltage_boundary_authority_resolved": resolved,
            "voltage_basis": authority.voltage_basis if authority is not None else "",
            "voltage_reference_plane": authority.reference_plane if authority is not None else "",
            "parameter_source": authority.parameter_source if authority is not None else "",
            "confidence": authority.confidence if authority is not None else "",
            "collection_exit_voltage_authority_state": expected_state,
            "topology_lv_ac_collection_authority_contract": (
                TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_CONTRACT_ID
            ),
            "topology_lv_ac_collection_authority_model": (
                TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_MODEL_ID
            ),
            "topology_lv_ac_collection_exit_voltage_authority_contract": (
                TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_CONTRACT_ID
            ),
            "topology_lv_ac_collection_exit_voltage_authority_model": (
                TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_MODEL_ID
            ),
            "topology_lv_ac_collection_exit_voltage_authority_scope": (
                TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_SCOPE
            ),
            "topology_lv_ac_collection_exit_voltage_authority_coverage_scope": (
                TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_COVERAGE_SCOPE
            ),
        }
        for column, expected in expected_values.items():
            if row[column] != expected:
                raise RuntimeError(f"S11B state does not close for {column}")
        if authority is None:
            if not math.isnan(float(row["voltage_line_to_line_rms_v"])):
                raise RuntimeError("S11B missing voltage must be NaN")
            if not pd.isna(row["voltage_is_zero"]):
                raise RuntimeError("S11B missing zero flag must be NA")
        else:
            independently_present += 1
            represented_exits.add(key[1])
            if resolved:
                independently_resolved += 1
            is_zero = authority.voltage_line_to_line_rms_v == 0.0
            independently_zero += int(is_zero)
            if row["voltage_line_to_line_rms_v"] != authority.voltage_line_to_line_rms_v:
                raise RuntimeError("S11B voltage value failed exact replay")
            if row["voltage_is_zero"] != is_zero:
                raise RuntimeError("S11B zero-voltage flag failed exact replay")

    row_count = len(expected_keys)
    expected_diagnostics = TopologyLvAcCollectionExitVoltageAuthorityDiagnostics(
        collection_exit_count=len(exit_ids),
        represented_collection_exit_count=len(represented_exits),
        timestamp_count=len(timestamps),
        row_count=row_count,
        voltage_state_present_count=independently_present,
        voltage_state_missing_count=row_count - independently_present,
        voltage_boundary_authority_resolved_count=independently_resolved,
        voltage_boundary_authority_unresolved_count=row_count - independently_resolved,
        explicit_zero_voltage_count=independently_zero,
        positive_voltage_count=independently_present - independently_zero,
        missing_network_basis_row_count=0 if basis_resolved else row_count,
        model=TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_MODEL_ID,
    )
    diagnostics = result.diagnostics
    if diagnostics != expected_diagnostics:
        raise RuntimeError("S11B diagnostics failed independent exact closure")
    if (
        diagnostics.voltage_state_present_count + diagnostics.voltage_state_missing_count
        != row_count
    ):
        raise RuntimeError("S11B present/missing diagnostics do not close")
    if (
        diagnostics.voltage_boundary_authority_resolved_count
        + diagnostics.voltage_boundary_authority_unresolved_count
        != row_count
    ):
        raise RuntimeError("S11B resolved/unresolved diagnostics do not close")
    if (
        diagnostics.explicit_zero_voltage_count + diagnostics.positive_voltage_count
        != independently_present
    ):
        raise RuntimeError("S11B zero/positive diagnostics do not close")
    if diagnostics.row_count != diagnostics.timestamp_count * diagnostics.collection_exit_count:
        raise RuntimeError("S11B Cartesian row diagnostics do not close")
    if diagnostics.represented_collection_exit_count > diagnostics.collection_exit_count:
        raise RuntimeError("S11B represented-exit diagnostics are invalid")
    if diagnostics.model != TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_MODEL_ID:
        raise RuntimeError("S11B diagnostics model is invalid")
