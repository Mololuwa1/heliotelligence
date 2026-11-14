"""Explicit dormant S8 sample ownership, independent of optical/electrical execution.

The existing Stage4a-2 parent-integrity inspector is reused solely to inspect
Stage4a-1 connectivity. No reverse parameters, solver or geometry adapter is run.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from types import MappingProxyType

from heliotelligence.geometry.models import PVReceiver, SiteGeometry
from heliotelligence.physics.string_member_topology_authority import (
    TopologyStringMemberAuthorityResult,
)
from heliotelligence.physics.string_section_reverse_breakdown_authority import (
    BypassSectionIdentity,
    _parent_section_pairs,
)

SECTION_OPTICAL_BINDING_CONTRACT_ID = "explicit_string_section_optical_sample_binding_authority_v1"
SECTION_OPTICAL_BINDING_MODEL_ID = (
    "explicit_receiver_visibility_sample_to_bypass_section_binding_v1"
)
SECTION_OPTICAL_BINDING_SCOPE = (
    "advanced_s8_optical_geometry_to_section_binding_before_section_electrical_state"
)
SECTION_OPTICAL_BINDING_COVERAGE_SCOPE = (
    "explicit_stage4a1_sections_with_geometry_revision_receiver_and_sample_cell_mapping"
)
_FIXED = (
    ("contract", SECTION_OPTICAL_BINDING_CONTRACT_ID),
    ("model", SECTION_OPTICAL_BINDING_MODEL_ID),
    ("scope", SECTION_OPTICAL_BINDING_SCOPE),
    ("coverage_scope", SECTION_OPTICAL_BINDING_COVERAGE_SCOPE),
)


def _text(value: object) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("identity/provenance requires exact non-empty unpadded text")


def _identity(value: BypassSectionIdentity) -> None:
    if type(value) is not BypassSectionIdentity:
        raise ValueError("expected exact canonical section identity")
    _text(value.module_id)
    _text(value.section_id)


@dataclass(frozen=True)
class SectionOpticalBinding:
    section_identity: BypassSectionIdentity
    physical_position_reference: str
    geometry_revision: str
    receiver_id: str
    samples_u: int
    samples_v: int
    sample_indices: tuple[int, ...]
    parameter_source: str
    confidence: str
    method_reference: str
    applicability_description: str

    def __post_init__(self) -> None:
        _validate_binding_fields(self)


def _validate_binding_fields(binding: SectionOpticalBinding) -> None:
    # Direct field checks are shared by construction and independent validation;
    # neither resolver nor constructors are called by the validator.
    _identity(binding.section_identity)
    for name in (
        "physical_position_reference",
        "geometry_revision",
        "receiver_id",
        "parameter_source",
        "confidence",
        "method_reference",
        "applicability_description",
    ):
        _text(getattr(binding, name))
    if binding.confidence not in {"high", "medium", "low", "unknown"}:
        raise ValueError("unknown confidence")
    for count in (binding.samples_u, binding.samples_v):
        if type(count) is not int or count <= 0:
            raise ValueError("sample grid dimensions require exact positive integers")
    indices = binding.sample_indices
    if type(indices) is not tuple or not indices:
        raise ValueError("sample_indices must be an exact non-empty tuple")
    previous = -1
    for index in indices:
        if type(index) is not int or not previous < index < binding.samples_u * binding.samples_v:
            raise ValueError("sample_indices must be exact in-range strictly increasing integers")
        previous = index


@dataclass(frozen=True)
class SectionOpticalBindingDiagnostics:
    topology_section_count: int
    optical_binding_section_count: int
    optical_binding_unavailable_section_count: int
    bound_sample_cell_count: int
    receiver_count_used: int


@dataclass(frozen=True)
class SectionOpticalBindingAuthorityResult:
    bindings_by_section: Mapping[BypassSectionIdentity, SectionOpticalBinding]
    resolved_section_ids: tuple[BypassSectionIdentity, ...]
    unavailable_section_ids: tuple[BypassSectionIdentity, ...]
    diagnostics: SectionOpticalBindingDiagnostics
    geometry_revision: str
    contract: str = SECTION_OPTICAL_BINDING_CONTRACT_ID
    model: str = SECTION_OPTICAL_BINDING_MODEL_ID
    scope: str = SECTION_OPTICAL_BINDING_SCOPE
    coverage_scope: str = SECTION_OPTICAL_BINDING_COVERAGE_SCOPE


def _context(
    parent: TopologyStringMemberAuthorityResult, geometry: SiteGeometry
) -> tuple[dict[BypassSectionIdentity, str], set[str]]:
    pairs = _parent_section_pairs(parent)  # Independent existing parent inspector.
    if type(geometry) is not SiteGeometry:
        raise ValueError("expected exact SiteGeometry")
    _text(geometry.geometry_revision)
    if type(geometry.pv_receivers) is not tuple:
        raise ValueError("expected canonical receiver tuple")
    receiver_ids = set()
    for receiver in geometry.pv_receivers:
        if type(receiver) is not PVReceiver:
            raise ValueError("expected exact PVReceiver")
        _text(receiver.id)
        if receiver.id in receiver_ids:
            raise ValueError("duplicate receiver identity")
        receiver_ids.add(receiver.id)
    references = {
        m.module_id: m.physical_position_reference
        for a in parent.authorities_by_string_id.values()
        for m in a.module_members
    }
    return {BypassSectionIdentity(*pair): references[pair[0]] for pair in pairs}, receiver_ids


def _binding_context(
    binding: SectionOpticalBinding,
    references: Mapping[BypassSectionIdentity, str],
    receivers: set[str],
    revision: str,
) -> None:
    if type(binding) is not SectionOpticalBinding:
        raise ValueError("expected exact section optical binding")
    _validate_binding_fields(binding)
    key = binding.section_identity
    if key not in references:
        raise ValueError("unknown Stage4a-1 section identity")
    if binding.physical_position_reference != references[key]:
        raise ValueError("physical_position_reference differs from owning module")
    if binding.geometry_revision != revision:
        raise ValueError("stale geometry revision")
    if binding.receiver_id not in receivers:
        raise ValueError("unknown receiver")


def resolve_section_optical_binding_authority(
    parent: TopologyStringMemberAuthorityResult,
    geometry: SiteGeometry,
    supplied: Mapping[BypassSectionIdentity, SectionOpticalBinding],
) -> SectionOpticalBindingAuthorityResult:
    """Detach explicit partial evidence in canonical topology order; infer nothing."""
    references, receivers = _context(parent, geometry)
    if not isinstance(supplied, Mapping):
        raise ValueError("bindings must be a mapping")
    for key, binding in supplied.items():
        _identity(key)
        _binding_context(binding, references, receivers, geometry.geometry_revision)
        if key != binding.section_identity:
            raise ValueError("mapping key and embedded identity disagree")
    owned = {
        key: replace(
            supplied[key], section_identity=BypassSectionIdentity(key.module_id, key.section_id)
        )
        for key in references
        if key in supplied
    }
    unavailable = tuple(key for key in references if key not in owned)
    result = SectionOpticalBindingAuthorityResult(
        MappingProxyType(owned),
        tuple(owned),
        unavailable,
        SectionOpticalBindingDiagnostics(
            len(references),
            len(owned),
            len(unavailable),
            sum(len(b.sample_indices) for b in owned.values()),
            len({b.receiver_id for b in owned.values()}),
        ),
        geometry.geometry_revision,
    )
    validate_section_optical_binding_authority(parent, geometry, result)
    return result


def validate_section_optical_binding_authority(
    parent: TopologyStringMemberAuthorityResult,
    geometry: SiteGeometry,
    result: SectionOpticalBindingAuthorityResult,
) -> None:
    """Independently inspect identity/ownership/order/closure; no rebuilding.

    Geometry is used for revision and receiver identity only. This does not prove
    a mesh-to-reference-grid conversion or authenticate the supplied evidence.
    """
    references, receivers = _context(parent, geometry)
    if type(result) is not SectionOpticalBindingAuthorityResult:
        raise ValueError("expected exact optical binding authority result")
    for name, required in _FIXED:
        value = getattr(result, name)
        if type(value) is not str or value != required:
            raise ValueError("invalid optical binding contract semantics")
    _text(result.geometry_revision)
    if result.geometry_revision != geometry.geometry_revision:
        raise ValueError("stale result geometry revision")
    if type(result.bindings_by_section) is not MappingProxyType:
        raise ValueError("optical bindings mapping must be immutable")
    occupied: set[tuple[str, str, int, int, int]] = set()
    for key, binding in result.bindings_by_section.items():
        _identity(key)
        _binding_context(binding, references, receivers, geometry.geometry_revision)
        if key != binding.section_identity:
            raise ValueError("mapping identity disagreement")
        for index in binding.sample_indices:
            cell = (
                binding.geometry_revision,
                binding.receiver_id,
                binding.samples_u,
                binding.samples_v,
                index,
            )
            if cell in occupied:
                raise ValueError("sample ownership overlap between sections")
            occupied.add(cell)
    expected_resolved = tuple(k for k in references if k in result.bindings_by_section)
    expected_unavailable = tuple(k for k in references if k not in result.bindings_by_section)
    if tuple(result.bindings_by_section) != expected_resolved:
        raise ValueError("binding order differs from canonical topology")
    for partition, expected in (
        (result.resolved_section_ids, expected_resolved),
        (result.unavailable_section_ids, expected_unavailable),
    ):
        if type(partition) is not tuple:
            raise ValueError("section coverage partition must be an exact tuple")
        for key in partition:
            _identity(key)
        if partition != expected:
            raise ValueError("section coverage partition does not close")
    d = result.diagnostics
    if type(d) is not SectionOpticalBindingDiagnostics:
        raise ValueError("invalid optical diagnostics type")
    counts = tuple(getattr(d, f.name) for f in fields(d))
    expected_counts = (
        len(references),
        len(expected_resolved),
        len(expected_unavailable),
        len(occupied),
        len({b.receiver_id for b in result.bindings_by_section.values()}),
    )
    if any(type(c) is not int for c in counts) or counts != expected_counts:
        raise ValueError("optical diagnostic counts do not close")
