"""Dormant approximate operating-level Method B; Method A remains the reference."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import pandas as pd  # type: ignore[import-untyped]
from pvlib import singlediode  # type: ignore[import-untyped]

from heliotelligence.geometry.models import SiteGeometry
from heliotelligence.physics.string_common_current_composition import (
    TopologyCommonCurrentIVResult,
    compose_topology_common_current_iv,
)
from heliotelligence.physics.string_member_topology_authority import (
    TopologyStringMemberAuthorityResult,
)
from heliotelligence.physics.string_operating_classes import (
    StringOperatingClassesResult,
    resolve_string_operating_classes,
)
from heliotelligence.physics.string_section_bypass_diode_authority import (
    SectionBypassDiodeAuthorityResult,
)
from heliotelligence.physics.string_section_direct_beam_state import (
    DirectBeamVisibilitySnapshot,
    SectionDirectBeamStateResult,
)
from heliotelligence.physics.string_section_electrical_state_authority import (
    SectionElectricalStateAuthorityResult,
)
from heliotelligence.physics.string_section_optical_binding_authority import (
    SectionOpticalBindingAuthorityResult,
)
from heliotelligence.physics.string_section_reverse_breakdown_authority import (
    BypassSectionIdentity,
    SectionReverseBreakdownAuthorityResult,
)

METHOD_B_CONTRACT_ID = "advanced_string_method_b_operating_level_candidates_v1"
METHOD_B_MODEL_ID = (
    "section_bishop_mpp_current_candidates_with_existing_common_current_composition_v1"
)
METHOD_B_SCOPE = "advanced_s8_method_b_candidate_operating_points_before_dc_branch"
METHOD_B_COVERAGE_SCOPE = (
    "complete_section_operating_reverse_breakdown_bypass_diode_and_exact_class_evidence"
)
_COLUMNS = (
    "string_id",
    "class_id",
    "candidate_index",
    "current_a",
    "voltage_v",
    "power_w",
    "source_section_ids",
    "source_section_count",
    "bypass_active_section_ids",
    "bypass_active_section_count",
    "is_selected_method_b",
)


@dataclass(frozen=True)
class MethodBDiagnostics:
    topology_string_count: int
    class_count: int
    classifiable_string_count: int
    resolved_active_string_count: int
    resolved_zero_string_count: int
    unavailable_string_count: int
    unique_candidate_current_count: int
    candidate_row_count: int
    selected_candidate_count: int


@dataclass(frozen=True)
class Stage4aMethodBResult:
    observation_timestamp: pd.Timestamp
    geometry_revision: str
    optical_snapshot_reference: str | None
    section_electrical_state_authority: SectionElectricalStateAuthorityResult
    string_classes: StringOperatingClassesResult
    candidate_currents_by_class: Mapping[str, tuple[float, ...]]
    section_mpp_currents_by_class: Mapping[str, tuple[float, ...]]
    composition: TopologyCommonCurrentIVResult
    candidates: pd.DataFrame
    states: pd.DataFrame
    diagnostics: MethodBDiagnostics
    contract: str = METHOD_B_CONTRACT_ID
    model: str = METHOD_B_MODEL_ID
    scope: str = METHOD_B_SCOPE
    coverage_scope: str = METHOD_B_COVERAGE_SCOPE


def _section_mpp_current(
    classes: StringOperatingClassesResult, key: BypassSectionIdentity
) -> float:
    state = classes.electrical_state_authority.bindings_by_section[key].operating_state
    reverse = classes.reverse_authority.authorities_by_section[key]
    if state.photocurrent_a == 0:
        return 0.0
    try:
        current, voltage, power = map(
            float,
            singlediode.bishop88_mpp(
                photocurrent=state.photocurrent_a,
                saturation_current=state.saturation_current_a,
                resistance_series=state.resistance_series_ohm,
                resistance_shunt=state.resistance_shunt_ohm,
                nNsVth=state.n_ns_vth_v,
                d2mutau=0.0,
                NsVbi=math.inf,
                breakdown_factor=reverse.breakdown_factor,
                breakdown_voltage=reverse.breakdown_voltage_v,
                breakdown_exp=reverse.breakdown_exponent,
                method="newton",
                method_kwargs={"tol": 1e-10, "maxiter": 100},
            ),
        )
        if any(not math.isfinite(v) or v < 0 for v in (current, voltage, power)) or abs(
            power - voltage * current
        ) > 1e-8 + 1e-9 * max(1.0, power):
            raise ValueError("invalid forward section MPP")
        return current
    except Exception as exc:
        raise ValueError(
            f"section MPP failed for {key!r} at {state.state_reference!r}: {exc}"
        ) from exc


def _selected_position(frame: pd.DataFrame) -> int:
    return min(
        range(len(frame)),
        key=lambda i: (-frame.iloc[i].power_w, frame.iloc[i].voltage_v, frame.iloc[i].current_a),
    )


def execute_string_method_b(
    parent: TopologyStringMemberAuthorityResult,
    geometry: SiteGeometry,
    optical_binding: SectionOpticalBindingAuthorityResult,
    snapshots: tuple[DirectBeamVisibilitySnapshot, ...],
    optical_state: SectionDirectBeamStateResult,
    electrical: SectionElectricalStateAuthorityResult,
    reverse: SectionReverseBreakdownAuthorityResult,
    diode: SectionBypassDiodeAuthorityResult,
) -> Stage4aMethodBResult:
    """Derive each exact class's candidate basis once, compose once, select samples.

    No global/PL search, rounded cache, baseline dispatch or downstream execution.
    Zero candidates retain explicit zero-photocurrent section owners, if any.
    """
    classes = resolve_string_operating_classes(
        parent, geometry, optical_binding, snapshots, optical_state, electrical, reverse, diode
    )
    p = classes.topology_authority
    e = classes.electrical_state_authority
    current_basis = {}
    section_basis = {}
    for group in classes.classes:
        topology = p.authorities_by_string_id[group.representative_string_id]
        values = tuple(
            _section_mpp_current(classes, BypassSectionIdentity(m.module_id, s.section_id))
            for m in topology.module_members
            for s in m.bypass_protected_sections
        )
        section_basis[group.class_id] = values
        current_basis[group.class_id] = tuple(sorted({0.0, *values}))
    union = tuple(sorted({0.0, *(i for currents in current_basis.values() for i in currents)}))
    composition = compose_topology_common_current_iv(
        p,
        classes.reverse_authority,
        classes.diode_authority,
        {k: v.operating_state for k, v in e.bindings_by_section.items()},
        union,
    )
    parts = []
    state_rows = []
    active = zero = 0
    ordered = tuple(p.authorities_by_string_id) + p.advanced_unavailable_string_ids
    for sid in ordered:
        if sid not in classes.class_id_by_string_id:
            state_rows.append(
                dict(string_id=sid, state="unavailable_missing_advanced_evidence", resolved=False)
            )
            continue
        class_id = classes.class_id_by_string_id[sid]
        topology = p.authorities_by_string_id[sid]
        keys = tuple(
            BypassSectionIdentity(m.module_id, s.section_id)
            for m in topology.module_members
            for s in m.bypass_protected_sections
        )
        values = section_basis[class_id]
        source = composition.string_iv_curves_by_string_id[sid]
        rows = []
        for index, current in enumerate(current_basis[class_id]):
            point = source.loc[source.current_a.eq(current)].iloc[0]
            owned = composition.section_samples
            at = owned.loc[owned.string_id.eq(sid) & owned.common_current_a.eq(current)]
            bypass = tuple(
                BypassSectionIdentity(row.module_id, row.section_id)
                for row in at.loc[at.bypass_active].itertuples(index=False)
            )
            origins = tuple(k for k, value in zip(keys, values, strict=True) if value == current)
            rows.append(
                dict(
                    string_id=sid,
                    class_id=class_id,
                    candidate_index=index,
                    current_a=current,
                    voltage_v=float(point.voltage_v),
                    power_w=float(point.power_w),
                    source_section_ids=origins,
                    source_section_count=len(origins),
                    bypass_active_section_ids=bypass,
                    bypass_active_section_count=len(bypass),
                    is_selected_method_b=False,
                )
            )
        frame = pd.DataFrame(rows, columns=_COLUMNS)
        frame.loc[_selected_position(frame), "is_selected_method_b"] = True
        parts.append(frame)
        dark = all(e.bindings_by_section[k].operating_state.photocurrent_a == 0 for k in keys)
        zero += int(dark)
        active += int(not dark)
        state_rows.append(
            dict(string_id=sid, state="resolved_zero" if dark else "resolved_active", resolved=True)
        )
    candidates = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=_COLUMNS)
    states = pd.DataFrame(state_rows, columns=("string_id", "state", "resolved"))
    d = classes.diagnostics
    diagnostics = MethodBDiagnostics(
        d.topology_string_count,
        d.class_count,
        d.classifiable_string_count,
        active,
        zero,
        d.unavailable_string_count,
        len(union),
        len(candidates),
        active + zero,
    )
    return Stage4aMethodBResult(
        e.observation_timestamp,
        e.geometry_revision,
        e.optical_snapshot_reference,
        e,
        classes,
        MappingProxyType(current_basis),
        MappingProxyType(section_basis),
        composition,
        candidates,
        states,
        diagnostics,
    )
