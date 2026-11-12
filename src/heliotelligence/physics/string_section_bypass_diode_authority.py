"""Dormant explicit constant-forward-voltage diode evidence for S8 sections."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from numbers import Real
from types import MappingProxyType

from heliotelligence.physics.string_member_topology_authority import (
    TopologyStringMemberAuthorityResult,
)
from heliotelligence.physics.string_section_reverse_breakdown_authority import (
    BypassSectionIdentity,
    SectionReverseBreakdownAuthorityResult,
    validate_section_reverse_breakdown_authority,
)

BYPASS_DIODE_CONTRACT_ID = "explicit_bypass_section_diode_authority_v1"
BYPASS_DIODE_MODEL_ID = "constant_forward_voltage_bypass_diode_v1"
BYPASS_DIODE_SCOPE = "advanced_s8_section_bypass_diode_before_common_current_composition"
BYPASS_DIODE_COVERAGE_SCOPE = (
    "explicit_stage4a1_bypass_sections_with_reviewed_diode_forward_voltage"
)


@dataclass(frozen=True)
class SectionBypassDiodeAuthority:
    identity: BypassSectionIdentity
    forward_voltage_v: float
    parameter_source: str
    confidence: str
    method_reference: str
    applicability_description: str
    contract: str = BYPASS_DIODE_CONTRACT_ID
    model: str = BYPASS_DIODE_MODEL_ID
    scope: str = BYPASS_DIODE_SCOPE
    coverage_scope: str = BYPASS_DIODE_COVERAGE_SCOPE

    def __post_init__(self) -> None:
        validate_section_bypass_diode_parameters(self)


def validate_section_bypass_diode_parameters(authority: SectionBypassDiodeAuthority) -> None:
    """Inspect original frozen fields without constructors or admission builders."""
    if type(authority) is not SectionBypassDiodeAuthority:
        raise ValueError("expected exact section diode authority")
    if type(authority.identity) is not BypassSectionIdentity:
        raise ValueError("expected canonical section identity")
    for text in (
        authority.identity.module_id,
        authority.identity.section_id,
        authority.parameter_source,
        authority.confidence,
        authority.method_reference,
        authority.applicability_description,
    ):
        if type(text) is not str or not text or text != text.strip():
            raise ValueError("invalid exact diode identity/provenance")
    value = authority.forward_voltage_v
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError("forward_voltage_v must be a positive finite non-Boolean real")
    if authority.confidence not in {"high", "medium", "low", "unknown"}:
        raise ValueError("unknown diode confidence")
    for name, required in _FIXED:
        value = getattr(authority, name)
        if type(value) is not str or value != required:
            raise ValueError("invalid diode contract semantics")


_FIXED = (
    ("contract", BYPASS_DIODE_CONTRACT_ID),
    ("model", BYPASS_DIODE_MODEL_ID),
    ("scope", BYPASS_DIODE_SCOPE),
    ("coverage_scope", BYPASS_DIODE_COVERAGE_SCOPE),
)


@dataclass(frozen=True)
class SectionBypassDiodeDiagnostics:
    topology_section_count: int
    diode_authority_section_count: int
    diode_authority_unavailable_section_count: int


@dataclass(frozen=True)
class SectionBypassDiodeAuthorityResult:
    authorities_by_section: Mapping[BypassSectionIdentity, SectionBypassDiodeAuthority]
    resolved_section_ids: tuple[BypassSectionIdentity, ...]
    unavailable_section_ids: tuple[BypassSectionIdentity, ...]
    diagnostics: SectionBypassDiodeDiagnostics
    contract: str = BYPASS_DIODE_CONTRACT_ID
    model: str = BYPASS_DIODE_MODEL_ID
    scope: str = BYPASS_DIODE_SCOPE
    coverage_scope: str = BYPASS_DIODE_COVERAGE_SCOPE


def _section_pairs(parent: TopologyStringMemberAuthorityResult) -> tuple[tuple[str, str], ...]:
    # Caller first validates the canonical Stage4a-1/2 parent via its public validator.
    return tuple(
        (m.module_id, s.section_id)
        for a in parent.authorities_by_string_id.values()
        for m in a.module_members
        for s in m.bypass_protected_sections
    )


def resolve_section_bypass_diode_authority(
    parent: TopologyStringMemberAuthorityResult,
    reverse_authority: SectionReverseBreakdownAuthorityResult,
    supplied: Mapping[BypassSectionIdentity, SectionBypassDiodeAuthority],
) -> SectionBypassDiodeAuthorityResult:
    """Bind diode evidence to Stage4a-1; reverse coverage itself may be empty.

    The Stage4a-2 result enables reuse of its public parent-integrity validator;
    it does not restrict diode coverage to reverse-electrically resolved sections.
    """
    validate_section_reverse_breakdown_authority(parent, reverse_authority)
    if not isinstance(supplied, Mapping):
        raise ValueError("diode evidence must be an explicit mapping")
    pairs = _section_pairs(parent)
    for key, authority in supplied.items():
        validate_section_bypass_diode_parameters(authority)
        if type(key) is not BypassSectionIdentity or key != authority.identity:
            raise ValueError("diode mapping identity mismatch")
        if (key.module_id, key.section_id) not in pairs:
            raise ValueError("unknown Stage4a-1 section")
    copied = {}
    unavailable = []
    for pair in pairs:
        identity = BypassSectionIdentity(*pair)
        if identity in supplied:
            copied[identity] = replace(supplied[identity], identity=identity)
        else:
            unavailable.append(identity)
    result = SectionBypassDiodeAuthorityResult(
        MappingProxyType(copied),
        tuple(copied),
        tuple(unavailable),
        SectionBypassDiodeDiagnostics(len(pairs), len(copied), len(unavailable)),
    )
    validate_section_bypass_diode_authority(parent, reverse_authority, result)
    return result


def validate_section_bypass_diode_authority(
    parent: TopologyStringMemberAuthorityResult,
    reverse_authority: SectionReverseBreakdownAuthorityResult,
    result: SectionBypassDiodeAuthorityResult,
) -> None:
    """Independent field/coverage/count inspection, never rebuilding a result."""
    validate_section_reverse_breakdown_authority(parent, reverse_authority)
    if type(result) is not SectionBypassDiodeAuthorityResult:
        raise ValueError("invalid diode authority result type")
    for name, required in _FIXED:
        value = getattr(result, name)
        if type(value) is not str or value != required:
            raise ValueError("invalid diode result semantics")
    if type(result.authorities_by_section) is not MappingProxyType:
        raise ValueError("diode mapping must be immutable")
    # Reconstruct order directly from the validated parent, not resolver helpers.
    pairs = [
        (m.module_id, s.section_id)
        for a in parent.authorities_by_string_id.values()
        for m in a.module_members
        for s in m.bypass_protected_sections
    ]
    actual = []
    for key, authority in result.authorities_by_section.items():
        validate_section_bypass_diode_parameters(authority)
        if type(key) is not BypassSectionIdentity or key != authority.identity:
            raise ValueError("invalid diode mapping identity")
        for text in (key.module_id, key.section_id):
            if type(text) is not str or not text or text != text.strip():
                raise ValueError("invalid canonical diode identity")
        pair = (key.module_id, key.section_id)
        if pair not in pairs or pair in actual:
            raise ValueError("unknown/repeated diode section")
        actual.append(pair)
    expected = [pair for pair in pairs if pair in actual]
    if actual != expected:
        raise ValueError("diode evidence ordering differs from parent")
    for partition, required_pairs in (
        (result.resolved_section_ids, expected),
        (result.unavailable_section_ids, [p for p in pairs if p not in actual]),
    ):
        if type(partition) is not tuple or any(
            type(k) is not BypassSectionIdentity for k in partition
        ):
            raise ValueError("invalid diode coverage tuple")
        if any(
            type(v) is not str or not v or v != v.strip()
            for k in partition
            for v in (k.module_id, k.section_id)
        ):
            raise ValueError("invalid diode partition identity")
        if [(k.module_id, k.section_id) for k in partition] != required_pairs:
            raise ValueError("diode coverage partition does not close")
    if type(result.diagnostics) is not SectionBypassDiodeDiagnostics:
        raise ValueError("invalid diode diagnostic type")
    counts = tuple(getattr(result.diagnostics, f.name) for f in fields(result.diagnostics))
    if any(type(v) is not int for v in counts) or counts != (
        len(pairs),
        len(actual),
        len(pairs) - len(actual),
    ):
        raise ValueError("diode diagnostics do not close")
