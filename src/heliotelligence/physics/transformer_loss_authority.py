"""Explicit transformer factory-test baseline loss authority.

S12B admits transformer-specific no-load and rated total load-loss evidence
with the factory-test conditions needed to interpret it. It performs no
operating loss, temperature correction, loading, energisation, or energy
calculation.
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

TRANSFORMER_LOSS_AUTHORITY_CONTRACT_ID = (
    "admitted_transformer_static_authority_to_explicit_factory_test_loss_authority_v1"
)
TRANSFORMER_LOSS_AUTHORITY_MODEL_ID = (
    "two_parameter_factory_test_no_load_and_rated_load_loss_authority_v1"
)
TRANSFORMER_LOSS_AUTHORITY_SCOPE = (
    "static_transformer_factory_test_loss_authority_before_energisation_"
    "temperature_and_operating_loss_evaluation"
)
TRANSFORMER_LOSS_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_no_load_loss_rated_total_load_loss_and_test_reference_conditions"
)

Confidence = Literal["high", "medium", "low", "unknown"]
TransformerSide = Literal["collection_side", "network_side"]
_CONFIDENCES = {"high", "medium", "low", "unknown"}
_SIDES = {"collection_side", "network_side"}
_ABSOLUTE_ZERO_C = -273.15
_COLUMNS = (
    "transformer_static_authority_resolved",
    "transformer_no_load_loss_authority_present",
    "transformer_rated_load_loss_authority_present",
    "transformer_factory_loss_authority_resolved",
    "no_load_loss_w",
    "no_load_test_reference_side",
    "no_load_test_voltage_condition",
    "no_load_test_voltage_basis",
    "no_load_test_frequency_hz",
    "rated_load_loss_w",
    "load_loss_test_current_reference_side",
    "load_loss_test_current_condition",
    "load_loss_reference_temperature_c",
    "load_loss_test_frequency_hz",
    "load_loss_semantics",
    "no_load_parameter_source",
    "no_load_confidence",
    "rated_load_parameter_source",
    "rated_load_confidence",
    "transformer_loss_authority_state",
    "transformer_static_authority_contract",
    "transformer_static_authority_model",
    "transformer_loss_authority_contract",
    "transformer_loss_authority_model",
    "transformer_loss_authority_scope",
    "transformer_loss_authority_coverage_scope",
)
_BOOL_COLUMNS = {
    "transformer_static_authority_resolved",
    "transformer_no_load_loss_authority_present",
    "transformer_rated_load_loss_authority_present",
    "transformer_factory_loss_authority_resolved",
}
_FLOAT_COLUMNS = {
    "no_load_loss_w",
    "no_load_test_frequency_hz",
    "rated_load_loss_w",
    "load_loss_reference_temperature_c",
    "load_loss_test_frequency_hz",
}


class _LossAuthority(Protocol):
    @property
    def transformer_id(self) -> str: ...


_AuthorityT = TypeVar("_AuthorityT", bound=_LossAuthority)


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


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real non-Boolean number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _nonnegative(value: object, name: str) -> float:
    normalized = _finite(value, name)
    if normalized < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return normalized


def _positive_frequency(value: object) -> float:
    normalized = _finite(value, "test_frequency_hz")
    if normalized <= 0.0:
        raise ValueError("test_frequency_hz must be strictly positive")
    return normalized


@dataclass(frozen=True)
class TransformerNoLoadLossAuthority:
    transformer_id: str
    no_load_loss_w: float
    test_reference_side: TransformerSide
    test_voltage_condition: Literal["rated_terminal_voltage"]
    test_voltage_basis: Literal["line_to_line_rms"]
    test_frequency_hz: float
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _identifier(self.transformer_id, "transformer_id")
        _validate_no_load(self)
        object.__setattr__(
            self, "no_load_loss_w", _nonnegative(self.no_load_loss_w, "no_load_loss_w")
        )
        object.__setattr__(self, "test_frequency_hz", _positive_frequency(self.test_frequency_hz))


@dataclass(frozen=True)
class TransformerRatedLoadLossAuthority:
    transformer_id: str
    rated_load_loss_w: float
    test_current_reference_side: TransformerSide
    test_current_condition: Literal["rated_current"]
    reference_temperature_c: float
    test_frequency_hz: float
    loss_semantics: Literal["total_rated_load_loss_including_winding_and_stray"]
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _identifier(self.transformer_id, "transformer_id")
        _validate_rated_load(self)
        object.__setattr__(
            self,
            "rated_load_loss_w",
            _nonnegative(self.rated_load_loss_w, "rated_load_loss_w"),
        )
        object.__setattr__(
            self,
            "reference_temperature_c",
            _finite(self.reference_temperature_c, "reference_temperature_c"),
        )
        object.__setattr__(self, "test_frequency_hz", _positive_frequency(self.test_frequency_hz))


@dataclass(frozen=True)
class TopologyTransformerLossAuthorityDiagnostics:
    transformer_record_count: int
    static_authority_resolved_count: int
    static_authority_unresolved_count: int
    no_load_loss_authority_count: int
    rated_load_loss_authority_count: int
    factory_loss_authority_resolved_count: int
    unresolved_upstream_static_count: int
    unresolved_missing_no_load_loss_count: int
    unresolved_missing_rated_load_loss_count: int
    model: str


@dataclass(frozen=True)
class TopologyTransformerLossAuthorityResult:
    no_load_loss_by_id: Mapping[str, TransformerNoLoadLossAuthority]
    rated_load_loss_by_id: Mapping[str, TransformerRatedLoadLossAuthority]
    transformer_states: pd.DataFrame
    diagnostics: TopologyTransformerLossAuthorityDiagnostics


def resolve_transformer_loss_authority(
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
) -> TopologyTransformerLossAuthorityResult:
    """Admit transformer-specific factory-test baseline loss evidence."""
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
    no_load = _admit_mapping(
        transformer_no_load_loss_by_id,
        TransformerNoLoadLossAuthority,
        known_ids,
        "no-load loss",
    )
    rated_load = _admit_mapping(
        transformer_rated_load_loss_by_id,
        TransformerRatedLoadLossAuthority,
        known_ids,
        "rated load loss",
    )
    for no_load_authority in no_load.values():
        _validate_no_load(no_load_authority)
    for rated_load_authority in rated_load.values():
        _validate_rated_load(rated_load_authority)
    _validate_frequency_compatibility(no_load, rated_load)
    records = [
        _record(
            bool(
                canonical_static.transformer_states.loc[
                    transformer_id, "transformer_static_authority_resolved"
                ]
            ),
            no_load.get(transformer_id),
            rated_load.get(transformer_id),
        )
        for transformer_id in transformer_ids
    ]
    states = _state_frame(transformer_ids, records)
    diagnostics = _diagnostics(states, no_load, rated_load)
    result = TopologyTransformerLossAuthorityResult(
        no_load_loss_by_id=MappingProxyType(dict(no_load)),
        rated_load_loss_by_id=MappingProxyType(dict(rated_load)),
        transformer_states=states.copy(deep=True),
        diagnostics=diagnostics,
    )
    _validate_result(canonical_static, result)
    return result


def _validate_no_load(authority: TransformerNoLoadLossAuthority) -> None:
    _identifier(authority.transformer_id, "transformer_id")
    _nonnegative(authority.no_load_loss_w, "no_load_loss_w")
    if (
        type(authority.test_reference_side) is not str
        or authority.test_reference_side not in _SIDES
    ):
        raise ValueError("test_reference_side is unsupported")
    if authority.test_voltage_condition != "rated_terminal_voltage":
        raise ValueError("test_voltage_condition must be rated_terminal_voltage")
    if authority.test_voltage_basis != "line_to_line_rms":
        raise ValueError("test_voltage_basis must be line_to_line_rms")
    _positive_frequency(authority.test_frequency_hz)
    _source(authority.parameter_source)
    _confidence(authority.confidence)


def _validate_rated_load(authority: TransformerRatedLoadLossAuthority) -> None:
    _identifier(authority.transformer_id, "transformer_id")
    _nonnegative(authority.rated_load_loss_w, "rated_load_loss_w")
    if (
        type(authority.test_current_reference_side) is not str
        or authority.test_current_reference_side not in _SIDES
    ):
        raise ValueError("test_current_reference_side is unsupported")
    if authority.test_current_condition != "rated_current":
        raise ValueError("test_current_condition must be rated_current")
    temperature = _finite(authority.reference_temperature_c, "reference_temperature_c")
    if temperature <= _ABSOLUTE_ZERO_C:
        raise ValueError("reference_temperature_c must be greater than absolute zero")
    _positive_frequency(authority.test_frequency_hz)
    if authority.loss_semantics != "total_rated_load_loss_including_winding_and_stray":
        raise ValueError("loss_semantics is unsupported")
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


def _validate_frequency_compatibility(
    no_load: Mapping[str, TransformerNoLoadLossAuthority],
    rated_load: Mapping[str, TransformerRatedLoadLossAuthority],
) -> None:
    for transformer_id in no_load.keys() & rated_load.keys():
        if (
            no_load[transformer_id].test_frequency_hz
            != rated_load[transformer_id].test_frequency_hz
        ):
            raise ValueError("no-load and rated-load factory-test frequencies must match exactly")


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


def _state(static_resolved: bool, no_load_present: bool, rated_load_present: bool) -> str:
    return (
        "unresolved_upstream_transformer_static_authority"
        if not static_resolved
        else "unresolved_missing_transformer_no_load_loss_authority"
        if not no_load_present
        else "unresolved_missing_transformer_rated_load_loss_authority"
        if not rated_load_present
        else "resolved_transformer_factory_loss_authority"
    )


def _record(
    static_resolved: bool,
    no_load: TransformerNoLoadLossAuthority | None,
    rated_load: TransformerRatedLoadLossAuthority | None,
) -> dict[str, object]:
    no_load_present = no_load is not None
    rated_load_present = rated_load is not None
    return {
        "transformer_static_authority_resolved": static_resolved,
        "transformer_no_load_loss_authority_present": no_load_present,
        "transformer_rated_load_loss_authority_present": rated_load_present,
        "transformer_factory_loss_authority_resolved": (
            static_resolved and no_load_present and rated_load_present
        ),
        "no_load_loss_w": no_load.no_load_loss_w if no_load else math.nan,
        "no_load_test_reference_side": no_load.test_reference_side if no_load else "",
        "no_load_test_voltage_condition": no_load.test_voltage_condition if no_load else "",
        "no_load_test_voltage_basis": no_load.test_voltage_basis if no_load else "",
        "no_load_test_frequency_hz": no_load.test_frequency_hz if no_load else math.nan,
        "rated_load_loss_w": rated_load.rated_load_loss_w if rated_load else math.nan,
        "load_loss_test_current_reference_side": (
            rated_load.test_current_reference_side if rated_load else ""
        ),
        "load_loss_test_current_condition": (
            rated_load.test_current_condition if rated_load else ""
        ),
        "load_loss_reference_temperature_c": (
            rated_load.reference_temperature_c if rated_load else math.nan
        ),
        "load_loss_test_frequency_hz": (rated_load.test_frequency_hz if rated_load else math.nan),
        "load_loss_semantics": rated_load.loss_semantics if rated_load else "",
        "no_load_parameter_source": no_load.parameter_source if no_load else "",
        "no_load_confidence": no_load.confidence if no_load else "",
        "rated_load_parameter_source": rated_load.parameter_source if rated_load else "",
        "rated_load_confidence": rated_load.confidence if rated_load else "",
        "transformer_loss_authority_state": _state(
            static_resolved, no_load_present, rated_load_present
        ),
        "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
        "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
        "transformer_loss_authority_contract": TRANSFORMER_LOSS_AUTHORITY_CONTRACT_ID,
        "transformer_loss_authority_model": TRANSFORMER_LOSS_AUTHORITY_MODEL_ID,
        "transformer_loss_authority_scope": TRANSFORMER_LOSS_AUTHORITY_SCOPE,
        "transformer_loss_authority_coverage_scope": (TRANSFORMER_LOSS_AUTHORITY_COVERAGE_SCOPE),
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
    no_load: Mapping[str, TransformerNoLoadLossAuthority],
    rated_load: Mapping[str, TransformerRatedLoadLossAuthority],
) -> TopologyTransformerLossAuthorityDiagnostics:
    counts = states["transformer_loss_authority_state"].value_counts()
    static_resolved = int(states["transformer_static_authority_resolved"].sum())
    return TopologyTransformerLossAuthorityDiagnostics(
        transformer_record_count=len(states),
        static_authority_resolved_count=static_resolved,
        static_authority_unresolved_count=len(states) - static_resolved,
        no_load_loss_authority_count=len(no_load),
        rated_load_loss_authority_count=len(rated_load),
        factory_loss_authority_resolved_count=int(
            counts.get("resolved_transformer_factory_loss_authority", 0)
        ),
        unresolved_upstream_static_count=int(
            counts.get("unresolved_upstream_transformer_static_authority", 0)
        ),
        unresolved_missing_no_load_loss_count=int(
            counts.get("unresolved_missing_transformer_no_load_loss_authority", 0)
        ),
        unresolved_missing_rated_load_loss_count=int(
            counts.get("unresolved_missing_transformer_rated_load_loss_authority", 0)
        ),
        model=TRANSFORMER_LOSS_AUTHORITY_MODEL_ID,
    )


def _equal(actual: object, expected: object) -> bool:
    if isinstance(expected, float) and math.isnan(expected):
        return bool(pd.isna(actual))
    return bool(actual == expected)


def _validate_result(
    static: TopologyTransformerStaticAuthorityResult,
    result: TopologyTransformerLossAuthorityResult,
) -> None:
    if type(result) is not TopologyTransformerLossAuthorityResult:
        raise RuntimeError("transformer loss authority result type is invalid")
    if any(
        type(mapping).__name__ != "mappingproxy"
        for mapping in (result.no_load_loss_by_id, result.rated_load_loss_by_id)
    ):
        raise RuntimeError("transformer loss authority result mappings must be immutable")
    transformer_ids = static.transformer_states.index.tolist()
    known_ids = set(transformer_ids)
    for key, no_load_authority in result.no_load_loss_by_id.items():
        if (
            type(no_load_authority) is not TransformerNoLoadLossAuthority
            or key != no_load_authority.transformer_id
        ):
            raise RuntimeError("transformer no-load mapping closure is invalid")
        if key not in known_ids:
            raise RuntimeError("transformer no-load authority contains an unknown ID")
        try:
            _validate_no_load(no_load_authority)
        except ValueError as error:
            raise RuntimeError("transformer no-load authority domain is invalid") from error
    for key, rated_load_authority in result.rated_load_loss_by_id.items():
        if (
            type(rated_load_authority) is not TransformerRatedLoadLossAuthority
            or key != rated_load_authority.transformer_id
        ):
            raise RuntimeError("transformer rated-load mapping closure is invalid")
        if key not in known_ids:
            raise RuntimeError("transformer rated-load authority contains an unknown ID")
        try:
            _validate_rated_load(rated_load_authority)
        except ValueError as error:
            raise RuntimeError("transformer rated-load authority domain is invalid") from error
    try:
        _validate_frequency_compatibility(result.no_load_loss_by_id, result.rated_load_loss_by_id)
    except ValueError as error:
        raise RuntimeError("transformer factory-test frequencies are incompatible") from error
    states = result.transformer_states
    if (
        tuple(states.columns) != _COLUMNS
        or states.index.name != "transformer_id"
        or states.index.has_duplicates
        or states.index.tolist() != transformer_ids
    ):
        raise RuntimeError("transformer loss state schema/index/order is invalid")
    for column in _COLUMNS:
        expected_dtype = (
            "bool"
            if column in _BOOL_COLUMNS
            else "float64"
            if column in _FLOAT_COLUMNS
            else "object"
        )
        if str(states[column].dtype) != expected_dtype:
            raise RuntimeError(f"transformer loss dtype is invalid for {column}")
    category_counts = {
        "resolved_transformer_factory_loss_authority": 0,
        "unresolved_upstream_transformer_static_authority": 0,
        "unresolved_missing_transformer_no_load_loss_authority": 0,
        "unresolved_missing_transformer_rated_load_loss_authority": 0,
    }
    static_resolved_count = 0
    for transformer_id, row in states.iterrows():
        static_resolved = bool(
            static.transformer_states.loc[transformer_id, "transformer_static_authority_resolved"]
        )
        no_load = result.no_load_loss_by_id.get(transformer_id)
        rated_load = result.rated_load_loss_by_id.get(transformer_id)
        no_load_present = no_load is not None
        rated_load_present = rated_load is not None
        resolved = static_resolved and no_load_present and rated_load_present
        state = (
            "unresolved_upstream_transformer_static_authority"
            if not static_resolved
            else "unresolved_missing_transformer_no_load_loss_authority"
            if not no_load_present
            else "unresolved_missing_transformer_rated_load_loss_authority"
            if not rated_load_present
            else "resolved_transformer_factory_loss_authority"
        )
        category_counts[state] += 1
        static_resolved_count += int(static_resolved)
        expected: dict[str, object] = {
            "transformer_static_authority_resolved": static_resolved,
            "transformer_no_load_loss_authority_present": no_load_present,
            "transformer_rated_load_loss_authority_present": rated_load_present,
            "transformer_factory_loss_authority_resolved": resolved,
            "no_load_loss_w": no_load.no_load_loss_w if no_load else math.nan,
            "no_load_test_reference_side": no_load.test_reference_side if no_load else "",
            "no_load_test_voltage_condition": no_load.test_voltage_condition if no_load else "",
            "no_load_test_voltage_basis": no_load.test_voltage_basis if no_load else "",
            "no_load_test_frequency_hz": no_load.test_frequency_hz if no_load else math.nan,
            "rated_load_loss_w": rated_load.rated_load_loss_w if rated_load else math.nan,
            "load_loss_test_current_reference_side": (
                rated_load.test_current_reference_side if rated_load else ""
            ),
            "load_loss_test_current_condition": (
                rated_load.test_current_condition if rated_load else ""
            ),
            "load_loss_reference_temperature_c": (
                rated_load.reference_temperature_c if rated_load else math.nan
            ),
            "load_loss_test_frequency_hz": (
                rated_load.test_frequency_hz if rated_load else math.nan
            ),
            "load_loss_semantics": rated_load.loss_semantics if rated_load else "",
            "no_load_parameter_source": no_load.parameter_source if no_load else "",
            "no_load_confidence": no_load.confidence if no_load else "",
            "rated_load_parameter_source": rated_load.parameter_source if rated_load else "",
            "rated_load_confidence": rated_load.confidence if rated_load else "",
            "transformer_loss_authority_state": state,
            "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
            "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
            "transformer_loss_authority_contract": TRANSFORMER_LOSS_AUTHORITY_CONTRACT_ID,
            "transformer_loss_authority_model": TRANSFORMER_LOSS_AUTHORITY_MODEL_ID,
            "transformer_loss_authority_scope": TRANSFORMER_LOSS_AUTHORITY_SCOPE,
            "transformer_loss_authority_coverage_scope": (
                TRANSFORMER_LOSS_AUTHORITY_COVERAGE_SCOPE
            ),
        }
        for column, wanted in expected.items():
            if not _equal(row[column], wanted):
                raise RuntimeError(f"transformer loss state does not close for {column}")
    expected_diagnostics = TopologyTransformerLossAuthorityDiagnostics(
        transformer_record_count=len(transformer_ids),
        static_authority_resolved_count=static_resolved_count,
        static_authority_unresolved_count=len(transformer_ids) - static_resolved_count,
        no_load_loss_authority_count=len(result.no_load_loss_by_id),
        rated_load_loss_authority_count=len(result.rated_load_loss_by_id),
        factory_loss_authority_resolved_count=category_counts[
            "resolved_transformer_factory_loss_authority"
        ],
        unresolved_upstream_static_count=category_counts[
            "unresolved_upstream_transformer_static_authority"
        ],
        unresolved_missing_no_load_loss_count=category_counts[
            "unresolved_missing_transformer_no_load_loss_authority"
        ],
        unresolved_missing_rated_load_loss_count=category_counts[
            "unresolved_missing_transformer_rated_load_loss_authority"
        ],
        model=TRANSFORMER_LOSS_AUTHORITY_MODEL_ID,
    )
    diagnostics = result.diagnostics
    if diagnostics != expected_diagnostics:
        raise RuntimeError("transformer loss diagnostics failed exact closure")
    if (
        diagnostics.static_authority_resolved_count + diagnostics.static_authority_unresolved_count
        != diagnostics.transformer_record_count
    ):
        raise RuntimeError("transformer static diagnostics do not close")
    if (
        diagnostics.factory_loss_authority_resolved_count
        + diagnostics.unresolved_upstream_static_count
        + diagnostics.unresolved_missing_no_load_loss_count
        + diagnostics.unresolved_missing_rated_load_loss_count
        != diagnostics.transformer_record_count
    ):
        raise RuntimeError("transformer loss state diagnostics do not close")
    if (
        diagnostics.no_load_loss_authority_count != len(result.no_load_loss_by_id)
        or diagnostics.rated_load_loss_authority_count != len(result.rated_load_loss_by_id)
        or diagnostics.factory_loss_authority_resolved_count
        > diagnostics.static_authority_resolved_count
        or diagnostics.model != TRANSFORMER_LOSS_AUTHORITY_MODEL_ID
    ):
        raise RuntimeError("transformer loss diagnostics domain is invalid")
