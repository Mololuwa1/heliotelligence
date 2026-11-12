"""Dormant S8 member/section connectivity, without electrical or optical evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from types import MappingProxyType

from heliotelligence.config.site import ElectricalTopologyConfig

STRING_MEMBER_TOPOLOGY_AUTHORITY_CONTRACT_ID = (
    "explicit_string_member_bypass_section_topology_authority_v1"
)
STRING_MEMBER_TOPOLOGY_AUTHORITY_MODEL_ID = (
    "ordered_physical_module_members_and_bypass_protected_sections_v1"
)
STRING_MEMBER_TOPOLOGY_AUTHORITY_SCOPE = (
    "advanced_s8_string_member_electrical_topology_before_section_iv_resolution"
)
STRING_MEMBER_TOPOLOGY_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_existing_physical_strings_with_complete_ordered_member_and_bypass_section_topology"
)
_CONFIDENCE = frozenset({"high", "medium", "low", "unknown"})


def _text(value: str) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("identity/provenance must be exact non-empty unpadded text")


def _integer(value: int, minimum: int = 1) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError("count/index must be an exact integer in its declared domain")


@dataclass(frozen=True)
class BypassProtectedSection:
    """One explicitly declared section; IDs are local to the parent module."""

    section_id: str
    series_cells_per_branch: int
    parallel_cell_branches: int

    def __post_init__(self) -> None:
        _text(self.section_id)
        _integer(self.series_cells_per_branch)
        _integer(self.parallel_cell_branches)


@dataclass(frozen=True)
class PhysicalModuleMember:
    """Zero-based electrical order; section tuple order is explicitly declared."""

    module_id: str
    series_index: int
    physical_position_reference: str
    bypass_protected_sections: tuple[BypassProtectedSection, ...]

    def __post_init__(self) -> None:
        _text(self.module_id)
        _integer(self.series_index, 0)
        _text(self.physical_position_reference)
        sections = self.bypass_protected_sections
        if type(sections) is not tuple or not sections:
            raise ValueError("module requires an exact non-empty section tuple")
        if any(type(s) is not BypassProtectedSection for s in sections):
            raise ValueError("section type must be exact")
        if len({s.section_id for s in sections}) != len(sections):
            raise ValueError("duplicate module-local section IDs")


@dataclass(frozen=True)
class StringMemberTopologyAuthority:
    """Connectivity only; confidence is provenance, never a numerical coefficient."""

    string_id: str
    module_members: tuple[PhysicalModuleMember, ...]
    parameter_source: str
    confidence: str
    method_reference: str
    applicability_description: str

    def __post_init__(self) -> None:
        for value in (
            self.string_id,
            self.parameter_source,
            self.confidence,
            self.method_reference,
            self.applicability_description,
        ):
            _text(value)
        if self.confidence not in _CONFIDENCE:
            raise ValueError("unknown confidence")
        members = self.module_members
        if type(members) is not tuple or not members:
            raise ValueError("string requires an exact non-empty member tuple")
        if any(type(m) is not PhysicalModuleMember for m in members):
            raise ValueError("member type must be exact")
        if tuple(m.series_index for m in members) != tuple(range(len(members))):
            raise ValueError("member indexes must be zero-based contiguous tuple order")
        if len({m.module_id for m in members}) != len(members):
            raise ValueError("duplicate physical module IDs")


@dataclass(frozen=True)
class StringMemberTopologyDiagnostics:
    topology_string_count: int
    advanced_authority_string_count: int
    advanced_unavailable_string_count: int
    module_member_count: int
    bypass_protected_section_count: int


@dataclass(frozen=True)
class TopologyStringMemberAuthorityResult:
    authorities_by_string_id: Mapping[str, StringMemberTopologyAuthority]
    advanced_resolved_string_ids: tuple[str, ...]
    advanced_unavailable_string_ids: tuple[str, ...]
    diagnostics: StringMemberTopologyDiagnostics
    contract: str = STRING_MEMBER_TOPOLOGY_AUTHORITY_CONTRACT_ID
    model: str = STRING_MEMBER_TOPOLOGY_AUTHORITY_MODEL_ID
    scope: str = STRING_MEMBER_TOPOLOGY_AUTHORITY_SCOPE
    coverage_scope: str = STRING_MEMBER_TOPOLOGY_AUTHORITY_COVERAGE_SCOPE


def resolve_topology_string_member_authority(
    topology: ElectricalTopologyConfig,
    authority_by_string_id: Mapping[str, StringMemberTopologyAuthority],
) -> TopologyStringMemberAuthorityResult:
    """Admit an explicit subset; copy all records and retain physical topology order.

    Resolution here means static connectivity coverage, never timestamped I-V
    resolution. No advanced dispatcher or baseline fallback is executed.
    """
    if type(topology) is not ElectricalTopologyConfig:
        raise ValueError("topology must be exactly ElectricalTopologyConfig")
    if not isinstance(authority_by_string_id, Mapping):
        raise ValueError("authority input must be a mapping")
    strings: dict[str, int] = {}
    for inverter in topology.inverters:
        for mppt in inverter.mppts:
            for string in mppt.strings:
                _text(string.id)
                _integer(string.modules_per_string)
                if string.id in strings:
                    raise ValueError("duplicate topology string")
                strings[string.id] = string.modules_per_string
    copied: dict[str, StringMemberTopologyAuthority] = {}
    for key, authority in authority_by_string_id.items():
        _text(key)
        if key not in strings or type(authority) is not StringMemberTopologyAuthority:
            raise ValueError("unknown string or invalid authority type")
        if authority.string_id != key:
            raise ValueError("mapping key disagrees with authority string ID")
        if type(authority.module_members) is not tuple or any(
            type(m) is not PhysicalModuleMember or type(m.bypass_protected_sections) is not tuple
            for m in authority.module_members
        ):
            raise ValueError("invalid nested member/section containers")
        # Validate original nested fields before copying: constructor coercion or
        # equality with bool must never conceal forged frozen records.
        probe = TopologyStringMemberAuthorityResult(
            MappingProxyType({key: authority}),
            (key,),
            tuple(s for s in strings if s != key),
            StringMemberTopologyDiagnostics(
                len(strings),
                1,
                len(strings) - 1,
                len(authority.module_members),
                sum(len(m.bypass_protected_sections) for m in authority.module_members),
            ),
        )
        validate_topology_string_member_authority(topology, probe)
        copied[key] = StringMemberTopologyAuthority(
            authority.string_id,
            tuple(
                PhysicalModuleMember(
                    m.module_id,
                    m.series_index,
                    m.physical_position_reference,
                    tuple(
                        BypassProtectedSection(
                            s.section_id, s.series_cells_per_branch, s.parallel_cell_branches
                        )
                        for s in m.bypass_protected_sections
                    ),
                )
                for m in authority.module_members
            ),
            authority.parameter_source,
            authority.confidence,
            authority.method_reference,
            authority.applicability_description,
        )
    ordered = {key: copied[key] for key in strings if key in copied}
    unavailable = tuple(key for key in strings if key not in ordered)
    result = TopologyStringMemberAuthorityResult(
        MappingProxyType(ordered),
        tuple(ordered),
        unavailable,
        StringMemberTopologyDiagnostics(
            len(strings),
            len(ordered),
            len(unavailable),
            sum(len(a.module_members) for a in ordered.values()),
            sum(
                len(m.bypass_protected_sections) for a in ordered.values() for m in a.module_members
            ),
        ),
    )
    validate_topology_string_member_authority(topology, result)
    return result


def validate_topology_string_member_authority(
    topology: ElectricalTopologyConfig,
    result: TopologyStringMemberAuthorityResult,
) -> None:
    """Independently reconstruct nested invariants and closure, without builders.

    This intentionally does not call constructors, post-init checks, resolver,
    private admission helpers, numerical physics or equality against a rebuild.
    """
    if type(topology) is not ElectricalTopologyConfig:
        raise ValueError("invalid topology type")
    if type(result) is not TopologyStringMemberAuthorityResult:
        raise ValueError("invalid result type")
    expected: dict[str, int] = {}
    for inverter in topology.inverters:
        for mppt in inverter.mppts:
            for string in mppt.strings:
                key, count = string.id, string.modules_per_string
                if type(key) is not str or not key or key != key.strip() or key in expected:
                    raise ValueError("invalid or repeated physical string identity")
                if type(count) is not int or count <= 0:
                    raise ValueError("invalid physical StringConfig member count")
                expected[key] = count
    fixed = (
        (result.contract, STRING_MEMBER_TOPOLOGY_AUTHORITY_CONTRACT_ID),
        (result.model, STRING_MEMBER_TOPOLOGY_AUTHORITY_MODEL_ID),
        (result.scope, STRING_MEMBER_TOPOLOGY_AUTHORITY_SCOPE),
        (result.coverage_scope, STRING_MEMBER_TOPOLOGY_AUTHORITY_COVERAGE_SCOPE),
    )
    if any(type(value) is not str or value != required for value, required in fixed):
        raise ValueError("invalid fixed contract semantics")
    if type(result.authorities_by_string_id) is not MappingProxyType:
        raise ValueError("public authority mapping must be immutable")
    authorities = result.authorities_by_string_id
    if any(type(k) is not str or k not in expected for k in authorities):
        raise ValueError("unknown physical string")
    resolved = tuple(k for k in expected if k in authorities)
    unavailable = tuple(k for k in expected if k not in authorities)
    if tuple(authorities) != resolved:
        raise ValueError("authority mapping must retain topology order")
    for actual, required in (
        (result.advanced_resolved_string_ids, resolved),
        (result.advanced_unavailable_string_ids, unavailable),
    ):
        if type(actual) is not tuple or actual != required:
            raise ValueError("invalid coverage partition or ordering")
    seen_modules: set[str] = set()
    member_count = section_count = 0
    for key, authority in authorities.items():
        if type(authority) is not StringMemberTopologyAuthority:
            raise ValueError("invalid string authority record")
        for text in (
            authority.string_id,
            authority.parameter_source,
            authority.confidence,
            authority.method_reference,
            authority.applicability_description,
        ):
            if type(text) is not str or not text or text != text.strip():
                raise ValueError("invalid identity/provenance")
        if authority.string_id != key or authority.confidence not in _CONFIDENCE:
            raise ValueError("invalid string binding or confidence")
        members = authority.module_members
        if type(members) is not tuple or not members or len(members) != expected[key]:
            raise ValueError("member tuple must match physical StringConfig count")
        for index, member in enumerate(members):
            if type(member) is not PhysicalModuleMember:
                raise ValueError("invalid module record")
            for text in (member.module_id, member.physical_position_reference):
                if type(text) is not str or not text or text != text.strip():
                    raise ValueError("invalid module identity/position reference")
            if type(member.series_index) is not int or member.series_index != index:
                raise ValueError("invalid member electrical order")
            if member.module_id in seen_modules:
                raise ValueError("physical module belongs to multiple members/strings")
            seen_modules.add(member.module_id)
            member_count += 1
            sections = member.bypass_protected_sections
            if type(sections) is not tuple or not sections:
                raise ValueError("invalid section tuple")
            seen_sections: set[str] = set()
            for section in sections:
                if type(section) is not BypassProtectedSection:
                    raise ValueError("invalid section record")
                label = section.section_id
                if type(label) is not str or not label or label != label.strip():
                    raise ValueError("invalid section identity")
                if label in seen_sections:
                    raise ValueError("duplicate module-local section")
                seen_sections.add(label)
                for count in (section.series_cells_per_branch, section.parallel_cell_branches):
                    if type(count) is not int or count <= 0:
                        raise ValueError(
                            "section cell/branch counts require positive exact integers"
                        )
                section_count += 1
    diagnostics = result.diagnostics
    if type(diagnostics) is not StringMemberTopologyDiagnostics:
        raise ValueError("invalid diagnostics type")
    counts = (len(expected), len(resolved), len(unavailable), member_count, section_count)
    actual_counts = tuple(getattr(diagnostics, f.name) for f in fields(diagnostics))
    if any(type(c) is not int or c < 0 for c in actual_counts) or actual_counts != counts:
        raise ValueError("diagnostics do not close")
