"""Stage4a-4 complete PL string-terminal domain and canonical peak analysis.

Exactness is over the admitted piecewise-linear I(V), not continuous Bishop.
No branch, parallel aggregation, inverter or optical solver is implemented here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.physics.electrical import (
    COMMON_VOLTAGE_CANDIDATE_COLUMNS,
    calculate_common_voltage_mppt_candidates,
)
from heliotelligence.physics.string_common_current_composition import (
    TopologyCommonCurrentIVResult,
    compose_topology_common_current_iv,
)
from heliotelligence.physics.string_member_topology_authority import (
    TopologyStringMemberAuthorityResult,
)
from heliotelligence.physics.string_section_bypass_diode_authority import (
    SectionBypassDiodeAuthorityResult,
)
from heliotelligence.physics.string_section_reverse_breakdown_authority import (
    BypassSectionIdentity,
    SectionReverseBreakdownAuthorityResult,
)
from heliotelligence.physics.string_section_reverse_iv import SectionSingleDiodeOperatingState

ADVANCED_STRING_CANDIDATE_CONTRACT_ID = "advanced_string_terminal_multi_peak_candidates_v1"
ADVANCED_STRING_CANDIDATE_MODEL_ID = "piecewise_linear_string_iv_complete_candidate_enumeration_v1"
ADVANCED_STRING_CANDIDATE_SCOPE = (
    "advanced_s8_string_terminal_multi_peak_analysis_before_dc_branch_transform"
)
ADVANCED_STRING_CANDIDATE_COVERAGE_SCOPE = (
    "complete_stage4a3_string_iv_with_search_complete_nonnegative_voltage_domain"
)


@dataclass(frozen=True)
class AdvancedStringCandidateDiagnostics:
    topology_string_count: int
    resolved_active_string_count: int
    resolved_zero_string_count: int
    unavailable_string_count: int
    inserted_transition_sample_count: int
    candidate_count: int
    local_maximum_count: int


@dataclass(frozen=True)
class AdvancedStringCandidateResult:
    string_iv_curves_by_string_id: Mapping[str, pd.DataFrame]
    candidates: pd.DataFrame
    states: pd.DataFrame
    source_composition: TopologyCommonCurrentIVResult
    replayed_composition: TopologyCommonCurrentIVResult
    inserted_transition_currents_a: tuple[float, ...]
    diagnostics: AdvancedStringCandidateDiagnostics
    reference_plane: str = "string_terminal"
    contract: str = ADVANCED_STRING_CANDIDATE_CONTRACT_ID
    model: str = ADVANCED_STRING_CANDIDATE_MODEL_ID
    scope: str = ADVANCED_STRING_CANDIDATE_SCOPE
    coverage_scope: str = ADVANCED_STRING_CANDIDATE_COVERAGE_SCOPE


def _same_snapshot(actual: Any, expected: Any) -> None:
    """Exact parent replay, including frozen field types and owned frame values."""
    if type(actual) is not type(expected):
        raise ValueError("Stage4a-3 parent field type differs from canonical replay")
    if isinstance(expected, pd.DataFrame):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    elif is_dataclass(expected):
        for field in fields(expected):
            _same_snapshot(getattr(actual, field.name), getattr(expected, field.name))
    elif isinstance(expected, Mapping):
        if tuple(actual) != tuple(expected):
            raise ValueError("Stage4a-3 parent mapping order differs")
        for actual_key, expected_key in zip(actual, expected, strict=True):
            _same_snapshot(actual_key, expected_key)
            _same_snapshot(actual[actual_key], expected[expected_key])
    elif isinstance(expected, tuple):
        if len(actual) != len(expected):
            raise ValueError("Stage4a-3 parent tuple length differs")
        for left, right in zip(actual, expected, strict=True):
            _same_snapshot(left, right)
    elif actual != expected:
        raise ValueError("Stage4a-3 parent value differs from canonical replay")


def _domain_state(curve: pd.DataFrame, starts_at_zero: bool, explicit_dark: bool) -> str:
    v = curve.voltage_v.to_numpy(dtype=float)
    i = curve.current_a.to_numpy(dtype=float)
    if not np.isfinite(v).all() or not np.isfinite(i).all():
        raise ValueError("nonfinite Stage4a-3 current/voltage domain")
    if not starts_at_zero:
        return "unavailable_missing_zero_current"
    tolerance = 1e-8 + 1e-10 * float(np.max(np.abs(v)))
    if (np.diff(v) > tolerance).any():
        raise ValueError("Stage4a-3 string voltage must be non-increasing with current")
    if explicit_dark and v[0] == 0:
        return "resolved_zero"
    if v[0] <= 0:
        raise ValueError("active string lacks a positive zero-current open-circuit endpoint")
    if not (v <= 0).any():
        return "unavailable_truncated_voltage_domain"
    return "resolved_complete_domain"


def _canonical_curve(curve: pd.DataFrame, timestamp: pd.Timestamp, zero: bool) -> pd.DataFrame:
    if zero:
        voltages, currents = np.array([0.0]), np.array([0.0])
    else:
        v = curve.voltage_v.to_numpy(dtype=float)
        i = curve.current_a.to_numpy(dtype=float)
        end = int(np.flatnonzero(v <= 0)[0])
        if v[end] == 0:
            crossing = i[end]
        else:
            crossing = i[end - 1] + (-v[end - 1]) / (v[end] - v[end - 1]) * (i[end] - i[end - 1])
        # Never discard physically distinct states to disguise a multivalued I(V).
        if not np.all(np.diff(v[:end]) < 0):
            raise ValueError("ambiguous repeated/increasing positive string-terminal voltage")
        voltages = np.concatenate(([0.0], v[:end][::-1]))
        currents = np.concatenate(([crossing], i[:end][::-1]))
    return pd.DataFrame(
        dict(
            timestamp=[timestamp] * len(voltages),
            curve_point=np.arange(len(voltages)),
            voltage_v=voltages,
            current_a=currents,
            power_w=voltages * currents,
        )
    )


def analyze_advanced_string_multi_peak_candidates(
    parent: TopologyStringMemberAuthorityResult,
    reverse_authority: SectionReverseBreakdownAuthorityResult,
    diode_authority: SectionBypassDiodeAuthorityResult,
    states_by_section: Mapping[BypassSectionIdentity, SectionSingleDiodeOperatingState],
    composition: TopologyCommonCurrentIVResult,
    timestamp: pd.Timestamp,
) -> AdvancedStringCandidateResult:
    """Validate/replay parents, retain required kinks and delegate peak mathematics.

    The timestamp is an explicit caller snapshot label; it creates no site time
    authority. Source-grid completeness is checked before inserting transitions.
    No zero crossing is extrapolated and no continuous-Bishop global claim is made.
    """
    if type(timestamp) is not pd.Timestamp or pd.isna(timestamp) or timestamp.tz is None:
        raise ValueError("timestamp must be an exact aware non-NaT pandas.Timestamp")
    if type(composition) is not TopologyCommonCurrentIVResult:
        raise ValueError("expected exact Stage4a-3 result")
    source = compose_topology_common_current_iv(
        parent, reverse_authority, diode_authority, states_by_section, composition.common_currents_a
    )
    try:
        _same_snapshot(composition, source)
    except (AssertionError, ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"Stage4a-3 parent fails canonical replay: {exc}") from exc
    domain_states: dict[str, str] = {}
    extra: set[float] = set()
    for string_id in parent.authorities_by_string_id:
        if string_id not in source.string_iv_curves_by_string_id:
            domain_states[string_id] = "unavailable_missing_advanced_evidence"
            continue
        curve = source.string_iv_curves_by_string_id[string_id]
        owned = source.section_samples.loc[source.section_samples.string_id.eq(string_id)]
        explicit_dark = all(
            source.section_inputs_by_identity[
                BypassSectionIdentity(m.module_id, s.section_id)
            ].operating_state.photocurrent_a
            == 0
            for m in parent.authorities_by_string_id[string_id].module_members
            for s in m.bypass_protected_sections
        )
        state = _domain_state(curve, source.common_currents_a[0] == 0, explicit_dark)
        domain_states[string_id] = state
        if state != "resolved_complete_domain":
            continue
        upper = float(curve.current_a.iloc[int(np.flatnonzero(curve.voltage_v.to_numpy() <= 0)[0])])
        for transition in owned.clamp_transition_current_a.unique():
            if 0 < transition < upper and transition not in source.common_currents_a:
                extra.add(float(transition))
    grid = tuple(sorted(set(source.common_currents_a).union(extra)))
    replay = compose_topology_common_current_iv(
        parent, reverse_authority, diode_authority, states_by_section, grid
    )
    curves: dict[str, pd.DataFrame] = {}
    candidate_parts = []
    state_rows = []
    for string_id, state in domain_states.items():
        complete = state in {"resolved_complete_domain", "resolved_zero"}
        state_rows.append(dict(string_id=string_id, state=state, search_complete=complete))
        if not complete:
            continue
        curve = _canonical_curve(
            replay.string_iv_curves_by_string_id[string_id], timestamp, state == "resolved_zero"
        )
        candidates = calculate_common_voltage_mppt_candidates([curve])
        if state == "resolved_zero":
            candidates["is_local_maximum"] = False  # Resolved zero is not a fabricated peak.
        candidates.insert(1, "string_id", string_id)
        transitions = replay.section_samples.loc[replay.section_samples.string_id.eq(string_id)]
        keys = tuple(
            BypassSectionIdentity(m.module_id, s.section_id)
            for m in parent.authorities_by_string_id[string_id].module_members
            for s in m.bypass_protected_sections
        )
        thresholds = {
            key: float(
                transitions.loc[
                    transitions.module_id.eq(key.module_id)
                    & transitions.section_id.eq(key.section_id),
                    "clamp_transition_current_a",
                ].iloc[0]
            )
            for key in keys
        }
        active_ids = [
            tuple(key for key in keys if current > thresholds[key])
            for current in candidates.current_a
        ]
        candidates["bypass_active_section_ids"] = active_ids
        candidates["bypass_active_section_count"] = [len(ids) for ids in active_ids]
        candidates["search_complete"] = True
        candidates["search_state"] = state
        curves[string_id] = curve
        candidate_parts.append(candidates)
    for string_id in parent.advanced_unavailable_string_ids:
        state_rows.append(
            dict(
                string_id=string_id,
                state="unavailable_missing_advanced_topology",
                search_complete=False,
            )
        )
    # Retain the candidate schema even when every advanced string is unavailable.
    empty_columns = list(COMMON_VOLTAGE_CANDIDATE_COLUMNS)
    empty_columns.insert(1, "string_id")
    empty_columns.extend(
        [
            "bypass_active_section_ids",
            "bypass_active_section_count",
            "search_complete",
            "search_state",
        ]
    )
    candidates = (
        pd.concat(candidate_parts, ignore_index=True)
        if candidate_parts
        else pd.DataFrame(columns=empty_columns)
    )

    states = pd.DataFrame(state_rows, columns=["string_id", "state", "search_complete"])
    active = sum(s == "resolved_complete_domain" for s in domain_states.values())
    zero = sum(s == "resolved_zero" for s in domain_states.values())
    diagnostics = AdvancedStringCandidateDiagnostics(
        parent.diagnostics.topology_string_count,
        active,
        zero,
        parent.diagnostics.topology_string_count - active - zero,
        len(extra),
        len(candidates),
        int(candidates.is_local_maximum.sum()) if len(candidates) else 0,
    )
    return AdvancedStringCandidateResult(
        MappingProxyType(curves),
        candidates,
        states,
        source,
        replay,
        tuple(sorted(extra)),
        diagnostics,
    )
