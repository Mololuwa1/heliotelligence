"""Dormant S8 series composition at explicit caller currents, without selection."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.physics.string_member_topology_authority import (
    StringMemberTopologyAuthority,
    TopologyStringMemberAuthorityResult,
)
from heliotelligence.physics.string_section_bypass_clamp import (
    evaluate_section_bypass_clamp,
    validate_common_current_grid,
)
from heliotelligence.physics.string_section_bypass_diode_authority import (
    SectionBypassDiodeAuthority,
    SectionBypassDiodeAuthorityResult,
    validate_section_bypass_diode_authority,
)
from heliotelligence.physics.string_section_reverse_breakdown_authority import (
    BypassSectionIdentity,
    SectionReverseBreakdownAuthority,
    SectionReverseBreakdownAuthorityResult,
)
from heliotelligence.physics.string_section_reverse_iv import (
    SectionSingleDiodeOperatingState,
    validate_section_single_diode_operating_state,
)

COMMON_CURRENT_COMPOSITION_CONTRACT_ID = (
    "explicit_topology_common_current_section_module_string_iv_v1"
)
COMMON_CURRENT_COMPOSITION_MODEL_ID = (
    "ordered_series_voltage_sum_with_explicit_section_bypass_clamps_v1"
)
COMMON_CURRENT_COMPOSITION_SCOPE = (
    "advanced_s8_physical_string_terminal_iv_before_dc_branch_and_mppt"
)
COMMON_CURRENT_COMPOSITION_COVERAGE_SCOPE = (
    "complete_per_string_section_sdm_reverse_breakdown_and_bypass_diode_authority"
)
STRING_TERMINAL_REFERENCE_PLANE = "string_terminal"


@dataclass(frozen=True)
class SectionEvidenceGap:
    identity: BypassSectionIdentity
    missing_kinds: tuple[str, ...]


@dataclass(frozen=True)
class SectionCompositionInput:
    operating_state: SectionSingleDiodeOperatingState
    reverse_authority: SectionReverseBreakdownAuthority
    diode_authority: SectionBypassDiodeAuthority


@dataclass(frozen=True)
class CommonCurrentCompositionDiagnostics:
    topology_string_count: int
    candidate_string_count: int
    resolved_string_count: int
    unavailable_candidate_string_count: int
    topology_unavailable_string_count: int
    section_sample_count: int
    module_sample_count: int
    string_sample_count: int
    common_current_sample_count: int


@dataclass(frozen=True)
class TopologyCommonCurrentIVResult:
    section_samples: pd.DataFrame
    module_samples: pd.DataFrame
    string_iv_curves_by_string_id: Mapping[str, pd.DataFrame]
    resolved_string_ids: tuple[str, ...]
    unavailable_string_ids: tuple[str, ...]
    topology_unavailable_string_ids: tuple[str, ...]
    missing_evidence_by_string_id: Mapping[str, tuple[SectionEvidenceGap, ...]]
    section_inputs_by_identity: Mapping[BypassSectionIdentity, SectionCompositionInput]
    topology_authorities_by_string_id: Mapping[str, StringMemberTopologyAuthority]
    common_currents_a: tuple[float, ...]
    diagnostics: CommonCurrentCompositionDiagnostics
    reference_plane: str = STRING_TERMINAL_REFERENCE_PLANE
    contract: str = COMMON_CURRENT_COMPOSITION_CONTRACT_ID
    model: str = COMMON_CURRENT_COMPOSITION_MODEL_ID
    scope: str = COMMON_CURRENT_COMPOSITION_SCOPE
    coverage_scope: str = COMMON_CURRENT_COMPOSITION_COVERAGE_SCOPE


_SECTION_COLUMNS = (
    "string_id",
    "module_id",
    "module_series_index",
    "section_id",
    "section_index",
    "physical_position_reference",
    "curve_point",
    "common_current_a",
    "raw_pv_voltage_v",
    "raw_voltage_evaluated",
    "raw_voltage_state",
    "pv_branch_current_a",
    "bypass_current_a",
    "pv_branch_voltage_v",
    "terminal_voltage_v",
    "bypass_active",
    "clamp_transition_current_a",
    "forward_voltage_v",
)
_MODULE_COLUMNS = (
    "string_id",
    "module_id",
    "module_series_index",
    "curve_point",
    "current_a",
    "voltage_v",
)


def compose_topology_common_current_iv(
    parent: TopologyStringMemberAuthorityResult,
    reverse_authority: SectionReverseBreakdownAuthorityResult,
    diode_authority: SectionBypassDiodeAuthorityResult,
    states_by_section: Mapping[BypassSectionIdentity, SectionSingleDiodeOperatingState],
    common_currents_a: tuple[float, ...],
) -> TopologyCommonCurrentIVResult:
    """Compose complete advanced candidates only; never hybridize missing sections.

    Unavailable Stage4a-1 strings remain a separate ordered partition because
    their parent result does not retain full interleaving with resolved strings.
    No topology, baseline substitution, adapter, peak or operating point is made.
    """
    validate_section_bypass_diode_authority(parent, reverse_authority, diode_authority)
    validate_common_current_grid(common_currents_a)
    if not isinstance(states_by_section, Mapping):
        raise ValueError("section states require an explicit mapping")
    known = {
        (m.module_id, s.section_id)
        for a in parent.authorities_by_string_id.values()
        for m in a.module_members
        for s in m.bypass_protected_sections
    }
    for identity, state in states_by_section.items():
        if type(identity) is not BypassSectionIdentity:
            raise ValueError("state key must be canonical section identity")
        for text in (identity.module_id, identity.section_id):
            if type(text) is not str or not text or text != text.strip():
                raise ValueError("invalid exact state section identity")
        if (identity.module_id, identity.section_id) not in known:
            raise ValueError("state supplied for unknown advanced section")
        validate_section_single_diode_operating_state(state)
    sections = []
    modules: list[dict[str, str | int | float]] = []
    curves: dict[str, pd.DataFrame] = {}
    gaps: dict[str, tuple[SectionEvidenceGap, ...]] = {}
    provenance = {}
    topologies = {}
    for string_id, topology in parent.authorities_by_string_id.items():
        # Snapshot *all* candidate topology provenance, including unavailable ones.
        topologies[string_id] = replace(
            topology,
            module_members=tuple(
                replace(
                    m,
                    bypass_protected_sections=tuple(
                        replace(s) for s in m.bypass_protected_sections
                    ),
                )
                for m in topology.module_members
            ),
        )
        missing = []
        for m in topology.module_members:
            for s in m.bypass_protected_sections:
                key = BypassSectionIdentity(m.module_id, s.section_id)
                kinds = tuple(
                    kind
                    for kind, present in (
                        ("reverse_breakdown", key in reverse_authority.authorities_by_section),
                        ("bypass_diode", key in diode_authority.authorities_by_section),
                        ("operating_state", key in states_by_section),
                    )
                    if not present
                )
                if kinds:
                    missing.append(SectionEvidenceGap(key, kinds))
        if missing:
            gaps[string_id] = tuple(missing)
            continue
        module_voltages = []
        for m in topology.module_members:
            section_voltages = []
            for index, s in enumerate(m.bypass_protected_sections):
                key = BypassSectionIdentity(m.module_id, s.section_id)
                clamped = evaluate_section_bypass_clamp(
                    states_by_section[key],
                    reverse_authority.authorities_by_section[key],
                    diode_authority.authorities_by_section[key],
                    common_currents_a,
                )
                provenance[key] = SectionCompositionInput(
                    clamped.operating_state, clamped.reverse_authority, clamped.diode_authority
                )
                section_voltages.append(clamped.samples.terminal_voltage_v.to_numpy(copy=True))
                frame = clamped.samples.copy(deep=True)
                frame["string_id"] = string_id
                frame["module_id"] = m.module_id
                frame["module_series_index"] = m.series_index
                frame["section_id"] = s.section_id
                frame["section_index"] = index
                frame["physical_position_reference"] = m.physical_position_reference
                sections.append(frame.loc[:, _SECTION_COLUMNS])
            summed = [
                math.fsum(v[point] for v in section_voltages)
                for point in range(len(common_currents_a))
            ]
            module_voltages.append(summed)
            modules.extend(
                dict(
                    string_id=string_id,
                    module_id=m.module_id,
                    module_series_index=m.series_index,
                    curve_point=point,
                    current_a=current,
                    voltage_v=summed[point],
                )
                for point, current in enumerate(common_currents_a)
            )
        voltage = np.array(
            [
                math.fsum(v[point] for v in module_voltages)
                for point in range(len(common_currents_a))
            ]
        )
        with np.errstate(over="raise", invalid="raise"):
            try:
                power = voltage * np.asarray(common_currents_a)
            except FloatingPointError as exc:
                raise ValueError(f"nonfinite string_terminal power for {string_id!r}") from exc
        if not np.isfinite(voltage).all() or not np.isfinite(power).all():
            raise ValueError(f"nonfinite string_terminal series composition for {string_id!r}")
        curves[string_id] = pd.DataFrame(
            dict(
                curve_point=np.arange(len(common_currents_a)),
                current_a=common_currents_a,
                voltage_v=voltage,
                power_w=power,
                reference_plane=STRING_TERMINAL_REFERENCE_PLANE,
            ),
            copy=True,
        )
    section_frame = (
        pd.concat(sections, ignore_index=True)
        if sections
        else pd.DataFrame(columns=_SECTION_COLUMNS)
    )
    module_frame = pd.DataFrame.from_records(modules, columns=_MODULE_COLUMNS)
    diagnostics = CommonCurrentCompositionDiagnostics(
        parent.diagnostics.topology_string_count,
        len(parent.authorities_by_string_id),
        len(curves),
        len(gaps),
        len(parent.advanced_unavailable_string_ids),
        len(section_frame),
        len(module_frame),
        sum(len(f) for f in curves.values()),
        len(common_currents_a),
    )
    return TopologyCommonCurrentIVResult(
        section_frame,
        module_frame,
        MappingProxyType(curves),
        tuple(curves),
        tuple(gaps),
        tuple(parent.advanced_unavailable_string_ids),
        MappingProxyType(gaps),
        MappingProxyType(provenance),
        MappingProxyType(topologies),
        tuple(common_currents_a),
        diagnostics,
    )
