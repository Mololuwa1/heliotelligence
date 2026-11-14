"""Search-complete PL handoff replays explicit Stage4a-3, never Bishop equations."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import electrical as e
from heliotelligence.physics import string_multi_peak_candidates as a
from heliotelligence.physics.string_common_current_composition import (
    compose_topology_common_current_iv,
)
from tests.unit.test_physics.test_string_common_current_composition import inputs

STAMP = pd.Timestamp("2024-06-21T12:00:00Z")


def run(grid: tuple[float, ...] = (0.0, 1.0, 3.0, 8.0, 12.0)) -> tuple[Any, Any]:
    p, rev, diodes, states = inputs()
    composed = compose_topology_common_current_iv(p, rev, diodes, states, grid)
    result = a.analyze_advanced_string_multi_peak_candidates(
        p, rev, diodes, states, composed, STAMP
    )
    return composed, result


def test_full_curve_multiple_peaks_and_bypass_candidates() -> None:
    composed, result = run()
    f = result.string_iv_curves_by_string_id["string-z"]
    assert f.voltage_v.iloc[0] == 0.0 and f.current_a.iloc[-1] == 0.0
    assert (np.diff(f.voltage_v) > 0).all() and (f.voltage_v >= 0).all()
    assert (composed.string_iv_curves_by_string_id["string-z"].voltage_v < 0).any()
    candidates = result.candidates[result.candidates.string_id == "string-z"]
    assert candidates.is_local_maximum.sum() >= 2
    selected = candidates[candidates.is_selected_global].iloc[0]
    assert selected.power_w == candidates.power_w.max()
    canonical = e.calculate_common_voltage_mppt([f]).iloc[0]
    assert selected.power_w == canonical.p_common_mppt_w
    assert selected.voltage_v == canonical.v_common_mppt_v
    sections = result.replayed_composition.section_samples
    for row in candidates.itertuples(index=False):
        expected = tuple(
            key
            for key in result.replayed_composition.section_inputs_by_identity
            if key.module_id.startswith("string-z")
            and row.current_a
            > float(
                sections[
                    (sections.module_id == key.module_id) & (sections.section_id == key.section_id)
                ].clamp_transition_current_a.iloc[0]
            )
        )
        assert row.bypass_active_section_ids == expected
        assert row.bypass_active_section_count == len(expected)
    assert (
        result.states.set_index("string_id").loc["string-z", "state"] == "resolved_complete_domain"
    )


def test_exact_transitions_replayed_not_nearest_and_input_not_mutated() -> None:
    composed, result = run()
    assert result.inserted_transition_currents_a
    for transition in result.inserted_transition_currents_a:
        assert transition not in composed.common_currents_a
        assert transition in result.replayed_composition.common_currents_a
    for key in result.replayed_composition.section_inputs_by_identity:
        rows = result.replayed_composition.section_samples
        transition = rows[
            (rows.module_id == key.module_id) & (rows.section_id == key.section_id)
        ].clamp_transition_current_a.iloc[0]
        if transition in result.inserted_transition_currents_a:
            at = rows[
                (rows.module_id == key.module_id)
                & (rows.section_id == key.section_id)
                & (rows.common_current_a == transition)
            ]
            assert not at.bypass_active.iloc[0]
    assert composed.common_currents_a == (0.0, 1.0, 3.0, 8.0, 12.0)
    assert result.source_composition is not composed
    again_composed, again = run()
    pd.testing.assert_frame_equal(result.candidates, again.candidates, check_exact=True)
    result.string_iv_curves_by_string_id["string-z"].loc[0, "current_a"] = -999
    assert again.string_iv_curves_by_string_id["string-z"].current_a.iloc[0] >= 0
    pd.testing.assert_frame_equal(composed.section_samples, again_composed.section_samples)


@pytest.mark.parametrize(
    "grid,reason",
    [
        ((1.0, 3.0, 12.0), "unavailable_missing_zero_current"),
        ((0.0, 1.0), "unavailable_truncated_voltage_domain"),
    ],
)
def test_incomplete_domains_never_claim_global(grid: tuple[float, ...], reason: str) -> None:
    _, result = run(grid)
    assert not result.string_iv_curves_by_string_id
    assert result.candidates.empty
    assert set(result.states.state) == {reason, "unavailable_missing_advanced_topology"}


def test_exact_zero_boundary_is_interpolated_without_extrapolation() -> None:
    _, result = run()
    for key, f in result.string_iv_curves_by_string_id.items():
        upstream = result.replayed_composition.string_iv_curves_by_string_id[key]
        nonpositive = int(np.flatnonzero(upstream.voltage_v.to_numpy() <= 0)[0])
        lo, hi = upstream.iloc[nonpositive - 1], upstream.iloc[nonpositive]
        expected = lo.current_a + (-lo.voltage_v) / (hi.voltage_v - lo.voltage_v) * (
            hi.current_a - lo.current_a
        )
        assert f.current_a.iloc[0] == expected
        assert lo.current_a <= expected <= hi.current_a
        assert f.power_w.iloc[0] == 0.0


def test_explicit_dark_state_resolved_zero_and_legacy_mixed_rule() -> None:
    p, rev, diodes, states = inputs()
    states = {k: replace(v, photocurrent_a=0.0) for k, v in states.items()}
    composed = compose_topology_common_current_iv(p, rev, diodes, states, (0.0, 1.0))
    result = a.analyze_advanced_string_multi_peak_candidates(
        p, rev, diodes, states, composed, STAMP
    )
    assert set(result.states.state) == {"resolved_zero", "unavailable_missing_advanced_topology"}
    for f in result.string_iv_curves_by_string_id.values():
        assert f[["voltage_v", "current_a", "power_w"]].eq(0).all().all()
    assert result.candidates.power_w.eq(0).all()
    assert not result.candidates.is_local_maximum.any()


@pytest.mark.parametrize(
    "field",
    [
        "section_samples",
        "module_samples",
        "string_iv_curves_by_string_id",
        "diagnostics",
        "contract",
    ],
)
def test_forged_stage3_result_rejected(field: str) -> None:
    p, rev, diodes, states = inputs()
    composed = compose_topology_common_current_iv(p, rev, diodes, states, (0.0, 1.0, 12.0))
    if field in {"section_samples", "module_samples"}:
        getattr(composed, field).iloc[0, 0] = "forged"
    elif field == "string_iv_curves_by_string_id":
        composed.string_iv_curves_by_string_id["string-z"].loc[0, "voltage_v"] = np.nan
    else:
        object.__setattr__(composed, field, None)
    with pytest.raises(ValueError):
        a.analyze_advanced_string_multi_peak_candidates(p, rev, diodes, states, composed, STAMP)


@pytest.mark.parametrize("stamp", [pd.NaT, pd.Timestamp("2024-01-01"), "2024-01-01"])
def test_timestamp_explicit(stamp: Any) -> None:
    p, rev, diodes, states = inputs()
    composed = compose_topology_common_current_iv(p, rev, diodes, states, (0.0, 1.0, 12.0))
    with pytest.raises(ValueError):
        a.analyze_advanced_string_multi_peak_candidates(p, rev, diodes, states, composed, stamp)


def test_no_downstream_optical_runtime_or_bishop_execution_imports() -> None:
    tree = ast.parse(Path(a.__file__).read_text())
    modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any(
        any(word in module for word in ("dc_collection", "inverter", "optical", "engine", "pvlib"))
        for module in modules
    )


def test_existing_direct_branch_owner_consumes_canonical_curve() -> None:
    from heliotelligence.physics.dc_collection import transform_string_terminal_iv_to_mppt_input

    _, result = run()
    source = result.string_iv_curves_by_string_id["string-z"]
    original = source.copy(deep=True)
    transformed, inserted = transform_string_terminal_iv_to_mppt_input(source, 0.05)
    assert transformed is not None and inserted
    assert transformed.voltage_v.iloc[0] == 0.0
    assert (np.diff(transformed.voltage_v) > 0).all()
    assert transformed.columns.tolist() == source.columns.tolist()
    before = e.calculate_common_voltage_mppt([source]).iloc[0]
    after = e.calculate_common_voltage_mppt([transformed]).iloc[0]
    assert 0 < after.p_common_mppt_w <= before.p_common_mppt_w
    pd.testing.assert_frame_equal(source, original)


def test_positive_domain_transitions_are_present_in_canonical_curve() -> None:
    _, result = run()
    for string_id, curve in result.string_iv_curves_by_string_id.items():
        replayed = result.replayed_composition.string_iv_curves_by_string_id[string_id]
        for transition in result.inserted_transition_currents_a:
            at = replayed.loc[replayed.current_a.eq(transition)]
            if len(at) and at.voltage_v.iloc[0] > 0:
                assert curve.current_a.eq(transition).any()


@pytest.mark.parametrize("missing", ["reverse", "diode", "state"])
def test_missing_advanced_evidence_stays_unavailable(missing: str) -> None:
    from heliotelligence.physics.string_section_bypass_diode_authority import (
        resolve_section_bypass_diode_authority,
    )
    from heliotelligence.physics.string_section_reverse_breakdown_authority import (
        resolve_section_reverse_breakdown_authority,
    )

    p, rev, diodes, states = inputs()
    key = rev.resolved_section_ids[0]
    if missing == "reverse":
        rev = resolve_section_reverse_breakdown_authority(
            p, {k: v for k, v in rev.authorities_by_section.items() if k != key}
        )
    elif missing == "diode":
        diodes = resolve_section_bypass_diode_authority(
            p, rev, {k: v for k, v in diodes.authorities_by_section.items() if k != key}
        )
    else:
        del states[key]
    composed = compose_topology_common_current_iv(p, rev, diodes, states, (0.0, 1.0, 12.0))
    result = a.analyze_advanced_string_multi_peak_candidates(
        p, rev, diodes, states, composed, STAMP
    )
    assert (
        result.states.set_index("string_id").loc["string-z", "state"]
        == "unavailable_missing_advanced_evidence"
    )
    assert "string-z" not in result.string_iv_curves_by_string_id
    assert not result.candidates.string_id.eq("string-z").any()


def test_forged_equal_but_wrong_type_frozen_parent_field_is_rejected() -> None:
    p, rev, diodes, states = inputs()
    composed = compose_topology_common_current_iv(p, rev, diodes, states, (0.0, 1.0, 12.0))
    object.__setattr__(
        composed.topology_authorities_by_string_id["string-z"].module_members[0],
        "series_index",
        False,
    )
    with pytest.raises(ValueError, match="parent"):
        a.analyze_advanced_string_multi_peak_candidates(p, rev, diodes, states, composed, STAMP)


def test_domain_helpers_reject_nonmonotonic_or_ambiguous_states() -> None:
    nonmonotonic = pd.DataFrame({"current_a": [0.0, 1.0, 2.0], "voltage_v": [3.0, 4.0, -1.0]})
    with pytest.raises(ValueError, match="non-increasing"):
        a._domain_state(nonmonotonic, True, False)
    plateau = pd.DataFrame({"current_a": [0.0, 1.0, 2.0], "voltage_v": [3.0, 3.0, -1.0]})
    with pytest.raises(ValueError, match="ambiguous"):
        a._canonical_curve(plateau, STAMP, False)


@pytest.mark.parametrize("resistance", [True, -1.0, np.nan, np.inf])
def test_direct_branch_numeric_handoff_rejects_invalid_resistance(resistance: Any) -> None:
    from heliotelligence.physics.dc_collection import transform_string_terminal_iv_to_mppt_input

    _, result = run()
    with pytest.raises(ValueError):
        transform_string_terminal_iv_to_mppt_input(
            result.string_iv_curves_by_string_id["string-z"], resistance
        )


def test_forged_equal_value_identity_key_type_is_rejected() -> None:
    class NoncanonicalText(str):
        pass

    p, rev, diodes, states = inputs()
    composed = compose_topology_common_current_iv(p, rev, diodes, states, (0.0, 1.0, 12.0))
    key = next(iter(composed.section_inputs_by_identity))
    object.__setattr__(key, "module_id", NoncanonicalText(key.module_id))
    with pytest.raises(ValueError, match="parent"):
        a.analyze_advanced_string_multi_peak_candidates(p, rev, diodes, states, composed, STAMP)
