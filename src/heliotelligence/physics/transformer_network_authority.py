"""Static transformer positive-sequence network authority.

S12E admits an explicit fixed voltage transfer and factory short-circuit
impedance magnitude. It performs no operating solve and deliberately admits no
independent resistance, reactance, active-loss, or excitation model.
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

TRANSFORMER_NETWORK_AUTHORITY_CONTRACT_ID = (
    "admitted_transformer_static_authority_to_positive_sequence_"
    "transfer_and_short_circuit_impedance_authority_v1"
)
TRANSFORMER_NETWORK_AUTHORITY_MODEL_ID = (
    "explicit_fixed_positive_sequence_voltage_transfer_and_"
    "factory_short_circuit_impedance_authority_v1"
)
TRANSFORMER_NETWORK_AUTHORITY_SCOPE = (
    "static_transformer_positive_sequence_network_authority_before_"
    "excitation_and_terminal_operating_solve"
)
TRANSFORMER_NETWORK_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_fixed_voltage_ratio_phase_displacement_and_short_circuit_impedance_magnitude"
)

Confidence = Literal["high", "medium", "low", "unknown"]
_CONFIDENCES = {"high", "medium", "low", "unknown"}
_ABSOLUTE_ZERO_C = -273.15
_COLUMNS = (
    "transformer_equipment_authority_present",
    "transformer_topology_authority_present",
    "transformer_static_authority_resolved",
    "transformer_voltage_transfer_authority_present",
    "transformer_short_circuit_impedance_authority_present",
    "transformer_positive_sequence_network_authority_resolved",
    "phase_sequence",
    "collection_voltage_basis",
    "network_voltage_basis",
    "ratio_state_semantics",
    "ratio_semantics",
    "network_to_collection_voltage_ratio",
    "phase_displacement_semantics",
    "network_side_phase_displacement_deg",
    "short_circuit_impedance_semantics",
    "short_circuit_impedance_basis",
    "short_circuit_impedance_magnitude_pu",
    "short_circuit_test_current_condition",
    "short_circuit_reference_temperature_c",
    "short_circuit_test_frequency_hz",
    "voltage_transfer_parameter_source",
    "voltage_transfer_confidence",
    "short_circuit_impedance_parameter_source",
    "short_circuit_impedance_confidence",
    "transformer_network_authority_state",
    "transformer_static_authority_contract",
    "transformer_static_authority_model",
    "transformer_network_authority_contract",
    "transformer_network_authority_model",
    "transformer_network_authority_scope",
    "transformer_network_authority_coverage_scope",
)
_BOOL_COLUMNS = {
    "transformer_equipment_authority_present",
    "transformer_topology_authority_present",
    "transformer_static_authority_resolved",
    "transformer_voltage_transfer_authority_present",
    "transformer_short_circuit_impedance_authority_present",
    "transformer_positive_sequence_network_authority_resolved",
}
_FLOAT_COLUMNS = {
    "network_to_collection_voltage_ratio",
    "network_side_phase_displacement_deg",
    "short_circuit_impedance_magnitude_pu",
    "short_circuit_reference_temperature_c",
    "short_circuit_test_frequency_hz",
}


class _NetworkAuthority(Protocol):
    @property
    def transformer_id(self) -> str: ...


_AuthorityT = TypeVar("_AuthorityT", bound=_NetworkAuthority)


def _identifier(value: object, name: str = "transformer_id") -> str:
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


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real non-Boolean number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _positive(value: object, name: str) -> float:
    normalized = _finite(value, name)
    if normalized <= 0.0:
        raise ValueError(f"{name} must be strictly positive")
    return normalized


@dataclass(frozen=True)
class TransformerVoltageTransferAuthority:
    transformer_id: str
    phase_sequence: Literal["positive_sequence"]
    collection_voltage_basis: Literal["line_to_line_rms"]
    network_voltage_basis: Literal["line_to_line_rms"]
    ratio_state_semantics: Literal["fixed_effective_no_load_ratio"]
    ratio_semantics: Literal["network_to_collection_line_to_line_voltage_magnitude_ratio"]
    network_to_collection_voltage_ratio: float
    phase_displacement_semantics: Literal[
        "network_side_positive_sequence_voltage_leads_collection_side_positive_deg"
    ]
    network_side_phase_displacement_deg: float
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _validate_transfer(self)
        object.__setattr__(
            self,
            "network_to_collection_voltage_ratio",
            _positive(
                self.network_to_collection_voltage_ratio, "network_to_collection_voltage_ratio"
            ),
        )
        object.__setattr__(
            self,
            "network_side_phase_displacement_deg",
            _finite(
                self.network_side_phase_displacement_deg, "network_side_phase_displacement_deg"
            ),
        )


@dataclass(frozen=True)
class TransformerShortCircuitImpedanceAuthority:
    transformer_id: str
    phase_sequence: Literal["positive_sequence"]
    impedance_semantics: Literal["total_two_winding_series_short_circuit_impedance_magnitude"]
    impedance_basis: Literal[
        "per_unit_on_s12a_rated_apparent_power_and_corresponding_rated_terminal_voltage_bases"
    ]
    short_circuit_impedance_magnitude_pu: float
    test_current_condition: Literal["rated_current"]
    reference_temperature_c: float
    test_frequency_hz: float
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _validate_impedance(self)
        object.__setattr__(
            self,
            "short_circuit_impedance_magnitude_pu",
            _positive(
                self.short_circuit_impedance_magnitude_pu, "short_circuit_impedance_magnitude_pu"
            ),
        )
        object.__setattr__(
            self,
            "reference_temperature_c",
            _finite(self.reference_temperature_c, "reference_temperature_c"),
        )
        object.__setattr__(
            self, "test_frequency_hz", _positive(self.test_frequency_hz, "test_frequency_hz")
        )


@dataclass(frozen=True)
class TopologyTransformerNetworkAuthorityDiagnostics:
    transformer_count: int
    equipment_authority_present_count: int
    topology_authority_present_count: int
    static_authority_resolved_count: int
    voltage_transfer_authority_count: int
    short_circuit_impedance_authority_count: int
    positive_sequence_network_authority_resolved_count: int
    unresolved_missing_equipment_basis_count: int
    unresolved_missing_voltage_transfer_count: int
    unresolved_missing_short_circuit_impedance_count: int
    model: str


@dataclass(frozen=True)
class TopologyTransformerNetworkAuthorityResult:
    voltage_transfer_by_id: Mapping[str, TransformerVoltageTransferAuthority]
    short_circuit_impedance_by_id: Mapping[str, TransformerShortCircuitImpedanceAuthority]
    transformer_states: pd.DataFrame
    diagnostics: TopologyTransformerNetworkAuthorityDiagnostics


def resolve_transformer_network_authority(
    topology: ElectricalTopologyConfig,
    network_basis: LvAcCollectionNetworkBasisAuthority | None,
    node_authority_by_id: Mapping[str, LvAcCollectionNodeAuthority],
    segment_authority_by_id: Mapping[str, LvAcCollectionSegmentAuthority],
    inverter_terminal_binding_by_inverter_id: Mapping[str, LvAcInverterTerminalBindingAuthority],
    lv_ac_collection_authority: TopologyLvAcCollectionAuthorityResult,
    transformer_equipment_by_id: Mapping[str, TransformerStaticEquipmentAuthority],
    transformer_topology_by_id: Mapping[str, TransformerBoundaryTopologyAuthority],
    transformer_static_authority: TopologyTransformerStaticAuthorityResult,
    transformer_voltage_transfer_by_id: Mapping[str, TransformerVoltageTransferAuthority],
    transformer_short_circuit_impedance_by_id: Mapping[
        str, TransformerShortCircuitImpedanceAuthority
    ],
) -> TopologyTransformerNetworkAuthorityResult:
    """Admit explicit fixed positive-sequence transformer network evidence."""
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
    _validate_parent_replay(transformer_static_authority, canonical)
    transformer_ids = canonical.transformer_states.index.tolist()
    known_ids = set(transformer_ids)
    transfer = _admit_mapping(
        transformer_voltage_transfer_by_id,
        TransformerVoltageTransferAuthority,
        known_ids,
        "voltage transfer",
    )
    impedance = _admit_mapping(
        transformer_short_circuit_impedance_by_id,
        TransformerShortCircuitImpedanceAuthority,
        known_ids,
        "short-circuit impedance",
    )
    records = [
        _record(
            canonical.transformer_states.loc[transformer_id],
            transfer.get(transformer_id),
            impedance.get(transformer_id),
        )
        for transformer_id in transformer_ids
    ]
    states = _state_frame(transformer_ids, records)
    diagnostics = _diagnostics(states, transfer, impedance)
    result = TopologyTransformerNetworkAuthorityResult(
        MappingProxyType(dict(transfer)),
        MappingProxyType(dict(impedance)),
        states.copy(deep=True),
        diagnostics,
    )
    _validate_result(canonical, result)
    return result


def _validate_transfer(authority: TransformerVoltageTransferAuthority) -> None:
    _identifier(authority.transformer_id)
    if authority.phase_sequence != "positive_sequence":
        raise ValueError("phase_sequence must be positive_sequence")
    if authority.collection_voltage_basis != "line_to_line_rms":
        raise ValueError("collection_voltage_basis must be line_to_line_rms")
    if authority.network_voltage_basis != "line_to_line_rms":
        raise ValueError("network_voltage_basis must be line_to_line_rms")
    if authority.ratio_state_semantics != "fixed_effective_no_load_ratio":
        raise ValueError("ratio_state_semantics is unsupported")
    if authority.ratio_semantics != "network_to_collection_line_to_line_voltage_magnitude_ratio":
        raise ValueError("ratio_semantics is unsupported")
    _positive(authority.network_to_collection_voltage_ratio, "network_to_collection_voltage_ratio")
    if (
        authority.phase_displacement_semantics
        != "network_side_positive_sequence_voltage_leads_collection_side_positive_deg"
    ):
        raise ValueError("phase_displacement_semantics is unsupported")
    displacement = _finite(
        authority.network_side_phase_displacement_deg, "network_side_phase_displacement_deg"
    )
    if displacement < -180.0 or displacement >= 180.0:
        raise ValueError("network_side_phase_displacement_deg must be in [-180, 180)")
    _source(authority.parameter_source)
    _confidence(authority.confidence)


def _validate_impedance(authority: TransformerShortCircuitImpedanceAuthority) -> None:
    _identifier(authority.transformer_id)
    if authority.phase_sequence != "positive_sequence":
        raise ValueError("phase_sequence must be positive_sequence")
    if (
        authority.impedance_semantics
        != "total_two_winding_series_short_circuit_impedance_magnitude"
    ):
        raise ValueError("impedance_semantics is unsupported")
    if (
        authority.impedance_basis
        != "per_unit_on_s12a_rated_apparent_power_and_corresponding_rated_terminal_voltage_bases"
    ):
        raise ValueError("impedance_basis is unsupported")
    _positive(
        authority.short_circuit_impedance_magnitude_pu, "short_circuit_impedance_magnitude_pu"
    )
    if authority.test_current_condition != "rated_current":
        raise ValueError("test_current_condition must be rated_current")
    temperature = _finite(authority.reference_temperature_c, "reference_temperature_c")
    if temperature <= _ABSOLUTE_ZERO_C:
        raise ValueError("reference_temperature_c must be greater than absolute zero")
    _positive(authority.test_frequency_hz, "test_frequency_hz")
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
        actual, expected = getattr(supplied, name), getattr(canonical, name)
        if type(actual).__name__ != "mappingproxy" or dict(actual) != dict(expected):
            raise ValueError(f"supplied S12A {name} does not match immutable canonical replay")
    try:
        pd.testing.assert_frame_equal(
            supplied.transformer_states, canonical.transformer_states, check_exact=True
        )
    except AssertionError as error:
        raise ValueError(
            "supplied S12A transformer states do not match canonical replay"
        ) from error
    if supplied.diagnostics != canonical.diagnostics:
        raise ValueError("supplied S12A diagnostics do not match canonical replay")


def _state(equipment: bool, transfer: bool, impedance: bool) -> str:
    if not equipment:
        return "unresolved_missing_transformer_equipment_basis_authority"
    if not transfer:
        return "unresolved_missing_transformer_voltage_transfer_authority"
    if not impedance:
        return "unresolved_missing_transformer_short_circuit_impedance_authority"
    return "resolved_transformer_positive_sequence_network_authority"


def _record(
    static_row: pd.Series,
    transfer: TransformerVoltageTransferAuthority | None,
    impedance: TransformerShortCircuitImpedanceAuthority | None,
) -> dict[str, object]:
    equipment = bool(static_row["transformer_equipment_authority_present"])
    topology = bool(static_row["transformer_topology_authority_present"])
    transfer_present = transfer is not None
    impedance_present = impedance is not None
    return {
        "transformer_equipment_authority_present": equipment,
        "transformer_topology_authority_present": topology,
        "transformer_static_authority_resolved": bool(
            static_row["transformer_static_authority_resolved"]
        ),
        "transformer_voltage_transfer_authority_present": transfer_present,
        "transformer_short_circuit_impedance_authority_present": impedance_present,
        "transformer_positive_sequence_network_authority_resolved": equipment
        and transfer_present
        and impedance_present,
        "phase_sequence": transfer.phase_sequence if transfer else "",
        "collection_voltage_basis": transfer.collection_voltage_basis if transfer else "",
        "network_voltage_basis": transfer.network_voltage_basis if transfer else "",
        "ratio_state_semantics": transfer.ratio_state_semantics if transfer else "",
        "ratio_semantics": transfer.ratio_semantics if transfer else "",
        "network_to_collection_voltage_ratio": transfer.network_to_collection_voltage_ratio
        if transfer
        else math.nan,
        "phase_displacement_semantics": transfer.phase_displacement_semantics if transfer else "",
        "network_side_phase_displacement_deg": transfer.network_side_phase_displacement_deg
        if transfer
        else math.nan,
        "short_circuit_impedance_semantics": impedance.impedance_semantics if impedance else "",
        "short_circuit_impedance_basis": impedance.impedance_basis if impedance else "",
        "short_circuit_impedance_magnitude_pu": impedance.short_circuit_impedance_magnitude_pu
        if impedance
        else math.nan,
        "short_circuit_test_current_condition": impedance.test_current_condition
        if impedance
        else "",
        "short_circuit_reference_temperature_c": impedance.reference_temperature_c
        if impedance
        else math.nan,
        "short_circuit_test_frequency_hz": impedance.test_frequency_hz if impedance else math.nan,
        "voltage_transfer_parameter_source": transfer.parameter_source if transfer else "",
        "voltage_transfer_confidence": transfer.confidence if transfer else "",
        "short_circuit_impedance_parameter_source": impedance.parameter_source if impedance else "",
        "short_circuit_impedance_confidence": impedance.confidence if impedance else "",
        "transformer_network_authority_state": _state(
            equipment, transfer_present, impedance_present
        ),
        "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
        "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
        "transformer_network_authority_contract": TRANSFORMER_NETWORK_AUTHORITY_CONTRACT_ID,
        "transformer_network_authority_model": TRANSFORMER_NETWORK_AUTHORITY_MODEL_ID,
        "transformer_network_authority_scope": TRANSFORMER_NETWORK_AUTHORITY_SCOPE,
        "transformer_network_authority_coverage_scope": (
            TRANSFORMER_NETWORK_AUTHORITY_COVERAGE_SCOPE
        ),
    }


def _state_frame(transformer_ids: list[str], records: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        records, index=pd.Index(transformer_ids, name="transformer_id", dtype=object)
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
    transfer: Mapping[str, TransformerVoltageTransferAuthority],
    impedance: Mapping[str, TransformerShortCircuitImpedanceAuthority],
) -> TopologyTransformerNetworkAuthorityDiagnostics:
    counts = states["transformer_network_authority_state"].value_counts()
    return TopologyTransformerNetworkAuthorityDiagnostics(
        len(states),
        int(states["transformer_equipment_authority_present"].sum()),
        int(states["transformer_topology_authority_present"].sum()),
        int(states["transformer_static_authority_resolved"].sum()),
        len(transfer),
        len(impedance),
        int(counts.get("resolved_transformer_positive_sequence_network_authority", 0)),
        int(counts.get("unresolved_missing_transformer_equipment_basis_authority", 0)),
        int(counts.get("unresolved_missing_transformer_voltage_transfer_authority", 0)),
        int(counts.get("unresolved_missing_transformer_short_circuit_impedance_authority", 0)),
        TRANSFORMER_NETWORK_AUTHORITY_MODEL_ID,
    )


def _equal(actual: object, expected: object) -> bool:
    if isinstance(expected, float) and math.isnan(expected):
        return bool(pd.isna(actual))
    return bool(actual == expected)


def _validator_record(
    static_row: pd.Series,
    transfer: TransformerVoltageTransferAuthority | None,
    impedance: TransformerShortCircuitImpedanceAuthority | None,
) -> dict[str, object]:
    """Reconstruct an expected row independently of the production builder."""
    equipment = bool(static_row["transformer_equipment_authority_present"])
    topology = bool(static_row["transformer_topology_authority_present"])
    static_resolved = bool(static_row["transformer_static_authority_resolved"])
    transfer_present = transfer is not None
    impedance_present = impedance is not None
    state = (
        "unresolved_missing_transformer_equipment_basis_authority"
        if not equipment
        else "unresolved_missing_transformer_voltage_transfer_authority"
        if not transfer_present
        else "unresolved_missing_transformer_short_circuit_impedance_authority"
        if not impedance_present
        else "resolved_transformer_positive_sequence_network_authority"
    )
    return {
        "transformer_equipment_authority_present": equipment,
        "transformer_topology_authority_present": topology,
        "transformer_static_authority_resolved": static_resolved,
        "transformer_voltage_transfer_authority_present": transfer_present,
        "transformer_short_circuit_impedance_authority_present": impedance_present,
        "transformer_positive_sequence_network_authority_resolved": (
            equipment and transfer_present and impedance_present
        ),
        "phase_sequence": transfer.phase_sequence if transfer else "",
        "collection_voltage_basis": transfer.collection_voltage_basis if transfer else "",
        "network_voltage_basis": transfer.network_voltage_basis if transfer else "",
        "ratio_state_semantics": transfer.ratio_state_semantics if transfer else "",
        "ratio_semantics": transfer.ratio_semantics if transfer else "",
        "network_to_collection_voltage_ratio": (
            transfer.network_to_collection_voltage_ratio if transfer else math.nan
        ),
        "phase_displacement_semantics": (transfer.phase_displacement_semantics if transfer else ""),
        "network_side_phase_displacement_deg": (
            transfer.network_side_phase_displacement_deg if transfer else math.nan
        ),
        "short_circuit_impedance_semantics": (impedance.impedance_semantics if impedance else ""),
        "short_circuit_impedance_basis": impedance.impedance_basis if impedance else "",
        "short_circuit_impedance_magnitude_pu": (
            impedance.short_circuit_impedance_magnitude_pu if impedance else math.nan
        ),
        "short_circuit_test_current_condition": (
            impedance.test_current_condition if impedance else ""
        ),
        "short_circuit_reference_temperature_c": (
            impedance.reference_temperature_c if impedance else math.nan
        ),
        "short_circuit_test_frequency_hz": (impedance.test_frequency_hz if impedance else math.nan),
        "voltage_transfer_parameter_source": transfer.parameter_source if transfer else "",
        "voltage_transfer_confidence": transfer.confidence if transfer else "",
        "short_circuit_impedance_parameter_source": (
            impedance.parameter_source if impedance else ""
        ),
        "short_circuit_impedance_confidence": impedance.confidence if impedance else "",
        "transformer_network_authority_state": state,
        "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
        "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
        "transformer_network_authority_contract": TRANSFORMER_NETWORK_AUTHORITY_CONTRACT_ID,
        "transformer_network_authority_model": TRANSFORMER_NETWORK_AUTHORITY_MODEL_ID,
        "transformer_network_authority_scope": TRANSFORMER_NETWORK_AUTHORITY_SCOPE,
        "transformer_network_authority_coverage_scope": (
            TRANSFORMER_NETWORK_AUTHORITY_COVERAGE_SCOPE
        ),
    }


def _validate_result(
    static: TopologyTransformerStaticAuthorityResult,
    result: TopologyTransformerNetworkAuthorityResult,
) -> None:
    if type(result) is not TopologyTransformerNetworkAuthorityResult:
        raise RuntimeError("transformer network authority result type is invalid")
    if (
        type(result.voltage_transfer_by_id).__name__ != "mappingproxy"
        or type(result.short_circuit_impedance_by_id).__name__ != "mappingproxy"
    ):
        raise RuntimeError("transformer network authority result mappings must be immutable")
    ids = static.transformer_states.index.tolist()
    known = set(ids)
    for key, transfer_authority in result.voltage_transfer_by_id.items():
        if (
            type(transfer_authority) is not TransformerVoltageTransferAuthority
            or key != transfer_authority.transformer_id
            or key not in known
        ):
            raise RuntimeError("transformer voltage transfer mapping closure is invalid")
        try:
            _validate_transfer(transfer_authority)
        except ValueError as error:
            raise RuntimeError("transformer voltage transfer domain is invalid") from error
    for key, impedance_authority in result.short_circuit_impedance_by_id.items():
        if (
            type(impedance_authority) is not TransformerShortCircuitImpedanceAuthority
            or key != impedance_authority.transformer_id
            or key not in known
        ):
            raise RuntimeError("transformer short-circuit impedance mapping closure is invalid")
        try:
            _validate_impedance(impedance_authority)
        except ValueError as error:
            raise RuntimeError("transformer short-circuit impedance domain is invalid") from error
    states = result.transformer_states
    if (
        tuple(states.columns) != _COLUMNS
        or states.index.name != "transformer_id"
        or states.index.has_duplicates
        or states.index.tolist() != ids
    ):
        raise RuntimeError("transformer network state schema/index/order is invalid")
    for column in _COLUMNS:
        dtype = (
            "bool"
            if column in _BOOL_COLUMNS
            else "float64"
            if column in _FLOAT_COLUMNS
            else "object"
        )
        if str(states[column].dtype) != dtype:
            raise RuntimeError(f"transformer network dtype is invalid for {column}")
    counts = {
        name: 0
        for name in (
            "resolved_transformer_positive_sequence_network_authority",
            "unresolved_missing_transformer_equipment_basis_authority",
            "unresolved_missing_transformer_voltage_transfer_authority",
            "unresolved_missing_transformer_short_circuit_impedance_authority",
        )
    }
    for transformer_id, row in states.iterrows():
        static_row = static.transformer_states.loc[transformer_id]
        transfer = result.voltage_transfer_by_id.get(transformer_id)
        impedance = result.short_circuit_impedance_by_id.get(transformer_id)
        expected = _validator_record(static_row, transfer, impedance)
        state = _state(
            bool(static_row["transformer_equipment_authority_present"]),
            transfer is not None,
            impedance is not None,
        )
        counts[state] += 1
        for column, value in expected.items():
            if not _equal(row[column], value):
                raise RuntimeError(f"transformer network row failed closure for {column}")
    expected_diagnostics = TopologyTransformerNetworkAuthorityDiagnostics(
        len(ids),
        int(static.transformer_states["transformer_equipment_authority_present"].sum()),
        int(static.transformer_states["transformer_topology_authority_present"].sum()),
        int(static.transformer_states["transformer_static_authority_resolved"].sum()),
        len(result.voltage_transfer_by_id),
        len(result.short_circuit_impedance_by_id),
        counts["resolved_transformer_positive_sequence_network_authority"],
        counts["unresolved_missing_transformer_equipment_basis_authority"],
        counts["unresolved_missing_transformer_voltage_transfer_authority"],
        counts["unresolved_missing_transformer_short_circuit_impedance_authority"],
        TRANSFORMER_NETWORK_AUTHORITY_MODEL_ID,
    )
    if result.diagnostics != expected_diagnostics:
        raise RuntimeError("transformer network diagnostics failed exact closure")
    diagnostics = result.diagnostics
    if (
        diagnostics.positive_sequence_network_authority_resolved_count
        + diagnostics.unresolved_missing_equipment_basis_count
        + diagnostics.unresolved_missing_voltage_transfer_count
        + diagnostics.unresolved_missing_short_circuit_impedance_count
        != diagnostics.transformer_count
    ):
        raise RuntimeError("transformer network state diagnostics do not close")
    if (
        diagnostics.voltage_transfer_authority_count != len(result.voltage_transfer_by_id)
        or diagnostics.short_circuit_impedance_authority_count
        != len(result.short_circuit_impedance_by_id)
        or diagnostics.model != TRANSFORMER_NETWORK_AUTHORITY_MODEL_ID
    ):
        raise RuntimeError("transformer network diagnostics domain is invalid")
