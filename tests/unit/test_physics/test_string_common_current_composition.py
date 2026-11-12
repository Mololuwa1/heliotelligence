"""Series voltage composition at explicit caller currents is not peak selection."""

from __future__ import annotations

import ast
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import string_common_current_composition as c
from heliotelligence.physics import string_section_bypass_diode_authority as d
from heliotelligence.physics import string_section_reverse_breakdown_authority as r
from tests.unit.test_physics.test_string_section_bypass_clamp import state
from tests.unit.test_physics.test_string_section_bypass_diode_authority import (
    diode,
    parent,
    reverse,
)


def inputs() -> tuple[Any, Any, Any, Any]:
    p = parent()
    rev = reverse(p)
    diodes = d.resolve_section_bypass_diode_authority(
        p, rev, {k: diode(k) for k in rev.resolved_section_ids}
    )
    states = {
        k: replace(state(2.0 if i in (0, 3) else 10.0), state_reference=f"state:{i}")
        for i, k in enumerate(rev.resolved_section_ids)
    }
    return p, rev, diodes, states


def test_ordered_current_and_exact_owned_sums() -> None:
    p, rev, diodes, states = inputs()
    currents = (0.0, 1.0, 4.0, 8.0)
    result = c.compose_topology_common_current_iv(p, rev, diodes, states, currents)
    assert result.reference_plane == "string_terminal"
    assert result.resolved_string_ids == ("string-z", "string-a")
    assert result.unavailable_string_ids == ()
    assert result.topology_unavailable_string_ids == ("string-no-members",)
    sections, modules = result.section_samples, result.module_samples
    assert list(
        sections.drop_duplicates(["module_id", "section_id"])[
            ["module_id", "section_id"]
        ].itertuples(index=False, name=None)
    ) == [(k.module_id, k.section_id) for k in rev.resolved_section_ids]
    for _, group in sections.groupby(["module_id", "section_id"], sort=False):
        assert tuple(group.common_current_a) == currents
    for row in modules.itertuples(index=False):
        owned = sections[
            (sections.module_id == row.module_id) & (sections.curve_point == row.curve_point)
        ]
        assert row.voltage_v == math.fsum(owned.terminal_voltage_v)
    for string_id, curve in result.string_iv_curves_by_string_id.items():
        assert tuple(curve.current_a) == currents
        assert (curve.reference_plane == "string_terminal").all()
        for point, row in curve.iterrows():
            owned = modules[(modules.string_id == string_id) & (modules.curve_point == point)]
            assert row.voltage_v == math.fsum(owned.voltage_v)
            assert row.power_w == row.voltage_v * row.current_a
    at4 = sections[(sections.string_id == "string-z") & (sections.common_current_a == 4.0)]
    assert at4.bypass_active.tolist() == [True, False, False, True]
    assert result.diagnostics.section_sample_count == 24
    assert result.diagnostics.module_sample_count == 12
    assert result.diagnostics.string_sample_count == 8
    permuted = c.compose_topology_common_current_iv(
        p, rev, diodes, dict(reversed(tuple(states.items()))), currents
    )
    pd.testing.assert_frame_equal(
        result.section_samples, permuted.section_samples, check_exact=True
    )
    pd.testing.assert_frame_equal(result.module_samples, permuted.module_samples, check_exact=True)
    for key in result.string_iv_curves_by_string_id:
        pd.testing.assert_frame_equal(
            result.string_iv_curves_by_string_id[key],
            permuted.string_iv_curves_by_string_id[key],
            check_exact=True,
        )


@pytest.mark.parametrize("missing", ["reverse_breakdown", "bypass_diode", "operating_state"])
def test_missing_section_blocks_whole_advanced_string_only(missing: str) -> None:
    p, rev, diodes, states = inputs()
    key = rev.resolved_section_ids[0]
    if missing == "reverse_breakdown":
        rev = r.resolve_section_reverse_breakdown_authority(
            p, {k: v for k, v in rev.authorities_by_section.items() if k != key}
        )
    elif missing == "bypass_diode":
        diodes = d.resolve_section_bypass_diode_authority(
            p, rev, {k: v for k, v in diodes.authorities_by_section.items() if k != key}
        )
    else:
        del states[key]
    result = c.compose_topology_common_current_iv(p, rev, diodes, states, (0.0, 4.0))
    assert result.resolved_string_ids == ("string-a",)
    assert result.unavailable_string_ids == ("string-z",)
    assert result.missing_evidence_by_string_id["string-z"][0].identity == key
    assert result.missing_evidence_by_string_id["string-z"][0].missing_kinds == (missing,)
    assert set(result.section_samples.string_id) == {"string-a"}
    assert "string-z" not in result.string_iv_curves_by_string_id
    assert not any(k.module_id.startswith("string-z") for k in result.section_inputs_by_identity)


def test_empty_evidence_no_substitution_and_multiple_gap_reasons() -> None:
    p, _, _, _ = inputs()
    rev = r.resolve_section_reverse_breakdown_authority(p, {})
    diodes = d.resolve_section_bypass_diode_authority(p, rev, {})
    result = c.compose_topology_common_current_iv(p, rev, diodes, {}, (0.0, 1.0))
    assert result.unavailable_string_ids == ("string-z", "string-a")
    assert not result.resolved_string_ids
    assert not result.string_iv_curves_by_string_id
    assert result.section_samples.empty and result.module_samples.empty
    assert result.missing_evidence_by_string_id["string-z"][0].missing_kinds == (
        "reverse_breakdown",
        "bypass_diode",
        "operating_state",
    )


def test_detached_provenance_and_no_mutation() -> None:
    p, rev, diodes, states = inputs()
    before = repr(p), repr(rev), repr(diodes), repr(states)
    result = c.compose_topology_common_current_iv(p, rev, diodes, states, (0.0, 4.0))
    assert (repr(p), repr(rev), repr(diodes), repr(states)) == before
    again = c.compose_topology_common_current_iv(p, rev, diodes, states, (0.0, 4.0))
    key = rev.resolved_section_ids[0]
    assert result.section_inputs_by_identity[key].operating_state is not states[key]
    object.__setattr__(states[key], "photocurrent_a", -1)
    assert result.section_inputs_by_identity[key].operating_state.photocurrent_a == 2.0
    a = p.authorities_by_string_id["string-z"]
    object.__setattr__(a.module_members[0], "physical_position_reference", "caller-changed")
    assert (
        result.topology_authorities_by_string_id["string-z"]
        .module_members[0]
        .physical_position_reference
        != "caller-changed"
    )
    result.section_samples.loc[0, "terminal_voltage_v"] = -999
    result.string_iv_curves_by_string_id["string-z"].loc[0, "voltage_v"] = -999
    assert again.section_samples.terminal_voltage_v.iloc[0] != -999
    assert again.string_iv_curves_by_string_id["string-z"].voltage_v.iloc[0] != -999
    with pytest.raises(TypeError):
        result.section_inputs_by_identity[key] = None  # type: ignore[index]


def test_unknown_or_invalid_state_rejected() -> None:
    p, rev, diodes, states = inputs()
    states[r.BypassSectionIdentity("unknown", "section")] = state()
    with pytest.raises(ValueError):
        c.compose_topology_common_current_iv(p, rev, diodes, states, (0.0,))
    states.pop(r.BypassSectionIdentity("unknown", "section"))
    object.__setattr__(next(iter(states.values())), "photocurrent_a", True)
    with pytest.raises(ValueError):
        c.compose_topology_common_current_iv(p, rev, diodes, states, (0.0,))


def test_string_terminal_can_include_negative_power_without_peak_selection() -> None:
    p, rev, diodes, states = inputs()
    result = c.compose_topology_common_current_iv(p, rev, diodes, states, (100.0, 1000.0))
    assert result.string_iv_curves_by_string_id["string-z"].voltage_v.tolist() == [-2.0, -2.0]
    assert result.string_iv_curves_by_string_id["string-z"].power_w.tolist() == [-200.0, -2000.0]
    assert not hasattr(result, "maximum_power_point")


def test_no_downstream_or_optical_imports() -> None:
    tree = ast.parse(Path(c.__file__).read_text())
    imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imports <= {
        "__future__",
        "collections.abc",
        "dataclasses",
        "types",
        "heliotelligence.physics.string_member_topology_authority",
        "heliotelligence.physics.string_section_reverse_breakdown_authority",
        "heliotelligence.physics.string_section_bypass_diode_authority",
        "heliotelligence.physics.string_section_bypass_clamp",
        "heliotelligence.physics.string_section_reverse_iv",
    }
    assert not any(
        n.attr in {"argmax", "idxmax", "find_peaks"}
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
    )


def test_diagnostics_close_and_empty_topology() -> None:
    from heliotelligence.config.site import ElectricalTopologyConfig
    from heliotelligence.physics.string_member_topology_authority import (
        resolve_topology_string_member_authority,
    )

    p, rev, diodes, states = inputs()
    result = c.compose_topology_common_current_iv(p, rev, diodes, states, (0.0, 4.0))
    diag = result.diagnostics
    assert (
        diag.topology_string_count
        == diag.candidate_string_count + diag.topology_unavailable_string_count
    )
    assert (
        diag.candidate_string_count
        == diag.resolved_string_count + diag.unavailable_candidate_string_count
    )
    assert diag.string_sample_count == diag.resolved_string_count * diag.common_current_sample_count
    assert (
        diag.section_sample_count
        == len(result.section_inputs_by_identity) * diag.common_current_sample_count
    )
    empty_parent = resolve_topology_string_member_authority(ElectricalTopologyConfig(), {})
    empty_reverse = r.resolve_section_reverse_breakdown_authority(empty_parent, {})
    empty_diodes = d.resolve_section_bypass_diode_authority(empty_parent, empty_reverse, {})
    empty = c.compose_topology_common_current_iv(
        empty_parent, empty_reverse, empty_diodes, {}, (0.0,)
    )
    assert not empty.resolved_string_ids and not empty.unavailable_string_ids
    assert empty.section_samples.empty and empty.module_samples.empty
    assert empty.diagnostics.topology_string_count == 0


def test_numerical_section_failure_does_not_become_missing_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p, rev, diodes, states = inputs()

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("synthetic section failure")

    monkeypatch.setattr(c, "evaluate_section_bypass_clamp", broken)
    with pytest.raises(ValueError, match="synthetic section failure"):
        c.compose_topology_common_current_iv(p, rev, diodes, states, (0.0, 4.0))


def test_final_contract_and_no_peak_output_fields() -> None:
    from dataclasses import fields

    p, rev, diodes, states = inputs()
    result = c.compose_topology_common_current_iv(p, rev, diodes, states, (0.0,))
    assert result.contract == c.COMMON_CURRENT_COMPOSITION_CONTRACT_ID
    assert result.model == c.COMMON_CURRENT_COMPOSITION_MODEL_ID
    assert result.scope == c.COMMON_CURRENT_COMPOSITION_SCOPE
    assert result.coverage_scope == c.COMMON_CURRENT_COMPOSITION_COVERAGE_SCOPE
    assert not any("peak" in f.name or "mpp" in f.name for f in fields(result))
