"""Method A orchestrates canonical owners; no second electrical solver."""

import ast
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import string_method_a as m
from heliotelligence.physics.string_common_current_composition import (
    compose_topology_common_current_iv,
)
from heliotelligence.physics.string_multi_peak_candidates import (
    analyze_advanced_string_multi_peak_candidates,
)
from heliotelligence.physics.string_section_bypass_diode_authority import (
    resolve_section_bypass_diode_authority,
)
from heliotelligence.physics.string_section_reverse_breakdown_authority import (
    resolve_section_reverse_breakdown_authority,
)
from tests.unit.test_physics.test_string_section_electrical_state_authority import (
    STAMP,
    context,
    resolve,
)

GRID = (0.0, 1.0, 3.0, 8.0, 12.0)


def run(c: Any = None, authority: Any = None, grid: Any = GRID, stamp: Any = STAMP) -> Any:
    c = context() if c is None else c
    return m.execute_string_method_a(
        c[0],
        c[1],
        c[2],
        c[3],
        c[4],
        resolve(ctx=c) if authority is None else authority,
        c[5],
        c[6],
        grid,
        stamp,
    )


def test_exact_manual_replay_multi_peak_handoff_and_metadata() -> None:
    c = context()
    authority = resolve(ctx=c)
    result = run(c, authority)
    states = {k: v.operating_state for k, v in authority.bindings_by_section.items()}
    composition = compose_topology_common_current_iv(c[0], c[5], c[6], states, GRID)
    manual = analyze_advanced_string_multi_peak_candidates(
        c[0], c[5], c[6], states, composition, STAMP
    )
    actual = result.advanced_string_candidates
    pd.testing.assert_frame_equal(actual.candidates, manual.candidates, check_exact=True)
    pd.testing.assert_frame_equal(
        actual.source_composition.section_samples, composition.section_samples, check_exact=True
    )
    pd.testing.assert_frame_equal(actual.states, manual.states, check_exact=True)
    for k, f in manual.string_iv_curves_by_string_id.items():
        pd.testing.assert_frame_equal(actual.string_iv_curves_by_string_id[k], f, check_exact=True)
        assert f.voltage_v.min() == 0 and f.voltage_v.ge(0).all()
    assert actual.inserted_transition_currents_a == manual.inserted_transition_currents_a
    assert actual.inserted_transition_currents_a
    assert (composition.string_iv_curves_by_string_id["string-z"].voltage_v < 0).any()
    assert actual.candidates[actual.candidates.string_id == "string-z"].is_local_maximum.sum() >= 2
    for _, g in actual.candidates.groupby("string_id"):
        selected = g[g.is_selected_global].iloc[0]
        assert selected.voltage_v == g[g.power_w == g.power_w.max()].voltage_v.min()
    assert result.contract == "advanced_string_method_a_full_iv_execution_v1"
    assert result.model == "explicit_section_state_existing_bishop_clamp_series_and_peak_replay_v1"
    assert (
        result.scope == "advanced_s8_method_a_string_terminal_reference_execution_before_dc_branch"
    )
    assert (
        result.coverage_scope
        == "complete_section_operating_reverse_breakdown_bypass_diode_and_topology_evidence"
    )
    assert (
        result.observation_timestamp == STAMP
        and result.optical_snapshot_reference == "snapshot:test"
    )
    d = result.diagnostics
    assert (
        d.topology_string_count
        == d.resolved_active_string_count
        + d.resolved_zero_string_count
        + d.unavailable_string_count
    )
    assert d.electrical_complete_candidate_string_count == 2


@pytest.mark.parametrize("missing", ["electrical", "reverse", "diode"])
def test_missing_section_withholds_whole_string(missing: str) -> None:
    c = list(context())
    key = next(iter(c[7]))
    authority = None
    if missing == "electrical":
        del c[7][key]
    elif missing == "reverse":
        c[5] = resolve_section_reverse_breakdown_authority(
            c[0], {k: v for k, v in c[5].authorities_by_section.items() if k != key}
        )
    else:
        c[6] = resolve_section_bypass_diode_authority(
            c[0], c[5], {k: v for k, v in c[6].authorities_by_section.items() if k != key}
        )
    result = run(c, authority).advanced_string_candidates
    assert "string-z" not in result.string_iv_curves_by_string_id
    assert "string-a" in result.string_iv_curves_by_string_id
    assert not result.candidates.string_id.eq("string-z").any()


def test_explicit_dark_empty_and_detached_results() -> None:
    c = context()
    for k, v in tuple(c[7].items()):
        c[7][k] = replace(v, operating_state=replace(v.operating_state, photocurrent_a=0.0))
    authority = resolve(ctx=c)
    result = run(c, authority)
    assert result.diagnostics.resolved_zero_string_count == 2
    assert result.advanced_string_candidates.candidates.power_w.eq(0).all()
    key = next(iter(authority.bindings_by_section))
    object.__setattr__(authority.bindings_by_section[key].operating_state, "photocurrent_a", -1.0)
    assert (
        result.section_electrical_state_authority.bindings_by_section[
            key
        ].operating_state.photocurrent_a
        == 0.0
    )
    empty = run(c, resolve({}, c))
    assert not empty.advanced_string_candidates.string_iv_curves_by_string_id


@pytest.mark.parametrize(
    "grid", [None, (), (1.0, 0.0), (0.0, 0.0), (False, 1.0), (0.0, float("nan"))]
)
def test_invalid_grid_rejected(grid: Any) -> None:
    with pytest.raises(ValueError):
        run(grid=grid)


@pytest.mark.parametrize(
    "stamp", [pd.NaT, pd.Timestamp("2024-01-01"), STAMP + pd.Timedelta(seconds=1)]
)
def test_timestamp_must_match_authority(stamp: Any) -> None:
    with pytest.raises(ValueError):
        run(stamp=stamp)


def test_mapping_order_and_truncated_domain_preserved() -> None:
    c = context()
    first = run(c)
    authority = resolve(
        {k: replace(v, confidence="low") for k, v in reversed(list(c[7].items()))}, c
    )
    second = run(c, authority)
    pd.testing.assert_frame_equal(
        first.advanced_string_candidates.candidates,
        second.advanced_string_candidates.candidates,
        check_exact=True,
    )
    assert not run(c, grid=(0.0, 1.0)).advanced_string_candidates.string_iv_curves_by_string_id


def test_only_canonical_stage4a_execution_owners() -> None:
    assert m.__file__ is not None
    tree = ast.parse(Path(m.__file__).read_text())
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            assert not (n.module or "").endswith(".electrical")
            assert not any(
                x in (n.module or "")
                for x in (
                    "dc_collection",
                    "inverter",
                    "engine",
                    "api",
                    "pvlib",
                    "shading",
                )
            )
        if isinstance(n, ast.Call):
            name = (
                n.func.id
                if isinstance(n.func, ast.Name)
                else n.func.attr
                if isinstance(n.func, ast.Attribute)
                else ""
            )
            assert name not in {
                "bishop88",
                "bishop88_v_from_i",
                "bishop88_i_from_v",
                "calcparams_desoto",
                "calculate_common_voltage_mppt",
            }


def test_canonical_exact_tie_policy_is_forwarded_without_reselection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from heliotelligence.physics.electrical import calculate_common_voltage_mppt_candidates

    # The physical replay test above proves end-to-end numerics. This owner seam
    # proves the coordinator does not reinterpret even an exact two-peak tie.
    original = analyze_advanced_string_multi_peak_candidates
    captured = []

    def canonical_owner(*args: Any, **kwargs: Any) -> Any:
        advanced = original(*args, **kwargs)
        curve = pd.DataFrame(
            {
                "timestamp": [STAMP] * 5,
                "curve_point": range(5),
                "voltage_v": [0.0, 1.0, 1.5, 4.0, 5.0],
                "current_a": [8.0, 8.0, 2.0, 2.0, 0.0],
                "power_w": [0.0, 8.0, 3.0, 8.0, 0.0],
            }
        )
        tied = replace(advanced, candidates=calculate_common_voltage_mppt_candidates([curve]))
        captured.append(tied)
        return tied

    monkeypatch.setattr(m, "analyze_advanced_string_multi_peak_candidates", canonical_owner)
    result = run()
    assert result.advanced_string_candidates is captured[0]
    candidates = result.advanced_string_candidates.candidates
    assert candidates.loc[candidates.power_w.eq(8.0), "voltage_v"].tolist() == [1.0, 4.0]
    assert candidates.loc[candidates.is_selected_global, "voltage_v"].tolist() == [1.0]
