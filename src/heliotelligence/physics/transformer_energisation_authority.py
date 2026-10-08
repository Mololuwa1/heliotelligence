"""Explicit timestamped transformer energisation-state authority.

S12C admits exact per-transformer energised or de-energised evidence. It does
not infer state temporally or from electrical operation, and performs no loss,
power-flow, temperature, loading, or energy calculation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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

TRANSFORMER_ENERGISATION_AUTHORITY_CONTRACT_ID = (
    "admitted_transformer_static_authority_to_timestamped_"
    "transformer_energisation_state_v1"
)
TRANSFORMER_ENERGISATION_AUTHORITY_MODEL_ID = (
    "explicit_timestamped_binary_transformer_energisation_state_v1"
)
TRANSFORMER_ENERGISATION_AUTHORITY_SCOPE = (
    "timestamped_transformer_energisation_authority_before_"
    "no_load_and_operating_loss_evaluation"
)
TRANSFORMER_ENERGISATION_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_per_transformer_energised_or_deenergised_state"
)

Confidence = Literal["high", "medium", "low", "unknown"]
_CONFIDENCES = {"high", "medium", "low", "unknown"}
_COLUMNS = (
    "transformer_static_authority_resolved",
    "transformer_energisation_state_present",
    "transformer_energisation_authority_resolved",
    "transformer_energised",
    "energisation_state_semantics",
    "energisation_parameter_source",
    "energisation_confidence",
    "transformer_energisation_authority_state",
    "transformer_static_authority_contract",
    "transformer_static_authority_model",
    "transformer_energisation_authority_contract",
    "transformer_energisation_authority_model",
    "transformer_energisation_authority_scope",
    "transformer_energisation_authority_coverage_scope",
)
_BOOL_COLUMNS = {
    "transformer_static_authority_resolved",
    "transformer_energisation_state_present",
    "transformer_energisation_authority_resolved",
}
_NULLABLE_BOOL_COLUMNS = {"transformer_energised"}


def _identifier(value: object) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(
            "transformer_id must be an exact non-empty string without surrounding whitespace"
        )
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


@dataclass(frozen=True)
class TransformerEnergisationState:
    energised: bool
    state_semantics: Literal["transformer_energised_state"]
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _validate_energisation_state(self)


@dataclass(frozen=True)
class TopologyTransformerEnergisationAuthorityDiagnostics:
    transformer_count: int
    static_authority_resolved_transformer_count: int
    timestamp_count: int
    row_count: int
    energisation_state_present_count: int
    energisation_state_missing_count: int
    energisation_authority_resolved_count: int
    energisation_authority_unresolved_count: int
    explicitly_energised_count: int
    explicitly_deenergised_count: int
    model: str


@dataclass(frozen=True)
class TopologyTransformerEnergisationAuthorityResult:
    energisation_states_by_key: Mapping[
        tuple[pd.Timestamp, str], TransformerEnergisationState
    ]
    states: pd.DataFrame
    diagnostics: TopologyTransformerEnergisationAuthorityDiagnostics


def resolve_transformer_energisation_authority(
    topology: ElectricalTopologyConfig,
    network_basis: LvAcCollectionNetworkBasisAuthority | None,
    node_authority_by_id: Mapping[str, LvAcCollectionNodeAuthority],
    segment_authority_by_id: Mapping[str, LvAcCollectionSegmentAuthority],
    inverter_terminal_binding_by_inverter_id: Mapping[
        str, LvAcInverterTerminalBindingAuthority
    ],
    lv_ac_collection_authority: TopologyLvAcCollectionAuthorityResult,
    transformer_equipment_by_id: Mapping[str, TransformerStaticEquipmentAuthority],
    transformer_topology_by_id: Mapping[str, TransformerBoundaryTopologyAuthority],
    transformer_static_authority: TopologyTransformerStaticAuthorityResult,
    transformer_energisation_by_key: Mapping[
        tuple[pd.Timestamp, str], TransformerEnergisationState
    ],
) -> TopologyTransformerEnergisationAuthorityResult:
    """Admit exact timestamped transformer energisation-state evidence."""
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
    transformer_ids = tuple(canonical_static.transformer_states.index.tolist())
    admitted = _admit_mapping(transformer_energisation_by_key, set(transformer_ids))
    timestamps = _canonical_timestamps(admitted)
    keys = tuple(
        (timestamp, transformer_id)
        for timestamp in timestamps
        for transformer_id in transformer_ids
    )
    canonical_states = {key: admitted[key] for key in keys if key in admitted}
    records = [
        _record(
            bool(
                canonical_static.transformer_states.loc[
                    transformer_id, "transformer_static_authority_resolved"
                ]
            ),
            canonical_states.get((timestamp, transformer_id)),
        )
        for timestamp, transformer_id in keys
    ]
    states = _state_frame(keys, records)
    diagnostics = _diagnostics(canonical_static, timestamps, canonical_states)
    result = TopologyTransformerEnergisationAuthorityResult(
        energisation_states_by_key=MappingProxyType(dict(canonical_states)),
        states=states.copy(deep=True),
        diagnostics=diagnostics,
    )
    _validate_result(canonical_static, result)
    return result


def _validate_energisation_state(state: TransformerEnergisationState) -> None:
    if type(state.energised) is not bool:
        raise ValueError("energised must be an exact built-in bool")
    if state.state_semantics != "transformer_energised_state":
        raise ValueError("state_semantics must be transformer_energised_state")
    _source(state.parameter_source)
    _confidence(state.confidence)


def _validate_parent_replay(
    supplied: object,
    canonical: TopologyTransformerStaticAuthorityResult,
) -> None:
    if type(supplied) is not TopologyTransformerStaticAuthorityResult:
        raise ValueError("supplied S12A result type is invalid")
    for name in ("equipment_by_id", "topology_by_id"):
        actual = getattr(supplied, name)
        expected = getattr(canonical, name)
        if type(actual).__name__ != "mappingproxy" or dict(actual) != dict(expected):
            raise ValueError(
                f"supplied S12A {name} does not match immutable canonical replay"
            )
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


def _admit_mapping(
    supplied: object,
    known_transformer_ids: set[str],
) -> dict[tuple[pd.Timestamp, str], TransformerEnergisationState]:
    if not isinstance(supplied, Mapping):
        raise TypeError("transformer_energisation_by_key must be a mapping")
    admitted: dict[tuple[pd.Timestamp, str], TransformerEnergisationState] = {}
    for key, state in supplied.items():
        if type(key) is not tuple or len(key) != 2:
            raise TypeError("energisation-state keys must be exact two-item tuples")
        timestamp, transformer_id = key
        if type(timestamp) is not pd.Timestamp or pd.isna(timestamp):
            raise TypeError(
                "energisation-state timestamp must be an exact non-NaT pd.Timestamp"
            )
        _identifier(transformer_id)
        if transformer_id not in known_transformer_ids:
            raise ValueError("energisation state references unknown S12A transformer")
        if type(state) is not TransformerEnergisationState:
            raise TypeError("energisation-state values must use the exact authority type")
        _validate_energisation_state(state)
        admitted[(timestamp, transformer_id)] = state
    return admitted


def _canonical_timestamps(
    states: Mapping[tuple[pd.Timestamp, str], TransformerEnergisationState],
) -> tuple[pd.Timestamp, ...]:
    try:
        return tuple(sorted({timestamp for timestamp, _ in states}))
    except TypeError as error:
        raise ValueError(
            "energisation-state timestamps have incompatible timezone semantics"
        ) from error


def _primary_state(state: TransformerEnergisationState | None) -> str:
    if state is None:
        return "unresolved_missing_transformer_energisation_state"
    return (
        "resolved_transformer_energised"
        if state.energised
        else "resolved_transformer_deenergised"
    )


def _record(
    static_resolved: bool,
    state: TransformerEnergisationState | None,
) -> dict[str, object]:
    present = state is not None
    return {
        "transformer_static_authority_resolved": static_resolved,
        "transformer_energisation_state_present": present,
        "transformer_energisation_authority_resolved": present,
        "transformer_energised": state.energised if state is not None else pd.NA,
        "energisation_state_semantics": state.state_semantics if state is not None else "",
        "energisation_parameter_source": state.parameter_source if state is not None else "",
        "energisation_confidence": state.confidence if state is not None else "",
        "transformer_energisation_authority_state": _primary_state(state),
        "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
        "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
        "transformer_energisation_authority_contract": (
            TRANSFORMER_ENERGISATION_AUTHORITY_CONTRACT_ID
        ),
        "transformer_energisation_authority_model": (
            TRANSFORMER_ENERGISATION_AUTHORITY_MODEL_ID
        ),
        "transformer_energisation_authority_scope": (
            TRANSFORMER_ENERGISATION_AUTHORITY_SCOPE
        ),
        "transformer_energisation_authority_coverage_scope": (
            TRANSFORMER_ENERGISATION_AUTHORITY_COVERAGE_SCOPE
        ),
    }


def _state_frame(
    keys: tuple[tuple[pd.Timestamp, str], ...],
    records: list[dict[str, object]],
) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(keys, names=["timestamp", "transformer_id"])
    frame = pd.DataFrame.from_records(records, columns=_COLUMNS, index=index)
    frame.index = index
    for column in _BOOL_COLUMNS:
        frame[column] = frame[column].astype("bool")
    for column in _NULLABLE_BOOL_COLUMNS:
        frame[column] = frame[column].astype("boolean")
    for column in set(_COLUMNS) - _BOOL_COLUMNS - _NULLABLE_BOOL_COLUMNS:
        frame[column] = frame[column].astype("object")
    return frame


def _diagnostics(
    static: TopologyTransformerStaticAuthorityResult,
    timestamps: tuple[pd.Timestamp, ...],
    states: Mapping[tuple[pd.Timestamp, str], TransformerEnergisationState],
) -> TopologyTransformerEnergisationAuthorityDiagnostics:
    transformer_count = len(static.transformer_states)
    row_count = transformer_count * len(timestamps)
    present = len(states)
    energised = sum(state.energised for state in states.values())
    return TopologyTransformerEnergisationAuthorityDiagnostics(
        transformer_count=transformer_count,
        static_authority_resolved_transformer_count=int(
            static.transformer_states["transformer_static_authority_resolved"].sum()
        ),
        timestamp_count=len(timestamps),
        row_count=row_count,
        energisation_state_present_count=present,
        energisation_state_missing_count=row_count - present,
        energisation_authority_resolved_count=present,
        energisation_authority_unresolved_count=row_count - present,
        explicitly_energised_count=energised,
        explicitly_deenergised_count=present - energised,
        model=TRANSFORMER_ENERGISATION_AUTHORITY_MODEL_ID,
    )


def _validate_result(
    static: TopologyTransformerStaticAuthorityResult,
    result: TopologyTransformerEnergisationAuthorityResult,
) -> None:
    """Independently close the S12C result against canonical S12A and evidence."""
    if type(result) is not TopologyTransformerEnergisationAuthorityResult:
        raise RuntimeError("transformer energisation result type is invalid")
    if type(result.energisation_states_by_key).__name__ != "mappingproxy":
        raise RuntimeError("transformer energisation result mapping must be immutable")
    transformer_ids = tuple(static.transformer_states.index.tolist())
    known_ids = set(transformer_ids)
    for key, state in result.energisation_states_by_key.items():
        if type(key) is not tuple or len(key) != 2:
            raise RuntimeError("transformer energisation mapping key is invalid")
        timestamp, transformer_id = key
        if type(timestamp) is not pd.Timestamp or pd.isna(timestamp):
            raise RuntimeError("transformer energisation timestamp is invalid")
        if type(transformer_id) is not str or transformer_id not in known_ids:
            raise RuntimeError("transformer energisation identity is invalid")
        if type(state) is not TransformerEnergisationState:
            raise RuntimeError("transformer energisation authority type is invalid")
        try:
            _validate_energisation_state(state)
        except ValueError as error:
            raise RuntimeError("transformer energisation authority domain is invalid") from error

    timestamps = _canonical_timestamps(result.energisation_states_by_key)
    expected_keys = tuple(
        (timestamp, transformer_id)
        for timestamp in timestamps
        for transformer_id in transformer_ids
    )
    states = result.states
    if tuple(states.columns) != _COLUMNS:
        raise RuntimeError("transformer energisation schema is invalid")
    if not isinstance(states.index, pd.MultiIndex):
        raise RuntimeError("transformer energisation index must be a MultiIndex")
    if list(states.index.names) != ["timestamp", "transformer_id"]:
        raise RuntimeError("transformer energisation index names are invalid")
    if states.index.has_duplicates or tuple(states.index.tolist()) != expected_keys:
        raise RuntimeError("transformer energisation canonical index/order is invalid")
    for column in _COLUMNS:
        expected_dtype = (
            "bool"
            if column in _BOOL_COLUMNS
            else "boolean"
            if column in _NULLABLE_BOOL_COLUMNS
            else "object"
        )
        if str(states[column].dtype) != expected_dtype:
            raise RuntimeError(f"transformer energisation dtype is invalid for {column}")

    present_count = 0
    energised_count = 0
    static_resolved_count = int(
        static.transformer_states["transformer_static_authority_resolved"].sum()
    )
    for key, row in states.iterrows():
        transformer_id = key[1]
        authority = result.energisation_states_by_key.get(key)
        present = authority is not None
        static_resolved = bool(
            static.transformer_states.loc[
                transformer_id, "transformer_static_authority_resolved"
            ]
        )
        expected: dict[str, object] = {
            "transformer_static_authority_resolved": static_resolved,
            "transformer_energisation_state_present": present,
            "transformer_energisation_authority_resolved": present,
            "energisation_state_semantics": (
                authority.state_semantics if authority is not None else ""
            ),
            "energisation_parameter_source": (
                authority.parameter_source if authority is not None else ""
            ),
            "energisation_confidence": authority.confidence if authority is not None else "",
            "transformer_energisation_authority_state": _primary_state(authority),
            "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
            "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
            "transformer_energisation_authority_contract": (
                TRANSFORMER_ENERGISATION_AUTHORITY_CONTRACT_ID
            ),
            "transformer_energisation_authority_model": (
                TRANSFORMER_ENERGISATION_AUTHORITY_MODEL_ID
            ),
            "transformer_energisation_authority_scope": (
                TRANSFORMER_ENERGISATION_AUTHORITY_SCOPE
            ),
            "transformer_energisation_authority_coverage_scope": (
                TRANSFORMER_ENERGISATION_AUTHORITY_COVERAGE_SCOPE
            ),
        }
        for column, wanted in expected.items():
            if row[column] != wanted:
                raise RuntimeError(f"transformer energisation state does not close for {column}")
        if authority is None:
            if not pd.isna(row["transformer_energised"]):
                raise RuntimeError("missing energisation state must use pd.NA")
        else:
            present_count += 1
            energised_count += int(authority.energised)
            if bool(row["transformer_energised"]) is not authority.energised:
                raise RuntimeError("transformer energisation value failed exact replay")

    row_count = len(expected_keys)
    expected_diagnostics = TopologyTransformerEnergisationAuthorityDiagnostics(
        transformer_count=len(transformer_ids),
        static_authority_resolved_transformer_count=static_resolved_count,
        timestamp_count=len(timestamps),
        row_count=row_count,
        energisation_state_present_count=present_count,
        energisation_state_missing_count=row_count - present_count,
        energisation_authority_resolved_count=present_count,
        energisation_authority_unresolved_count=row_count - present_count,
        explicitly_energised_count=energised_count,
        explicitly_deenergised_count=present_count - energised_count,
        model=TRANSFORMER_ENERGISATION_AUTHORITY_MODEL_ID,
    )
    diagnostics = result.diagnostics
    if diagnostics != expected_diagnostics:
        raise RuntimeError("transformer energisation diagnostics failed exact closure")
    if diagnostics.row_count != diagnostics.transformer_count * diagnostics.timestamp_count:
        raise RuntimeError("transformer energisation Cartesian diagnostics do not close")
    if (
        diagnostics.energisation_state_present_count
        + diagnostics.energisation_state_missing_count
        != diagnostics.row_count
    ):
        raise RuntimeError("transformer energisation present/missing diagnostics do not close")
    if (
        diagnostics.energisation_authority_resolved_count
        + diagnostics.energisation_authority_unresolved_count
        != diagnostics.row_count
    ):
        raise RuntimeError("transformer energisation resolution diagnostics do not close")
    if (
        diagnostics.energisation_authority_resolved_count
        != diagnostics.energisation_state_present_count
    ):
        raise RuntimeError("transformer energisation present/resolved diagnostics differ")
    if (
        diagnostics.explicitly_energised_count
        + diagnostics.explicitly_deenergised_count
        != diagnostics.energisation_state_present_count
    ):
        raise RuntimeError("transformer energisation binary diagnostics do not close")
    if diagnostics.model != TRANSFORMER_ENERGISATION_AUTHORITY_MODEL_ID:
        raise RuntimeError("transformer energisation diagnostics model is invalid")
