"""Transformer-terminal harmonic-current characterisation authority.

S12I records explicit transformer-terminal current spectra and derives only
dimensionless current-characterisation factors. It does not calculate loss
watts, alter S12F/S12G, or apply a spectrum to operating timestamps. Raw
inverter type-test spectra are not transformer-terminal evidence unless an
external documented aggregation has already established that reference plane.
S12K owns later harmonic loss correction.
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
    TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
    TopologyTransformerStaticAuthorityResult,
    TransformerBoundaryTopologyAuthority,
    TransformerStaticEquipmentAuthority,
    resolve_transformer_static_authority,
)

TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_CONTRACT_ID = (
    "admitted_transformer_static_authority_to_terminal_integer_harmonic_"
    "current_characterisation_v1"
)
TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_MODEL_ID = (
    "balanced_three_phase_representative_line_current_ieee_c57_110_"
    "harmonic_factor_characterisation_v1"
)
TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_SCOPE = (
    "static_transformer_terminal_harmonic_current_characterisation_before_"
    "harmonic_loss_correction_and_thermal_state"
)
TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_normalized_integer_harmonic_current_spectrum_to_thd_rms_"
    "k_factor_winding_eddy_and_other_stray_harmonic_factors"
)
HARMONIC_METHOD_REFERENCE_STANDARD = "IEEE C57.110-2018"
HARMONIC_METHOD_SEMANTICS = (
    "integer_harmonic_current_weighting_h2_for_winding_eddy_"
    "and_h0p8_for_other_stray"
)
WINDING_EDDY_HARMONIC_FACTOR_SEMANTICS = (
    "dimensionless_winding_eddy_current_harmonic_loss_factor_h2_weighting"
)
OTHER_STRAY_HARMONIC_FACTOR_SEMANTICS = (
    "dimensionless_other_stray_harmonic_loss_factor_h0p8_weighting"
)
LOAD_CURRENT_K_FACTOR_SEMANTICS = (
    "h2_weighted_load_current_k_factor_not_transformer_nameplate_k_rating"
)

Confidence = Literal["high", "medium", "low", "unknown"]
ReferencePlane = Literal[
    "transformer_collection_side_terminal", "transformer_network_side_terminal"
]
EvidenceKind = Literal[
    "site_power_quality_measurement_at_transformer_terminal",
    "commissioning_power_quality_test_at_transformer_terminal",
    "documented_engineering_aggregation_to_transformer_terminal",
    "other_documented_transformer_terminal_spectrum",
]
Applicability = Literal[
    "single_declared_operating_condition", "declared_representative_normalized_spectrum"
]

_PLANES = {"transformer_collection_side_terminal", "transformer_network_side_terminal"}
_PHASE_SCOPE = "balanced_three_phase_representative_line_current"
_SPECTRUM_BASIS = "per_harmonic_rms_current_ratio_to_fundamental_rms_current"
_EVIDENCE_KINDS = {
    "site_power_quality_measurement_at_transformer_terminal",
    "commissioning_power_quality_test_at_transformer_terminal",
    "documented_engineering_aggregation_to_transformer_terminal",
    "other_documented_transformer_terminal_spectrum",
}
_APPLICABILITY = {
    "single_declared_operating_condition",
    "declared_representative_normalized_spectrum",
}
_CONFIDENCES = {"high", "medium", "low", "unknown"}
_STATES = (
    "unresolved_upstream_transformer_static_authority",
    "unresolved_missing_transformer_harmonic_current_spectrum_authority",
    "unresolved_nonfinite_harmonic_current_characterisation",
    "resolved_transformer_harmonic_current_characterisation",
)
_BOOL_COLUMNS = {
    "transformer_static_authority_resolved",
    "transformer_harmonic_current_spectrum_authority_present",
    "transformer_harmonic_current_characterisation_resolved",
}
_FLOAT_COLUMNS = {
    "fundamental_frequency_hz",
    "highest_harmonic_frequency_hz",
    "sum_current_ratio_squared",
    "nonfundamental_sum_current_ratio_squared",
    "total_rms_current_to_fundamental_ratio",
    "fundamental_current_fraction_of_total_rms",
    "current_thd_ratio",
    "current_thd_percent",
    "winding_eddy_harmonic_loss_factor",
    "other_stray_harmonic_loss_factor",
    "load_current_k_factor",
}
_COLUMNS = (
    "transformer_static_authority_resolved",
    "transformer_harmonic_current_spectrum_authority_present",
    "spectrum_reference_plane",
    "harmonic_current_reference_terminal_id",
    "harmonic_current_reference_side",
    "phase_scope",
    "current_spectrum_basis",
    "fundamental_frequency_hz",
    "evidence_kind",
    "applicability_semantics",
    "operating_condition_description",
    "harmonic_spectrum_parameter_source",
    "harmonic_spectrum_confidence",
    "harmonic_order_count",
    "highest_harmonic_order",
    "highest_harmonic_frequency_hz",
    "sum_current_ratio_squared",
    "nonfundamental_sum_current_ratio_squared",
    "total_rms_current_to_fundamental_ratio",
    "fundamental_current_fraction_of_total_rms",
    "current_thd_ratio",
    "current_thd_percent",
    "winding_eddy_harmonic_loss_factor",
    "other_stray_harmonic_loss_factor",
    "load_current_k_factor",
    "winding_eddy_harmonic_factor_semantics",
    "other_stray_harmonic_factor_semantics",
    "load_current_k_factor_semantics",
    "harmonic_method_semantics",
    "harmonic_method_reference_standard",
    "transformer_harmonic_current_characterisation_resolved",
    "transformer_harmonic_current_authority_state",
    "transformer_static_authority_contract",
    "transformer_static_authority_model",
    "transformer_harmonic_current_authority_contract",
    "transformer_harmonic_current_authority_model",
    "transformer_harmonic_current_authority_scope",
    "transformer_harmonic_current_authority_coverage_scope",
)


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be an exact non-empty string without padding")
    return value


def _literal(value: object, allowed: set[str], name: str) -> str:
    if type(value) is not str or value not in allowed:
        raise ValueError(f"{name} is unsupported")
    return value


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a non-Boolean real number")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{name} must be finite and strictly positive")
    return number


@dataclass(frozen=True)
class TransformerHarmonicCurrentSpectrumAuthority:
    transformer_id: str
    spectrum_reference_plane: ReferencePlane
    phase_scope: Literal["balanced_three_phase_representative_line_current"]
    current_spectrum_basis: Literal[
        "per_harmonic_rms_current_ratio_to_fundamental_rms_current"
    ]
    fundamental_frequency_hz: float
    harmonic_current_ratio_by_order: Mapping[int, float]
    evidence_kind: EvidenceKind
    applicability_semantics: Applicability
    operating_condition_description: str
    parameter_source: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _text(self.transformer_id, "transformer_id")
        _literal(self.spectrum_reference_plane, _PLANES, "spectrum_reference_plane")
        _literal(self.phase_scope, {_PHASE_SCOPE}, "phase_scope")
        _literal(self.current_spectrum_basis, {_SPECTRUM_BASIS}, "current_spectrum_basis")
        _positive_number(self.fundamental_frequency_hz, "fundamental_frequency_hz")
        if not isinstance(self.harmonic_current_ratio_by_order, Mapping):
            raise TypeError("harmonic_current_ratio_by_order must be a mapping")
        spectrum: dict[int, float] = {}
        for order, ratio in self.harmonic_current_ratio_by_order.items():
            if isinstance(order, bool) or type(order) is not int or order < 1:
                raise ValueError("harmonic orders must be Python integers >= 1")
            if isinstance(ratio, bool) or not isinstance(ratio, Real):
                raise ValueError("harmonic ratios must be non-Boolean real numbers")
            value = float(ratio)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError("harmonic ratios must be finite and non-negative")
            spectrum[order] = value
        if 1 not in spectrum:
            raise ValueError("harmonic spectrum must contain order 1")
        if spectrum[1] != 1.0:
            raise ValueError("order 1 harmonic ratio must be exactly 1.0")
        object.__setattr__(
            self,
            "harmonic_current_ratio_by_order",
            MappingProxyType(dict(sorted(spectrum.items()))),
        )
        _literal(self.evidence_kind, _EVIDENCE_KINDS, "evidence_kind")
        _literal(self.applicability_semantics, _APPLICABILITY, "applicability_semantics")
        _text(self.operating_condition_description, "operating_condition_description")
        _text(self.parameter_source, "parameter_source")
        _literal(self.confidence, _CONFIDENCES, "confidence")


@dataclass(frozen=True)
class TopologyTransformerHarmonicCurrentAuthorityDiagnostics:
    transformer_count: int
    harmonic_spectrum_authority_count: int
    resolved_harmonic_characterisation_count: int
    unresolved_upstream_static_count: int
    missing_harmonic_spectrum_count: int
    nonfinite_harmonic_characterisation_count: int
    collection_side_spectrum_count: int
    network_side_spectrum_count: int
    site_measurement_count: int
    commissioning_test_count: int
    engineering_aggregation_count: int
    representative_spectrum_count: int
    single_condition_spectrum_count: int
    state_counts: tuple[tuple[str, int], ...]
    model: str


@dataclass(frozen=True)
class TopologyTransformerHarmonicCurrentAuthorityResult:
    harmonic_current_spectrum_by_id: Mapping[str, TransformerHarmonicCurrentSpectrumAuthority]
    transformer_states: pd.DataFrame
    diagnostics: TopologyTransformerHarmonicCurrentAuthorityDiagnostics


def resolve_transformer_harmonic_current_authority(
    topology: ElectricalTopologyConfig,
    network_basis: LvAcCollectionNetworkBasisAuthority | None,
    node_authority_by_id: Mapping[str, LvAcCollectionNodeAuthority],
    segment_authority_by_id: Mapping[str, LvAcCollectionSegmentAuthority],
    inverter_terminal_binding_by_inverter_id: Mapping[str, LvAcInverterTerminalBindingAuthority],
    lv_ac_collection_authority: TopologyLvAcCollectionAuthorityResult,
    transformer_equipment_by_id: Mapping[str, TransformerStaticEquipmentAuthority],
    transformer_topology_by_id: Mapping[str, TransformerBoundaryTopologyAuthority],
    transformer_static_authority: TopologyTransformerStaticAuthorityResult,
    transformer_harmonic_current_spectrum_by_id: Mapping[
        str, TransformerHarmonicCurrentSpectrumAuthority
    ],
) -> TopologyTransformerHarmonicCurrentAuthorityResult:
    """Resolve transformer-terminal harmonic-current characterisation."""
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
    _validate_static_replay(transformer_static_authority, canonical_static)
    ids = canonical_static.transformer_states.index.tolist()
    spectra = _admit_spectra(transformer_harmonic_current_spectrum_by_id, set(ids))
    records = [
        _record(
            canonical_static.transformer_states.loc[identifier],
            canonical_static.topology_by_id.get(identifier),
            spectra.get(identifier),
        )
        for identifier in ids
    ]
    frame = _frame(ids, records)
    result = TopologyTransformerHarmonicCurrentAuthorityResult(
        MappingProxyType(dict(spectra)), frame.copy(deep=True), _diagnostics(frame)
    )
    _validate_result(canonical_static, spectra, result)
    return result


def _validate_static_replay(
    supplied: TopologyTransformerStaticAuthorityResult,
    canonical: TopologyTransformerStaticAuthorityResult,
) -> None:
    if type(supplied) is not TopologyTransformerStaticAuthorityResult:
        raise ValueError("supplied S12A result type is invalid")
    for name in ("equipment_by_id", "topology_by_id"):
        actual = getattr(supplied, name)
        expected = getattr(canonical, name)
        if type(actual) is not MappingProxyType or tuple(actual.items()) != tuple(expected.items()):
            raise ValueError(f"supplied S12A {name} failed immutable canonical replay")
    try:
        pd.testing.assert_frame_equal(
            supplied.transformer_states, canonical.transformer_states, check_exact=True
        )
    except AssertionError as error:
        raise ValueError("supplied S12A frame failed canonical replay") from error
    if supplied.diagnostics != canonical.diagnostics:
        raise ValueError("supplied S12A diagnostics failed canonical replay")


def _admit_spectra(
    supplied: Mapping[str, TransformerHarmonicCurrentSpectrumAuthority], known: set[str]
) -> dict[str, TransformerHarmonicCurrentSpectrumAuthority]:
    if not isinstance(supplied, Mapping):
        raise TypeError("harmonic spectrum authority must be a mapping")
    admitted: dict[str, TransformerHarmonicCurrentSpectrumAuthority] = {}
    for key, authority in supplied.items():
        _text(key, "transformer mapping key")
        if type(authority) is not TransformerHarmonicCurrentSpectrumAuthority:
            raise TypeError("harmonic spectrum authority has invalid value type")
        if key != authority.transformer_id:
            raise ValueError("harmonic spectrum authority mapping key mismatch")
        if key not in known:
            raise ValueError("harmonic spectrum authority references unknown transformer")
        admitted[key] = authority
    return dict(sorted(admitted.items()))


def _derive(
    authority: TransformerHarmonicCurrentSpectrumAuthority,
) -> tuple[float, float, float, float, float, float, float, float, float, float] | None:
    try:
        squared = [ratio * ratio for ratio in authority.harmonic_current_ratio_by_order.values()]
        nonfundamental = [
            ratio * ratio
            for order, ratio in authority.harmonic_current_ratio_by_order.items()
            if order > 1
        ]
        s2 = math.fsum(squared)
        s2_nonfundamental = math.fsum(nonfundamental)
        total_ratio = math.sqrt(s2)
        fundamental_fraction = 1.0 / total_ratio
        thd = math.sqrt(s2_nonfundamental)
        thd_percent = thd * 100.0
        eddy_terms = [
            ratio * ratio * order * order
            for order, ratio in authority.harmonic_current_ratio_by_order.items()
        ]
        other_stray_terms = [
            ratio * ratio * math.pow(order, 0.8)
            for order, ratio in authority.harmonic_current_ratio_by_order.items()
        ]
        eddy_factor = math.fsum(eddy_terms) / s2
        other_stray_factor = math.fsum(other_stray_terms) / s2
        highest_frequency = authority.fundamental_frequency_hz * max(
            authority.harmonic_current_ratio_by_order
        )
        values = (
            highest_frequency,
            s2,
            s2_nonfundamental,
            total_ratio,
            fundamental_fraction,
            thd,
            thd_percent,
            eddy_factor,
            other_stray_factor,
            eddy_factor,
        )
    except (ArithmeticError, OverflowError, ValueError):
        return None
    return values if all(math.isfinite(value) for value in values) else None


def _record(
    static_row: pd.Series,
    topology: TransformerBoundaryTopologyAuthority | None,
    authority: TransformerHarmonicCurrentSpectrumAuthority | None,
) -> dict[str, object]:
    static_ok = bool(static_row["transformer_static_authority_resolved"])
    derived = _derive(authority) if authority else None
    if not static_ok:
        state = _STATES[0]
    elif authority is None:
        state = _STATES[1]
    elif derived is None:
        state = _STATES[2]
    else:
        state = _STATES[3]
    return _values(static_ok, topology, authority, derived, state)


def _values(
    static_ok: bool,
    topology: TransformerBoundaryTopologyAuthority | None,
    authority: TransformerHarmonicCurrentSpectrumAuthority | None,
    derived: tuple[float, float, float, float, float, float, float, float, float, float]
    | None,
    state: str,
) -> dict[str, object]:
    nan = math.nan
    if authority and authority.spectrum_reference_plane == "transformer_collection_side_terminal":
        terminal = topology.transformer_collection_terminal_id if topology else ""
        side = "collection_side"
    elif authority:
        terminal = topology.transformer_network_terminal_id if topology else ""
        side = "network_side"
    else:
        terminal = side = ""
    metrics = derived or (nan,) * 10
    return {
        "transformer_static_authority_resolved": static_ok,
        "transformer_harmonic_current_spectrum_authority_present": authority is not None,
        "spectrum_reference_plane": authority.spectrum_reference_plane if authority else "",
        "harmonic_current_reference_terminal_id": terminal,
        "harmonic_current_reference_side": side,
        "phase_scope": authority.phase_scope if authority else "",
        "current_spectrum_basis": authority.current_spectrum_basis if authority else "",
        "fundamental_frequency_hz": authority.fundamental_frequency_hz if authority else nan,
        "evidence_kind": authority.evidence_kind if authority else "",
        "applicability_semantics": authority.applicability_semantics if authority else "",
        "operating_condition_description": (
            authority.operating_condition_description if authority else ""
        ),
        "harmonic_spectrum_parameter_source": authority.parameter_source if authority else "",
        "harmonic_spectrum_confidence": authority.confidence if authority else "",
        "harmonic_order_count": (
            len(authority.harmonic_current_ratio_by_order) if authority else None
        ),
        "highest_harmonic_order": (
            max(authority.harmonic_current_ratio_by_order) if authority else None
        ),
        "highest_harmonic_frequency_hz": metrics[0],
        "sum_current_ratio_squared": metrics[1],
        "nonfundamental_sum_current_ratio_squared": metrics[2],
        "total_rms_current_to_fundamental_ratio": metrics[3],
        "fundamental_current_fraction_of_total_rms": metrics[4],
        "current_thd_ratio": metrics[5],
        "current_thd_percent": metrics[6],
        "winding_eddy_harmonic_loss_factor": metrics[7],
        "other_stray_harmonic_loss_factor": metrics[8],
        "load_current_k_factor": metrics[9],
        "winding_eddy_harmonic_factor_semantics": WINDING_EDDY_HARMONIC_FACTOR_SEMANTICS,
        "other_stray_harmonic_factor_semantics": OTHER_STRAY_HARMONIC_FACTOR_SEMANTICS,
        "load_current_k_factor_semantics": LOAD_CURRENT_K_FACTOR_SEMANTICS,
        "harmonic_method_semantics": HARMONIC_METHOD_SEMANTICS,
        "harmonic_method_reference_standard": HARMONIC_METHOD_REFERENCE_STANDARD,
        "transformer_harmonic_current_characterisation_resolved": (
            static_ok and authority is not None and derived is not None
        ),
        "transformer_harmonic_current_authority_state": state,
        "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
        "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
        "transformer_harmonic_current_authority_contract": (
            TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_CONTRACT_ID
        ),
        "transformer_harmonic_current_authority_model": (
            TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_MODEL_ID
        ),
        "transformer_harmonic_current_authority_scope": (
            TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_SCOPE
        ),
        "transformer_harmonic_current_authority_coverage_scope": (
            TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_COVERAGE_SCOPE
        ),
    }


def _frame(ids: list[str], records: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        records,
        index=pd.Index(ids, name="transformer_id", dtype=object),
        dtype=object,
    )
    frame = frame.reindex(columns=_COLUMNS)
    for column in _COLUMNS:
        if column in _BOOL_COLUMNS:
            frame[column] = frame[column].astype(bool)
        elif column in _FLOAT_COLUMNS:
            frame[column] = frame[column].astype("float64")
        else:
            frame[column] = frame[column].astype(object)
    return frame


def _diagnostics(frame: pd.DataFrame) -> TopologyTransformerHarmonicCurrentAuthorityDiagnostics:
    present = frame["transformer_harmonic_current_spectrum_authority_present"]
    states = tuple(
        (state, int(frame["transformer_harmonic_current_authority_state"].eq(state).sum()))
        for state in _STATES
    )
    return TopologyTransformerHarmonicCurrentAuthorityDiagnostics(
        len(frame),
        int(present.sum()),
        int(frame["transformer_harmonic_current_characterisation_resolved"].sum()),
        int((~frame["transformer_static_authority_resolved"]).sum()),
        int((~present).sum()),
        int((present & frame["highest_harmonic_frequency_hz"].isna()).sum()),
        int(frame["spectrum_reference_plane"].eq("transformer_collection_side_terminal").sum()),
        int(frame["spectrum_reference_plane"].eq("transformer_network_side_terminal").sum()),
        int(
            frame["evidence_kind"]
            .eq("site_power_quality_measurement_at_transformer_terminal")
            .sum()
        ),
        int(
            frame["evidence_kind"]
            .eq("commissioning_power_quality_test_at_transformer_terminal")
            .sum()
        ),
        int(
            frame["evidence_kind"]
            .eq("documented_engineering_aggregation_to_transformer_terminal")
            .sum()
        ),
        int(frame["applicability_semantics"].eq("declared_representative_normalized_spectrum").sum()),
        int(frame["applicability_semantics"].eq("single_declared_operating_condition").sum()),
        states,
        TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_MODEL_ID,
    )


def _validate_result(
    static: TopologyTransformerStaticAuthorityResult,
    spectra: Mapping[str, TransformerHarmonicCurrentSpectrumAuthority],
    result: TopologyTransformerHarmonicCurrentAuthorityResult,
) -> None:
    if type(result) is not TopologyTransformerHarmonicCurrentAuthorityResult:
        raise RuntimeError("S12I result type is invalid")
    if type(result.harmonic_current_spectrum_by_id) is not MappingProxyType:
        raise RuntimeError("S12I spectrum mapping must be immutable")
    if tuple(result.harmonic_current_spectrum_by_id.items()) != tuple(spectra.items()):
        raise RuntimeError("S12I spectrum mapping failed independent closure")
    ids = static.transformer_states.index.tolist()
    records = [
        _validator_record(
            static.transformer_states.loc[identifier],
            static.topology_by_id.get(identifier),
            spectra.get(identifier),
        )
        for identifier in ids
    ]
    expected = _validator_frame(ids, records)
    try:
        pd.testing.assert_frame_equal(result.transformer_states, expected, check_exact=True)
    except AssertionError as error:
        raise RuntimeError("S12I result frame failed independent closure") from error
    diagnostics = _validator_diagnostics(expected)
    if result.diagnostics != diagnostics:
        raise RuntimeError("S12I diagnostics failed independent closure")
    if sum(count for _, count in diagnostics.state_counts) != diagnostics.transformer_count:
        raise RuntimeError("S12I primary states do not partition transformers")


def _validator_record(
    static_row: pd.Series,
    topology: TransformerBoundaryTopologyAuthority | None,
    authority: TransformerHarmonicCurrentSpectrumAuthority | None,
) -> dict[str, object]:
    static_ok = bool(static_row["transformer_static_authority_resolved"])
    calculated: tuple[float, ...] | None = None
    if authority is not None:
        try:
            pairs = tuple(authority.harmonic_current_ratio_by_order.items())
            squares = tuple(ratio**2 for _, ratio in pairs)
            denominator = math.fsum(squares)
            nonfundamental = math.fsum(
                ratio**2 for order, ratio in pairs if order != 1
            )
            rms = math.sqrt(denominator)
            thd = math.sqrt(nonfundamental)
            eddy = math.fsum(ratio**2 * order**2 for order, ratio in pairs) / denominator
            osl = math.fsum(ratio**2 * math.pow(order, 0.8) for order, ratio in pairs) / denominator
            calculated = (
                authority.fundamental_frequency_hz * max(dict(pairs)),
                denominator,
                nonfundamental,
                rms,
                1.0 / rms,
                thd,
                thd * 100.0,
                eddy,
                osl,
                eddy,
            )
            if not all(math.isfinite(value) for value in calculated):
                calculated = None
        except (ArithmeticError, OverflowError, ValueError):
            calculated = None
    if not static_ok:
        state = _STATES[0]
    elif authority is None:
        state = _STATES[1]
    elif calculated is None:
        state = _STATES[2]
    else:
        state = _STATES[3]
    # This validator spells out the complete expected record independently of
    # the production record builder while sharing only immutable contract constants.
    nan = math.nan
    metrics = calculated or (nan,) * 10
    if authority and authority.spectrum_reference_plane == "transformer_collection_side_terminal":
        terminal = topology.transformer_collection_terminal_id if topology else ""
        side = "collection_side"
    elif authority:
        terminal = topology.transformer_network_terminal_id if topology else ""
        side = "network_side"
    else:
        terminal = side = ""
    return {
        "transformer_static_authority_resolved": static_ok,
        "transformer_harmonic_current_spectrum_authority_present": authority is not None,
        "spectrum_reference_plane": authority.spectrum_reference_plane if authority else "",
        "harmonic_current_reference_terminal_id": terminal,
        "harmonic_current_reference_side": side,
        "phase_scope": authority.phase_scope if authority else "",
        "current_spectrum_basis": authority.current_spectrum_basis if authority else "",
        "fundamental_frequency_hz": authority.fundamental_frequency_hz if authority else nan,
        "evidence_kind": authority.evidence_kind if authority else "",
        "applicability_semantics": authority.applicability_semantics if authority else "",
        "operating_condition_description": (
            authority.operating_condition_description if authority else ""
        ),
        "harmonic_spectrum_parameter_source": authority.parameter_source if authority else "",
        "harmonic_spectrum_confidence": authority.confidence if authority else "",
        "harmonic_order_count": (
            len(authority.harmonic_current_ratio_by_order) if authority else None
        ),
        "highest_harmonic_order": (
            max(authority.harmonic_current_ratio_by_order) if authority else None
        ),
        "highest_harmonic_frequency_hz": metrics[0],
        "sum_current_ratio_squared": metrics[1],
        "nonfundamental_sum_current_ratio_squared": metrics[2],
        "total_rms_current_to_fundamental_ratio": metrics[3],
        "fundamental_current_fraction_of_total_rms": metrics[4],
        "current_thd_ratio": metrics[5],
        "current_thd_percent": metrics[6],
        "winding_eddy_harmonic_loss_factor": metrics[7],
        "other_stray_harmonic_loss_factor": metrics[8],
        "load_current_k_factor": metrics[9],
        "winding_eddy_harmonic_factor_semantics": WINDING_EDDY_HARMONIC_FACTOR_SEMANTICS,
        "other_stray_harmonic_factor_semantics": OTHER_STRAY_HARMONIC_FACTOR_SEMANTICS,
        "load_current_k_factor_semantics": LOAD_CURRENT_K_FACTOR_SEMANTICS,
        "harmonic_method_semantics": HARMONIC_METHOD_SEMANTICS,
        "harmonic_method_reference_standard": HARMONIC_METHOD_REFERENCE_STANDARD,
        "transformer_harmonic_current_characterisation_resolved": bool(
            static_ok and authority is not None and calculated is not None
        ),
        "transformer_harmonic_current_authority_state": state,
        "transformer_static_authority_contract": TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
        "transformer_static_authority_model": TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
        "transformer_harmonic_current_authority_contract": (
            TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_CONTRACT_ID
        ),
        "transformer_harmonic_current_authority_model": (
            TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_MODEL_ID
        ),
        "transformer_harmonic_current_authority_scope": (
            TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_SCOPE
        ),
        "transformer_harmonic_current_authority_coverage_scope": (
            TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_COVERAGE_SCOPE
        ),
    }


def _validator_frame(ids: list[str], records: list[dict[str, object]]) -> pd.DataFrame:
    expected = pd.DataFrame(
        records,
        index=pd.Index(ids, name="transformer_id", dtype=object),
        dtype=object,
    )
    expected = expected.loc[:, list(_COLUMNS)]
    for column in _COLUMNS:
        dtype: object
        if column in _BOOL_COLUMNS:
            dtype = bool
        elif column in _FLOAT_COLUMNS:
            dtype = "float64"
        else:
            dtype = object
        expected[column] = expected[column].astype(dtype)
    return expected


def _validator_diagnostics(
    frame: pd.DataFrame,
) -> TopologyTransformerHarmonicCurrentAuthorityDiagnostics:
    present = frame["transformer_harmonic_current_spectrum_authority_present"]
    state_counts = tuple(
        (state, int((frame["transformer_harmonic_current_authority_state"] == state).sum()))
        for state in _STATES
    )
    return TopologyTransformerHarmonicCurrentAuthorityDiagnostics(
        transformer_count=len(frame),
        harmonic_spectrum_authority_count=int(present.sum()),
        resolved_harmonic_characterisation_count=int(
            frame["transformer_harmonic_current_characterisation_resolved"].sum()
        ),
        unresolved_upstream_static_count=int((~frame["transformer_static_authority_resolved"]).sum()),
        missing_harmonic_spectrum_count=int((~present).sum()),
        nonfinite_harmonic_characterisation_count=int(
            (present & frame["highest_harmonic_frequency_hz"].isna()).sum()
        ),
        collection_side_spectrum_count=int(
            frame["spectrum_reference_plane"].eq("transformer_collection_side_terminal").sum()
        ),
        network_side_spectrum_count=int(
            frame["spectrum_reference_plane"].eq("transformer_network_side_terminal").sum()
        ),
        site_measurement_count=int(
            frame["evidence_kind"].eq("site_power_quality_measurement_at_transformer_terminal").sum()
        ),
        commissioning_test_count=int(
            frame["evidence_kind"].eq("commissioning_power_quality_test_at_transformer_terminal").sum()
        ),
        engineering_aggregation_count=int(
            frame["evidence_kind"].eq("documented_engineering_aggregation_to_transformer_terminal").sum()
        ),
        representative_spectrum_count=int(
            frame["applicability_semantics"].eq("declared_representative_normalized_spectrum").sum()
        ),
        single_condition_spectrum_count=int(
            frame["applicability_semantics"].eq("single_declared_operating_condition").sum()
        ),
        state_counts=state_counts,
        model=TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_MODEL_ID,
    )
