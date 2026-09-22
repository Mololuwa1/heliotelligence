"""Tests for the S7A canonical receiver/time optical-state contract."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any, Literal

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
from heliotelligence.physics.pvsyst_far_horizon import (
    PVsystFarHorizonProfile,
    evaluate_pvsyst_far_horizon,
)
from heliotelligence.physics.pvsyst_horizon_authority import (
    PVsystHorizonActivation,
    compare_and_select_pvsyst_far_horizon,
)
from heliotelligence.physics.pvsyst_linear_shading import (
    PVsystLinearShadingTable,
    evaluate_pvsyst_linear_beam_shading,
)
from heliotelligence.physics.pvsyst_shading_authority import (
    PVsystNearShadingScope,
    compare_and_select_pvsyst_near_shading,
)
from heliotelligence.physics.terrain_horizon import (
    TerrainHorizonScene,
    calculate_terrain_horizon_direct_beam_shading,
)


def _receiver(
    identifier: str,
    *,
    kind: ReceiverKind = ReceiverKind.FIXED_TABLE,
    normal: tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> PVReceiver:
    vertices = np.asarray(((0.0, 0.0, 1.0), (0.0, 1.0, 1.0), (1.0, 0.0, 1.0)))
    return PVReceiver(
        identifier,
        TriangleMesh(vertices, np.asarray(((0, 1, 2),))),
        (1 / 3, 1 / 3, 1.0),
        normal,
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
    bundle = {
        "receivers": receivers,
        "front_poa_by_receiver": front,
        "beam_iam_by_receiver": iam,
        "terrain_horizon": terrain,
        "fixed_inter_row": fixed,
        "near_object": near,
        "diffuse_sky_visibility": diffuse,
        "rear_mode_by_receiver": {"a": "not_applicable", "b": "not_applicable"},
    }
    _refresh_authorities(bundle)
    return bundle


def _refresh_authorities(
    bundle: dict[str, Any],
    *,
    near_transmission: float = 1.0,
    horizon_activation: Literal["enabled", "disabled", "unknown"] = "enabled",
) -> None:
    receivers = bundle["receivers"]
    first_front = bundle["front_poa_by_receiver"][receivers[0].id]
    zenith = first_front["apparent_solar_zenith_deg"]
    azimuth = first_front["solar_azimuth_deg"]
    elevation = 90.0 - zenith
    near_table = PVsystLinearShadingTable(
        "table",
        "south",
        None,
        (1.0, 90.0),
        (-180.0, 180.0),
        ((near_transmission, near_transmission), (near_transmission, near_transmission)),
        "transmission_fraction",
        "test",
        None,
        None,
    )
    near_result = evaluate_pvsyst_linear_beam_shading(
        near_table, elevation, azimuth, hemisphere="north"
    )
    near_authority = compare_and_select_pvsyst_near_shading(
        receivers,
        bundle["fixed_inter_row"],
        bundle["near_object"],
        {"table": near_result},
        [
            PVsystNearShadingScope(f"scope-{receiver.id}", "table", (receiver.id,))
            for receiver in receivers
        ],
        fallback_policy="no_fallback",
    )
    horizon_profile = PVsystFarHorizonProfile(
        "profile",
        (-180.0, 0.0, 180.0),
        (-5.0, -5.0, -5.0),
        "full_azimuth_periodic",
        "test",
        None,
        None,
    )
    horizon_result = evaluate_pvsyst_far_horizon(
        horizon_profile, elevation, azimuth, hemisphere="north"
    )
    horizon_authority = compare_and_select_pvsyst_far_horizon(
        receivers,
        bundle["terrain_horizon"],
        horizon_result,
        activation=PVsystHorizonActivation("profile", "variant", horizon_activation, "test"),
        fallback_policy="no_fallback",
    )
    bundle["near_shading_authority"] = near_authority
    bundle["far_horizon_authority"] = horizon_authority


def _assemble(bundle: dict[str, Any]) -> OpticalStateResult:
    return assemble_receiver_optical_state(**bundle)


def _set_near_selection(
    bundle: dict[str, Any], key: tuple[pd.Timestamp, str], value: float | None
) -> None:
    result = bundle["near_shading_authority"]
    frame = result.receiver_authority.copy(deep=True)
    resolved = value is not None
    frame.loc[key, "selected_near_shading_beam_transmission_fraction"] = value
    frame.loc[key, "selected_near_shading_beam_shaded_fraction"] = (
        None if value is None else 1.0 - value
    )
    frame.loc[key, "selected_near_shading_resolved"] = resolved
    frame.loc[key, "selected_near_shading_source"] = "pvsyst" if resolved else "none"
    frame.loc[key, "selected_near_shading_state"] = (
        "resolved_pvsyst_authority" if resolved else "unresolved_both_sources"
    )
    frame.loc[key, "pvsyst_near_shading_beam_transmission_fraction"] = value
    frame.loc[key, "pvsyst_near_shading_beam_shaded_fraction"] = (
        None if value is None else 1.0 - value
    )
    frame.loc[key, "pvsyst_near_shading_resolved"] = resolved
    if not resolved:
        frame.loc[key, "helio_near_shading_beam_transmission_fraction"] = np.nan
        frame.loc[key, "helio_near_shading_beam_shaded_fraction"] = np.nan
        frame.loc[key, "helio_near_shading_resolved"] = False
    bundle["near_shading_authority"] = replace(result, receiver_authority=frame)


def _set_horizon_selection(
    bundle: dict[str, Any],
    key: tuple[pd.Timestamp, str],
    value: float | None,
    *,
    disabled: bool = False,
) -> None:
    result = bundle["far_horizon_authority"]
    frame = result.receiver_authority.copy(deep=True)
    resolved = value is not None
    frame.loc[key, "selected_horizon_beam_visible_factor"] = value
    frame.loc[key, "selected_horizon_visibility_resolved"] = resolved
    frame.loc[key, "selected_horizon_source"] = (
        "pvsyst_project_horizon_disabled" if disabled else "pvsyst" if resolved else "none"
    )
    frame.loc[key, "selected_horizon_state"] = (
        "resolved_pvsyst_project_horizon_disabled_clear"
        if disabled
        else "resolved_pvsyst_horizon_authority"
        if resolved
        else "unresolved_both_sources"
    )
    frame.loc[key, "pvsyst_horizon_activation_state"] = (
        "disabled" if disabled else "enabled" if resolved else "unknown"
    )
    frame.loc[key, "pvsyst_horizon_authority_factor"] = value
    frame.loc[key, "pvsyst_horizon_authority_resolved"] = resolved
    frame.loc[key, "pvsyst_horizon_authority_source"] = (
        "pvsyst_project_horizon_disabled" if disabled else "pvsyst" if resolved else "none"
    )
    frame.loc[key, "pvsyst_horizon_authority_state"] = (
        "resolved_project_horizon_disabled_clear"
        if disabled
        else "resolved_pvsyst_horizon_authority"
        if resolved
        else "unresolved_project_horizon_activation_unknown"
    )
    if not resolved:
        frame.loc[key, "terrain_horizon_visibility_resolved"] = False
        frame.loc[key, "terrain_horizon_beam_visible_factor"] = np.nan
        terrain = bundle["terrain_horizon"].copy(deep=True)
        terrain.loc[key, "terrain_horizon_visibility_resolved"] = False
        terrain.loc[key, "terrain_horizon_beam_visible_factor"] = np.nan
        bundle["terrain_horizon"] = terrain
    bundle["far_horizon_authority"] = replace(result, receiver_authority=frame)


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


@pytest.mark.parametrize(
    "column",
    [
        "ghi_wm2",
        "dhi_wm2",
        "dni_wm2",
        "apparent_solar_zenith_deg",
        "solar_azimuth_deg",
        "dni_extra_wm2",
    ],
)
def test_common_front_meteorology_and_solar_state_is_required(column: str) -> None:
    bundle = _bundle()
    frame = bundle["front_poa_by_receiver"]["b"]
    frame.iloc[0, frame.columns.get_loc(column)] += 1.0
    with pytest.raises(ValueError, match="inconsistent receiver front meteorology/solar state"):
        _assemble(bundle)


def test_common_front_irradiance_nan_pattern_is_required() -> None:
    bundle = _bundle()
    bundle["front_poa_by_receiver"]["b"].iloc[0, 0] = np.nan
    with pytest.raises(ValueError, match="inconsistent receiver front meteorology/solar state"):
        _assemble(bundle)


def test_receiver_specific_orientation_poa_and_aoi_remain_valid() -> None:
    bundle = _bundle()
    tilted = _receiver("b", normal=(0.0, -0.5, float(np.sqrt(3.0) / 2.0)))
    bundle["receivers"] = [bundle["receivers"][1], tilted]
    ghi, dhi, dni, zenith, azimuth = _inputs()
    tilted_front = calculate_raw_poa_transposition(
        ghi,
        dhi,
        dni,
        zenith,
        azimuth,
        surface_tilt_deg=30.0,
        surface_azimuth_deg=180.0,
        albedo=0.2,
        model="perez-driesse",
    )
    bundle["front_poa_by_receiver"]["b"] = tilted_front
    bundle["beam_iam_by_receiver"]["b"] = calculate_beam_iam(
        tilted_front["aoi_deg"], model="ashrae", model_parameters={"b": 0.05}
    )
    for mechanism in ("terrain_horizon", "fixed_inter_row", "near_object"):
        for timestamp in tilted_front.index:
            bundle[mechanism].loc[(timestamp, "b"), "poa_direct_raw_wm2"] = tilted_front.loc[
                timestamp, "poa_direct_raw_wm2"
            ]
    bundle["diffuse_sky_visibility"] = DiffuseSkyScene(
        bundle["receivers"],
        samples_per_receiver=2,
        sky_direction_count=8,
        max_rays_per_batch=7,
    ).calculate_visibility()
    _refresh_authorities(bundle)
    state = _assemble(bundle).state
    assert not np.allclose(
        state.loc[(slice(None), "a"), "aoi_deg"],
        state.loc[(slice(None), "b"), "aoi_deg"],
    )
    assert not np.allclose(
        state.loc[(slice(None), "a"), "poa_global_raw_wm2"],
        state.loc[(slice(None), "b"), "poa_global_raw_wm2"],
    )


@pytest.mark.parametrize("factor", [-0.1, 1.1, np.inf, -np.inf, True, "0.5"])
def test_resolved_iam_factor_must_be_physical(factor: object) -> None:
    bundle = _bundle()
    frame = bundle["beam_iam_by_receiver"]["a"]
    frame["beam_iam_factor"] = frame["beam_iam_factor"].astype(object)
    frame.iloc[0, frame.columns.get_loc("beam_iam_factor")] = factor
    with pytest.raises(ValueError, match="beam IAM factor"):
        _assemble(bundle)


def test_unresolved_iam_factor_is_preserved_without_replacement() -> None:
    bundle = _bundle()
    frame = bundle["beam_iam_by_receiver"]["a"]
    frame.loc[frame.index[0], "beam_iam_resolved"] = False
    frame.loc[frame.index[0], "beam_iam_factor"] = np.nan
    row = _assemble(bundle).state.loc[(frame.index[0], "a")]
    assert not bool(row["beam_iam_resolved"])
    assert np.isnan(row["beam_iam_factor"])
    assert "poa_direct_after_iam_wm2" not in row.index


def test_diffuse_receiver_normal_identity_is_required() -> None:
    bundle = _bundle()
    diffuse = bundle["diffuse_sky_visibility"]
    diffuse.receivers.loc[0, "receiver_normal_east"] += 0.1
    with pytest.raises(ValueError, match="receiver normal"):
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
    ("terrain", "fixed", "near"),
    [
        (1.0, 0.7, 1.0),
        (1.0, 1.0, 0.6),
        (0.0, 0.7, 0.6),
        (1.0, 0.0, 0.6),
        (1.0, 0.7, 0.0),
        (1.0, 0.7, 0.6),
    ],
)
def test_exact_direct_composition_gate(
    terrain: float,
    fixed: float,
    near: float,
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
    _refresh_authorities(bundle)
    row = _assemble(bundle).state.loc[key]
    assert row["front_direct_geometric_visible_fraction"] == pytest.approx(1.0)
    assert bool(row["front_direct_geometric_composition_resolved"])
    assert row["selected_near_shading_source"] == "pvsyst"
    assert row["front_direct_composition_model"] == DIRECT_COMPOSITION_ID


@pytest.mark.parametrize(
    ("horizon", "near", "expected", "resolved", "state"),
    [
        (1.0, 0.72, 0.72, True, "resolved_selected_shading_authorities"),
        (0.0, 0.63, 0.0, True, "resolved_selected_shading_authorities"),
        (1.0, 0.0, 0.0, True, "resolved_selected_shading_authorities"),
        (0.0, None, 0.0, True, "resolved_fully_blocked_by_selected_authority"),
        (None, 0.0, 0.0, True, "resolved_fully_blocked_by_selected_authority"),
        (None, 0.5, np.nan, False, "unresolved_selected_authority_dependency"),
        (1.0, None, np.nan, False, "unresolved_selected_authority_dependency"),
        (None, None, np.nan, False, "unresolved_selected_authority_dependency"),
    ],
)
def test_selected_authority_composition_and_zero_dominance(
    horizon: float | None,
    near: float | None,
    expected: float,
    resolved: bool,
    state: str,
) -> None:
    bundle = _bundle()
    key = (_inputs()[0].index[0], "a")
    _set_horizon_selection(bundle, key, horizon)
    _set_near_selection(bundle, key, near)
    row = _assemble(bundle).state.loc[key]
    if np.isnan(expected):
        assert np.isnan(row["front_direct_geometric_visible_fraction"])
    else:
        assert row["front_direct_geometric_visible_fraction"] == pytest.approx(expected)
        assert row["front_direct_geometric_shaded_fraction"] == pytest.approx(1.0 - expected)
    assert bool(row["front_direct_geometric_composition_resolved"]) is resolved
    assert row["front_direct_geometric_state"] == state


def test_real_disabled_horizon_authority_overrides_blocked_raw_terrain() -> None:
    bundle = _bundle()
    key = (_inputs()[0].index[0], "a")
    bundle["terrain_horizon"].loc[key, "terrain_horizon_beam_visible_factor"] = 0.0
    _refresh_authorities(bundle, horizon_activation="disabled")
    row = _assemble(bundle).state.loc[key]
    assert row["pvsyst_horizon_activation_state"] == "disabled"
    assert row["terrain_horizon_beam_visible_factor"] == 0.0
    assert row["selected_horizon_source"] == "pvsyst_project_horizon_disabled"
    assert row["selected_horizon_beam_visible_factor"] == 1.0
    assert row["front_direct_geometric_visible_fraction"] == pytest.approx(1.0)


def test_real_pvsyst_near_authority_overrides_helio_challenger() -> None:
    bundle = _bundle()
    key = (_inputs()[0].index[0], "a")
    bundle["fixed_inter_row"].loc[
        key,
        ["fixed_inter_row_beam_visible_fraction", "fixed_inter_row_beam_shaded_fraction"],
    ] = (0.4, 0.6)
    _refresh_authorities(bundle, near_transmission=0.8)
    authority_row = bundle["near_shading_authority"].receiver_authority.loc[key]
    row = _assemble(bundle).state.loc[key]
    assert authority_row["helio_near_shading_beam_transmission_fraction"] == pytest.approx(0.4)
    assert authority_row["pvsyst_near_shading_beam_transmission_fraction"] == pytest.approx(0.8)
    assert row["selected_near_shading_source"] == "pvsyst"
    assert row["selected_near_shading_beam_transmission_fraction"] == pytest.approx(0.8)
    assert row["front_direct_geometric_visible_fraction"] == pytest.approx(0.8)


def test_authority_type_contract_count_and_area_tamper_are_rejected() -> None:
    bundle = _bundle()
    bundle["near_shading_authority"] = bundle["near_shading_authority"].receiver_authority
    with pytest.raises(ValueError, match="PVsystNearShadingAuthorityResult"):
        _assemble(bundle)

    bundle = _bundle()
    result = bundle["near_shading_authority"]
    frame = result.receiver_authority.copy(deep=True)
    frame.iloc[0, frame.columns.get_loc("pvsyst_shading_authority_contract")] = "forged"
    bundle["near_shading_authority"] = replace(result, receiver_authority=frame)
    with pytest.raises(ValueError, match="not canonical"):
        _assemble(bundle)

    bundle = _bundle()
    result = bundle["far_horizon_authority"]
    frame = result.receiver_authority.copy(deep=True)
    frame.iloc[0, frame.columns.get_loc("receiver_surface_area_m2")] *= 2.0
    bundle["far_horizon_authority"] = replace(result, receiver_authority=frame)
    with pytest.raises(ValueError, match="surface area"):
        _assemble(bundle)


def test_authority_candidate_replay_contradictions_are_rejected() -> None:
    key = (_inputs()[0].index[0], "a")

    bundle = _bundle()
    result = bundle["far_horizon_authority"]
    frame = result.receiver_authority.copy(deep=True)
    frame.loc[key, "selected_horizon_source"] = "pvsyst_project_horizon_disabled"
    frame.loc[key, "selected_horizon_state"] = "resolved_pvsyst_project_horizon_disabled_clear"
    bundle["far_horizon_authority"] = replace(result, receiver_authority=frame)
    with pytest.raises(ValueError, match="replay"):
        _assemble(bundle)

    bundle = _bundle()
    result = bundle["far_horizon_authority"]
    frame = result.receiver_authority.copy(deep=True)
    frame.loc[key, "selected_horizon_source"] = "heliotelligence_fallback"
    frame.loc[key, "selected_horizon_state"] = "resolved_heliotelligence_fallback"
    bundle["far_horizon_authority"] = replace(result, receiver_authority=frame)
    with pytest.raises(ValueError, match="replay"):
        _assemble(bundle)

    bundle = _bundle()
    result = bundle["far_horizon_authority"]
    frame = result.receiver_authority.copy(deep=True)
    frame.loc[key, "selected_horizon_beam_visible_factor"] = 0.0
    bundle["far_horizon_authority"] = replace(result, receiver_authority=frame)
    with pytest.raises(ValueError, match="replay"):
        _assemble(bundle)

    bundle = _bundle()
    result = bundle["near_shading_authority"]
    frame = result.receiver_authority.copy(deep=True)
    frame.loc[key, "selected_near_shading_source"] = "heliotelligence_fallback"
    frame.loc[key, "selected_near_shading_state"] = "resolved_heliotelligence_fallback"
    bundle["near_shading_authority"] = replace(result, receiver_authority=frame)
    with pytest.raises(ValueError, match="fallback provenance"):
        _assemble(bundle)

    bundle = _bundle()
    result = bundle["near_shading_authority"]
    frame = result.receiver_authority.copy(deep=True)
    frame.loc[key, "selected_near_shading_beam_transmission_fraction"] = 0.8
    frame.loc[key, "selected_near_shading_beam_shaded_fraction"] = 0.2
    bundle["near_shading_authority"] = replace(result, receiver_authority=frame)
    with pytest.raises(ValueError, match="PVsyst candidate"):
        _assemble(bundle)

    bundle = _bundle()
    result = bundle["near_shading_authority"]
    frame = result.receiver_authority.copy(deep=True)
    frame.loc[key, "fallback_policy"] = "heliotelligence_if_pvsyst_unresolved"
    frame.loc[key, "selected_near_shading_source"] = "heliotelligence_fallback"
    frame.loc[key, "selected_near_shading_state"] = "resolved_heliotelligence_fallback"
    frame.loc[key, "selected_near_shading_beam_transmission_fraction"] = 0.8
    frame.loc[key, "selected_near_shading_beam_shaded_fraction"] = 0.2
    frame.loc[key, "pvsyst_near_shading_resolved"] = False
    bundle["near_shading_authority"] = replace(result, receiver_authority=frame)
    with pytest.raises(ValueError, match="Helio candidate"):
        _assemble(bundle)


def test_helio_fallback_is_rejected_when_pvsyst_candidate_resolves() -> None:
    bundle = _bundle()
    key = (_inputs()[0].index[0], "a")
    result = bundle["near_shading_authority"]
    frame = result.receiver_authority.copy(deep=True)
    assert bool(frame.loc[key, "pvsyst_near_shading_resolved"])
    assert bool(frame.loc[key, "helio_near_shading_resolved"])
    frame.loc[key, "fallback_policy"] = "heliotelligence_if_pvsyst_unresolved"
    frame.loc[key, "selected_near_shading_source"] = "heliotelligence_fallback"
    frame.loc[key, "selected_near_shading_state"] = "resolved_heliotelligence_fallback"
    frame.loc[key, "selected_near_shading_beam_transmission_fraction"] = frame.loc[
        key, "helio_near_shading_beam_transmission_fraction"
    ]
    frame.loc[key, "selected_near_shading_beam_shaded_fraction"] = frame.loc[
        key, "helio_near_shading_beam_shaded_fraction"
    ]
    bundle["near_shading_authority"] = replace(result, receiver_authority=frame)
    with pytest.raises(ValueError, match="fallback provenance"):
        _assemble(bundle)


def test_horizon_unresolved_selection_requires_canonical_candidate_availability() -> None:
    key = (_inputs()[0].index[0], "a")

    # A: policy refusal is impossible when the Helio terrain candidate is unresolved.
    bundle = _bundle()
    _refresh_authorities(bundle, horizon_activation="unknown")
    terrain = bundle["terrain_horizon"].copy(deep=True)
    terrain.loc[key, "terrain_horizon_visibility_resolved"] = False
    terrain.loc[key, "terrain_horizon_beam_visible_factor"] = np.nan
    bundle["terrain_horizon"] = terrain
    result = bundle["far_horizon_authority"]
    frame = result.receiver_authority.copy(deep=True)
    frame.loc[key, "terrain_horizon_visibility_resolved"] = False
    frame.loc[key, "terrain_horizon_beam_visible_factor"] = np.nan
    bundle["far_horizon_authority"] = replace(result, receiver_authority=frame)
    with pytest.raises(ValueError, match="unresolved PVsyst horizon authority candidates"):
        _assemble(bundle)

    # B: both-unresolved is impossible when Helio terrain resolves.
    bundle = _bundle()
    _refresh_authorities(bundle, horizon_activation="unknown")
    result = bundle["far_horizon_authority"]
    frame = result.receiver_authority.copy(deep=True)
    frame.loc[key, "selected_horizon_state"] = "unresolved_both_sources"
    bundle["far_horizon_authority"] = replace(result, receiver_authority=frame)
    with pytest.raises(ValueError, match="both-unresolved horizon authority candidates"):
        _assemble(bundle)


@pytest.mark.parametrize(
    ("activation", "candidate_column", "candidate_value"),
    [
        ("disabled", "pvsyst_horizon_activation_state", "disabled"),
        ("unknown", "pvsyst_horizon_authority_factor", 1.0),
        ("unknown", "pvsyst_horizon_authority_source", "pvsyst"),
        ("unknown", "pvsyst_horizon_authority_state", "wrong"),
        ("enabled_unresolved", "pvsyst_horizon_authority_state", "wrong"),
    ],
)
def test_unresolved_horizon_candidate_provenance_contradictions_are_rejected(
    activation: str, candidate_column: str, candidate_value: object
) -> None:
    """C-G: unresolved candidates must match their activation provenance exactly."""
    bundle = _bundle()
    key = (_inputs()[0].index[0], "a")
    _refresh_authorities(bundle, horizon_activation="unknown")
    result = bundle["far_horizon_authority"]
    frame = result.receiver_authority.copy(deep=True)
    if activation == "enabled_unresolved":
        frame.loc[key, "pvsyst_horizon_activation_state"] = "enabled"
        frame.loc[key, "pvsyst_horizon_authority_state"] = "unresolved_pvsyst_profile_visibility"
    frame.loc[key, candidate_column] = candidate_value
    bundle["far_horizon_authority"] = replace(result, receiver_authority=frame)
    with pytest.raises(ValueError, match="candidate provenance"):
        _assemble(bundle)


@pytest.mark.parametrize("activation", ["enabled", "disabled"])
def test_resolved_horizon_candidate_state_contradictions_are_rejected(activation: str) -> None:
    """H-I: enabled and disabled resolved candidates retain canonical candidate states."""
    bundle = _bundle()
    key = (_inputs()[0].index[0], "a")
    _refresh_authorities(bundle, horizon_activation=activation)  # type: ignore[arg-type]
    result = bundle["far_horizon_authority"]
    frame = result.receiver_authority.copy(deep=True)
    frame.loc[key, "pvsyst_horizon_authority_state"] = "wrong"
    bundle["far_horizon_authority"] = replace(result, receiver_authority=frame)
    with pytest.raises(ValueError, match="candidate provenance"):
        _assemble(bundle)


@pytest.mark.parametrize(
    ("state", "pvsyst_resolved", "helio_resolved"),
    [
        ("unresolved_pvsyst_authority", True, True),
        ("unresolved_pvsyst_authority", False, False),
        ("unresolved_both_sources", True, False),
        ("unresolved_both_sources", False, True),
    ],
)
def test_unresolved_near_selection_requires_canonical_candidate_states(
    state: str, pvsyst_resolved: bool, helio_resolved: bool
) -> None:
    bundle = _bundle()
    key = (_inputs()[0].index[0], "a")
    result = bundle["near_shading_authority"]
    frame = result.receiver_authority.copy(deep=True)
    frame.loc[key, "selected_near_shading_resolved"] = False
    frame.loc[key, "selected_near_shading_source"] = "none"
    frame.loc[key, "selected_near_shading_state"] = state
    frame.loc[key, "selected_near_shading_beam_transmission_fraction"] = np.nan
    frame.loc[key, "selected_near_shading_beam_shaded_fraction"] = np.nan
    frame.loc[key, "fallback_policy"] = "no_fallback"
    frame.loc[key, "pvsyst_near_shading_resolved"] = pvsyst_resolved
    frame.loc[key, "helio_near_shading_resolved"] = helio_resolved
    bundle["near_shading_authority"] = replace(result, receiver_authority=frame)
    with pytest.raises(ValueError, match="candidates are inconsistent"):
        _assemble(bundle)


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
    for name in ("near_shading_authority", "far_horizon_authority"):
        result = second[name]
        second[name] = replace(result, receiver_authority=result.receiver_authority.iloc[::-1])
    pd.testing.assert_frame_equal(_assemble(second).state, expected)


def test_unresolved_front_irradiance_is_not_filled() -> None:
    bundle = _bundle()
    key = (_inputs()[0].index[0], "a")
    front = bundle["front_poa_by_receiver"]["a"]
    front.loc[key[0], ["ghi_wm2", "poa_direct_raw_wm2", "poa_global_raw_wm2"]] = np.nan
    front.loc[key[0], "poa_transposition_resolved"] = False
    bundle["front_poa_by_receiver"]["b"].loc[key[0], "ghi_wm2"] = np.nan
    for name in ("terrain_horizon", "fixed_inter_row", "near_object"):
        bundle[name].loc[key, "poa_direct_raw_wm2"] = np.nan
    _refresh_authorities(bundle)
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
    _refresh_authorities(bundle)
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
