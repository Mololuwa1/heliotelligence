"""Dormant S8 reverse-breakdown evidence for explicit Stage4a-1 sections."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from numbers import Real
from types import MappingProxyType

from heliotelligence.physics import string_member_topology_authority as parent_contract

SECTION_REVERSE_BREAKDOWN_CONTRACT_ID = "explicit_bypass_section_reverse_breakdown_authority_v1"
SECTION_REVERSE_BREAKDOWN_MODEL_ID = "bishop88_explicit_section_reverse_breakdown_parameters_v1"
SECTION_REVERSE_BREAKDOWN_SCOPE = (
    "advanced_s8_section_reverse_breakdown_before_diode_clamp_and_series_composition"
)
SECTION_REVERSE_BREAKDOWN_COVERAGE_SCOPE = (
    "explicit_stage4a1_bypass_sections_with_reviewed_reverse_breakdown_parameters"
)
_CONFIDENCE = frozenset({"high", "medium", "low", "unknown"})


def _text(value: str) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("identity/provenance requires exact non-empty unpadded text")


@dataclass(frozen=True)
class BypassSectionIdentity:
    module_id: str
    section_id: str

    def __post_init__(self) -> None:
        _text(self.module_id)
        _text(self.section_id)


@dataclass(frozen=True)
class SectionReverseBreakdownAuthority:
    """Section-equivalent Bishop parameters, never inferred cell/module values."""

    identity: BypassSectionIdentity
    breakdown_factor: float
    breakdown_voltage_v: float
    breakdown_exponent: float
    parameter_source: str
    confidence: str
    method_reference: str
    applicability_description: str
    contract: str = SECTION_REVERSE_BREAKDOWN_CONTRACT_ID
    model: str = SECTION_REVERSE_BREAKDOWN_MODEL_ID
    scope: str = SECTION_REVERSE_BREAKDOWN_SCOPE
    coverage_scope: str = SECTION_REVERSE_BREAKDOWN_COVERAGE_SCOPE

    def __post_init__(self) -> None:
        # Full independent checks also protect callers passing forged identities.
        validate_section_reverse_breakdown_parameters(self)


def validate_section_reverse_breakdown_parameters(
    authority: SectionReverseBreakdownAuthority,
) -> None:
    """Inspect frozen fields directly; no constructor, resolver or admission helper."""
    if type(authority) is not SectionReverseBreakdownAuthority:
        raise ValueError("authority type must be exact")
    identity = authority.identity
    if type(identity) is not BypassSectionIdentity:
        raise ValueError("section identity type must be exact")
    for value in (
        identity.module_id,
        identity.section_id,
        authority.parameter_source,
        authority.confidence,
        authority.method_reference,
        authority.applicability_description,
    ):
        if type(value) is not str or not value or value != value.strip():
            raise ValueError("invalid exact section identity/provenance")
    if authority.confidence not in _CONFIDENCE:
        raise ValueError("unknown confidence")
    for numeric_value in (
        authority.breakdown_factor,
        authority.breakdown_voltage_v,
        authority.breakdown_exponent,
    ):
        if (
            isinstance(numeric_value, bool)
            or not isinstance(numeric_value, Real)
            or not math.isfinite(numeric_value)
        ):
            raise ValueError("breakdown parameters must be finite non-Boolean reals")
    if not 0 <= authority.breakdown_factor <= 1:
        raise ValueError("breakdown_factor must be in [0, 1]")
    if authority.breakdown_voltage_v >= 0 or authority.breakdown_exponent <= 0:
        raise ValueError("breakdown voltage must be negative and exponent positive")
    for value, expected in (
        (authority.contract, SECTION_REVERSE_BREAKDOWN_CONTRACT_ID),
        (authority.model, SECTION_REVERSE_BREAKDOWN_MODEL_ID),
        (authority.scope, SECTION_REVERSE_BREAKDOWN_SCOPE),
        (authority.coverage_scope, SECTION_REVERSE_BREAKDOWN_COVERAGE_SCOPE),
    ):
        if type(value) is not str or value != expected:
            raise ValueError("invalid reverse-breakdown contract semantics")


@dataclass(frozen=True)
class SectionReverseBreakdownDiagnostics:
    topology_section_count: int
    reverse_authority_section_count: int
    reverse_authority_unavailable_section_count: int
    avalanche_enabled_section_count: int


@dataclass(frozen=True)
class SectionReverseBreakdownAuthorityResult:
    authorities_by_section: Mapping[BypassSectionIdentity, SectionReverseBreakdownAuthority]
    resolved_section_ids: tuple[BypassSectionIdentity, ...]
    unavailable_section_ids: tuple[BypassSectionIdentity, ...]
    diagnostics: SectionReverseBreakdownDiagnostics
    contract: str = SECTION_REVERSE_BREAKDOWN_CONTRACT_ID
    model: str = SECTION_REVERSE_BREAKDOWN_MODEL_ID
    scope: str = SECTION_REVERSE_BREAKDOWN_SCOPE
    coverage_scope: str = SECTION_REVERSE_BREAKDOWN_COVERAGE_SCOPE


def _parent_section_pairs(
    parent: parent_contract.TopologyStringMemberAuthorityResult,
) -> tuple[tuple[str, str], ...]:
    """Validate the supplied parent internally, without reconstructing SiteConfig.

    Stage4a-1 owns binding to physical StringConfig counts. Here we check all
    reconstructible parent invariants, not evidence authenticity or a new binding.
    """
    p = parent_contract
    if type(parent) is not p.TopologyStringMemberAuthorityResult:
        raise ValueError("expected exact Stage4a-1 parent result")
    for value, expected in (
        (parent.contract, p.STRING_MEMBER_TOPOLOGY_AUTHORITY_CONTRACT_ID),
        (parent.model, p.STRING_MEMBER_TOPOLOGY_AUTHORITY_MODEL_ID),
        (parent.scope, p.STRING_MEMBER_TOPOLOGY_AUTHORITY_SCOPE),
        (parent.coverage_scope, p.STRING_MEMBER_TOPOLOGY_AUTHORITY_COVERAGE_SCOPE),
    ):
        if type(value) is not str or value != expected:
            raise ValueError("invalid Stage4a-1 parent semantics")
    if type(parent.authorities_by_string_id) is not MappingProxyType:
        raise ValueError("Stage4a-1 parent mapping must be immutable")
    identifiers: list[str] = []
    for partition in (parent.advanced_resolved_string_ids, parent.advanced_unavailable_string_ids):
        if type(partition) is not tuple:
            raise ValueError("invalid Stage4a-1 coverage tuple")
        for key in partition:
            if type(key) is not str or not key or key != key.strip() or key in identifiers:
                raise ValueError("invalid Stage4a-1 string identity partition")
            identifiers.append(key)
    if tuple(parent.authorities_by_string_id) != parent.advanced_resolved_string_ids:
        raise ValueError("Stage4a-1 parent ordering mismatch")
    pairs: list[tuple[str, str]] = []
    modules: set[str] = set()
    for key, authority in parent.authorities_by_string_id.items():
        if type(authority) is not p.StringMemberTopologyAuthority or authority.string_id != key:
            raise ValueError("invalid Stage4a-1 string binding")
        for text in (
            authority.string_id,
            authority.parameter_source,
            authority.confidence,
            authority.method_reference,
            authority.applicability_description,
        ):
            if type(text) is not str or not text or text != text.strip():
                raise ValueError("invalid Stage4a-1 provenance")
        if authority.confidence not in _CONFIDENCE:
            raise ValueError("invalid Stage4a-1 confidence")
        if type(authority.module_members) is not tuple or not authority.module_members:
            raise ValueError("invalid Stage4a-1 module tuple")
        for index, member in enumerate(authority.module_members):
            if type(member) is not p.PhysicalModuleMember:
                raise ValueError("invalid Stage4a-1 module record")
            for text in (member.module_id, member.physical_position_reference):
                if type(text) is not str or not text or text != text.strip():
                    raise ValueError("invalid Stage4a-1 module identity/provenance")
            if type(member.series_index) is not int or member.series_index != index:
                raise ValueError("invalid Stage4a-1 member order")
            if member.module_id in modules:
                raise ValueError("duplicate Stage4a-1 physical module")
            modules.add(member.module_id)
            if (
                type(member.bypass_protected_sections) is not tuple
                or not member.bypass_protected_sections
            ):
                raise ValueError("invalid Stage4a-1 section tuple")
            sections: set[str] = set()
            for section in member.bypass_protected_sections:
                if type(section) is not p.BypassProtectedSection:
                    raise ValueError("invalid Stage4a-1 section record")
                label = section.section_id
                if (
                    type(label) is not str
                    or not label
                    or label != label.strip()
                    or label in sections
                ):
                    raise ValueError("invalid Stage4a-1 local section identity")
                sections.add(label)
                for count in (section.series_cells_per_branch, section.parallel_cell_branches):
                    if type(count) is not int or count <= 0:
                        raise ValueError("invalid Stage4a-1 cell/branch count")
                pairs.append((member.module_id, label))
    d = parent.diagnostics
    if type(d) is not p.StringMemberTopologyDiagnostics:
        raise ValueError("invalid Stage4a-1 diagnostics type")
    actual = tuple(getattr(d, f.name) for f in fields(d))
    expected_counts = (
        len(identifiers),
        len(parent.advanced_resolved_string_ids),
        len(parent.advanced_unavailable_string_ids),
        len(modules),
        len(pairs),
    )
    if any(type(v) is not int for v in actual) or actual != expected_counts:
        raise ValueError("Stage4a-1 diagnostics do not close")
    return tuple(pairs)


def resolve_section_reverse_breakdown_authority(
    parent: parent_contract.TopologyStringMemberAuthorityResult,
    authority_by_section: Mapping[BypassSectionIdentity, SectionReverseBreakdownAuthority],
) -> SectionReverseBreakdownAuthorityResult:
    """Admit explicit partial section evidence in parent order; no numerical work."""
    pairs = _parent_section_pairs(parent)
    if not isinstance(authority_by_section, Mapping):
        raise ValueError("section authority must be a mapping")
    supplied: dict[tuple[str, str], SectionReverseBreakdownAuthority] = {}
    for key, authority in authority_by_section.items():
        validate_section_reverse_breakdown_parameters(authority)
        if type(key) is not BypassSectionIdentity or key != authority.identity:
            raise ValueError("mapping key and embedded section identity disagree")
        for text in (key.module_id, key.section_id):
            if type(text) is not str or not text or text != text.strip():
                raise ValueError("invalid exact mapping section identity")
        pair = (key.module_id, key.section_id)
        if pair not in pairs or pair in supplied:
            raise ValueError("unknown or duplicate Stage4a-1 section")
        supplied[pair] = authority
    copied: dict[BypassSectionIdentity, SectionReverseBreakdownAuthority] = {}
    unavailable: list[BypassSectionIdentity] = []
    for pair in pairs:
        identity = BypassSectionIdentity(*pair)
        if pair in supplied:
            copied[identity] = replace(supplied[pair], identity=identity)
        else:
            unavailable.append(identity)
    result = SectionReverseBreakdownAuthorityResult(
        MappingProxyType(copied),
        tuple(copied),
        tuple(unavailable),
        SectionReverseBreakdownDiagnostics(
            len(pairs),
            len(copied),
            len(unavailable),
            sum(v.breakdown_factor > 0 for v in copied.values()),
        ),
    )
    validate_section_reverse_breakdown_authority(parent, result)
    return result


def validate_section_reverse_breakdown_authority(
    parent: parent_contract.TopologyStringMemberAuthorityResult,
    result: SectionReverseBreakdownAuthorityResult,
) -> None:
    """Reconstruct coverage, parameters and counts without any admission builder."""
    pairs = _parent_section_pairs(parent)
    if type(result) is not SectionReverseBreakdownAuthorityResult:
        raise ValueError("invalid reverse authority result type")
    for name, expected in (
        ("contract", SECTION_REVERSE_BREAKDOWN_CONTRACT_ID),
        ("model", SECTION_REVERSE_BREAKDOWN_MODEL_ID),
        ("scope", SECTION_REVERSE_BREAKDOWN_SCOPE),
        ("coverage_scope", SECTION_REVERSE_BREAKDOWN_COVERAGE_SCOPE),
    ):
        value = getattr(result, name)
        if type(value) is not str or value != expected:
            raise ValueError("invalid reverse authority result semantics")
    if type(result.authorities_by_section) is not MappingProxyType:
        raise ValueError("reverse authority mapping must be immutable")
    actual: list[tuple[str, str]] = []
    for key, authority in result.authorities_by_section.items():
        validate_section_reverse_breakdown_parameters(authority)
        if type(key) is not BypassSectionIdentity or key != authority.identity:
            raise ValueError("invalid section mapping identity")
        for text in (key.module_id, key.section_id):
            if type(text) is not str or not text or text != text.strip():
                raise ValueError("invalid exact mapping section identity")
        pair = (key.module_id, key.section_id)
        if pair not in pairs or pair in actual:
            raise ValueError("unknown/repeated section authority")
        actual.append(pair)
    resolved = [pair for pair in pairs if pair in actual]
    if actual != resolved:
        raise ValueError("reverse authority must retain Stage4a-1 order")
    unavailable = [pair for pair in pairs if pair not in actual]
    for partition, expected_pairs in (
        (result.resolved_section_ids, resolved),
        (result.unavailable_section_ids, unavailable),
    ):
        if type(partition) is not tuple or any(
            type(k) is not BypassSectionIdentity for k in partition
        ):
            raise ValueError("invalid section identity partition")
        if any(
            type(text) is not str or not text or text != text.strip()
            for key in partition
            for text in (key.module_id, key.section_id)
        ):
            raise ValueError("invalid exact section partition identity")
        if [(k.module_id, k.section_id) for k in partition] != expected_pairs:
            raise ValueError("section partition does not close")
    d = result.diagnostics
    if type(d) is not SectionReverseBreakdownDiagnostics:
        raise ValueError("invalid reverse diagnostics type")
    counts = tuple(getattr(d, f.name) for f in fields(d))
    expected_counts = (
        len(pairs),
        len(resolved),
        len(unavailable),
        sum(v.breakdown_factor > 0 for v in result.authorities_by_section.values()),
    )
    if any(type(v) is not int for v in counts) or counts != expected_counts:
        raise ValueError("reverse authority diagnostics do not close")
