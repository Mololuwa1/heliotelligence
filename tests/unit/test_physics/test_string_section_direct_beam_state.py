"""Assigned finite sample sets, not continuous area or electrical factors."""

import ast
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import string_section_direct_beam_state as s
from heliotelligence.physics import string_section_optical_binding_authority as a
from heliotelligence.physics.shading import (
    RectangularSurface3D,
    calculate_direct_beam_visibility_map,
)
from tests.unit.test_physics.test_string_member_topology_authority import resolved
from tests.unit.test_physics.test_string_section_optical_binding_authority import (
    bindings,
    geometry,
    resolve,
)


def frame() -> pd.DataFrame:
    # Uses the existing ray tracer on explicit synthetic rectangles; no canonical
    # geometry conversion or physical layout inference is asserted by this fixture.
    surface = RectangularSurface3D(
        "receiver-independent", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), 1.0, 1.0
    )
    return calculate_direct_beam_visibility_map(
        [surface],
        ["receiver-independent"],
        solar_zenith_deg=0.0,
        solar_azimuth_deg=0.0,
        samples_u=2,
        samples_v=4,
    )


def snapshot(f: Any = None, **changes: Any) -> s.DirectBeamVisibilitySnapshot:
    return s.DirectBeamVisibilitySnapshot(
        "revision-1", "snapshot:test", 2, 4, frame() if f is None else f, **changes
    )


def run(f: Any = None, authority: Any = None, snaps: Any = None) -> s.SectionDirectBeamStateResult:
    return s.resolve_section_direct_beam_state(
        resolved(),
        geometry(),
        resolve() if authority is None else authority,
        (snapshot(f),) if snaps is None else snaps,
    )


def test_visible_shaded_partial_count_and_metadata() -> None:
    f = frame()
    f.loc[[2, 3, 5, 6, 7], "beam_visible"] = False
    f["beam_shaded"] = ~f.beam_visible
    r = run(f)
    states = list(r.states_by_section.values())
    assert [(x.visible_sample_count, x.shaded_sample_count) for x in states] == [
        (2, 0),
        (0, 2),
        (1, 1),
        (0, 2),
    ]
    assert r.contract == "section_direct_beam_visibility_state_v1"
    assert r.model == "bound_receiver_sample_visibility_aggregation_v1"
    assert (
        r.scope
        == "advanced_s8_section_optical_state_before_section_electrical_parameter_resolution"
    )
    assert r.coverage_scope == "explicit_bound_visibility_samples_on_reviewed_geometry_revision"
    for x in states:
        assert x.visible_sample_count + x.shaded_sample_count == x.bound_sample_count
        assert x.beam_visible_fraction + x.beam_shaded_fraction == pytest.approx(1.0, abs=1e-15)
        assert x.resolved and x.state == "resolved_assigned_direct_beam_samples"
        assert x.snapshot_reference == "snapshot:test" and x.geometry_revision == "revision-1"
        assert x.confidence == "unknown" and x.solar_zenith_deg is None
    assert states[0].all_samples_visible and states[1].all_samples_shaded


def test_receiver_half_shaded_does_not_make_each_section_half_shaded() -> None:
    b = bindings()
    k = list(b)
    b = {
        k[0]: replace(b[k[0]], samples_v=2, sample_indices=(0, 1)),
        k[1]: replace(b[k[1]], samples_v=2, sample_indices=(2, 3)),
    }
    auth = resolve(b)
    f = frame().iloc[:4].copy()
    f["sample_u_index"] = [0, 0, 1, 1]
    f["sample_v_index"] = [0, 1, 0, 1]
    f["beam_visible"] = [True, True, False, False]
    f["beam_shaded"] = ~f.beam_visible
    snap = replace(snapshot(f), samples_v=2)
    r = run(authority=auth, snaps=(snap,))
    x = list(r.states_by_section.values())
    assert f.beam_shaded.mean() == 0.5
    assert [v.beam_shaded_fraction for v in x] == [0.0, 1.0]
    assert len(r.unavailable_section_ids) == 2


def test_interleaved_permutation_unbound_and_extra_rows() -> None:
    b = bindings()
    k = list(b)
    auth = resolve(
        {
            k[0]: replace(b[k[0]], sample_indices=(0, 3, 6)),
            k[1]: replace(b[k[1]], sample_indices=(1, 4)),
        }
    )
    f = frame()
    f.loc[[3, 4], "beam_visible"] = False
    f["beam_shaded"] = ~f.beam_visible
    original = f.copy(deep=True)
    r = run(f, auth)
    extra = f.copy()
    extra["receiver_id"] = "unrelated"
    again = run(pd.concat([f, extra]).sample(frac=1, random_state=1), auth)
    assert r == again
    assert list(r.states_by_section.values())[0].shaded_sample_indices == (3,)
    pd.testing.assert_frame_equal(f, original)
    assert r.states_by_section is not again.states_by_section
    assert next(iter(r.states_by_section.values())) is not next(
        iter(again.states_by_section.values())
    )


@pytest.mark.parametrize(
    "column,value",
    [
        ("sample_index", 9),
        ("sample_index", True),
        ("sample_u_index", 2),
        ("sample_v_index", True),
        ("sample_v_index", 1),
        ("sample_east_m", float("nan")),
        ("sample_up_m", float("inf")),
        ("sample_north_m", True),
        ("beam_visible", 1),
        ("beam_visible", "true"),
        ("beam_shaded", 0),
        ("beam_shaded", True),
        ("receiver_id", "wrong"),
    ],
)
def test_invalid_map_row_rejected(column: str, value: Any) -> None:
    f = frame().astype(object)
    f.loc[0, column] = value
    with pytest.raises(ValueError):
        run(f)


def test_missing_duplicate_schema_stale_and_grid_rejected() -> None:
    f = frame()
    for bad in (f.iloc[1:], pd.concat([f, f.iloc[:1]]), f.drop(columns="beam_visible")):
        with pytest.raises(ValueError):
            run(bad)
    for bad in (
        replace(snapshot(), geometry_revision="old"),
        replace(snapshot(), samples_v=3),
        replace(snapshot(), samples_u=True),
        replace(snapshot(), snapshot_reference=" "),
    ):
        with pytest.raises(ValueError):
            run(snaps=(bad,))


def test_optional_angles_explicit_empty_and_multiple_grids() -> None:
    r = run(snaps=(snapshot(solar_zenith_deg=30.0, solar_azimuth_deg=100.0),))
    assert all(x.solar_zenith_deg == 30.0 for x in r.states_by_section.values())
    assert not run(authority=resolve({}), snaps=()).states_by_section
    with pytest.raises(ValueError):
        run(snaps=())
    with pytest.raises(ValueError):
        run(snaps=(snapshot(), snapshot()))
    with pytest.raises(ValueError):
        run(snaps=(snapshot(solar_zenith_deg=True),))


def test_no_electrical_or_runtime_execution_imports() -> None:
    forbidden = (
        "string_section_reverse_iv",
        "string_section_bypass_clamp",
        "string_common_current_composition",
        "string_multi_peak_candidates",
        "dc_collection",
        "inverter",
        "engine",
        "api",
        "pvlib",
    )
    for module in (a, s):
        assert module.__file__ is not None
        tree = ast.parse(Path(module.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not any(x in (node.module or "") for x in forbidden)
            if isinstance(node, ast.Import):
                assert not any(x in alias.name for alias in node.names for x in forbidden)


def test_different_explicit_grids_and_unbound_cells() -> None:
    b = bindings()
    k = list(b)
    auth = resolve(
        {
            k[0]: replace(b[k[0]], samples_u=1, samples_v=2, sample_indices=(0,)),
            k[1]: replace(b[k[1]], sample_indices=(2, 3)),
        }
    )
    small = frame().iloc[:2].copy()
    snaps = (replace(snapshot(small), samples_u=1, samples_v=2), snapshot())
    before = run(authority=auth, snaps=snaps)
    small.loc[1, "beam_visible"] = False
    small.loc[1, "beam_shaded"] = True
    assert run(authority=auth, snaps=tuple(reversed(snaps))) == before
    assert list(before.states_by_section) == list(auth.resolved_section_ids)
    assert before.unavailable_section_ids == auth.unavailable_section_ids


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "30", -1.0])
def test_invalid_optional_angles(value: Any) -> None:
    with pytest.raises(ValueError):
        run(snaps=(snapshot(solar_zenith_deg=value),))


def test_output_is_optical_only_and_caller_mutation_cannot_change_it() -> None:
    from dataclasses import fields
    from types import MappingProxyType

    f = frame()
    r = run(f)
    before = next(iter(r.states_by_section.values()))
    f.loc[0, "beam_visible"] = False
    f.loc[0, "beam_shaded"] = True
    assert before.beam_visible_fraction == 1.0
    assert type(r.states_by_section) is MappingProxyType
    names = {x.name for x in fields(before)}
    assert not names & {
        "effective_irradiance_wm2",
        "cell_temperature_c",
        "photocurrent_a",
        "saturation_current_a",
        "resistance_series_ohm",
        "resistance_shunt_ohm",
        "n_ns_vth_v",
    }
