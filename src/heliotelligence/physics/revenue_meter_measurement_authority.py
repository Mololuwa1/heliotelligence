"""Timestamped measured power authority at explicit revenue-meter boundaries.

S13D admits already-scaled, signed three-phase P/Q measurements at S13A's
named revenue-meter reference planes.  It does not consume S13B or S13C,
perform network physics, infer meter engineering, or compare measurements to
expected power.  The first expected/actual comparison belongs to S14.
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

REVENUE_METER_MEASUREMENT_AUTHORITY_CONTRACT_ID = (
    "admitted_revenue_meter_boundary_to_timestamped_measured_power_state_v1"
)
REVENUE_METER_MEASUREMENT_AUTHORITY_MODEL_ID = (
    "explicit_signed_three_phase_revenue_meter_active_reactive_power_"
    "measurement_state_v1"
)
REVENUE_METER_MEASUREMENT_AUTHORITY_SCOPE = (
    "timestamped_measured_revenue_meter_power_authority_before_expected_actual_"
    "benchmarking"
)
REVENUE_METER_MEASUREMENT_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_revenue_meter_boundary_pq_measurements_with_declared_temporal_"
    "semantics_and_no_inferred_scaling"
)

Confidence = Literal["high", "medium", "low", "unknown"]
MeasurementTimeSemantics = Literal[
    "instantaneous_snapshot", "interval_average_ending_at_timestamp"
]
_CONFIDENCES = {"high", "medium", "low", "unknown"}
_COLUMNS = (
    "network_basis_resolved",
    "measured_power_state_present",
    "measured_power_authority_resolved",
    "revenue_meter_node_id",
    "revenue_meter_node_kind",
    "revenue_meter_reference_plane",
    "revenue_meter_colocated_with_grid_boundary",
    "colocated_grid_boundary_id",
    "measured_active_power_w",
    "measured_reactive_power_var",
    "measured_apparent_power_magnitude_va",
    "measured_active_power_is_zero",
    "measured_reactive_power_is_zero",
    "measurement_reference_plane",
    "active_power_sign_convention",
    "reactive_power_sign_convention",
    "power_basis",
    "measurement_value_basis",
    "measurement_time_semantics",
    "averaging_interval_seconds",
    "parameter_source",
    "confidence",
    "revenue_meter_measurement_authority_state",
    "mv_hv_network_authority_contract",
    "mv_hv_network_authority_model",
    "revenue_meter_measurement_authority_contract",
    "revenue_meter_measurement_authority_model",
    "revenue_meter_measurement_authority_scope",
    "revenue_meter_measurement_authority_coverage_scope",
)
_BOOL_COLUMNS = {
    "network_basis_resolved",
    "measured_power_state_present",
    "measured_power_authority_resolved",
    "revenue_meter_colocated_with_grid_boundary",
}
_FLOAT_COLUMNS = {
    "measured_active_power_w",
    "measured_reactive_power_var",
    "measured_apparent_power_magnitude_va",
    "averaging_interval_seconds",
}
_NULLABLE_BOOL_COLUMNS = {
    "measured_active_power_is_zero",
    "measured_reactive_power_is_zero",
}


def _identifier(value: object) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(
            "revenue_meter_id must be an exact non-empty string without surrounding whitespace"
        )
    return value


def _source(value: object) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(
            "parameter_source must be an exact non-empty string without surrounding whitespace"
        )
    return value


def _finite_signed(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real non-Boolean number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


@dataclass(frozen=True)
class RevenueMeterMeasuredPowerState:
    """Explicit signed measured P/Q at one revenue meter and timestamp."""

    active_power_w: float
    reactive_power_var: float
    reference_plane: Literal["revenue_meter_boundary"]
    active_power_sign_convention: Literal["positive_plant_to_grid"]
    reactive_power_sign_convention: Literal["positive_plant_to_grid"]
    power_basis: Literal["three_phase_total"]
    measurement_value_basis: Literal[
        "primary_engineering_units_at_revenue_meter_boundary"
    ]
    measurement_time_semantics: MeasurementTimeSemantics
    averaging_interval_seconds: float | None
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        p = _finite_signed(self.active_power_w, "active_power_w")
        q = _finite_signed(self.reactive_power_var, "reactive_power_var")
        if self.reference_plane != "revenue_meter_boundary":
            raise ValueError("reference_plane must be revenue_meter_boundary")
        if self.active_power_sign_convention != "positive_plant_to_grid":
            raise ValueError("active_power_sign_convention must be positive_plant_to_grid")
        if self.reactive_power_sign_convention != "positive_plant_to_grid":
            raise ValueError("reactive_power_sign_convention must be positive_plant_to_grid")
        if self.power_basis != "three_phase_total":
            raise ValueError("power_basis must be three_phase_total")
        if (
            self.measurement_value_basis
            != "primary_engineering_units_at_revenue_meter_boundary"
        ):
            raise ValueError("measurement_value_basis is unsupported")
        if self.measurement_time_semantics == "instantaneous_snapshot":
            if self.averaging_interval_seconds is not None:
                raise ValueError("instantaneous_snapshot requires no averaging interval")
        elif self.measurement_time_semantics == "interval_average_ending_at_timestamp":
            interval = self.averaging_interval_seconds
            if isinstance(interval, bool) or not isinstance(interval, Real):
                raise ValueError("interval-average measurement requires a real interval")
            normalized_interval = float(interval)
            if not math.isfinite(normalized_interval) or normalized_interval <= 0.0:
                raise ValueError("averaging_interval_seconds must be finite and positive")
            object.__setattr__(self, "averaging_interval_seconds", normalized_interval)
        else:
            raise ValueError("measurement_time_semantics is unsupported")
        _source(self.parameter_source)
        if type(self.confidence) is not str or self.confidence not in _CONFIDENCES:
            raise ValueError("confidence is unsupported")
        if not math.isfinite(math.hypot(p, q)):
            raise ValueError("derived apparent power must be finite")
        object.__setattr__(self, "active_power_w", p)
        object.__setattr__(self, "reactive_power_var", q)


@dataclass(frozen=True)
class TopologyRevenueMeterMeasurementAuthorityDiagnostics:
    revenue_meter_count: int
    represented_revenue_meter_count: int
    timestamp_count: int
    row_count: int
    measured_power_state_present_count: int
    measured_power_state_missing_count: int
    measured_power_authority_resolved_count: int
    measured_power_authority_unresolved_count: int
    instantaneous_snapshot_state_count: int
    interval_average_state_count: int
    active_power_positive_count: int
    active_power_negative_count: int
    active_power_zero_count: int
    reactive_power_positive_count: int
    reactive_power_negative_count: int
    reactive_power_zero_count: int
    revenue_meter_colocated_with_grid_boundary_count: int
    missing_network_basis_row_count: int
    model: str


@dataclass(frozen=True)
class TopologyRevenueMeterMeasurementAuthorityResult:
    measured_power_states_by_key: Mapping[
        tuple[pd.Timestamp, str], RevenueMeterMeasuredPowerState
    ]
    states: pd.DataFrame
    diagnostics: TopologyRevenueMeterMeasurementAuthorityDiagnostics


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


def _admit_mapping(
    supplied: object, parent: TopologyMvHvNetworkAuthorityResult
) -> dict[tuple[pd.Timestamp, str], RevenueMeterMeasuredPowerState]:
    if not isinstance(supplied, Mapping):
        raise TypeError("revenue_meter_measured_power_by_key must be a mapping")
    admitted: dict[tuple[pd.Timestamp, str], RevenueMeterMeasuredPowerState] = {}
    for key, state in supplied.items():
        if type(key) is not tuple or len(key) != 2:
            raise TypeError("measured-power keys must be exact two-item tuples")
        timestamp, meter_id = key
        if type(timestamp) is not pd.Timestamp or pd.isna(timestamp):
            raise TypeError("measurement timestamp must be an exact non-NaT pd.Timestamp")
        _identifier(meter_id)
        if meter_id not in parent.revenue_meter_boundary_by_id:
            raise ValueError("measurement key references an unknown revenue meter")
        if type(state) is not RevenueMeterMeasuredPowerState:
            raise TypeError("measurement values must use the exact authority type")
        meter = parent.revenue_meter_boundary_by_id[meter_id]
        if (
            state.reference_plane != meter.reference_plane
            or state.active_power_sign_convention != meter.active_power_sign_convention
            or state.reactive_power_sign_convention != meter.reactive_power_sign_convention
            or state.power_basis != meter.power_basis
        ):
            raise ValueError("measurement semantics do not match canonical S13A revenue meter")
        admitted[(timestamp, meter_id)] = state
    return admitted


def _timestamps(
    admitted: Mapping[tuple[pd.Timestamp, str], RevenueMeterMeasuredPowerState],
) -> tuple[pd.Timestamp, ...]:
    try:
        return tuple(sorted({timestamp for timestamp, _ in admitted}))
    except TypeError as error:
        raise ValueError("measurement timestamps have incompatible timezone semantics") from error


def _grid_by_node(parent: TopologyMvHvNetworkAuthorityResult) -> dict[str, str]:
    return {grid.node_id: identifier for identifier, grid in parent.grid_boundary_by_id.items()}


def _record(
    parent: TopologyMvHvNetworkAuthorityResult,
    meter_id: str,
    state: RevenueMeterMeasuredPowerState | None,
) -> dict[str, object]:
    meter = parent.revenue_meter_boundary_by_id[meter_id]
    node = parent.nodes_by_id[meter.node_id]
    colocated_id = _grid_by_node(parent).get(meter.node_id)
    present = state is not None
    p = state.active_power_w if state is not None else math.nan
    q = state.reactive_power_var if state is not None else math.nan
    return {
        "network_basis_resolved": parent.network_basis is not None,
        "measured_power_state_present": present,
        "measured_power_authority_resolved": present,
        "revenue_meter_node_id": meter.node_id,
        "revenue_meter_node_kind": node.node_kind,
        "revenue_meter_reference_plane": meter.reference_plane,
        "revenue_meter_colocated_with_grid_boundary": colocated_id is not None,
        "colocated_grid_boundary_id": colocated_id,
        "measured_active_power_w": p,
        "measured_reactive_power_var": q,
        "measured_apparent_power_magnitude_va": math.hypot(p, q) if present else math.nan,
        "measured_active_power_is_zero": p == 0.0 if present else pd.NA,
        "measured_reactive_power_is_zero": q == 0.0 if present else pd.NA,
        "measurement_reference_plane": state.reference_plane if state is not None else "",
        "active_power_sign_convention": meter.active_power_sign_convention,
        "reactive_power_sign_convention": meter.reactive_power_sign_convention,
        "power_basis": meter.power_basis,
        "measurement_value_basis": state.measurement_value_basis if state is not None else "",
        "measurement_time_semantics": (
            state.measurement_time_semantics if state is not None else ""
        ),
        "averaging_interval_seconds": (
            state.averaging_interval_seconds
            if state is not None and state.averaging_interval_seconds is not None
            else math.nan
        ),
        "parameter_source": state.parameter_source if state is not None else "",
        "confidence": state.confidence if state is not None else "",
        "revenue_meter_measurement_authority_state": (
            "resolved_explicit_revenue_meter_measured_power_state"
            if present
            else "unresolved_missing_revenue_meter_measured_power_state"
        ),
        "mv_hv_network_authority_contract": MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
        "mv_hv_network_authority_model": MV_HV_NETWORK_AUTHORITY_MODEL_ID,
        "revenue_meter_measurement_authority_contract": (
            REVENUE_METER_MEASUREMENT_AUTHORITY_CONTRACT_ID
        ),
        "revenue_meter_measurement_authority_model": (
            REVENUE_METER_MEASUREMENT_AUTHORITY_MODEL_ID
        ),
        "revenue_meter_measurement_authority_scope": (
            REVENUE_METER_MEASUREMENT_AUTHORITY_SCOPE
        ),
        "revenue_meter_measurement_authority_coverage_scope": (
            REVENUE_METER_MEASUREMENT_AUTHORITY_COVERAGE_SCOPE
        ),
    }


def _apply_dtypes(frame: pd.DataFrame) -> None:
    for column in _BOOL_COLUMNS:
        frame[column] = frame[column].astype("bool")
    for column in _FLOAT_COLUMNS:
        frame[column] = frame[column].astype("float64")
    for column in _NULLABLE_BOOL_COLUMNS:
        frame[column] = frame[column].astype("boolean")
    for column in set(_COLUMNS) - _BOOL_COLUMNS - _FLOAT_COLUMNS - _NULLABLE_BOOL_COLUMNS:
        frame[column] = frame[column].astype("object")


def _frame(
    keys: tuple[tuple[pd.Timestamp, str], ...], records: list[dict[str, object]]
) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(keys, names=["timestamp", "revenue_meter_id"])
    frame = pd.DataFrame.from_records(records, columns=_COLUMNS, index=index)
    frame.index = index
    _apply_dtypes(frame)
    return frame


def _diagnostics(
    parent: TopologyMvHvNetworkAuthorityResult,
    meter_ids: tuple[str, ...],
    timestamps: tuple[pd.Timestamp, ...],
    admitted: Mapping[tuple[pd.Timestamp, str], RevenueMeterMeasuredPowerState],
) -> TopologyRevenueMeterMeasurementAuthorityDiagnostics:
    rows = len(meter_ids) * len(timestamps)
    values = tuple(admitted.values())
    colocated_nodes = set(_grid_by_node(parent))
    colocated_count = sum(
        parent.revenue_meter_boundary_by_id[meter_id].node_id in colocated_nodes
        for meter_id in meter_ids
    )
    return TopologyRevenueMeterMeasurementAuthorityDiagnostics(
        len(meter_ids),
        len({meter_id for _, meter_id in admitted}),
        len(timestamps),
        rows,
        len(values),
        rows - len(values),
        len(values),
        rows - len(values),
        sum(value.measurement_time_semantics == "instantaneous_snapshot" for value in values),
        sum(
            value.measurement_time_semantics == "interval_average_ending_at_timestamp"
            for value in values
        ),
        sum(value.active_power_w > 0.0 for value in values),
        sum(value.active_power_w < 0.0 for value in values),
        sum(value.active_power_w == 0.0 for value in values),
        sum(value.reactive_power_var > 0.0 for value in values),
        sum(value.reactive_power_var < 0.0 for value in values),
        sum(value.reactive_power_var == 0.0 for value in values),
        colocated_count,
        0 if parent.network_basis is not None else rows,
        REVENUE_METER_MEASUREMENT_AUTHORITY_MODEL_ID,
    )


def resolve_topology_revenue_meter_measurement_authority(
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
    revenue_meter_measured_power_by_key: Mapping[
        tuple[pd.Timestamp, str], RevenueMeterMeasuredPowerState
    ],
) -> TopologyRevenueMeterMeasurementAuthorityResult:
    """Resolve explicit timestamped revenue-meter measured P/Q evidence."""

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
    admitted = _admit_mapping(revenue_meter_measured_power_by_key, canonical)
    meter_ids = tuple(canonical.revenue_meter_boundary_by_id)
    timestamps = _timestamps(admitted)
    keys = tuple((timestamp, meter_id) for timestamp in timestamps for meter_id in meter_ids)
    canonical_states = {key: admitted[key] for key in keys if key in admitted}
    records = [
        _record(canonical, meter_id, canonical_states.get((timestamp, meter_id)))
        for timestamp, meter_id in keys
    ]
    result = TopologyRevenueMeterMeasurementAuthorityResult(
        MappingProxyType(dict(canonical_states)),
        _frame(keys, records).copy(deep=True),
        _diagnostics(canonical, meter_ids, timestamps, canonical_states),
    )
    _validate_result(canonical, result)
    return result


# Validator construction deliberately duplicates S13D logic and never calls
# or captures production record, frame, or diagnostics builders.
def _validator_record(
    parent: TopologyMvHvNetworkAuthorityResult,
    meter_id: str,
    state: RevenueMeterMeasuredPowerState | None,
) -> dict[str, object]:
    meter = parent.revenue_meter_boundary_by_id[meter_id]
    node = parent.nodes_by_id[meter.node_id]
    colocated = {
        grid.node_id: identifier for identifier, grid in parent.grid_boundary_by_id.items()
    }.get(meter.node_id)
    present = state is not None
    p = state.active_power_w if state is not None else math.nan
    q = state.reactive_power_var if state is not None else math.nan
    return {
        "network_basis_resolved": parent.network_basis is not None,
        "measured_power_state_present": present,
        "measured_power_authority_resolved": present,
        "revenue_meter_node_id": meter.node_id,
        "revenue_meter_node_kind": node.node_kind,
        "revenue_meter_reference_plane": meter.reference_plane,
        "revenue_meter_colocated_with_grid_boundary": colocated is not None,
        "colocated_grid_boundary_id": colocated,
        "measured_active_power_w": p,
        "measured_reactive_power_var": q,
        "measured_apparent_power_magnitude_va": math.hypot(p, q) if present else math.nan,
        "measured_active_power_is_zero": p == 0.0 if present else pd.NA,
        "measured_reactive_power_is_zero": q == 0.0 if present else pd.NA,
        "measurement_reference_plane": state.reference_plane if state is not None else "",
        "active_power_sign_convention": meter.active_power_sign_convention,
        "reactive_power_sign_convention": meter.reactive_power_sign_convention,
        "power_basis": meter.power_basis,
        "measurement_value_basis": state.measurement_value_basis if state is not None else "",
        "measurement_time_semantics": (
            state.measurement_time_semantics if state is not None else ""
        ),
        "averaging_interval_seconds": (
            state.averaging_interval_seconds
            if state is not None and state.averaging_interval_seconds is not None
            else math.nan
        ),
        "parameter_source": state.parameter_source if state is not None else "",
        "confidence": state.confidence if state is not None else "",
        "revenue_meter_measurement_authority_state": (
            "resolved_explicit_revenue_meter_measured_power_state"
            if present
            else "unresolved_missing_revenue_meter_measured_power_state"
        ),
        "mv_hv_network_authority_contract": MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
        "mv_hv_network_authority_model": MV_HV_NETWORK_AUTHORITY_MODEL_ID,
        "revenue_meter_measurement_authority_contract": (
            REVENUE_METER_MEASUREMENT_AUTHORITY_CONTRACT_ID
        ),
        "revenue_meter_measurement_authority_model": (
            REVENUE_METER_MEASUREMENT_AUTHORITY_MODEL_ID
        ),
        "revenue_meter_measurement_authority_scope": (
            REVENUE_METER_MEASUREMENT_AUTHORITY_SCOPE
        ),
        "revenue_meter_measurement_authority_coverage_scope": (
            REVENUE_METER_MEASUREMENT_AUTHORITY_COVERAGE_SCOPE
        ),
    }


def _validator_frame(
    keys: tuple[tuple[pd.Timestamp, str], ...], records: list[dict[str, object]]
) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(keys, names=["timestamp", "revenue_meter_id"])
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
    parent: TopologyMvHvNetworkAuthorityResult,
    meter_ids: tuple[str, ...],
    timestamps: tuple[pd.Timestamp, ...],
    admitted: Mapping[tuple[pd.Timestamp, str], RevenueMeterMeasuredPowerState],
) -> TopologyRevenueMeterMeasurementAuthorityDiagnostics:
    rows = len(meter_ids) * len(timestamps)
    values = tuple(admitted.values())
    grid_nodes = {grid.node_id for grid in parent.grid_boundary_by_id.values()}
    return TopologyRevenueMeterMeasurementAuthorityDiagnostics(
        len(meter_ids),
        len({meter_id for _, meter_id in admitted}),
        len(timestamps),
        rows,
        len(values),
        rows - len(values),
        len(values),
        rows - len(values),
        sum(value.measurement_time_semantics == "instantaneous_snapshot" for value in values),
        sum(
            value.measurement_time_semantics == "interval_average_ending_at_timestamp"
            for value in values
        ),
        sum(value.active_power_w > 0.0 for value in values),
        sum(value.active_power_w < 0.0 for value in values),
        sum(value.active_power_w == 0.0 for value in values),
        sum(value.reactive_power_var > 0.0 for value in values),
        sum(value.reactive_power_var < 0.0 for value in values),
        sum(value.reactive_power_var == 0.0 for value in values),
        sum(
            parent.revenue_meter_boundary_by_id[meter_id].node_id in grid_nodes
            for meter_id in meter_ids
        ),
        0 if parent.network_basis is not None else rows,
        REVENUE_METER_MEASUREMENT_AUTHORITY_MODEL_ID,
    )


def _validate_result(
    canonical: TopologyMvHvNetworkAuthorityResult,
    result: TopologyRevenueMeterMeasurementAuthorityResult,
) -> None:
    """Independently reconstruct and close the complete S13D result."""

    if type(result) is not TopologyRevenueMeterMeasurementAuthorityResult:
        raise RuntimeError("S13D result type is invalid")
    if type(result.measured_power_states_by_key) is not MappingProxyType:
        raise RuntimeError("S13D measured-power mapping must be immutable")
    meter_ids = tuple(canonical.revenue_meter_boundary_by_id)
    for key, state in result.measured_power_states_by_key.items():
        if type(key) is not tuple or len(key) != 2:
            raise RuntimeError("S13D result mapping key is invalid")
        timestamp, meter_id = key
        if type(timestamp) is not pd.Timestamp or pd.isna(timestamp):
            raise RuntimeError("S13D result timestamp is invalid")
        if type(meter_id) is not str or meter_id not in meter_ids:
            raise RuntimeError("S13D result meter identity is invalid")
        if type(state) is not RevenueMeterMeasuredPowerState:
            raise RuntimeError("S13D result authority type is invalid")
        meter = canonical.revenue_meter_boundary_by_id[meter_id]
        if (
            state.reference_plane != meter.reference_plane
            or state.active_power_sign_convention != meter.active_power_sign_convention
            or state.reactive_power_sign_convention != meter.reactive_power_sign_convention
            or state.power_basis != meter.power_basis
        ):
            raise RuntimeError("S13D result meter semantics failed exact closure")
    timestamps = _timestamps(result.measured_power_states_by_key)
    keys = tuple((timestamp, meter_id) for timestamp in timestamps for meter_id in meter_ids)
    if tuple(result.measured_power_states_by_key) != tuple(
        key for key in keys if key in result.measured_power_states_by_key
    ):
        raise RuntimeError("S13D measured-power mapping order failed exact closure")
    expected = _validator_frame(
        keys,
        [
            _validator_record(
                canonical,
                meter_id,
                result.measured_power_states_by_key.get((timestamp, meter_id)),
            )
            for timestamp, meter_id in keys
        ],
    )
    try:
        pd.testing.assert_frame_equal(result.states, expected, check_exact=True)
    except AssertionError as error:
        raise RuntimeError("S13D state frame failed independent exact closure") from error
    diagnostics = _validator_diagnostics(
        canonical, meter_ids, timestamps, result.measured_power_states_by_key
    )
    if result.diagnostics != diagnostics:
        raise RuntimeError("S13D diagnostics failed independent exact closure")
