"""Tests for component-resolved front optical effective irradiance."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.geometry import PVReceiver, ReceiverKind, TriangleMesh
from heliotelligence.physics.diffuse_sky_visibility import (
    DiffuseComponentOpticalTransmission,
    DiffuseSkyScene,
)
from heliotelligence.physics.effective_irradiance import (
    EFFECTIVE_IRRADIANCE_MODEL_ID,
    EFFECTIVE_IRRADIANCE_SCOPE,
    FrontEffectiveIrradianceResult,
    calculate_front_effective_irradiance,
)
from heliotelligence.physics.fixed_inter_row_shading import (
    FixedInterRowScene,
    FixedRowArrayDefinition,
    FixedRowDefinition,
    calculate_fixed_inter_row_direct_beam_shading,
)
from heliotelligence.physics.iam import calculate_beam_iam
from heliotelligence.physics.iam_parameters import resolve_beam_iam_parameters
from heliotelligence.physics.near_object_shading import (
    NearObjectBeamScene,
    calculate_near_object_direct_beam_shading,
)
from heliotelligence.physics.optical_state import (
    OpticalStateResult,
    assemble_receiver_optical_state,
)
from heliotelligence.physics.poa_transposition import calculate_raw_poa_transposition
from heliotelligence.physics.pvsyst_far_horizon import (
    PVsystFarHorizonProfile,
    evaluate_pvsyst_far_horizon,
)
from heliotelligence.physics.pvsyst_horizon_authority import (
    PVsystFarHorizonAuthorityResult,
    PVsystHorizonActivation,
    compare_and_select_pvsyst_far_horizon,
)
from heliotelligence.physics.pvsyst_linear_shading import (
    PVsystLinearShadingTable,
    evaluate_pvsyst_linear_beam_shading,
)
from heliotelligence.physics.pvsyst_shading_authority import (
    PVsystNearShadingAuthorityResult,
    PVsystNearShadingScope,
    compare_and_select_pvsyst_near_shading,
)
from heliotelligence.physics.terrain_horizon import (
    TerrainHorizonScene,
    calculate_terrain_horizon_direct_beam_shading,
)


def _receiver(
    identifier: str = "receiver", *, horizontal: bool = False, tilt_deg: float = 30.0
) -> PVReceiver:
    if horizontal:
        normal = (0.0, 0.0, 1.0)
        vertices = np.asarray(((-0.5, -0.5, 2.0), (0.5, -0.5, 2.0), (0.0, 0.5, 2.0)))
    else:
        tilt = np.radians(tilt_deg)
        normal = (0.0, -float(np.sin(tilt)), float(np.cos(tilt)))
        vertices = np.asarray(((-0.5, 0.0, 2.3), (0.5, 0.0, 2.3), (0.0, 0.8, 1.8)))
    return PVReceiver(
        identifier,
        TriangleMesh(vertices, np.asarray(((0, 1, 2),))),
        tuple(np.mean(vertices, axis=0)),
        normal,
        ReceiverKind.FIXED_TABLE,
    )


def _inputs(*, missing: bool = False) -> tuple[pd.Series, ...]:
    index = pd.date_range("2026-06-01 12:00", periods=3, freq="h", tz="UTC", name="time")
    ghi = (800.0, 500.0, 0.0)
    dhi = (120.0, 90.0, 0.0)
    dni = (700.0, 400.0, 0.0)
    if missing:
        ghi = (np.nan, *ghi[1:])
        dhi = (np.nan, *dhi[1:])
        dni = (np.nan, *dni[1:])
    return (
        pd.Series(ghi, index=index),
        pd.Series(dhi, index=index),
        pd.Series(dni, index=index),
        pd.Series((35.0, 70.0, 100.0), index=index),
        pd.Series((180.0, 210.0, 180.0), index=index),
    )


def _bundle(
    *,
    model: str = "perez-driesse",
    horizontal: bool = False,
    missing: bool = False,
    tilt_deg: float = 30.0,
    inputs: tuple[pd.Series, ...] | None = None,
) -> tuple[
    list[PVReceiver], OpticalStateResult, DiffuseComponentOpticalTransmission, dict[str, object]
]:
    receiver = _receiver(horizontal=horizontal, tilt_deg=tilt_deg)
    inputs = _inputs(missing=missing) if inputs is None else inputs
    tilt = 0.0 if horizontal else tilt_deg
    front = calculate_raw_poa_transposition(
        *inputs,
        surface_tilt_deg=tilt,
        surface_azimuth_deg=180.0,
        albedo=0.2,
        model=model,  # type: ignore[arg-type]
    )
    parameters = resolve_beam_iam_parameters(
        model="ashrae",
        method="direct",
        source_label="test",
        source_reference="test-reference",
        model_parameters={"b": 0.05},
    )
    iam = calculate_beam_iam(front["aoi_deg"], model="ashrae", model_parameters={"b": 0.05})
    raw = pd.DataFrame({receiver.id: front["poa_direct_raw_wm2"]})
    zenith, azimuth = inputs[3], inputs[4]
    row = FixedRowDefinition("row", (receiver.id,), 0.0, 2.0)
    array = FixedRowArrayDefinition("array", 0.0, 0.0, (row,), ())
    terrain = calculate_terrain_horizon_direct_beam_shading(
        raw, zenith, azimuth, scene=TerrainHorizonScene([receiver], [])
    )
    fixed = calculate_fixed_inter_row_direct_beam_shading(
        raw, zenith, azimuth, scene=FixedInterRowScene([receiver], [array])
    )
    near = calculate_near_object_direct_beam_shading(
        raw,
        zenith,
        azimuth,
        scene=NearObjectBeamScene([receiver], [], samples_per_receiver=4),
    )
    near_authority, horizon_authority = _authorities(
        receiver, terrain, fixed, near, zenith, azimuth
    )
    diffuse_scene = DiffuseSkyScene(
        [receiver],
        samples_per_receiver=4,
        sky_direction_count=64,
        max_rays_per_batch=31,
    )
    optical = assemble_receiver_optical_state(
        [receiver],
        {receiver.id: front},
        {receiver.id: iam},
        terrain,
        fixed,
        near,
        diffuse_scene.calculate_visibility(),
        near_shading_authority=near_authority,
        far_horizon_authority=horizon_authority,
        rear_mode_by_receiver={receiver.id: "not_applicable"},
    )
    components = diffuse_scene.calculate_component_optical_transmission(
        horizon_zenith_count=2,
        horizon_azimuth_count=36,
        ground_direction_count=128,
        ground_plane_z_m=0.0,
        beam_iam_model_by_receiver={receiver.id: "ashrae"},
        model_parameters_by_receiver={receiver.id: {"b": 0.05}},
    )
    return [receiver], optical, components, parameters


def _authorities(
    receiver: PVReceiver | Sequence[PVReceiver],
    terrain: pd.DataFrame,
    fixed: pd.DataFrame,
    near: pd.DataFrame,
    zenith: pd.Series,
    azimuth: pd.Series,
) -> tuple[PVsystNearShadingAuthorityResult, PVsystFarHorizonAuthorityResult]:
    receivers = [receiver] if isinstance(receiver, PVReceiver) else list(receiver)
    elevation = 90.0 - zenith
    table = PVsystLinearShadingTable(
        "table",
        "south",
        None,
        (1.0, 90.0),
        (-180.0, 180.0),
        ((1.0, 1.0), (1.0, 1.0)),
        "transmission_fraction",
        "test",
    )
    near_result = evaluate_pvsyst_linear_beam_shading(table, elevation, azimuth, hemisphere="north")
    near_authority = compare_and_select_pvsyst_near_shading(
        receivers,
        fixed,
        near,
        {"table": near_result},
        [PVsystNearShadingScope(f"site-{item.id}", "table", (item.id,)) for item in receivers],
        fallback_policy="no_fallback",
    )
    profile = PVsystFarHorizonProfile(
        "profile",
        (-180.0, 0.0, 180.0),
        (-5.0, -5.0, -5.0),
        "full_azimuth_periodic",
        "test",
    )
    horizon_result = evaluate_pvsyst_far_horizon(profile, elevation, azimuth, hemisphere="north")
    horizon_authority = compare_and_select_pvsyst_far_horizon(
        receivers,
        terrain,
        horizon_result,
        activation=PVsystHorizonActivation("profile", "variant", "enabled", "test"),
        fallback_policy="no_fallback",
    )
    return near_authority, horizon_authority


def _calculate(
    bundle: tuple[
        list[PVReceiver],
        OpticalStateResult,
        DiffuseComponentOpticalTransmission,
        dict[str, object],
    ],
) -> FrontEffectiveIrradianceResult:
    receivers, optical, components, parameters = bundle
    return calculate_front_effective_irradiance(
        receivers,
        optical,
        components,
        beam_iam_parameters_by_receiver={receivers[0].id: parameters},
    )


@pytest.mark.parametrize("model", ["perez", "perez-driesse"])
def test_complete_production_chain_and_perez_component_parity(model: str) -> None:
    result = _calculate(_bundle(model=model))
    frame = result.irradiance
    daylight = frame[frame["front_effective_irradiance_resolved"]]
    assert not daylight.empty
    assert np.allclose(
        daylight["poa_front_isotropic_raw_wm2"]
        + daylight["poa_front_circumsolar_raw_wm2"]
        + daylight["poa_front_horizon_raw_wm2"],
        daylight["poa_front_sky_diffuse_raw_wm2"],
    )
    assert np.isfinite(daylight["poa_front_effective_optical_wm2"]).all()
    assert (daylight["effective_irradiance_model"] == EFFECTIVE_IRRADIANCE_MODEL_ID).all()
    assert (daylight["effective_irradiance_scope"] == EFFECTIVE_IRRADIANCE_SCOPE).all()


def test_beam_iam_parameter_reproduction_gate() -> None:
    receivers, optical, components, parameters = _bundle()
    wrong = deepcopy(parameters)
    wrong["model_parameters"] = {"b": 0.2}
    with pytest.raises(ValueError, match="do not match|do not reproduce"):
        calculate_front_effective_irradiance(
            receivers,
            optical,
            components,
            beam_iam_parameters_by_receiver={receivers[0].id: wrong},
        )


def test_component_classification_and_output_closure() -> None:
    receivers, optical, components, parameters = _bundle()
    state = optical.state.copy()
    key = state.index[0]
    state.loc[key, "front_direct_geometric_visible_fraction"] = 0.5
    component_frame = components.receivers.copy()
    component_frame.loc[0, "diffuse_sky_visible_fraction"] = 0.3
    component_frame.loc[0, "diffuse_sky_blocked_fraction"] = 0.7
    component_frame.loc[0, "diffuse_horizon_visible_fraction"] = 0.4
    component_frame.loc[0, "diffuse_horizon_blocked_fraction"] = 0.6
    component_frame.loc[0, "diffuse_ground_visible_fraction"] = 0.2
    component_frame.loc[0, "diffuse_ground_blocked_fraction"] = 0.8
    component_frame.loc[0, "diffuse_sky_joint_optical_transmission_factor"] = 0.21
    component_frame.loc[0, "diffuse_horizon_joint_optical_transmission_factor"] = 0.31
    component_frame.loc[0, "diffuse_ground_joint_optical_transmission_factor"] = 0.11
    component_frame.loc[0, "diffuse_sky_visible_region_iam_factor"] = 0.70
    component_frame.loc[0, "diffuse_horizon_visible_region_iam_factor"] = 0.775
    component_frame.loc[0, "diffuse_ground_visible_region_iam_factor"] = 0.55
    # Keep S7A/S7B-1 sky identity consistent while testing component classification.
    state.loc[:, "diffuse_sky_visible_fraction"] = 0.3
    state.loc[:, "diffuse_sky_blocked_fraction"] = 0.7
    result = calculate_front_effective_irradiance(
        receivers,
        OpticalStateResult(state, optical.diagnostics),
        DiffuseComponentOpticalTransmission(component_frame),
        beam_iam_parameters_by_receiver={receivers[0].id: parameters},
    ).irradiance.loc[key]
    direct_expected = result["poa_front_direct_raw_wm2"] * 0.5 * result["beam_iam_factor"]
    circumsolar_expected = result["poa_front_circumsolar_raw_wm2"] * 0.5 * result["beam_iam_factor"]
    isotropic_expected = result["poa_front_isotropic_raw_wm2"] * 0.21
    horizon_expected = result["poa_front_horizon_raw_wm2"] * 0.31
    ground_expected = result["poa_front_ground_diffuse_raw_wm2"] * 0.11
    assert result["poa_front_direct_effective_wm2"] == pytest.approx(direct_expected)
    assert result["poa_front_circumsolar_effective_wm2"] == pytest.approx(circumsolar_expected)
    assert result["poa_front_isotropic_effective_wm2"] == pytest.approx(isotropic_expected)
    assert result["poa_front_horizon_effective_wm2"] == pytest.approx(horizon_expected)
    assert result["poa_front_ground_diffuse_effective_wm2"] == pytest.approx(ground_expected)
    separable_isotropic = (
        result["poa_front_isotropic_raw_wm2"]
        * 0.3
        * result["diffuse_sky_marion_unobstructed_iam_reference"]
    )
    assert abs(isotropic_expected - separable_isotropic) > 0.1
    assert result["poa_front_sky_diffuse_effective_wm2"] == pytest.approx(
        circumsolar_expected + isotropic_expected + horizon_expected
    )
    assert result["poa_front_effective_optical_wm2"] == pytest.approx(
        direct_expected
        + circumsolar_expected
        + isotropic_expected
        + horizon_expected
        + ground_expected
    )


def test_direct_overlap_guard_and_zero_dependency() -> None:
    receivers, optical, components, parameters = _bundle()
    state = optical.state.copy()
    key = state.index[0]
    state.loc[key, "front_direct_geometric_composition_resolved"] = False
    state.loc[key, "front_direct_geometric_visible_fraction"] = np.nan
    result = calculate_front_effective_irradiance(
        receivers,
        OpticalStateResult(state, optical.diagnostics),
        components,
        beam_iam_parameters_by_receiver={receivers[0].id: parameters},
    ).irradiance.loc[key]
    assert np.isnan(result["poa_front_direct_effective_wm2"])
    assert np.isnan(result["poa_front_circumsolar_effective_wm2"])
    assert np.isnan(result["poa_front_effective_optical_wm2"])
    assert not bool(result["front_effective_irradiance_resolved"])

    night_key = state.index[-1]
    state.loc[night_key, "front_direct_geometric_composition_resolved"] = False
    state.loc[night_key, "front_direct_geometric_visible_fraction"] = np.nan
    night = calculate_front_effective_irradiance(
        receivers,
        OpticalStateResult(state, optical.diagnostics),
        components,
        beam_iam_parameters_by_receiver={receivers[0].id: parameters},
    ).irradiance.loc[night_key]
    assert night["poa_front_direct_effective_wm2"] == 0.0
    assert night["poa_front_circumsolar_effective_wm2"] == 0.0
    assert night["poa_front_effective_optical_wm2"] == pytest.approx(0.0)
    assert bool(night["front_effective_irradiance_resolved"])


def test_horizontal_ground_zero_dependency() -> None:
    result = _calculate(_bundle(horizontal=True)).irradiance
    assert result["diffuse_ground_visible_fraction"].isna().all()
    assert (result["poa_front_ground_diffuse_raw_wm2"] == 0.0).all()
    assert (result["poa_front_ground_diffuse_effective_wm2"] == 0.0).all()


def test_component_visibility_identity_gates() -> None:
    receivers, optical, components, parameters = _bundle()
    changed = components.receivers.copy()
    changed.loc[0, "diffuse_sky_visible_fraction"] -= 0.1
    with pytest.raises(ValueError, match="does not match"):
        calculate_front_effective_irradiance(
            receivers,
            optical,
            DiffuseComponentOpticalTransmission(changed),
            beam_iam_parameters_by_receiver={receivers[0].id: parameters},
        )
    changed = components.receivers.copy()
    changed.loc[0, "receiver_normal_east"] += 0.1
    with pytest.raises(ValueError, match="normal"):
        calculate_front_effective_irradiance(
            receivers,
            optical,
            DiffuseComponentOpticalTransmission(changed),
            beam_iam_parameters_by_receiver={receivers[0].id: parameters},
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "joint_factor",
        "visible_iam",
        "impossible_full_block",
        "contradictory_resolution",
    ],
)
def test_tampered_joint_optical_state_is_rejected(mutation: str) -> None:
    receivers, optical, components, parameters = _bundle()
    changed = components.receivers.copy()
    if mutation == "joint_factor":
        changed.loc[0, "diffuse_sky_joint_optical_transmission_factor"] *= 0.8
    elif mutation == "visible_iam":
        changed.loc[0, "diffuse_horizon_visible_region_iam_factor"] *= 0.8
    elif mutation == "impossible_full_block":
        changed.loc[0, "diffuse_sky_visible_fraction"] = 0.0
        changed.loc[0, "diffuse_sky_blocked_fraction"] = 1.0
        changed.loc[0, "diffuse_sky_joint_optical_transmission_factor"] = 0.2
        optical_state = optical.state.copy()
        optical_state.loc[:, "diffuse_sky_visible_fraction"] = 0.0
        optical_state.loc[:, "diffuse_sky_blocked_fraction"] = 1.0
        optical = OpticalStateResult(optical_state, optical.diagnostics)
    else:
        changed.loc[0, "diffuse_horizon_visibility_resolved"] = False
        changed.loc[0, "diffuse_horizon_joint_optical_resolved"] = True
    with pytest.raises(ValueError, match="joint|closure|inconsistent"):
        calculate_front_effective_irradiance(
            receivers,
            optical,
            DiffuseComponentOpticalTransmission(changed),
            beam_iam_parameters_by_receiver={receivers[0].id: parameters},
        )


def test_unresolved_upstream_irradiance_remains_nan() -> None:
    result = _calculate(_bundle(missing=True)).irradiance.iloc[0]
    assert np.isnan(result["poa_front_circumsolar_raw_wm2"])
    assert np.isnan(result["poa_front_direct_effective_wm2"])
    assert np.isnan(result["poa_front_effective_optical_wm2"])
    assert result["front_effective_irradiance_state"] == "unresolved_upstream_irradiance"


def test_rear_state_is_context_only() -> None:
    receivers, optical, components, parameters = _bundle()
    state = optical.state.copy()
    state.loc[:, "rear_mode"] = "fixed_bifacial_rear"
    state.loc[:, "poa_rear_global_raw_wm2"] = 9999.0
    first = calculate_front_effective_irradiance(
        receivers,
        OpticalStateResult(state, optical.diagnostics),
        components,
        beam_iam_parameters_by_receiver={receivers[0].id: parameters},
    ).irradiance
    state.loc[:, "poa_rear_global_raw_wm2"] = 1.0
    second = calculate_front_effective_irradiance(
        receivers,
        OpticalStateResult(state, optical.diagnostics),
        components,
        beam_iam_parameters_by_receiver={receivers[0].id: parameters},
    ).irradiance
    pd.testing.assert_series_equal(
        first["poa_front_effective_optical_wm2"],
        second["poa_front_effective_optical_wm2"],
    )
    assert "effective_irradiance_wm2" not in first
    assert not any("bifaciality" in column for column in first)


def test_transposition_model_contract_and_raw_sky_parity() -> None:
    receivers, optical, components, parameters = _bundle()
    state = optical.state.copy()
    state.loc[state.index[0], "transposition_model"] = "unsupported"
    with pytest.raises(ValueError, match="transposition model"):
        calculate_front_effective_irradiance(
            receivers,
            OpticalStateResult(state, optical.diagnostics),
            components,
            beam_iam_parameters_by_receiver={receivers[0].id: parameters},
        )
    state = optical.state.copy()
    state.loc[state.index[0], "poa_sky_diffuse_raw_wm2"] += 10.0
    with pytest.raises(RuntimeError, match="does not match"):
        calculate_front_effective_irradiance(
            receivers,
            OpticalStateResult(state, optical.diagnostics),
            components,
            beam_iam_parameters_by_receiver={receivers[0].id: parameters},
        )

    state = optical.state.copy()
    state.loc[state.index[0], "transposition_model"] = "perez"
    with pytest.raises(ValueError, match="common"):
        calculate_front_effective_irradiance(
            receivers,
            OpticalStateResult(state, optical.diagnostics),
            components,
            beam_iam_parameters_by_receiver={receivers[0].id: parameters},
        )


def test_negative_perez_horizon_is_preserved_and_scaled() -> None:
    index = pd.date_range("2026-06-01 18:00", periods=1, tz="UTC", name="time")
    inputs = (
        pd.Series((500.0,), index=index),
        pd.Series((100.0,), index=index),
        pd.Series((500.0,), index=index),
        pd.Series((85.0,), index=index),
        pd.Series((180.0,), index=index),
    )
    receivers, optical, components, parameters = _bundle(
        model="perez", tilt_deg=60.0, inputs=inputs
    )
    components.receivers.loc[0, "diffuse_horizon_visible_fraction"] = 0.5
    components.receivers.loc[0, "diffuse_horizon_blocked_fraction"] = 0.5
    components.receivers.loc[0, "diffuse_horizon_joint_optical_transmission_factor"] = (
        0.5 * components.receivers.loc[0, "diffuse_horizon_visible_region_iam_factor"]
    )
    result = calculate_front_effective_irradiance(
        receivers,
        optical,
        components,
        beam_iam_parameters_by_receiver={receivers[0].id: parameters},
    ).irradiance.iloc[0]
    assert result["poa_front_horizon_raw_wm2"] < 0.0
    assert result["poa_front_horizon_after_geometry_wm2"] == pytest.approx(
        result["poa_front_horizon_raw_wm2"] * 0.5
    )
    assert result["poa_front_horizon_effective_wm2"] == pytest.approx(
        result["poa_front_horizon_raw_wm2"]
        * result["diffuse_horizon_joint_optical_transmission_factor"]
    )
    assert result["poa_front_effective_optical_wm2"] >= 0.0


def test_horizon_visibility_zero_dependency() -> None:
    receivers, optical, components, parameters = _bundle()
    changed = components.receivers.copy()
    changed.loc[0, "diffuse_horizon_visibility_resolved"] = False
    changed.loc[0, "diffuse_horizon_visible_fraction"] = np.nan
    changed.loc[0, "diffuse_horizon_blocked_fraction"] = np.nan
    changed.loc[0, "diffuse_horizon_joint_optical_resolved"] = False
    changed.loc[0, "diffuse_horizon_joint_optical_transmission_factor"] = np.nan
    changed.loc[0, "diffuse_horizon_visible_region_iam_factor"] = np.nan
    changed.loc[0, "diffuse_horizon_unobstructed_iam_factor"] = np.nan
    changed.loc[0, "diffuse_horizon_joint_optical_state"] = "not_applicable_no_front_side_view"
    result = calculate_front_effective_irradiance(
        receivers,
        optical,
        DiffuseComponentOpticalTransmission(changed),
        beam_iam_parameters_by_receiver={receivers[0].id: parameters},
    ).irradiance
    assert np.isnan(result.iloc[0]["poa_front_horizon_effective_wm2"])
    assert not bool(result.iloc[0]["front_effective_irradiance_resolved"])
    assert result.iloc[-1]["poa_front_horizon_raw_wm2"] == pytest.approx(0.0)
    assert result.iloc[-1]["poa_front_horizon_effective_wm2"] == pytest.approx(0.0)


def test_determinism_and_empty_timestamp_output() -> None:
    bundle = _bundle()
    first = _calculate(bundle).irradiance
    receivers, optical, components, parameters = bundle
    reversed_components = DiffuseComponentOpticalTransmission(components.receivers.iloc[::-1])
    second = calculate_front_effective_irradiance(
        list(reversed(receivers)),
        optical,
        reversed_components,
        beam_iam_parameters_by_receiver=dict(reversed([(receivers[0].id, parameters)])),
    ).irradiance
    pd.testing.assert_frame_equal(first, second)

    empty_state = optical.state.iloc[:0]
    empty = calculate_front_effective_irradiance(
        receivers,
        OpticalStateResult(empty_state, optical.diagnostics),
        components,
        beam_iam_parameters_by_receiver={receivers[0].id: parameters},
    )
    assert empty.irradiance.empty
    assert list(empty.irradiance.columns)
