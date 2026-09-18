"""Tests for the S7A canonical receiver/time optical-state contract."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.geometry import PVReceiver, ReceiverKind, TriangleMesh
from heliotelligence.physics.diffuse_sky_visibility import DiffuseSkyScene
from heliotelligence.physics.fixed_bifacial_rear import (
    FixedBifacialRearParameters,
    FixedBifacialRearScene,
    calculate_fixed_bifacial_rear_irradiance,
)
from heliotelligence.physics.fixed_inter_row_shading import (
    FixedInterRowScene,
    FixedRowArrayDefinition,
    FixedRowBlockingPair,
    FixedRowDefinition,
    calculate_fixed_inter_row_direct_beam_shading,
)
from heliotelligence.physics.iam import calculate_beam_iam
from heliotelligence.physics.near_object_shading import (
    NearObjectBeamScene,
    calculate_near_object_direct_beam_shading,
)
from heliotelligence.physics.optical_state import (
    DIFFUSE_SKY_ROLE,
    DIRECT_COMPOSITION_ID,
    STATE_CONTRACT_ID,
    OpticalStateResult,
    assemble_receiver_optical_state,
)
from heliotelligence.physics.poa_transposition import calculate_raw_poa_transposition
from heliotelligence.physics.terrain_horizon import (
    TerrainHorizonScene,
    calculate_terrain_horizon_direct_beam_shading,
)


def _receiver(identifier: str, *, kind: ReceiverKind = ReceiverKind.FIXED_TABLE) -> PVReceiver:
    vertices = np.asarray(((0.0, 0.0, 1.0), (0.0, 1.0, 1.0), (1.0, 0.0, 1.0)))
    return PVReceiver(
        identifier,
        TriangleMesh(vertices, np.asarray(((0, 1, 2),))),
        (1 / 3, 1 / 3, 1.0),
        (0.0, 0.0, 1.0),
        kind,
    )


def _inputs() -> tuple[pd.Series, ...]:
    index = pd.date_range("2026-06-01 12:00", periods=3, freq="h", tz="UTC", name="time")
    return (
        pd.Series((800.0, 600.0, 0.0), index=index),
        pd.Series((100.0, 80.0, 0.0), index=index),
        pd.Series((700.0, 500.0, 0.0), index=index),
        pd.Series((30.0, 60.0, 100.0), index=index),
        pd.Series((180.0, 180.0, 180.0), index=index),
    )


def _bundle() -> dict[str, Any]:
    receivers = [_receiver("b"), _receiver("a")]
    ghi, dhi, dni, zenith, azimuth = _inputs()
    front = {
        receiver.id: calculate_raw_poa_transposition(
            ghi,
            dhi,
            dni,
            zenith,
            azimuth,
            surface_tilt_deg=0.0,
            surface_azimuth_deg=180.0,
            albedo=0.2,
            model="perez-driesse",
        )
        for receiver in receivers
    }
    iam = {
        receiver.id: calculate_beam_iam(
            front[receiver.id]["aoi_deg"], model="ashrae", model_parameters={"b": 0.05}
        )
        for receiver in receivers
    }
    raw = pd.DataFrame(
        {receiver.id: front[receiver.id]["poa_direct_raw_wm2"] for receiver in receivers}
    )
    row = FixedRowDefinition("row", ("a", "b"), 0.0, 2.0)
    array = FixedRowArrayDefinition("array", 0.0, 0.0, (row,), ())
    terrain = calculate_terrain_horizon_direct_beam_shading(
        raw, zenith, azimuth, scene=TerrainHorizonScene(receivers, [])
    )
    fixed = calculate_fixed_inter_row_direct_beam_shading(
        raw, zenith, azimuth, scene=FixedInterRowScene(receivers, [array])
    )
    near = calculate_near_object_direct_beam_shading(
        raw,
        zenith,
        azimuth,
        scene=NearObjectBeamScene(receivers, [], samples_per_receiver=4),
    )
    diffuse = DiffuseSkyScene(
        receivers, samples_per_receiver=2, sky_direction_count=8, max_rays_per_batch=7
    ).calculate_visibility()
    return {
        "receivers": receivers,
        "front_poa_by_receiver": front,
        "beam_iam_by_receiver": iam,
        "terrain_horizon": terrain,
        "fixed_inter_row": fixed,
        "near_object": near,
        "diffuse_sky_visibility": diffuse,
        "rear_mode_by_receiver": {"a": "not_applicable", "b": "not_applicable"},
    }


def _assemble(bundle: dict[str, Any]) -> OpticalStateResult:
    return assemble_receiver_optical_state(**bundle)


def test_real_primitives_integrate_and_preserve_boundaries() -> None:
    bundle = _bundle()
    result = _assemble(bundle)
    state = result.state
    assert state.index.names == ["time", "receiver_id"]
    assert state.index.get_level_values("receiver_id").tolist() == ["a", "b"] * 3
    assert (state["optical_state_contract"] == STATE_CONTRACT_ID).all()
    assert (state["diffuse_sky_application_role"] == DIFFUSE_SKY_ROLE).all()
    assert state["poa_sky_diffuse_raw_wm2"].equals(
        pd.concat(bundle["front_poa_by_receiver"], names=["receiver_id", "time"])[
            "poa_sky_diffuse_raw_wm2"
        ]
        .swaplevel()
        .sort_index()
    )
    assert not any("effective" in column or "after_visibility" in column for column in state)
    assert result.diagnostics.state_contract == STATE_CONTRACT_ID


def test_aoi_and_iam_consistency_gates() -> None:
    bundle = _bundle()
    front = deepcopy(bundle["front_poa_by_receiver"])
    front["a"].iloc[0, front["a"].columns.get_loc("aoi_deg")] += 1.0
    bundle["front_poa_by_receiver"] = front
    with pytest.raises(ValueError, match="AOI"):
        _assemble(bundle)
    bundle = _bundle()
    iam = deepcopy(bundle["beam_iam_by_receiver"])
    iam["a"].iloc[0, iam["a"].columns.get_loc("aoi_deg")] += 1.0
    bundle["beam_iam_by_receiver"] = iam
    with pytest.raises(ValueError, match="IAM AOI"):
        _assemble(bundle)


@pytest.mark.parametrize("mechanism", ["terrain_horizon", "fixed_inter_row", "near_object"])
def test_stale_direct_mechanisms_are_rejected(mechanism: str) -> None:
    bundle = _bundle()
    frame = bundle[mechanism].copy()
    frame.iloc[0, frame.columns.get_loc("poa_direct_raw_wm2")] += 2.0
    bundle[mechanism] = frame
    with pytest.raises(ValueError, match="does not match"):
        _assemble(bundle)


def test_solar_geometry_mismatch_is_rejected() -> None:
    bundle = _bundle()
    frame = bundle["terrain_horizon"].copy()
    frame.iloc[0, frame.columns.get_loc("solar_azimuth_deg")] += 1.0
    bundle["terrain_horizon"] = frame
    with pytest.raises(ValueError, match="solar_azimuth"):
        _assemble(bundle)


@pytest.mark.parametrize(
    ("terrain", "fixed", "near", "expected", "resolved", "overlap"),
    [
        (1.0, 0.7, 1.0, 0.7, True, "exact_no_partial_overlap_ambiguity"),
        (1.0, 1.0, 0.6, 0.6, True, "exact_no_partial_overlap_ambiguity"),
        (0.0, 0.7, 0.6, 0.0, True, "exact_no_partial_overlap_ambiguity"),
        (1.0, 0.0, 0.6, 0.0, True, "exact_no_partial_overlap_ambiguity"),
        (1.0, 0.7, 0.0, 0.0, True, "exact_no_partial_overlap_ambiguity"),
        (1.0, 0.7, 0.6, np.nan, False, "unresolved_fixed_near_partial_overlap"),
    ],
)
def test_exact_direct_composition_gate(
    terrain: float,
    fixed: float,
    near: float,
    expected: float,
    resolved: bool,
    overlap: str,
) -> None:
    bundle = _bundle()
    key = (_inputs()[0].index[0], "a")
    bundle["terrain_horizon"].loc[key, "terrain_horizon_beam_visible_factor"] = terrain
    bundle["fixed_inter_row"].loc[
        key,
        [
            "fixed_inter_row_beam_visible_fraction",
            "fixed_inter_row_beam_shaded_fraction",
        ],
    ] = (fixed, 1.0 - fixed)
    bundle["near_object"].loc[
        key,
        [
            "near_object_beam_visible_fraction",
            "near_object_beam_shaded_fraction",
        ],
    ] = (near, 1.0 - near)
    row = _assemble(bundle).state.loc[key]
    if np.isnan(expected):
        assert np.isnan(row["front_direct_geometric_visible_fraction"])
        assert row["front_direct_geometric_visible_fraction"] != pytest.approx(0.7 * 0.6)
    else:
        assert row["front_direct_geometric_visible_fraction"] == pytest.approx(expected)
    assert bool(row["front_direct_geometric_composition_resolved"]) is resolved
    assert row["front_direct_overlap_state"] == overlap
    assert row["front_direct_composition_model"] == DIRECT_COMPOSITION_ID


def test_below_horizon_and_diffuse_geometric_only() -> None:
    bundle = _bundle()
    diffuse = bundle["diffuse_sky_visibility"]
    diffuse.receivers.loc[:, "diffuse_sky_visible_fraction"] = 0.4
    diffuse.receivers.loc[:, "diffuse_sky_blocked_fraction"] = 0.6
    state = _assemble(bundle).state
    daylight = state.iloc[0]
    assert daylight["diffuse_sky_visible_fraction"] == pytest.approx(0.4)
    expected = bundle["front_poa_by_receiver"]["a"].iloc[0]["poa_sky_diffuse_raw_wm2"]
    assert daylight["poa_sky_diffuse_raw_wm2"] == expected
    night = state.loc[(_inputs()[0].index[2], "a")]
    assert np.isnan(night["front_direct_geometric_visible_fraction"])
    assert night["front_direct_geometric_state"] == "not_evaluated_no_above_horizon_direct_beam"


def test_not_applicable_rear_is_explicit() -> None:
    state = _assemble(_bundle()).state
    assert state["poa_rear_global_raw_wm2"].isna().all()
    assert (state["rear_irradiance_state"] == "not_applicable").all()
    assert not state["rear_irradiance_resolved"].any()
    assert not any("bifaciality" in column for column in state)


def _rear_frame(bundle: dict[str, Any]) -> pd.DataFrame:
    receivers = bundle["receivers"]
    rows = (
        FixedRowDefinition("rear-row-a", ("a",), 0.0, 2.0),
        FixedRowDefinition("rear-row-b", ("b",), 0.0, 2.0),
    )
    array = FixedRowArrayDefinition(
        "rear-array",
        0.0,
        0.0,
        rows,
        (FixedRowBlockingPair("rear-row-a", "rear-row-b", 4.0, 0.0),),
    )
    scene = FixedBifacialRearScene(
        receivers,
        [array],
        [FixedBifacialRearParameters("rear-array", 1.5, 0.2)],
        view_factor_points=20,
    )
    return calculate_fixed_bifacial_rear_irradiance(*_inputs(), scene=scene, model="haydavies")


def test_actual_rear_integration_and_mixed_modes() -> None:
    bundle = _bundle()
    rear = _rear_frame(bundle)
    bundle["rear_mode_by_receiver"] = {"a": "fixed_bifacial_rear", "b": "not_applicable"}
    bundle["rear_irradiance"] = rear.loc[(slice(None), ["a"]), :]
    state = _assemble(bundle).state
    source = rear.loc[(slice(None), "a"), "poa_rear_global_raw_wm2"].droplevel("receiver_id")
    actual = state.loc[(slice(None), "a"), "poa_rear_global_raw_wm2"].droplevel("receiver_id")
    pd.testing.assert_series_equal(actual, source, check_names=False, check_freq=False)
    assert state.loc[(slice(None), "b"), "poa_rear_global_raw_wm2"].isna().all()
    resolved = state.loc[(slice(None), "a"), "rear_irradiance_resolved"]
    assert np.allclose(
        state.loc[resolved.index, "poa_rear_global_raw_wm2"],
        state.loc[resolved.index, "poa_rear_direct_raw_wm2"]
        + state.loc[resolved.index, "poa_rear_diffuse_raw_wm2"],
    )


@pytest.mark.parametrize(
    "column", ["ghi_wm2", "dni_wm2", "apparent_solar_zenith_deg", "solar_azimuth_deg"]
)
def test_rear_input_mismatch_rejected(column: str) -> None:
    bundle = _bundle()
    rear = _rear_frame(bundle).loc[(slice(None), ["a"]), :].copy()
    rear.iloc[0, rear.columns.get_loc(column)] += 1.0
    bundle["rear_mode_by_receiver"] = {"a": "fixed_bifacial_rear", "b": "not_applicable"}
    bundle["rear_irradiance"] = rear
    with pytest.raises(ValueError, match=column):
        _assemble(bundle)


def test_determinism_under_input_reordering() -> None:
    first = _bundle()
    expected = _assemble(first).state
    second = _bundle()
    second["receivers"] = list(reversed(second["receivers"]))
    second["front_poa_by_receiver"] = dict(reversed(list(second["front_poa_by_receiver"].items())))
    second["beam_iam_by_receiver"] = dict(reversed(list(second["beam_iam_by_receiver"].items())))
    second["rear_mode_by_receiver"] = dict(reversed(list(second["rear_mode_by_receiver"].items())))
    for name in ("terrain_horizon", "fixed_inter_row", "near_object"):
        second[name] = second[name].iloc[::-1]
    pd.testing.assert_frame_equal(_assemble(second).state, expected)


def test_unresolved_front_irradiance_is_not_filled() -> None:
    bundle = _bundle()
    key = (_inputs()[0].index[0], "a")
    front = bundle["front_poa_by_receiver"]["a"]
    front.loc[key[0], ["ghi_wm2", "poa_direct_raw_wm2", "poa_global_raw_wm2"]] = np.nan
    front.loc[key[0], "poa_transposition_resolved"] = False
    for name in ("terrain_horizon", "fixed_inter_row", "near_object"):
        bundle[name].loc[key, "poa_direct_raw_wm2"] = np.nan
    row = _assemble(bundle).state.loc[key]
    assert np.isnan(row["poa_direct_raw_wm2"])
    assert np.isnan(row["front_direct_geometric_visible_fraction"])
    assert row["front_direct_geometric_state"] == "unresolved_upstream_direct_irradiance"


def test_contract_validation_failures() -> None:
    bundle = _bundle()
    bundle["rear_mode_by_receiver"] = {"a": "not_applicable"}
    with pytest.raises(ValueError, match="mapping keys"):
        _assemble(bundle)
    bundle = _bundle()
    duplicate = list(bundle["receivers"])
    duplicate.append(duplicate[0])
    bundle["receivers"] = duplicate
    with pytest.raises(ValueError, match="unique"):
        _assemble(bundle)
    bundle = _bundle()
    bundle["receivers"] = [_receiver("a", kind=ReceiverKind.TRACKER_TABLE), _receiver("b")]
    with pytest.raises(ValueError, match="S6C"):
        _assemble(bundle)
    bundle = _bundle()
    frame = bundle["fixed_inter_row"].iloc[:-1]
    bundle["fixed_inter_row"] = frame
    with pytest.raises(ValueError, match="exactly one"):
        _assemble(bundle)


def test_timestamp_and_rear_row_contracts_are_exact() -> None:
    bundle = _bundle()
    front = bundle["front_poa_by_receiver"]["a"].copy()
    front.index = front.index.tz_localize(None)
    bundle["front_poa_by_receiver"]["a"] = front
    with pytest.raises(ValueError, match="timezone-aware"):
        _assemble(bundle)

    bundle = _bundle()
    rear = _rear_frame(bundle).loc[(slice(None), ["a"]), :].iloc[:-1]
    bundle["rear_mode_by_receiver"] = {
        "a": "fixed_bifacial_rear",
        "b": "not_applicable",
    }
    bundle["rear_irradiance"] = rear
    with pytest.raises(ValueError, match="exactly match"):
        _assemble(bundle)


def test_empty_time_axis_returns_stable_typed_state() -> None:
    bundle = _bundle()
    for mapping_name in ("front_poa_by_receiver", "beam_iam_by_receiver"):
        bundle[mapping_name] = {
            receiver_id: frame.iloc[:0] for receiver_id, frame in bundle[mapping_name].items()
        }
    for mechanism in ("terrain_horizon", "fixed_inter_row", "near_object"):
        bundle[mechanism] = bundle[mechanism].iloc[:0]
    result = _assemble(bundle)
    assert result.state.empty
    assert result.state.index.names == ["time", "receiver_id"]
    assert list(result.state.columns)
    assert result.diagnostics.timestamp_count == 0
    assert result.diagnostics.row_count == 0


def test_invalid_factor_and_closure_are_rejected() -> None:
    bundle = _bundle()
    bundle["fixed_inter_row"].iloc[
        0,
        bundle["fixed_inter_row"].columns.get_loc("fixed_inter_row_beam_visible_fraction"),
    ] = 1.2
    with pytest.raises(ValueError, match="fractions"):
        _assemble(bundle)
    bundle = _bundle()
    bundle["front_poa_by_receiver"]["a"].iloc[
        0,
        bundle["front_poa_by_receiver"]["a"].columns.get_loc("poa_global_raw_wm2"),
    ] += 10.0
    with pytest.raises(ValueError, match="do not close"):
        _assemble(bundle)
