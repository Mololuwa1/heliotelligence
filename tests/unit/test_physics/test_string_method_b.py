"""Operating-level candidates use explicit section Bishop and canonical composition."""

import ast
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest
from pvlib import singlediode  # type: ignore[import-untyped]

from heliotelligence.physics import string_method_b as b
from heliotelligence.physics.string_section_reverse_breakdown_authority import BypassSectionIdentity
from tests.unit.test_physics.test_string_operating_classes import inputs, update_electrical


def run(x: Any = None) -> Any:
    x = inputs() if x is None else x
    return b.execute_string_method_b(x[0], x[1], x[2], x[3], x[4], x[5], x[6], x[7])


def test_candidate_basis_class_reuse_and_canonical_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    original = singlediode.bishop88_mpp

    def spy(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(singlediode, "bishop88_mpp", spy)
    r = run()
    assert len(calls) == 2
    assert all(
        k["method"] == "newton" and k["d2mutau"] == 0 and k["NsVbi"] == float("inf") for k in calls
    )
    currents = r.candidate_currents_by_class["operating-class-0000"]
    assert currents[0] == 0 and len(currents) == 3
    assert currents == tuple(sorted({0.0, *(float(original(**kw)[0]) for kw in calls)}))
    assert r.candidates.groupby("string_id", sort=False).size().tolist() == [3, 3, 3]
    assert (r.candidates.power_w == r.candidates.voltage_v * r.candidates.current_a).all()
    for row in r.candidates.itertuples(index=False):
        owned = r.composition.section_samples
        at = owned[(owned.string_id == row.string_id) & (owned.common_current_a == row.current_a)]
        expected = tuple(
            BypassSectionIdentity(z.module_id, z.section_id)
            for z in at[at.bypass_active].itertuples()
        )
        assert row.bypass_active_section_ids == expected
        assert row.bypass_active_section_count == len(expected)
        assert row.source_section_count == len(row.source_section_ids)
    for _, rows in r.candidates.groupby("string_id"):
        selected = rows[rows.is_selected_method_b].iloc[0]
        assert selected.power_w == rows.power_w.max()
    assert r.diagnostics.classifiable_string_count == 3
    assert r.diagnostics.selected_candidate_count == 3


def test_dark_exact_zero_sources_and_missing_evidence() -> None:
    x = inputs()
    bindings = {
        k: replace(v, operating_state=replace(v.operating_state, photocurrent_a=0.0))
        for k, v in x[5].bindings_by_section.items()
    }
    update_electrical(x, bindings)
    r = run(x)
    assert r.candidates.power_w.eq(0).all() and len(r.candidates) == 3
    assert r.candidates.source_section_count.eq(2).all()
    assert r.states.state.eq("resolved_zero").all()
    del bindings[next(iter(bindings))]
    update_electrical(x, bindings)
    r = run(x)
    assert (
        r.states.set_index("string_id").loc["string-z", "state"]
        == "unavailable_missing_advanced_evidence"
    )
    assert not r.candidates.string_id.eq("string-z").any()


def test_exact_duplicates_deduplicate_near_equal_currents_stay_distinct() -> None:
    x = inputs()
    v = list(x[5].bindings_by_section.values())[0].operating_state
    update_electrical(
        x, {k: replace(s, operating_state=v) for k, s in x[5].bindings_by_section.items()}
    )
    duplicate = run(x)
    assert len(duplicate.candidate_currents_by_class["operating-class-0000"]) == 2
    assert (
        duplicate.candidates.loc[duplicate.candidates.current_a.gt(0), "source_section_count"]
        .eq(2)
        .all()
    )
    states = dict(x[5].bindings_by_section)
    key = list(states)[1]
    states[key] = replace(
        states[key], operating_state=replace(v, photocurrent_a=v.photocurrent_a + 1e-10)
    )
    update_electrical(x, states)
    assert len(run(x).candidate_currents_by_class["operating-class-0000"]) == 3


def test_exact_ties_select_lowest_voltage_then_current() -> None:
    f = pd.DataFrame({"power_w": [8.0, 8.0], "voltage_v": [4.0, 1.0], "current_a": [2.0, 8.0]})
    assert b._selected_position(f) == 1


def test_output_detachment_and_repeat_determinism() -> None:
    x = inputs()
    r = run(x)
    again = run(x)
    pd.testing.assert_frame_equal(r.candidates, again.candidates, check_exact=True)
    key = next(iter(x[5].bindings_by_section))
    object.__setattr__(x[5].bindings_by_section[key].operating_state, "photocurrent_a", -1.0)
    assert (
        r.section_electrical_state_authority.bindings_by_section[key].operating_state.photocurrent_a
        == 2.0
    )
    r.candidates.loc[0, "power_w"] = -999
    assert again.candidates.power_w.iloc[0] == 0


def test_solver_failure_has_context_and_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(**kwargs: Any) -> Any:
        raise RuntimeError("test failure")

    monkeypatch.setattr(singlediode, "bishop88_mpp", fail)
    with pytest.raises(ValueError, match="section MPP"):
        run()


def test_no_global_search_downstream_or_approximate_defaults() -> None:
    assert b.__file__ is not None
    tree = ast.parse(Path(b.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not any(
                s in (node.module or "")
                for s in ("multi_peak", "dc_collection", "inverter", "engine", "api", "runtime")
            )
        if isinstance(node, ast.Call):
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            assert name not in {
                "round",
                "isclose",
                "bishop88_v_from_i",
                "bishop88_i_from_v",
                "calculate_common_voltage_mppt",
            }


@pytest.mark.parametrize("kind", ["reverse", "diode"])
def test_missing_reverse_or_diode_is_unavailable(kind: str) -> None:
    from heliotelligence.physics.string_section_bypass_diode_authority import (
        resolve_section_bypass_diode_authority,
    )
    from heliotelligence.physics.string_section_reverse_breakdown_authority import (
        resolve_section_reverse_breakdown_authority,
    )

    x = inputs()
    key = next(iter(x[6].authorities_by_section))
    if kind == "reverse":
        x[6] = resolve_section_reverse_breakdown_authority(
            x[0], {k: v for k, v in x[6].authorities_by_section.items() if k != key}
        )
    else:
        x[7] = resolve_section_bypass_diode_authority(
            x[0], x[6], {k: v for k, v in x[7].authorities_by_section.items() if k != key}
        )
    r = run(x)
    assert not r.candidates.string_id.eq("string-z").any()
    assert r.diagnostics.unavailable_string_count == 1


def test_composition_once_and_filter_each_class_candidate_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from heliotelligence.physics.string_common_current_composition import (
        compose_topology_common_current_iv,
    )

    calls = []

    def spy(*args: Any) -> Any:
        calls.append(args)
        return compose_topology_common_current_iv(*args)

    monkeypatch.setattr(b, "compose_topology_common_current_iv", spy)
    x = inputs()
    states = dict(x[5].bindings_by_section)
    key = list(states)[3]
    states[key] = replace(
        states[key], operating_state=replace(states[key].operating_state, photocurrent_a=20.0)
    )
    update_electrical(x, states)
    r = run(x)
    assert len(calls) == 1 and r.diagnostics.class_count == 2
    assert r.diagnostics.unique_candidate_current_count == 4
    for sid, rows in r.candidates.groupby("string_id", sort=False):
        class_id = r.string_classes.class_id_by_string_id[sid]
        assert tuple(rows.current_a) == r.candidate_currents_by_class[class_id]
        assert len(rows) == 3


@pytest.mark.parametrize("reply", [(float("nan"), 1.0, 1.0), (-1.0, 1.0, -1.0), (1.0, 1.0, 9.0)])
def test_invalid_mpp_reply_fails_closed(reply: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(singlediode, "bishop88_mpp", lambda **kwargs: reply)
    with pytest.raises(ValueError, match="section MPP"):
        run()


def test_zero_power_voltage_tie_uses_lowest_current() -> None:
    frame = pd.DataFrame(
        {"power_w": [0.0, 0.0, 0.0], "voltage_v": [0.0, 0.0, 0.0], "current_a": [2.0, 1.0, 3.0]}
    )
    assert b._selected_position(frame) == 1
