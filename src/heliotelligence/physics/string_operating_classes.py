"""Exact per-observation numerical classes; physical identity/provenance is retained.

No rounding, approximate grouping, runtime hash identity or cache lifecycle.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from types import MappingProxyType
from typing import Any, cast

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.geometry.models import SiteGeometry
from heliotelligence.physics.string_member_topology_authority import (
    TopologyStringMemberAuthorityResult,
)
from heliotelligence.physics.string_section_bypass_diode_authority import (
    SectionBypassDiodeAuthorityResult,
    validate_section_bypass_diode_authority,
)
from heliotelligence.physics.string_section_direct_beam_state import (
    DirectBeamVisibilitySnapshot,
    SectionDirectBeamStateResult,
)
from heliotelligence.physics.string_section_electrical_state_authority import (
    SectionElectricalStateAuthorityResult,
    validate_section_electrical_state_authority,
)
from heliotelligence.physics.string_section_optical_binding_authority import (
    SectionOpticalBindingAuthorityResult,
)
from heliotelligence.physics.string_section_reverse_breakdown_authority import (
    BypassSectionIdentity,
    SectionReverseBreakdownAuthorityResult,
)

STRING_CLASS_CONTRACT_ID = "exact_advanced_string_operating_equivalence_classes_v1"
STRING_CLASS_MODEL_ID = "ordered_section_topology_and_complete_numerical_state_equivalence_v1"
STRING_CLASS_SCOPE = "advanced_s8_exact_string_classification_before_method_b_candidate_evaluation"
STRING_CLASS_COVERAGE_SCOPE = "complete_stage4a_section_state_reverse_and_bypass_diode_evidence"
Signature = tuple[tuple[tuple[object, ...], ...], ...]
_STATE_NUMERICS = (
    "effective_irradiance_wm2",
    "cell_temperature_c",
    "photocurrent_a",
    "saturation_current_a",
    "resistance_series_ohm",
    "resistance_shunt_ohm",
    "n_ns_vth_v",
)


def _detach(value: Any) -> Any:
    """Copy validated frozen authorities only; no frames/geometry are passed here."""
    if is_dataclass(value):
        return replace(
            cast(Any, value), **{f.name: _detach(getattr(value, f.name)) for f in fields(value)}
        )
    if isinstance(value, Mapping):
        return MappingProxyType({_detach(k): _detach(v) for k, v in value.items()})
    if isinstance(value, tuple):
        return tuple(_detach(v) for v in value)
    return value


def _same(actual: Any, expected: Any) -> None:
    """Exact frozen-field integrity, including key types and traversal order."""
    if type(actual) is not type(expected):
        raise ValueError("exact field type mismatch")
    if is_dataclass(expected):
        for f in fields(expected):
            _same(getattr(actual, f.name), getattr(expected, f.name))
    elif isinstance(expected, Mapping):
        if len(actual) != len(expected):
            raise ValueError("mapping size mismatch")
        for a, b in zip(actual, expected, strict=True):
            _same(a, b)
            _same(actual[a], expected[b])
    elif isinstance(expected, tuple):
        if len(actual) != len(expected):
            raise ValueError("tuple size mismatch")
        for a, b in zip(actual, expected, strict=True):
            _same(a, b)
    elif isinstance(expected, pd.Timestamp):
        if actual != expected or actual.tz != expected.tz:
            raise ValueError("timestamp/timezone mismatch")
    elif actual != expected:
        raise ValueError("exact value mismatch")


@dataclass(frozen=True)
class StringOperatingClass:
    class_id: str
    representative_string_id: str
    member_string_ids: tuple[str, ...]
    signature: Signature


@dataclass(frozen=True)
class StringOperatingClassDiagnostics:
    topology_string_count: int
    advanced_candidate_string_count: int
    classifiable_string_count: int
    unavailable_string_count: int
    class_count: int
    reused_member_count: int


@dataclass(frozen=True)
class StringOperatingClassesResult:
    classes: tuple[StringOperatingClass, ...]
    class_id_by_string_id: Mapping[str, str]
    unavailable_string_ids: tuple[str, ...]
    topology_authority: TopologyStringMemberAuthorityResult
    electrical_state_authority: SectionElectricalStateAuthorityResult
    reverse_authority: SectionReverseBreakdownAuthorityResult
    diode_authority: SectionBypassDiodeAuthorityResult
    diagnostics: StringOperatingClassDiagnostics
    contract: str = STRING_CLASS_CONTRACT_ID
    model: str = STRING_CLASS_MODEL_ID
    scope: str = STRING_CLASS_SCOPE
    coverage_scope: str = STRING_CLASS_COVERAGE_SCOPE


def _signatures(
    parent: TopologyStringMemberAuthorityResult,
    electrical: SectionElectricalStateAuthorityResult,
    reverse: SectionReverseBreakdownAuthorityResult,
    diode: SectionBypassDiodeAuthorityResult,
) -> dict[str, Signature]:
    result = {}
    for sid, authority in parent.authorities_by_string_id.items():
        modules = []
        complete = True
        for member in authority.module_members:
            sections = []
            for section in member.bypass_protected_sections:
                key = BypassSectionIdentity(member.module_id, section.section_id)
                if not all(
                    key in mapping
                    for mapping in (
                        electrical.bindings_by_section,
                        reverse.authorities_by_section,
                        diode.authorities_by_section,
                    )
                ):
                    complete = False
                    break
                state = electrical.bindings_by_section[key].operating_state
                r = reverse.authorities_by_section[key]
                sections.append(
                    (
                        section.series_cells_per_branch,
                        section.parallel_cell_branches,
                        *(getattr(state, n) for n in _STATE_NUMERICS),
                        r.breakdown_factor,
                        r.breakdown_voltage_v,
                        r.breakdown_exponent,
                        diode.authorities_by_section[key].forward_voltage_v,
                    )
                )
            modules.append(tuple(sections))
        if complete:
            result[sid] = tuple(modules)
    return result


def resolve_string_operating_classes(
    parent: TopologyStringMemberAuthorityResult,
    geometry: SiteGeometry,
    optical_binding: SectionOpticalBindingAuthorityResult,
    snapshots: tuple[DirectBeamVisibilitySnapshot, ...],
    optical_state: SectionDirectBeamStateResult,
    electrical: SectionElectricalStateAuthorityResult,
    reverse: SectionReverseBreakdownAuthorityResult,
    diode: SectionBypassDiodeAuthorityResult,
) -> StringOperatingClassesResult:
    validate_section_electrical_state_authority(
        parent, geometry, optical_binding, snapshots, optical_state, electrical
    )
    validate_section_bypass_diode_authority(parent, reverse, diode)
    signatures = _signatures(parent, electrical, reverse, diode)
    groups: dict[Signature, list[str]] = {}
    for sid, signature in signatures.items():
        groups.setdefault(signature, []).append(sid)
    classes = tuple(
        StringOperatingClass(f"operating-class-{i:04d}", members[0], tuple(members), signature)
        for i, (signature, members) in enumerate(groups.items())
    )
    membership = {
        sid: next(c.class_id for c in classes if sid in c.member_string_ids) for sid in signatures
    }
    unavailable = (
        tuple(sid for sid in parent.authorities_by_string_id if sid not in signatures)
        + parent.advanced_unavailable_string_ids
    )
    result = StringOperatingClassesResult(
        classes,
        MappingProxyType(membership),
        unavailable,
        _detach(parent),
        _detach(electrical),
        _detach(reverse),
        _detach(diode),
        StringOperatingClassDiagnostics(
            parent.diagnostics.topology_string_count,
            len(parent.authorities_by_string_id),
            len(signatures),
            len(unavailable),
            len(classes),
            len(signatures) - len(classes),
        ),
    )
    validate_string_operating_classes(
        parent,
        geometry,
        optical_binding,
        snapshots,
        optical_state,
        electrical,
        reverse,
        diode,
        result,
    )
    return result


def validate_string_operating_classes(
    parent: TopologyStringMemberAuthorityResult,
    geometry: SiteGeometry,
    optical_binding: SectionOpticalBindingAuthorityResult,
    snapshots: tuple[DirectBeamVisibilitySnapshot, ...],
    optical_state: SectionDirectBeamStateResult,
    electrical: SectionElectricalStateAuthorityResult,
    reverse: SectionReverseBreakdownAuthorityResult,
    diode: SectionBypassDiodeAuthorityResult,
    result: StringOperatingClassesResult,
) -> None:
    """Reconstruct signatures/partitions independently; never call class resolver."""
    validate_section_electrical_state_authority(
        parent, geometry, optical_binding, snapshots, optical_state, electrical
    )
    validate_section_bypass_diode_authority(parent, reverse, diode)
    if type(result) is not StringOperatingClassesResult:
        raise ValueError("invalid class result type")
    for name, required in (
        ("contract", STRING_CLASS_CONTRACT_ID),
        ("model", STRING_CLASS_MODEL_ID),
        ("scope", STRING_CLASS_SCOPE),
        ("coverage_scope", STRING_CLASS_COVERAGE_SCOPE),
    ):
        _same(getattr(result, name), required)
    for actual, expected in (
        (result.topology_authority, parent),
        (result.electrical_state_authority, electrical),
        (result.reverse_authority, reverse),
        (result.diode_authority, diode),
    ):
        _same(actual, expected)
    signatures = _signatures(parent, electrical, reverse, diode)
    if (
        type(result.classes) is not tuple
        or type(result.class_id_by_string_id) is not MappingProxyType
    ):
        raise ValueError("class containers must be immutable")
    remaining = list(signatures)
    expected_membership = {}
    for index, group in enumerate(result.classes):
        if type(group) is not StringOperatingClass or not remaining:
            raise ValueError("invalid class partition")
        representative = remaining[0]
        signature = signatures[representative]
        members = tuple(sid for sid in remaining if signatures[sid] == signature)
        _same(group.class_id, f"operating-class-{index:04d}")
        _same(group.representative_string_id, representative)
        _same(group.member_string_ids, members)
        _same(group.signature, signature)
        for sid in members:
            expected_membership[sid] = group.class_id
            remaining.remove(sid)
    if remaining:
        raise ValueError("class partition incomplete")
    expected_membership = {sid: expected_membership[sid] for sid in signatures}
    _same(result.class_id_by_string_id, MappingProxyType(expected_membership))
    unavailable = (
        tuple(sid for sid in parent.authorities_by_string_id if sid not in signatures)
        + parent.advanced_unavailable_string_ids
    )
    _same(result.unavailable_string_ids, unavailable)
    expected_counts = (
        parent.diagnostics.topology_string_count,
        len(parent.authorities_by_string_id),
        len(signatures),
        len(unavailable),
        len(result.classes),
        len(signatures) - len(result.classes),
    )
    if type(result.diagnostics) is not StringOperatingClassDiagnostics:
        raise ValueError("invalid class diagnostics")
    _same(
        tuple(getattr(result.diagnostics, f.name) for f in fields(result.diagnostics)),
        expected_counts,
    )
