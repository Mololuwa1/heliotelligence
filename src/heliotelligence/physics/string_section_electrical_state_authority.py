"""Reviewed complete section SDM state bound to one explicit optical observation.

Admission only. Geometric visibility fractions and free-text basis descriptions
are never interpreted as electrical equations or module-to-section transforms.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from types import MappingProxyType

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.geometry.models import SiteGeometry
from heliotelligence.physics.string_member_topology_authority import (
    TopologyStringMemberAuthorityResult,
)
from heliotelligence.physics.string_section_direct_beam_state import (
    DirectBeamVisibilitySnapshot,
    SectionDirectBeamStateResult,
    validate_section_direct_beam_state,
)
from heliotelligence.physics.string_section_optical_binding_authority import (
    SectionOpticalBindingAuthorityResult,
)
from heliotelligence.physics.string_section_reverse_breakdown_authority import (
    BypassSectionIdentity,
    _parent_section_pairs,
)
from heliotelligence.physics.string_section_reverse_iv import (
    SectionSingleDiodeOperatingState,
    validate_section_single_diode_operating_state,
)

SECTION_ELECTRICAL_STATE_CONTRACT_ID = "explicit_section_sdm_operating_state_binding_authority_v1"
SECTION_ELECTRICAL_STATE_MODEL_ID = (
    "explicit_complete_section_single_diode_state_bound_to_optical_snapshot_v1"
)
SECTION_ELECTRICAL_STATE_SCOPE = (
    "advanced_s8_section_electrical_state_before_bishop_clamp_and_series_composition"
)
SECTION_ELECTRICAL_STATE_COVERAGE_SCOPE = (
    "explicit_stage4a5a_sections_with_complete_reviewed_section_sdm_operating_state"
)
_FIXED = (
    ("contract", SECTION_ELECTRICAL_STATE_CONTRACT_ID),
    ("model", SECTION_ELECTRICAL_STATE_MODEL_ID),
    ("scope", SECTION_ELECTRICAL_STATE_SCOPE),
    ("coverage_scope", SECTION_ELECTRICAL_STATE_COVERAGE_SCOPE),
)


def validate_section_observation_timestamp(value: pd.Timestamp) -> None:
    if type(value) is not pd.Timestamp or pd.isna(value) or value.tz is None:
        raise ValueError("observation_timestamp must be an exact aware non-NaT Timestamp")


def _text(value: object) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("identity/provenance requires exact non-empty unpadded text")


def _identity(value: BypassSectionIdentity) -> None:
    if type(value) is not BypassSectionIdentity:
        raise ValueError("expected canonical exact section identity")
    _text(value.module_id)
    _text(value.section_id)


def _same_time(left: pd.Timestamp, right: pd.Timestamp) -> bool:
    return bool(left == right and left.tz == right.tz)


@dataclass(frozen=True)
class SectionElectricalOperatingStateBinding:
    section_identity: BypassSectionIdentity
    geometry_revision: str
    optical_snapshot_reference: str
    observation_timestamp: pd.Timestamp
    operating_state: SectionSingleDiodeOperatingState
    parameter_source: str
    confidence: str
    method_reference: str
    irradiance_basis_description: str
    temperature_basis_description: str
    applicability_description: str

    def __post_init__(self) -> None:
        _binding_fields(self)


def _binding_fields(binding: SectionElectricalOperatingStateBinding) -> None:
    if type(binding) is not SectionElectricalOperatingStateBinding:
        raise ValueError("expected exact section electrical-state binding")
    _identity(binding.section_identity)
    for name in (
        "geometry_revision",
        "optical_snapshot_reference",
        "parameter_source",
        "confidence",
        "method_reference",
        "irradiance_basis_description",
        "temperature_basis_description",
        "applicability_description",
    ):
        _text(getattr(binding, name))
    if binding.confidence not in {"high", "medium", "low", "unknown"}:
        raise ValueError("unknown confidence")
    validate_section_observation_timestamp(binding.observation_timestamp)
    validate_section_single_diode_operating_state(binding.operating_state)


@dataclass(frozen=True)
class SectionElectricalStateDiagnostics:
    topology_section_count: int
    optical_resolved_section_count: int
    electrical_state_section_count: int
    electrical_state_unavailable_section_count: int


@dataclass(frozen=True)
class SectionElectricalStateAuthorityResult:
    bindings_by_section: Mapping[BypassSectionIdentity, SectionElectricalOperatingStateBinding]
    resolved_section_ids: tuple[BypassSectionIdentity, ...]
    unavailable_section_ids: tuple[BypassSectionIdentity, ...]
    observation_timestamp: pd.Timestamp
    geometry_revision: str
    optical_snapshot_reference: str | None
    diagnostics: SectionElectricalStateDiagnostics
    contract: str = SECTION_ELECTRICAL_STATE_CONTRACT_ID
    model: str = SECTION_ELECTRICAL_STATE_MODEL_ID
    scope: str = SECTION_ELECTRICAL_STATE_SCOPE
    coverage_scope: str = SECTION_ELECTRICAL_STATE_COVERAGE_SCOPE


def _context(
    parent: TopologyStringMemberAuthorityResult,
    geometry: SiteGeometry,
    optical_binding: SectionOpticalBindingAuthorityResult,
    snapshots: tuple[DirectBeamVisibilitySnapshot, ...],
    optical_state: SectionDirectBeamStateResult,
) -> tuple[BypassSectionIdentity, ...]:
    validate_section_direct_beam_state(parent, geometry, optical_binding, snapshots, optical_state)
    return tuple(BypassSectionIdentity(*pair) for pair in _parent_section_pairs(parent))


def _bound(
    binding: SectionElectricalOperatingStateBinding,
    optical_state: SectionDirectBeamStateResult,
    timestamp: pd.Timestamp,
) -> None:
    _binding_fields(binding)
    if binding.section_identity not in optical_state.states_by_section:
        raise ValueError("electrical binding requires a resolved Stage4a-5a section")
    if (
        binding.geometry_revision != optical_state.geometry_revision
        or binding.optical_snapshot_reference != optical_state.snapshot_reference
    ):
        raise ValueError("electrical binding differs from exact optical context")
    if not _same_time(binding.observation_timestamp, timestamp):
        raise ValueError("section electrical observation timestamps must match exactly")


def resolve_section_electrical_state_authority(
    parent: TopologyStringMemberAuthorityResult,
    geometry: SiteGeometry,
    optical_binding: SectionOpticalBindingAuthorityResult,
    snapshots: tuple[DirectBeamVisibilitySnapshot, ...],
    optical_state: SectionDirectBeamStateResult,
    observation_timestamp: pd.Timestamp,
    supplied: Mapping[BypassSectionIdentity, SectionElectricalOperatingStateBinding],
) -> SectionElectricalStateAuthorityResult:
    """Bind explicit complete states, including partial/empty coverage; infer none.

    The supplied timestamp labels this calculation even for empty evidence. It
    does not infer time from an opaque optical reference or create time authority.
    """
    keys = _context(parent, geometry, optical_binding, snapshots, optical_state)
    validate_section_observation_timestamp(observation_timestamp)
    if not isinstance(supplied, Mapping):
        raise ValueError("bindings require a mapping")
    for key, binding in supplied.items():
        _identity(key)
        _bound(binding, optical_state, observation_timestamp)
        if key != binding.section_identity:
            raise ValueError("section mapping identity mismatch")
    owned = {
        key: replace(
            supplied[key],
            section_identity=replace(key),
            operating_state=replace(supplied[key].operating_state),
        )
        for key in keys
        if key in supplied
    }
    unavailable = tuple(k for k in keys if k not in owned)
    result = SectionElectricalStateAuthorityResult(
        MappingProxyType(owned),
        tuple(owned),
        unavailable,
        observation_timestamp,
        optical_state.geometry_revision,
        optical_state.snapshot_reference,
        SectionElectricalStateDiagnostics(
            len(keys), len(optical_state.states_by_section), len(owned), len(unavailable)
        ),
    )
    validate_section_electrical_state_authority(
        parent, geometry, optical_binding, snapshots, optical_state, result
    )
    return result


def validate_section_electrical_state_authority(
    parent: TopologyStringMemberAuthorityResult,
    geometry: SiteGeometry,
    optical_binding: SectionOpticalBindingAuthorityResult,
    snapshots: tuple[DirectBeamVisibilitySnapshot, ...],
    optical_state: SectionDirectBeamStateResult,
    result: SectionElectricalStateAuthorityResult,
) -> None:
    """Independent electrical field/partition inspection, with canonical 5a replay."""
    keys = _context(parent, geometry, optical_binding, snapshots, optical_state)
    if type(result) is not SectionElectricalStateAuthorityResult:
        raise ValueError("invalid electrical authority type")
    for name, expected in _FIXED:
        value = getattr(result, name)
        if type(value) is not str or value != expected:
            raise ValueError("invalid electrical authority semantics")
    validate_section_observation_timestamp(result.observation_timestamp)
    _text(result.geometry_revision)
    if result.optical_snapshot_reference is not None:
        _text(result.optical_snapshot_reference)
    if (
        result.geometry_revision != optical_state.geometry_revision
        or result.optical_snapshot_reference != optical_state.snapshot_reference
    ):
        raise ValueError("electrical result optical context mismatch")
    if type(result.bindings_by_section) is not MappingProxyType:
        raise ValueError("electrical bindings must be immutable")
    for key, binding in result.bindings_by_section.items():
        _identity(key)
        _bound(binding, optical_state, result.observation_timestamp)
        if key != binding.section_identity:
            raise ValueError("electrical identity mismatch")
    resolved = tuple(k for k in keys if k in result.bindings_by_section)
    unavailable = tuple(k for k in keys if k not in result.bindings_by_section)
    if tuple(result.bindings_by_section) != resolved:
        raise ValueError("electrical order mismatch")
    for partition, expected_partition in (
        (result.resolved_section_ids, resolved),
        (result.unavailable_section_ids, unavailable),
    ):
        if type(partition) is not tuple:
            raise ValueError("invalid electrical partition")
        for key in partition:
            _identity(key)
        if partition != expected_partition:
            raise ValueError("electrical partition does not close")
    d = result.diagnostics
    if type(d) is not SectionElectricalStateDiagnostics:
        raise ValueError("invalid electrical diagnostics")
    counts = tuple(getattr(d, f.name) for f in fields(d))
    if any(type(v) is not int for v in counts) or counts != (
        len(keys),
        len(optical_state.states_by_section),
        len(resolved),
        len(unavailable),
    ):
        raise ValueError("electrical diagnostics do not close")
