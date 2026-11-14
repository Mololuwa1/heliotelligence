"""Dormant Method A orchestration: existing Stage4a owners, no new equations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.geometry.models import SiteGeometry
from heliotelligence.physics.string_common_current_composition import (
    compose_topology_common_current_iv,
)
from heliotelligence.physics.string_member_topology_authority import (
    TopologyStringMemberAuthorityResult,
)
from heliotelligence.physics.string_multi_peak_candidates import (
    AdvancedStringCandidateResult,
    analyze_advanced_string_multi_peak_candidates,
)
from heliotelligence.physics.string_section_bypass_clamp import validate_common_current_grid
from heliotelligence.physics.string_section_bypass_diode_authority import (
    SectionBypassDiodeAuthorityResult,
)
from heliotelligence.physics.string_section_direct_beam_state import (
    DirectBeamVisibilitySnapshot,
    SectionDirectBeamStateResult,
)
from heliotelligence.physics.string_section_electrical_state_authority import (
    SectionElectricalStateAuthorityResult,
    validate_section_electrical_state_authority,
    validate_section_observation_timestamp,
)
from heliotelligence.physics.string_section_optical_binding_authority import (
    SectionOpticalBindingAuthorityResult,
)
from heliotelligence.physics.string_section_reverse_breakdown_authority import (
    SectionReverseBreakdownAuthorityResult,
)

METHOD_A_CONTRACT_ID = "advanced_string_method_a_full_iv_execution_v1"
METHOD_A_MODEL_ID = "explicit_section_state_existing_bishop_clamp_series_and_peak_replay_v1"
METHOD_A_SCOPE = "advanced_s8_method_a_string_terminal_reference_execution_before_dc_branch"
METHOD_A_COVERAGE_SCOPE = (
    "complete_section_operating_reverse_breakdown_bypass_diode_and_topology_evidence"
)


@dataclass(frozen=True)
class Stage4aMethodADiagnostics:
    topology_string_count: int
    electrical_complete_candidate_string_count: int
    resolved_active_string_count: int
    resolved_zero_string_count: int
    unavailable_string_count: int
    candidate_count: int
    local_maximum_count: int


@dataclass(frozen=True)
class Stage4aMethodAResult:
    observation_timestamp: pd.Timestamp
    geometry_revision: str
    optical_snapshot_reference: str | None
    section_electrical_state_authority: SectionElectricalStateAuthorityResult
    advanced_string_candidates: AdvancedStringCandidateResult
    diagnostics: Stage4aMethodADiagnostics
    contract: str = METHOD_A_CONTRACT_ID
    model: str = METHOD_A_MODEL_ID
    scope: str = METHOD_A_SCOPE
    coverage_scope: str = METHOD_A_COVERAGE_SCOPE


def execute_string_method_a(
    parent: TopologyStringMemberAuthorityResult,
    geometry: SiteGeometry,
    optical_binding: SectionOpticalBindingAuthorityResult,
    snapshots: tuple[DirectBeamVisibilitySnapshot, ...],
    optical_state: SectionDirectBeamStateResult,
    electrical_authority: SectionElectricalStateAuthorityResult,
    reverse_authority: SectionReverseBreakdownAuthorityResult,
    diode_authority: SectionBypassDiodeAuthorityResult,
    common_currents_a: tuple[float, ...],
    observation_timestamp: pd.Timestamp,
) -> Stage4aMethodAResult:
    """Validate and execute one explicit snapshot at caller-controlled currents.

    Stage4a-3 owns complete-string gating and Bishop/clamp/series physics;
    Stage4a-4 owns transition replay, search completeness and represented peaks.
    This coordinator neither infers SDM parameters nor dispatches a baseline.
    """
    validate_section_electrical_state_authority(
        parent, geometry, optical_binding, snapshots, optical_state, electrical_authority
    )
    validate_section_observation_timestamp(observation_timestamp)
    if (
        observation_timestamp != electrical_authority.observation_timestamp
        or observation_timestamp.tz != electrical_authority.observation_timestamp.tz
    ):
        raise ValueError("Method A timestamp must exactly match electrical authority")
    validate_common_current_grid(common_currents_a)
    # Own a detached authority without duplicating any numerical frames.
    owned = replace(
        electrical_authority,
        bindings_by_section=MappingProxyType(
            {
                replace(k): replace(
                    v,
                    section_identity=replace(v.section_identity),
                    operating_state=replace(v.operating_state),
                )
                for k, v in electrical_authority.bindings_by_section.items()
            }
        ),
        resolved_section_ids=tuple(replace(k) for k in electrical_authority.resolved_section_ids),
        unavailable_section_ids=tuple(
            replace(k) for k in electrical_authority.unavailable_section_ids
        ),
        diagnostics=replace(electrical_authority.diagnostics),
    )
    states = {k: v.operating_state for k, v in owned.bindings_by_section.items()}
    composition = compose_topology_common_current_iv(
        parent, reverse_authority, diode_authority, states, common_currents_a
    )
    advanced = analyze_advanced_string_multi_peak_candidates(
        parent, reverse_authority, diode_authority, states, composition, observation_timestamp
    )
    d = advanced.diagnostics
    diagnostics = Stage4aMethodADiagnostics(
        d.topology_string_count,
        composition.diagnostics.resolved_string_count,
        d.resolved_active_string_count,
        d.resolved_zero_string_count,
        d.unavailable_string_count,
        d.candidate_count,
        d.local_maximum_count,
    )
    return Stage4aMethodAResult(
        observation_timestamp,
        owned.geometry_revision,
        owned.optical_snapshot_reference,
        owned,
        advanced,
        diagnostics,
    )
