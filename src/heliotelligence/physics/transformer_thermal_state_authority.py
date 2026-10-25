"""Timestamped transformer thermal-state evidence authority.

S12J records temperature evidence and provenance only. S12K owns temperature
and harmonic correction of component losses. S12M owns any internally
predicted thermal trajectory and iterative temperature/loss closure.
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
    TopologyTransformerStaticAuthorityResult,
    TransformerBoundaryTopologyAuthority,
    TransformerStaticEquipmentAuthority,
)
from heliotelligence.physics.transformer_loss_authority import (
    TopologyTransformerLossAuthorityResult,
    TransformerNoLoadLossAuthority,
    TransformerRatedLoadLossAuthority,
)
from heliotelligence.physics.transformer_loss_component_authority import (
    TRANSFORMER_LOSS_COMPONENT_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_LOSS_COMPONENT_AUTHORITY_MODEL_ID,
    TopologyTransformerLossComponentAuthorityResult,
    TransformerAdvancedConstructionAuthority,
    TransformerRatedLoadLossComponentAuthority,
    resolve_transformer_loss_component_authority,
)

TRANSFORMER_THERMAL_STATE_AUTHORITY_CONTRACT_ID = (
    "admitted_transformer_advanced_construction_to_timestamped_"
    "multichannel_thermal_state_authority_v1"
)
TRANSFORMER_THERMAL_STATE_AUTHORITY_MODEL_ID = (
    "explicit_transformer_ambient_average_winding_hot_spot_and_"
    "top_oil_temperature_state_authority_v1"
)
TRANSFORMER_THERMAL_STATE_AUTHORITY_SCOPE = (
    "timestamped_transformer_temperature_state_authority_before_"
    "temperature_and_harmonic_corrected_load_loss_evaluation"
)
TRANSFORMER_THERMAL_STATE_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_timestamped_transformer_wide_and_optional_winding_resolved_"
    "temperature_evidence_before_load_loss_correction"
)
LOAD_LOSS_TEMPERATURE_QUANTITY = "average_winding_temperature"
LOAD_LOSS_TEMPERATURE_BASIS_SEMANTICS = (
    "explicit_average_winding_temperature_for_component_loss_temperature_correction"
)
WINDING_RESOLVED_TEMPERATURE_BASIS_SEMANTICS = (
    "explicit_collection_and_network_average_winding_temperature_evidence_"
    "without_cross_side_or_transformer_average_inference"
)

Confidence = Literal["high", "medium", "low", "unknown"]
EvidenceKind = Literal[
    "direct_sensor_measurement",
    "scada_condition_monitoring_estimate",
    "resistance_based_winding_temperature_estimate",
    "manufacturer_thermal_model_estimate",
    "documented_external_engineering_model_estimate",
    "other_documented_temperature_evidence",
]
_KINDS = {
    "direct_sensor_measurement",
    "scada_condition_monitoring_estimate",
    "resistance_based_winding_temperature_estimate",
    "manufacturer_thermal_model_estimate",
    "documented_external_engineering_model_estimate",
    "other_documented_temperature_evidence",
}
_CONFIDENCES = {"high", "medium", "low", "unknown"}
_CHANNELS = (
    "ambient_air_temperature",
    "average_winding_temperature",
    "winding_hot_spot_temperature",
    "top_oil_temperature",
    "collection_winding_average_temperature",
    "network_winding_average_temperature",
)
_STATES = (
    "unresolved_upstream_transformer_static_authority",
    "unresolved_missing_transformer_construction_authority",
    "unresolved_missing_transformer_thermal_state",
    "unresolved_missing_average_winding_temperature",
    "resolved_transformer_load_loss_temperature_state",
)
_BOOL_COLUMNS = {
    "transformer_static_authority_resolved",
    "transformer_construction_authority_present",
    "transformer_thermal_state_present",
    *{f"{channel}_present" for channel in _CHANNELS},
    "transformer_load_loss_temperature_basis_resolved",
    "incompatible_supplementary_top_oil_evidence",
    "dynamic_thermal_model_applied",
    "temperature_interpolation_applied",
    "temperature_extrapolation_applied",
    "temperature_loss_correction_applied",
    "winding_resolved_conductor_authority_resolved",
    "winding_resolved_temperature_evidence_present",
    "winding_resolved_temperature_pair_complete",
    "winding_resolved_temperature_basis_resolved",
}
_FLOAT_COLUMNS = {f"{channel}_c" for channel in _CHANNELS}
_BASE_COLUMNS = (
    "transformer_static_authority_resolved",
    "transformer_construction_authority_present",
    "thermal_construction_family",
    "winding_conductor_material",
    "cooling_method_code",
    "winding_resolved_conductor_authority_resolved",
    "collection_winding_conductor_material",
    "network_winding_conductor_material",
    "conductor_authority_basis",
    "transformer_thermal_state_present",
    "ambient_air_temperature_present",
    "average_winding_temperature_present",
    "winding_hot_spot_temperature_present",
    "top_oil_temperature_present",
    "collection_winding_average_temperature_present",
    "network_winding_average_temperature_present",
    "transformer_load_loss_temperature_basis_resolved",
    "winding_resolved_temperature_evidence_present",
    "winding_resolved_temperature_pair_complete",
    "winding_resolved_temperature_basis_resolved",
    "load_loss_temperature_quantity",
    "load_loss_temperature_basis_semantics",
    "winding_resolved_temperature_basis_semantics",
    "ambient_air_temperature_c",
    "average_winding_temperature_c",
    "winding_hot_spot_temperature_c",
    "top_oil_temperature_c",
    "collection_winding_average_temperature_c",
    "network_winding_average_temperature_c",
)
_METADATA_COLUMNS = tuple(
    f"{channel}_{suffix}"
    for channel in _CHANNELS
    for suffix in ("evidence_kind", "method_reference", "parameter_source", "confidence")
)
_TAIL_COLUMNS = (
    "state_context_description",
    "top_oil_temperature_applicability",
    "incompatible_supplementary_top_oil_evidence",
    "dynamic_thermal_model_applied",
    "temperature_interpolation_applied",
    "temperature_extrapolation_applied",
    "temperature_loss_correction_applied",
    "transformer_thermal_state_authority_state",
    "transformer_loss_component_authority_contract",
    "transformer_loss_component_authority_model",
    "transformer_thermal_state_authority_contract",
    "transformer_thermal_state_authority_model",
    "transformer_thermal_state_authority_scope",
    "transformer_thermal_state_authority_coverage_scope",
)
_COLUMNS = _BASE_COLUMNS + _METADATA_COLUMNS + _TAIL_COLUMNS


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be an exact non-empty string without padding")
    return value


@dataclass(frozen=True)
class TransformerTemperatureEvidence:
    temperature_c: float
    evidence_kind: EvidenceKind
    method_reference: str
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        if isinstance(self.temperature_c, bool) or not isinstance(self.temperature_c, Real):
            raise ValueError("temperature_c must be a non-Boolean real number")
        value = float(self.temperature_c)
        if not math.isfinite(value) or value <= -273.15:
            raise ValueError("temperature_c must be finite and above absolute zero")
        if type(self.evidence_kind) is not str or self.evidence_kind not in _KINDS:
            raise ValueError("evidence_kind is unsupported")
        _text(self.method_reference, "method_reference")
        _text(self.parameter_source, "parameter_source")
        if type(self.confidence) is not str or self.confidence not in _CONFIDENCES:
            raise ValueError("confidence is unsupported")


@dataclass(frozen=True)
class TransformerThermalState:
    ambient_air_temperature: TransformerTemperatureEvidence | None
    average_winding_temperature: TransformerTemperatureEvidence | None
    winding_hot_spot_temperature: TransformerTemperatureEvidence | None
    top_oil_temperature: TransformerTemperatureEvidence | None
    state_context_description: str
    collection_winding_average_temperature: TransformerTemperatureEvidence | None = None
    network_winding_average_temperature: TransformerTemperatureEvidence | None = None

    def __post_init__(self) -> None:
        supplied = False
        for channel in _CHANNELS:
            evidence = getattr(self, channel)
            if evidence is not None and type(evidence) is not TransformerTemperatureEvidence:
                raise TypeError(f"{channel} must be exact TransformerTemperatureEvidence")
            supplied = supplied or evidence is not None
            if (
                channel
                not in {
                    "average_winding_temperature",
                    "collection_winding_average_temperature",
                    "network_winding_average_temperature",
                }
                and evidence is not None
                and evidence.evidence_kind == "resistance_based_winding_temperature_estimate"
            ):
                raise ValueError(
                    "resistance-based winding temperature evidence is valid only "
                    "for average winding"
                )
        if not supplied:
            raise ValueError("at least one temperature channel must be supplied")
        _text(self.state_context_description, "state_context_description")


@dataclass(frozen=True)
class TopologyTransformerThermalStateAuthorityDiagnostics:
    transformer_count: int
    timestamp_count: int
    row_count: int
    represented_transformer_count: int
    thermal_state_present_count: int
    thermal_state_missing_count: int
    construction_authority_present_row_count: int
    construction_authority_missing_row_count: int
    average_winding_temperature_present_count: int
    average_winding_temperature_missing_count: int
    load_loss_temperature_basis_resolved_count: int
    load_loss_temperature_basis_unresolved_count: int
    ambient_temperature_present_count: int
    hot_spot_temperature_present_count: int
    top_oil_temperature_present_count: int
    dry_type_top_oil_conflict_count: int
    direct_sensor_evidence_count: int
    scada_monitoring_evidence_count: int
    resistance_based_winding_temperature_evidence_count: int
    manufacturer_model_evidence_count: int
    external_engineering_model_evidence_count: int
    collection_winding_average_temperature_present_count: int
    network_winding_average_temperature_present_count: int
    winding_resolved_temperature_evidence_present_count: int
    winding_resolved_temperature_pair_complete_count: int
    winding_resolved_temperature_pair_incomplete_count: int
    winding_resolved_temperature_basis_resolved_count: int
    state_counts: tuple[tuple[str, int], ...]
    model: str


@dataclass(frozen=True)
class TopologyTransformerThermalStateAuthorityResult:
    thermal_state_by_key: Mapping[tuple[pd.Timestamp, str], TransformerThermalState]
    states: pd.DataFrame
    diagnostics: TopologyTransformerThermalStateAuthorityDiagnostics


def resolve_transformer_thermal_state_authority(
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
    transformer_loss_component_authority: TopologyTransformerLossComponentAuthorityResult,
    transformer_thermal_state_by_key: Mapping[tuple[pd.Timestamp, str], TransformerThermalState],
) -> TopologyTransformerThermalStateAuthorityResult:
    canonical = resolve_transformer_loss_component_authority(
        topology,
        network_basis,
        node_authority_by_id,
        segment_authority_by_id,
        inverter_terminal_binding_by_inverter_id,
        lv_ac_collection_authority,
        transformer_equipment_by_id,
        transformer_topology_by_id,
        transformer_static_authority,
        transformer_no_load_loss_by_id,
        transformer_rated_load_loss_by_id,
        transformer_loss_authority,
        transformer_construction_by_id,
        transformer_rated_load_loss_component_by_id,
    )
    _validate_s12h_replay(transformer_loss_component_authority, canonical)
    ids = canonical.transformer_states.index.tolist()
    admitted, timestamps = _admit_states(transformer_thermal_state_by_key, set(ids))
    keys = [(timestamp, identifier) for timestamp in timestamps for identifier in ids]
    records = [
        _record(
            canonical.transformer_states.loc[identifier],
            canonical.construction_by_id.get(identifier),
            admitted.get((timestamp, identifier)),
        )
        for timestamp, identifier in keys
    ]
    frame = _frame(keys, records)
    result = TopologyTransformerThermalStateAuthorityResult(
        MappingProxyType(dict(admitted)),
        frame.copy(deep=True),
        _diagnostics(frame, ids, timestamps),
    )
    _validate_result(canonical, admitted, timestamps, result)
    return result


def _validate_s12h_replay(
    supplied: TopologyTransformerLossComponentAuthorityResult,
    canonical: TopologyTransformerLossComponentAuthorityResult,
) -> None:
    if type(supplied) is not TopologyTransformerLossComponentAuthorityResult:
        raise ValueError("supplied S12H result type is invalid")
    for name in (
        "construction_by_id",
        "rated_load_loss_component_by_id",
        "winding_resolved_load_loss_by_id",
    ):
        actual = getattr(supplied, name)
        expected = getattr(canonical, name)
        if type(actual) is not MappingProxyType or tuple(actual.items()) != tuple(expected.items()):
            raise ValueError(f"supplied S12H {name} failed immutable canonical replay")
    try:
        pd.testing.assert_frame_equal(
            supplied.transformer_states, canonical.transformer_states, check_exact=True
        )
    except AssertionError as error:
        raise ValueError("supplied S12H frame failed canonical replay") from error
    if supplied.diagnostics != canonical.diagnostics:
        raise ValueError("supplied S12H diagnostics failed canonical replay")


def _admit_states(
    supplied: Mapping[tuple[pd.Timestamp, str], TransformerThermalState], known: set[str]
) -> tuple[dict[tuple[pd.Timestamp, str], TransformerThermalState], list[pd.Timestamp]]:
    if not isinstance(supplied, Mapping):
        raise TypeError("transformer thermal-state authority must be a mapping")
    copied: dict[tuple[pd.Timestamp, str], TransformerThermalState] = {}
    timestamp_set: set[pd.Timestamp] = set()
    for key, state in supplied.items():
        if type(key) is not tuple or len(key) != 2:
            raise ValueError("transformer thermal-state key must be an exact two-item tuple")
        timestamp, identifier = key
        if type(timestamp) is not pd.Timestamp or pd.isna(timestamp):
            raise ValueError(
                "transformer thermal-state timestamp must be an exact non-NaT Timestamp"
            )
        _text(identifier, "transformer_id")
        if identifier not in known:
            raise ValueError("transformer thermal state references unknown transformer")
        if type(state) is not TransformerThermalState:
            raise TypeError("transformer thermal-state mapping has invalid value type")
        copied[(timestamp, identifier)] = state
        timestamp_set.add(timestamp)
    try:
        timestamps = sorted(timestamp_set)
    except TypeError as error:
        raise ValueError(
            "transformer thermal-state timestamps have incompatible timezone semantics"
        ) from error
    ordered = {
        (timestamp, identifier): copied[(timestamp, identifier)]
        for timestamp in timestamps
        for identifier in sorted(known)
        if (timestamp, identifier) in copied
    }
    return ordered, timestamps


def _top_oil(family: str, present: bool) -> tuple[str, bool]:
    if not present:
        return "not_supplied", False
    if family == "mineral_oil_immersed":
        return "applicable", False
    if family == "dry_type":
        return "not_applicable", True
    return "unknown", False


def _record(
    parent_row: pd.Series,
    construction: TransformerAdvancedConstructionAuthority | None,
    state: TransformerThermalState | None,
) -> dict[str, object]:
    static_ok = bool(parent_row["transformer_static_authority_resolved"])
    winding_conductor_ok = bool(parent_row["winding_resolved_conductor_authority_resolved"])
    average = state.average_winding_temperature if state else None
    if not static_ok:
        primary = _STATES[0]
    elif construction is None:
        primary = _STATES[1]
    elif state is None:
        primary = _STATES[2]
    elif average is None:
        primary = _STATES[3]
    else:
        primary = _STATES[4]
    return _record_values(
        static_ok,
        winding_conductor_ok,
        str(parent_row["collection_winding_conductor_material"]),
        str(parent_row["network_winding_conductor_material"]),
        str(parent_row["conductor_authority_basis"]),
        construction,
        state,
        primary,
    )


def _record_values(
    static_ok: bool,
    winding_conductor_ok: bool,
    collection_material: str,
    network_material: str,
    conductor_basis: str,
    construction: TransformerAdvancedConstructionAuthority | None,
    state: TransformerThermalState | None,
    primary: str,
) -> dict[str, object]:
    family = construction.thermal_construction_family if construction else ""
    present = {channel: getattr(state, channel) if state else None for channel in _CHANNELS}
    applicability, conflict = _top_oil(family, present["top_oil_temperature"] is not None)
    resolved = bool(static_ok and construction and state and present["average_winding_temperature"])
    collection_present = present["collection_winding_average_temperature"] is not None
    network_present = present["network_winding_average_temperature"] is not None
    winding_evidence_present = collection_present or network_present
    pair_complete = collection_present and network_present
    winding_resolved = bool(
        static_ok and construction is not None and winding_conductor_ok and pair_complete
    )
    record: dict[str, object] = {
        "transformer_static_authority_resolved": static_ok,
        "transformer_construction_authority_present": construction is not None,
        "thermal_construction_family": family,
        "winding_conductor_material": construction.winding_conductor_material
        if construction
        else "",
        "cooling_method_code": construction.cooling_method_code if construction else "",
        "winding_resolved_conductor_authority_resolved": winding_conductor_ok,
        "collection_winding_conductor_material": collection_material,
        "network_winding_conductor_material": network_material,
        "conductor_authority_basis": conductor_basis,
        "transformer_thermal_state_present": state is not None,
        "transformer_load_loss_temperature_basis_resolved": resolved,
        "winding_resolved_temperature_evidence_present": winding_evidence_present,
        "winding_resolved_temperature_pair_complete": pair_complete,
        "winding_resolved_temperature_basis_resolved": winding_resolved,
        "load_loss_temperature_quantity": LOAD_LOSS_TEMPERATURE_QUANTITY,
        "load_loss_temperature_basis_semantics": LOAD_LOSS_TEMPERATURE_BASIS_SEMANTICS,
        "winding_resolved_temperature_basis_semantics": (
            WINDING_RESOLVED_TEMPERATURE_BASIS_SEMANTICS
        ),
        "state_context_description": state.state_context_description if state else "",
        "top_oil_temperature_applicability": applicability,
        "incompatible_supplementary_top_oil_evidence": conflict,
        "dynamic_thermal_model_applied": False,
        "temperature_interpolation_applied": False,
        "temperature_extrapolation_applied": False,
        "temperature_loss_correction_applied": False,
        "transformer_thermal_state_authority_state": primary,
        "transformer_loss_component_authority_contract": (
            TRANSFORMER_LOSS_COMPONENT_AUTHORITY_CONTRACT_ID
        ),
        "transformer_loss_component_authority_model": TRANSFORMER_LOSS_COMPONENT_AUTHORITY_MODEL_ID,
        "transformer_thermal_state_authority_contract": (
            TRANSFORMER_THERMAL_STATE_AUTHORITY_CONTRACT_ID
        ),
        "transformer_thermal_state_authority_model": TRANSFORMER_THERMAL_STATE_AUTHORITY_MODEL_ID,
        "transformer_thermal_state_authority_scope": TRANSFORMER_THERMAL_STATE_AUTHORITY_SCOPE,
        "transformer_thermal_state_authority_coverage_scope": (
            TRANSFORMER_THERMAL_STATE_AUTHORITY_COVERAGE_SCOPE
        ),
    }
    for channel, evidence in present.items():
        record[f"{channel}_present"] = evidence is not None
        record[f"{channel}_c"] = evidence.temperature_c if evidence else math.nan
        for suffix in ("evidence_kind", "method_reference", "parameter_source", "confidence"):
            record[f"{channel}_{suffix}"] = getattr(evidence, suffix) if evidence else ""
    return record


def _index(keys: list[tuple[pd.Timestamp, str]]) -> pd.MultiIndex:
    if not keys:
        return pd.MultiIndex.from_arrays(
            [pd.DatetimeIndex([]), pd.Index([], dtype=object)],
            names=["timestamp", "transformer_id"],
        )
    return pd.MultiIndex.from_tuples(keys, names=["timestamp", "transformer_id"])


def _frame(keys: list[tuple[pd.Timestamp, str]], records: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(records, index=_index(keys), columns=_COLUMNS, dtype=object)
    for column in _COLUMNS:
        if column in _BOOL_COLUMNS:
            frame[column] = frame[column].astype(bool)
        elif column in _FLOAT_COLUMNS:
            frame[column] = frame[column].astype("float64")
        else:
            frame[column] = frame[column].astype(object)
    return frame


def _diagnostics(
    frame: pd.DataFrame, ids: list[str], timestamps: list[pd.Timestamp]
) -> TopologyTransformerThermalStateAuthorityDiagnostics:
    present = frame["transformer_thermal_state_present"]
    construction = frame["transformer_construction_authority_present"]
    average = frame["average_winding_temperature_present"]
    resolved = frame["transformer_load_loss_temperature_basis_resolved"]
    collection = frame["collection_winding_average_temperature_present"]
    network = frame["network_winding_average_temperature_present"]
    winding_present = frame["winding_resolved_temperature_evidence_present"]
    pair = frame["winding_resolved_temperature_pair_complete"]
    winding_resolved = frame["winding_resolved_temperature_basis_resolved"]
    kinds = [frame[f"{channel}_evidence_kind"] for channel in _CHANNELS]

    def count_kind(kind: str) -> int:
        return sum(int(series.eq(kind).sum()) for series in kinds)

    state_counts = tuple(
        (state, int(frame["transformer_thermal_state_authority_state"].eq(state).sum()))
        for state in _STATES
    )
    represented = len(set(frame.index.get_level_values("transformer_id"))) if len(frame) else 0
    return TopologyTransformerThermalStateAuthorityDiagnostics(
        len(ids),
        len(timestamps),
        len(frame),
        represented,
        int(present.sum()),
        int((~present).sum()),
        int(construction.sum()),
        int((~construction).sum()),
        int(average.sum()),
        int((~average).sum()),
        int(resolved.sum()),
        int((~resolved).sum()),
        int(frame["ambient_air_temperature_present"].sum()),
        int(frame["winding_hot_spot_temperature_present"].sum()),
        int(frame["top_oil_temperature_present"].sum()),
        int(frame["incompatible_supplementary_top_oil_evidence"].sum()),
        count_kind("direct_sensor_measurement"),
        count_kind("scada_condition_monitoring_estimate"),
        count_kind("resistance_based_winding_temperature_estimate"),
        count_kind("manufacturer_thermal_model_estimate"),
        count_kind("documented_external_engineering_model_estimate"),
        int(collection.sum()),
        int(network.sum()),
        int(winding_present.sum()),
        int(pair.sum()),
        int((collection ^ network).sum()),
        int(winding_resolved.sum()),
        state_counts,
        TRANSFORMER_THERMAL_STATE_AUTHORITY_MODEL_ID,
    )


def _validate_result(
    parent: TopologyTransformerLossComponentAuthorityResult,
    admitted: Mapping[tuple[pd.Timestamp, str], TransformerThermalState],
    timestamps: list[pd.Timestamp],
    result: TopologyTransformerThermalStateAuthorityResult,
) -> None:
    if type(result) is not TopologyTransformerThermalStateAuthorityResult:
        raise RuntimeError("S12J result type is invalid")
    if type(result.thermal_state_by_key) is not MappingProxyType:
        raise RuntimeError("S12J thermal-state mapping must be immutable")
    if tuple(result.thermal_state_by_key.items()) != tuple(admitted.items()):
        raise RuntimeError("S12J thermal-state mapping failed independent closure")
    ids = parent.transformer_states.index.tolist()
    keys = [(timestamp, identifier) for timestamp in timestamps for identifier in ids]
    records = [
        _validator_record(
            parent.transformer_states.loc[identifier],
            parent.construction_by_id.get(identifier),
            admitted.get((timestamp, identifier)),
        )
        for timestamp, identifier in keys
    ]
    expected = _validator_frame(keys, records)
    try:
        pd.testing.assert_frame_equal(result.states, expected, check_exact=True)
    except AssertionError as error:
        raise RuntimeError("S12J result frame failed independent closure") from error
    expected_diagnostics = _validator_diagnostics(expected, ids, timestamps)
    if result.diagnostics != expected_diagnostics:
        raise RuntimeError("S12J diagnostics failed independent closure")


def _validator_record(
    parent_row: pd.Series,
    construction: TransformerAdvancedConstructionAuthority | None,
    state: TransformerThermalState | None,
) -> dict[str, object]:
    static_ok = bool(parent_row["transformer_static_authority_resolved"])
    winding_conductor_ok = bool(parent_row["winding_resolved_conductor_authority_resolved"])
    average = state.average_winding_temperature if state else None
    conditions = (static_ok, construction is not None, state is not None, average is not None)
    primary = _STATES[4]
    for position, condition in enumerate(conditions):
        if not condition:
            primary = _STATES[position]
            break
    family = construction.thermal_construction_family if construction else ""
    evidence_by_channel = {
        channel: getattr(state, channel) if state else None for channel in _CHANNELS
    }
    collection_present = evidence_by_channel["collection_winding_average_temperature"] is not None
    network_present = evidence_by_channel["network_winding_average_temperature"] is not None
    side_evidence_present = collection_present or network_present
    side_pair_complete = collection_present and network_present
    side_basis_resolved = bool(
        static_ok
        and construction is not None
        and winding_conductor_ok
        and side_pair_complete
    )
    top_oil_present = evidence_by_channel["top_oil_temperature"] is not None
    if not top_oil_present:
        applicability, conflict = "not_supplied", False
    elif family == "mineral_oil_immersed":
        applicability, conflict = "applicable", False
    elif family == "dry_type":
        applicability, conflict = "not_applicable", True
    else:
        applicability, conflict = "unknown", False
    record: dict[str, object] = {
        "transformer_static_authority_resolved": static_ok,
        "transformer_construction_authority_present": construction is not None,
        "thermal_construction_family": family,
        "winding_conductor_material": construction.winding_conductor_material
        if construction
        else "",
        "cooling_method_code": construction.cooling_method_code if construction else "",
        "winding_resolved_conductor_authority_resolved": winding_conductor_ok,
        "collection_winding_conductor_material": str(
            parent_row["collection_winding_conductor_material"]
        ),
        "network_winding_conductor_material": str(
            parent_row["network_winding_conductor_material"]
        ),
        "conductor_authority_basis": str(parent_row["conductor_authority_basis"]),
        "transformer_thermal_state_present": state is not None,
        "transformer_load_loss_temperature_basis_resolved": all(conditions),
        "winding_resolved_temperature_evidence_present": side_evidence_present,
        "winding_resolved_temperature_pair_complete": side_pair_complete,
        "winding_resolved_temperature_basis_resolved": side_basis_resolved,
        "load_loss_temperature_quantity": LOAD_LOSS_TEMPERATURE_QUANTITY,
        "load_loss_temperature_basis_semantics": LOAD_LOSS_TEMPERATURE_BASIS_SEMANTICS,
        "winding_resolved_temperature_basis_semantics": (
            WINDING_RESOLVED_TEMPERATURE_BASIS_SEMANTICS
        ),
        "state_context_description": state.state_context_description if state else "",
        "top_oil_temperature_applicability": applicability,
        "incompatible_supplementary_top_oil_evidence": conflict,
        "dynamic_thermal_model_applied": False,
        "temperature_interpolation_applied": False,
        "temperature_extrapolation_applied": False,
        "temperature_loss_correction_applied": False,
        "transformer_thermal_state_authority_state": primary,
        "transformer_loss_component_authority_contract": (
            TRANSFORMER_LOSS_COMPONENT_AUTHORITY_CONTRACT_ID
        ),
        "transformer_loss_component_authority_model": TRANSFORMER_LOSS_COMPONENT_AUTHORITY_MODEL_ID,
        "transformer_thermal_state_authority_contract": (
            TRANSFORMER_THERMAL_STATE_AUTHORITY_CONTRACT_ID
        ),
        "transformer_thermal_state_authority_model": TRANSFORMER_THERMAL_STATE_AUTHORITY_MODEL_ID,
        "transformer_thermal_state_authority_scope": TRANSFORMER_THERMAL_STATE_AUTHORITY_SCOPE,
        "transformer_thermal_state_authority_coverage_scope": (
            TRANSFORMER_THERMAL_STATE_AUTHORITY_COVERAGE_SCOPE
        ),
    }
    for channel, evidence in evidence_by_channel.items():
        record[f"{channel}_present"] = evidence is not None
        record[f"{channel}_c"] = evidence.temperature_c if evidence else math.nan
        record[f"{channel}_evidence_kind"] = evidence.evidence_kind if evidence else ""
        record[f"{channel}_method_reference"] = evidence.method_reference if evidence else ""
        record[f"{channel}_parameter_source"] = evidence.parameter_source if evidence else ""
        record[f"{channel}_confidence"] = evidence.confidence if evidence else ""
    return record


def _validator_frame(
    keys: list[tuple[pd.Timestamp, str]], records: list[dict[str, object]]
) -> pd.DataFrame:
    if keys:
        index = pd.MultiIndex.from_tuples(keys, names=["timestamp", "transformer_id"])
    else:
        index = pd.MultiIndex.from_arrays(
            [pd.DatetimeIndex([]), pd.Index([], dtype=object)],
            names=["timestamp", "transformer_id"],
        )
    expected = pd.DataFrame(records, index=index, columns=_COLUMNS, dtype=object)
    for column in _COLUMNS:
        if column in _BOOL_COLUMNS:
            expected[column] = expected[column].astype(bool)
        elif column in _FLOAT_COLUMNS:
            expected[column] = expected[column].astype("float64")
        else:
            expected[column] = expected[column].astype(object)
    return expected


def _validator_diagnostics(
    frame: pd.DataFrame, ids: list[str], timestamps: list[pd.Timestamp]
) -> TopologyTransformerThermalStateAuthorityDiagnostics:
    # Independent reconstruction uses direct masks and per-channel evidence observations.
    present = frame["transformer_thermal_state_present"]
    construction = frame["transformer_construction_authority_present"]
    average = frame["average_winding_temperature_present"]
    resolved = frame["transformer_load_loss_temperature_basis_resolved"]
    collection = frame["collection_winding_average_temperature_present"]
    network = frame["network_winding_average_temperature_present"]

    def evidence_count(kind: str) -> int:
        return sum(int(frame[f"{channel}_evidence_kind"].eq(kind).sum()) for channel in _CHANNELS)

    counts = tuple(
        (state, int(frame["transformer_thermal_state_authority_state"].eq(state).sum()))
        for state in _STATES
    )
    represented = len(set(frame.index.get_level_values("transformer_id"))) if len(frame) else 0
    return TopologyTransformerThermalStateAuthorityDiagnostics(
        len(ids),
        len(timestamps),
        len(frame),
        represented,
        int(present.sum()),
        int((~present).sum()),
        int(construction.sum()),
        int((~construction).sum()),
        int(average.sum()),
        int((~average).sum()),
        int(resolved.sum()),
        int((~resolved).sum()),
        int(frame["ambient_air_temperature_present"].sum()),
        int(frame["winding_hot_spot_temperature_present"].sum()),
        int(frame["top_oil_temperature_present"].sum()),
        int(frame["incompatible_supplementary_top_oil_evidence"].sum()),
        evidence_count("direct_sensor_measurement"),
        evidence_count("scada_condition_monitoring_estimate"),
        evidence_count("resistance_based_winding_temperature_estimate"),
        evidence_count("manufacturer_thermal_model_estimate"),
        evidence_count("documented_external_engineering_model_estimate"),
        int(collection.sum()),
        int(network.sum()),
        int(frame["winding_resolved_temperature_evidence_present"].sum()),
        int(frame["winding_resolved_temperature_pair_complete"].sum()),
        int((collection ^ network).sum()),
        int(frame["winding_resolved_temperature_basis_resolved"].sum()),
        counts,
        TRANSFORMER_THERMAL_STATE_AUTHORITY_MODEL_ID,
    )
