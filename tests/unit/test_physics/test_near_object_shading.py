"""Production tests for canonical near-object direct-beam shading."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

import heliotelligence.physics.near_object_shading as near_module
from heliotelligence.geometry import (
    PVReceiver,
    ReceiverKind,
    ShadingObject,
    ShadowRole,
    TerrainSurface,
    TriangleMesh,
)
from heliotelligence.physics.near_object_shading import (
    MODEL_ID,
    NearObjectBeamScene,
    calculate_near_object_direct_beam_shading,
    couple_sample_near_object_direct_beam,
    sample_triangle_mesh,
)
from heliotelligence.physics.shading import (
    RectangularSurface3D,
    calculate_direct_beam_visibility_map,
    solar_direction_enu,
)


def _rectangle(
    *,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    width: float = 2.0,
    height: float = 2.0,
    reverse: bool = False,
) -> TriangleMesh:
    x, y, z = center
    vertices = np.asarray(
        (
            (x - width / 2, y - height / 2, z),
            (x + width / 2, y - height / 2, z),
            (x + width / 2, y + height / 2, z),
            (x - width / 2, y + height / 2, z),
        ),
        dtype=np.float64,
    )
    faces = np.asarray(((0, 2, 1), (0, 3, 2)) if reverse else ((0, 1, 2), (0, 2, 3)))
    return TriangleMesh(vertices, faces)


def _receiver(
    receiver_id: str = "receiver",
    *,
    mesh: TriangleMesh | None = None,
    kind: ReceiverKind = ReceiverKind.FIXED_TABLE,
) -> PVReceiver:
    mesh = mesh or _rectangle()
    return PVReceiver(receiver_id, mesh, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), kind)


def _object(
    object_id: str,
    *,
    center: tuple[float, float, float] = (0.0, 0.0, 1.0),
    role: ShadowRole = ShadowRole.OCCLUDER,
    width: float = 4.0,
    height: float = 4.0,
    reverse: bool = False,
) -> ShadingObject:
    return ShadingObject(
        object_id,
        _rectangle(center=center, width=width, height=height, reverse=reverse),
        role,
    )


def _timeseries(raw: list[float]) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    index = pd.date_range("2026-01-01", periods=len(raw), freq="h", tz="UTC", name="time")
    return (
        pd.DataFrame({"receiver": raw}, index=index),
        pd.Series([0.0] * len(raw), index=index),
        pd.Series([180.0] * len(raw), index=index),
    )


def test_scene_validation_empty_receivers_and_empty_receiver_mesh() -> None:
    scene = NearObjectBeamScene([], [], samples_per_receiver=4)
    visibility = scene.calculate_visibility(
        apparent_solar_zenith_deg=0.0, solar_azimuth_deg=0.0
    )
    assert visibility.samples.empty and visibility.receivers.empty
    with pytest.raises(ValueError, match="unique"):
        NearObjectBeamScene([_receiver("same"), _receiver("same")], [], samples_per_receiver=4)
    empty = TriangleMesh(np.empty((0, 3)), np.empty((0, 3), dtype=np.int64))
    with pytest.raises(ValueError, match="non-empty"):
        NearObjectBeamScene([_receiver(mesh=empty)], [], samples_per_receiver=4)
    with pytest.raises(ValueError, match="samples_per_receiver"):
        NearObjectBeamScene([_receiver()], [], samples_per_receiver=0)


@pytest.mark.parametrize("count", [1, 7, 64])
def test_sampler_is_deterministic_finite_weighted_and_on_triangle(count: int) -> None:
    mesh = TriangleMesh(
        np.asarray(((0.0, 0.0, 2.0), (2.0, 0.0, 2.0), (0.0, 2.0, 2.0))),
        np.asarray(((0, 1, 2),)),
    )
    first = sample_triangle_mesh(mesh, count)
    second = sample_triangle_mesh(mesh, count)
    np.testing.assert_array_equal(first, second)
    assert first.shape == (count, 3)
    assert np.isfinite(first).all()
    np.testing.assert_allclose(first[:, 2], 2.0)
    assert np.all(first[:, 0] >= 0) and np.all(first[:, 1] >= 0)
    assert np.all(first[:, 0] + first[:, 1] <= 2.0 + 1e-12)


def test_sampler_area_distribution_translation_and_input_immutability() -> None:
    vertices = np.asarray(
        (
            (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 2.0, 0.0),
            (10.0, 0.0, 0.0), (13.0, 0.0, 0.0), (10.0, 2.0, 0.0),
        )
    )
    mesh = TriangleMesh(vertices, np.asarray(((0, 1, 2), (3, 4, 5))))
    before = mesh.vertices_enu_m.copy()
    samples = sample_triangle_mesh(mesh, 40)
    assert np.count_nonzero(samples[:, 0] < 5.0) == 10
    assert np.count_nonzero(samples[:, 0] > 5.0) == 30
    translated = TriangleMesh(vertices + (1000.0, 1000.0, 1000.0), mesh.faces)
    np.testing.assert_allclose(sample_triangle_mesh(translated, 40), samples + 1000.0)
    np.testing.assert_array_equal(mesh.vertices_enu_m, before)


@pytest.mark.parametrize(
    ("role", "expected_shaded"),
    [
        (ShadowRole.OCCLUDER, True),
        (ShadowRole.NON_OCCLUDER, False),
        (ShadowRole.UNKNOWN, False),
    ],
)
def test_only_explicit_occluder_casts(role: ShadowRole, expected_shaded: bool) -> None:
    scene = NearObjectBeamScene(
        [_receiver()], [_object("candidate", role=role)], samples_per_receiver=16
    )
    visibility = scene.calculate_visibility(
        apparent_solar_zenith_deg=0.0, solar_azimuth_deg=180.0
    )
    assert bool(visibility.samples["beam_shaded"].all()) is expected_shaded
    assert scene.diagnostics.eligible_occluder_count == int(expected_shaded)


def test_mixed_roles_empty_scene_and_diagnostics() -> None:
    scene = NearObjectBeamScene(
        [_receiver()],
        [
            _object("approved"),
            _object("ignored", role=ShadowRole.NON_OCCLUDER),
            _object("unknown", role=ShadowRole.UNKNOWN),
        ],
        samples_per_receiver=8,
    )
    assert scene.diagnostics.eligible_occluder_count == 1
    assert scene.diagnostics.ignored_non_occluder_count == 1
    assert scene.diagnostics.ignored_unknown_count == 1
    assert scene.diagnostics.ray_primitive_count == 2
    empty = NearObjectBeamScene([_receiver()], [], samples_per_receiver=8)
    result = empty.calculate_visibility(
        apparent_solar_zenith_deg=0.0, solar_azimuth_deg=180.0
    )
    assert result.receivers.iloc[0]["visible_fraction"] == 1.0
    assert result.samples["blocking_object_id"].isna().all()
    assert np.isinf(result.samples["blocking_distance_m"]).all()


def test_partial_multiple_overlapping_and_nearest_blocker() -> None:
    scene = NearObjectBeamScene(
        [_receiver()],
        [
            _object("near", center=(-0.5, 0.0, 1.0), width=1.0),
            _object("overlap-far", center=(-0.5, 0.0, 2.0), width=1.0),
            _object("right", center=(0.5, 0.0, 1.5), width=1.0),
        ],
        samples_per_receiver=256,
    )
    result = scene.calculate_visibility(
        apparent_solar_zenith_deg=0.0, solar_azimuth_deg=180.0
    )
    assert result.receivers.iloc[0]["shaded_fraction"] == 1.0
    left = result.samples[result.samples["sample_east_m"] < 0.0]
    assert set(left["blocking_object_id"]) == {"near"}


def test_occluder_input_order_does_not_change_nonambiguous_physics() -> None:
    objects = [
        _object("near", center=(0.0, 0.0, 1.0)),
        _object("far", center=(0.0, 0.0, 2.0)),
    ]
    first = NearObjectBeamScene([_receiver()], objects, samples_per_receiver=16)
    second = NearObjectBeamScene([_receiver()], list(reversed(objects)), samples_per_receiver=16)
    first_result = first.calculate_visibility(
        apparent_solar_zenith_deg=0.0, solar_azimuth_deg=180.0
    )
    second_result = second.calculate_visibility(
        apparent_solar_zenith_deg=0.0, solar_azimuth_deg=180.0
    )
    assert set(first_result.samples["blocking_object_id"]) == {"near"}
    assert set(second_result.samples["blocking_object_id"]) == {"near"}
    np.testing.assert_allclose(
        first_result.samples["blocking_distance_m"],
        second_result.samples["blocking_distance_m"],
    )


def test_backface_arbitrary_blocker_and_tracker_pose_are_supported() -> None:
    triangle = TriangleMesh(
        np.asarray(((-2.0, -2.0, 1.0), (2.0, -2.0, 1.0), (0.0, 2.0, 1.0))),
        np.asarray(((0, 2, 1),)),
    )
    blocker = ShadingObject("triangle", triangle, ShadowRole.OCCLUDER)
    scene = NearObjectBeamScene(
        [_receiver(kind=ReceiverKind.TRACKER_TABLE)], [blocker], samples_per_receiver=16
    )
    result = scene.calculate_visibility(
        apparent_solar_zenith_deg=0.0, solar_azimuth_deg=180.0
    )
    assert result.samples["beam_shaded"].any()


def test_other_receivers_and_terrain_are_not_automatic_occluders() -> None:
    lower = _receiver("lower")
    upper = _receiver("upper", mesh=_rectangle(center=(0.0, 0.0, 1.0)))
    terrain = TerrainSurface("terrain", _rectangle(center=(0.0, 0.0, 0.5)))
    scene = NearObjectBeamScene([lower, upper], [], samples_per_receiver=8)
    result = scene.calculate_visibility(
        apparent_solar_zenith_deg=0.0, solar_azimuth_deg=180.0
    )
    assert result.samples["beam_visible"].all()
    assert terrain.id == "terrain"


def test_above_horizon_direction_and_invalid_horizon() -> None:
    east_blocker = _object("east", center=(1.0, 0.0, 1.0), width=1.5)
    scene = NearObjectBeamScene([_receiver()], [east_blocker], samples_per_receiver=64)
    east_sun = scene.calculate_visibility(
        apparent_solar_zenith_deg=45.0, solar_azimuth_deg=90.0
    )
    west_sun = scene.calculate_visibility(
        apparent_solar_zenith_deg=45.0, solar_azimuth_deg=270.0
    )
    assert east_sun.receivers.iloc[0]["shaded_fraction"] > 0.0
    assert west_sun.receivers.iloc[0]["shaded_fraction"] == 0.0
    with pytest.raises(ValueError):
        scene.calculate_visibility(apparent_solar_zenith_deg=90.0, solar_azimuth_deg=0.0)


def test_visibility_schema_weights_conservation_and_blocker_provenance() -> None:
    scene = NearObjectBeamScene([_receiver()], [_object("blocker")], samples_per_receiver=9)
    result = scene.calculate_visibility(
        apparent_solar_zenith_deg=0.0, solar_azimuth_deg=180.0
    )
    assert result.samples.columns.tolist() == near_module._SAMPLE_COLUMNS
    assert (result.samples["sample_weight_fraction"] > 0.0).all()
    np.testing.assert_allclose(result.samples["sample_weight_fraction"].sum(), 1.0)
    row = result.receivers.iloc[0]
    np.testing.assert_allclose(row["visible_fraction"] + row["shaded_fraction"], 1.0)
    assert set(result.samples["blocking_object_id"]) == {"blocker"}
    assert np.isfinite(result.samples["blocking_distance_m"]).all()


def test_timeseries_direct_coupling_and_states_preserve_inputs() -> None:
    scene = NearObjectBeamScene([_receiver()], [_object("blocker")], samples_per_receiver=8)
    raw, zenith, azimuth = _timeseries([800.0, 0.0, np.nan, 0.0, 50.0])
    zenith.iloc[3:] = 90.0
    raw_before = raw.copy(deep=True)
    result = calculate_near_object_direct_beam_shading(raw, zenith, azimuth, scene=scene)
    first = result.iloc[0]
    assert first["poa_direct_near_object_visible_wm2"] == 0.0
    assert first["near_object_shading_loss_wm2"] == 800.0
    assert first["near_object_shading_model"] == MODEL_ID
    assert result.iloc[1]["near_object_shading_loss_wm2"] == 0.0
    assert result.iloc[1]["near_object_visibility_resolved"]
    assert np.isnan(result.iloc[2]["poa_direct_near_object_visible_wm2"])
    assert result.iloc[2]["near_object_visibility_resolved"]
    assert result.iloc[3]["near_object_shading_state"] == "no_above_horizon_direct_beam"
    assert (
        result.iloc[4]["near_object_shading_state"]
        == "below_horizon_positive_direct_inconsistent"
    )
    assert not result.iloc[4]["near_object_shading_resolved"]
    pd.testing.assert_frame_equal(raw, raw_before)


def test_sample_irradiance_conservation_and_weighted_receiver_equivalence() -> None:
    scene = NearObjectBeamScene(
        [_receiver()], [_object("half", center=(-0.5, 0.0, 1.0), width=1.0)],
        samples_per_receiver=256,
    )
    visibility = scene.calculate_visibility(
        apparent_solar_zenith_deg=0.0, solar_azimuth_deg=180.0
    )
    visibility_before = visibility.samples.copy(deep=True)
    spatial = couple_sample_near_object_direct_beam(visibility, {"receiver": 900.0})
    np.testing.assert_allclose(
        spatial["poa_direct_raw_wm2"],
        spatial["poa_direct_near_object_visible_wm2"]
        + spatial["near_object_shading_loss_wm2"],
    )
    weighted = np.sum(
        spatial["sample_weight_fraction"]
        * spatial["poa_direct_near_object_visible_wm2"]
    )
    expected = 900.0 * visibility.receivers.iloc[0]["visible_fraction"]
    np.testing.assert_allclose(weighted, expected)
    pd.testing.assert_frame_equal(visibility.samples, visibility_before)


def test_sample_missing_irradiance_remains_nan() -> None:
    scene = NearObjectBeamScene([_receiver()], [], samples_per_receiver=4)
    visibility = scene.calculate_visibility(
        apparent_solar_zenith_deg=0.0, solar_azimuth_deg=0.0
    )
    spatial = couple_sample_near_object_direct_beam(visibility, {"receiver": np.nan})
    assert spatial["poa_direct_near_object_visible_wm2"].isna().all()
    assert spatial["near_object_shading_loss_wm2"].isna().all()


@pytest.mark.parametrize("offset", [0.0, 1_000.0, 10_000_000.0])
def test_large_coordinate_equivalence(offset: float) -> None:
    receiver = _receiver(mesh=_rectangle(center=(offset, offset, offset)))
    blocker = _object("blocker", center=(offset, offset, offset + 2.0))
    scene = NearObjectBeamScene([receiver], [blocker], samples_per_receiver=32)
    result = scene.calculate_visibility(
        apparent_solar_zenith_deg=0.0, solar_azimuth_deg=180.0
    )
    assert result.receivers.iloc[0]["shaded_fraction"] == 1.0
    assert set(result.samples["blocking_object_id"]) == {"blocker"}
    np.testing.assert_allclose(result.samples["blocking_distance_m"], 2.0, atol=1e-6)


def test_scene_reuses_samples_and_ray_scene_and_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    scene = NearObjectBeamScene([_receiver()], [_object("blocker")], samples_per_receiver=16)
    ray_scene = scene._ray_scene
    points = scene._sample_points
    calls = 0
    real_cast = ray_scene.cast_first

    def counted(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_cast(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ray_scene, "cast_first", counted)
    first = scene.calculate_visibility(apparent_solar_zenith_deg=0.0, solar_azimuth_deg=0.0)
    second = scene.calculate_visibility(apparent_solar_zenith_deg=0.0, solar_azimuth_deg=0.0)
    assert scene._ray_scene is ray_scene and scene._sample_points is points
    assert calls == 2
    pd.testing.assert_frame_equal(first.samples, second.samples)


def test_half_blocker_convergence_sanity() -> None:
    fractions = []
    for count in (16, 64, 256, 1024):
        scene = NearObjectBeamScene(
            [_receiver()],
            [_object("half", center=(-0.5, 0.0, 1.0), width=1.0)],
            samples_per_receiver=count,
        )
        result = scene.calculate_visibility(
            apparent_solar_zenith_deg=0.0, solar_azimuth_deg=180.0
        )
        fractions.append(float(result.receivers.iloc[0]["shaded_fraction"]))
    assert abs(fractions[-1] - 0.5) <= 0.02


def test_rectangle_oracle_same_100_origins_has_zero_mismatches() -> None:
    receiver = RectangularSurface3D(
        "receiver", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), 2.0, 2.0
    )
    blocker = RectangularSurface3D(
        "blocker", (0.55, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), 0.8, 2.4
    )
    reference = calculate_direct_beam_visibility_map(
        [receiver, blocker], ["receiver"],
        solar_zenith_deg=0.0, solar_azimuth_deg=180.0, samples_u=10, samples_v=10,
    )
    scene = NearObjectBeamScene(
        [_receiver()],
        [_object("blocker", center=blocker.center_enu_m, width=0.8, height=2.4)],
        samples_per_receiver=4,
    )
    origins = reference[["sample_east_m", "sample_north_m", "sample_up_m"]].to_numpy()
    directions = np.tile(solar_direction_enu(0.0, 180.0), (100, 1))
    actual = scene._ray_scene.cast_first(origins, directions).hit
    np.testing.assert_array_equal(actual, reference["beam_shaded"].to_numpy())


def test_visibility_result_is_frozen_and_receiver_order_preserved() -> None:
    scene = NearObjectBeamScene([_receiver("b"), _receiver("a")], [], samples_per_receiver=2)
    result = scene.calculate_visibility(
        apparent_solar_zenith_deg=0.0, solar_azimuth_deg=0.0
    )
    assert result.receivers["receiver_id"].tolist() == ["b", "a"]
    with pytest.raises(FrozenInstanceError):
        result.solar_azimuth_deg = 5.0  # type: ignore[misc]
