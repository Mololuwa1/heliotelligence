"""Production tests for supplied-canonical-terrain horizon visibility."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.geometry import (
    PVReceiver,
    ReceiverKind,
    ShadingObject,
    ShadowRole,
    TerrainSurface,
    TriangleMesh,
)
from heliotelligence.physics.ray_backend import RayFirstHitBatch
from heliotelligence.physics.terrain_horizon import (
    COVERAGE_SCOPE,
    MODEL_ID,
    TerrainHorizonScene,
    calculate_terrain_horizon_direct_beam_shading,
)


def _mesh(
    vertices: tuple[tuple[float, float, float], ...],
    faces: tuple[tuple[int, int, int], ...],
) -> TriangleMesh:
    return TriangleMesh(np.asarray(vertices, dtype=np.float64), np.asarray(faces, dtype=np.int64))


def _empty_mesh() -> TriangleMesh:
    return TriangleMesh(np.empty((0, 3)), np.empty((0, 3), dtype=np.int64))


def _receiver(
    receiver_id: str = "receiver",
    centre: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> PVReceiver:
    x, y, z = centre
    mesh = _mesh(((x, y, z), (x + 1.0, y, z), (x, y + 1.0, z)), ((0, 1, 2),))
    return PVReceiver(receiver_id, mesh, centre, (0.0, 0.0, 1.0), ReceiverKind.FIXED_TABLE)


def _ridge(
    terrain_id: str = "ridge",
    *,
    distance: float = 10.0,
    height: float = 10.0,
    offset: float = 0.0,
    reverse: bool = False,
) -> TerrainSurface:
    vertices = (
        (offset + distance, offset - distance, offset),
        (offset + distance, offset + distance, offset),
        (offset + distance, offset + distance, offset + height),
        (offset + distance, offset - distance, offset + height),
    )
    faces = ((0, 2, 1), (0, 3, 2)) if reverse else ((0, 1, 2), (0, 2, 3))
    return TerrainSurface(terrain_id, _mesh(vertices, faces))


def _visibility(
    scene: TerrainHorizonScene, *, elevation: float = 20.0, azimuth: float = 90.0
) -> pd.Series:
    return scene.calculate_visibility(
        apparent_solar_zenith_deg=90.0 - elevation, solar_azimuth_deg=azimuth
    ).receivers.iloc[0]


def _timeseries(raw: list[float], zenith: list[float]) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    index = pd.date_range("2026-01-01", periods=len(raw), freq="h", tz="UTC", name="time")
    return (
        pd.DataFrame({"receiver": raw}, index=index),
        pd.Series(zenith, index=index),
        pd.Series([90.0] * len(raw), index=index),
    )


def test_scene_contract_validation_and_diagnostics() -> None:
    terrain = _ridge()
    scene = TerrainHorizonScene([_receiver()], [terrain])
    assert scene.receiver_ids == ("receiver",)
    assert scene.diagnostics.receiver_count == 1
    assert scene.diagnostics.terrain_surface_count == 1
    assert scene.diagnostics.nonempty_terrain_surface_count == 1
    assert scene.diagnostics.terrain_triangle_count == 2
    assert scene.diagnostics.coverage_scope == COVERAGE_SCOPE
    with pytest.raises(ValueError, match="receivers"):
        TerrainHorizonScene([object()], [])  # type: ignore[list-item]
    with pytest.raises(ValueError, match="terrain_surfaces"):
        TerrainHorizonScene([], [object()])  # type: ignore[list-item]
    with pytest.raises(ValueError, match="receiver IDs"):
        TerrainHorizonScene([_receiver("same"), _receiver("same")], [])
    with pytest.raises(ValueError, match="terrain surface IDs"):
        TerrainHorizonScene([], [terrain, _ridge()])
    shading = ShadingObject("object", terrain.mesh, ShadowRole.OCCLUDER)
    with pytest.raises(ValueError, match="terrain_surfaces"):
        TerrainHorizonScene([], [shading])  # type: ignore[list-item]


def test_empty_receivers_and_empty_terrain_are_safe_and_typed() -> None:
    empty_receivers = TerrainHorizonScene([], [])
    result = empty_receivers.calculate_visibility(
        apparent_solar_zenith_deg=20.0, solar_azimuth_deg=0.0
    ).receivers
    assert result.empty
    scene = TerrainHorizonScene([_receiver()], [])
    clear = _visibility(scene)
    assert clear["terrain_beam_visible"]
    assert clear["terrain_horizon_beam_visible_factor"] == 1.0
    assert clear["blocking_terrain_id"] is None
    assert np.isinf(clear["blocking_distance_m"])
    all_empty = TerrainHorizonScene([_receiver()], [TerrainSurface("empty", _empty_mesh())])
    assert _visibility(all_empty)["terrain_beam_visible"]


def test_analytic_ridge_threshold_distance_and_azimuth() -> None:
    scene = TerrainHorizonScene([_receiver()], [_ridge()])
    blocked = _visibility(scene, elevation=20.0, azimuth=90.0)
    assert blocked["terrain_beam_blocked"]
    assert blocked["blocking_terrain_id"] == "ridge"
    assert blocked["blocking_distance_m"] == pytest.approx(
        10.0 / np.cos(np.radians(20.0)), rel=1e-7
    )
    assert _visibility(scene, elevation=60.0, azimuth=90.0)["terrain_beam_visible"]
    assert _visibility(scene, elevation=20.0, azimuth=270.0)["terrain_beam_visible"]
    assert _visibility(scene, elevation=20.0, azimuth=0.0)["terrain_beam_visible"]


@pytest.mark.parametrize("distance", [10.0, 1000.0, 10_000.0])
def test_far_terrain_preserves_angular_horizon(distance: float) -> None:
    scene = TerrainHorizonScene([_receiver()], [_ridge(distance=distance, height=distance)])
    assert _visibility(scene, elevation=20.0)["terrain_beam_blocked"]
    assert _visibility(scene, elevation=60.0)["terrain_beam_visible"]


@pytest.mark.parametrize("offset", [0.0, 1000.0, 10_000_000.0])
def test_coordinate_offset_preserves_identity_and_distance(offset: float) -> None:
    scene = TerrainHorizonScene(
        [_receiver(centre=(offset, offset, offset))],
        [_ridge(offset=offset)],
    )
    row = _visibility(scene)
    assert row["terrain_beam_blocked"]
    assert row["blocking_terrain_id"] == "ridge"
    assert row["blocking_distance_m"] == pytest.approx(10.0 / np.cos(np.radians(20.0)), rel=1e-7)


def test_two_sided_single_triangle_and_disconnected_terrain() -> None:
    triangle = _mesh(((10.0, -5.0, 0.0), (10.0, 5.0, 0.0), (10.0, 0.0, 10.0)), ((0, 1, 2),))
    forward = TerrainHorizonScene([_receiver()], [TerrainSurface("one", triangle)])
    reversed_mesh = TriangleMesh(triangle.vertices_enu_m, triangle.faces[:, ::-1])
    reverse = TerrainHorizonScene([_receiver()], [TerrainSurface("one", reversed_mesh)])
    assert _visibility(forward)["terrain_beam_blocked"]
    assert _visibility(reverse)["terrain_beam_blocked"]
    disconnected = _mesh(
        (
            (10.0, -5.0, 0.0),
            (10.0, 5.0, 0.0),
            (10.0, 0.0, 10.0),
            (-10.0, -5.0, 0.0),
            (-10.0, 5.0, 0.0),
            (-10.0, 0.0, 10.0),
        ),
        ((0, 1, 2), (3, 4, 5)),
    )
    scene = TerrainHorizonScene([_receiver()], [TerrainSurface("disconnected", disconnected)])
    assert _visibility(scene, azimuth=90.0)["terrain_beam_blocked"]
    assert _visibility(scene, azimuth=270.0)["terrain_beam_blocked"]


def test_sloped_non_watertight_terrain_blocks_zenith_ray() -> None:
    sloped = _mesh(
        ((-5.0, -5.0, 5.0), (5.0, -5.0, 5.0), (0.0, 5.0, 10.0)),
        ((0, 1, 2),),
    )
    scene = TerrainHorizonScene([_receiver()], [TerrainSurface("slope", sloped)])
    row = scene.calculate_visibility(
        apparent_solar_zenith_deg=0.0, solar_azimuth_deg=0.0
    ).receivers.iloc[0]
    assert row["terrain_beam_blocked"]
    assert row["blocking_terrain_id"] == "slope"


def test_zero_area_terrain_fails_explicitly() -> None:
    zero = _mesh(((1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0)), ((0, 1, 2),))
    with pytest.raises(ValueError, match="zero-area"):
        TerrainHorizonScene([_receiver()], [TerrainSurface("zero", zero)])


def test_multiple_receivers_nearest_terrain_and_order_independence() -> None:
    receivers = [_receiver("low"), _receiver("high", (0.0, 0.0, 20.0))]
    near = _ridge("near", distance=10.0)
    far = _ridge("far", distance=20.0, height=20.0)
    first = (
        TerrainHorizonScene(receivers, [far, near])
        .calculate_visibility(apparent_solar_zenith_deg=70.0, solar_azimuth_deg=90.0)
        .receivers
    )
    second = (
        TerrainHorizonScene(receivers, [near, far])
        .calculate_visibility(apparent_solar_zenith_deg=70.0, solar_azimuth_deg=90.0)
        .receivers
    )
    assert first["receiver_id"].tolist() == ["low", "high"]
    assert first.loc[0, "blocking_terrain_id"] == "near"
    assert first.loc[1, "terrain_beam_visible"]
    pd.testing.assert_series_equal(first["terrain_beam_visible"], second["terrain_beam_visible"])
    pd.testing.assert_series_equal(first["blocking_terrain_id"], second["blocking_terrain_id"])


def test_visibility_angle_validation() -> None:
    scene = TerrainHorizonScene([_receiver()], [])
    for zenith in (90.0, -1.0, np.nan):
        with pytest.raises(ValueError):
            scene.calculate_visibility(apparent_solar_zenith_deg=zenith, solar_azimuth_deg=0.0)
    for azimuth in (360.0, -1.0, np.inf):
        with pytest.raises(ValueError):
            scene.calculate_visibility(apparent_solar_zenith_deg=0.0, solar_azimuth_deg=azimuth)


def test_direct_poa_coupling_conservation_and_states() -> None:
    scene = TerrainHorizonScene([_receiver()], [_ridge()])
    raw, zenith, azimuth = _timeseries(
        [800.0, 0.0, np.nan, 0.0, np.nan, 800.0],
        [70.0, 70.0, 70.0, 90.0, 100.0, 90.0],
    )
    result = calculate_terrain_horizon_direct_beam_shading(raw, zenith, azimuth, scene=scene)
    assert result.iloc[0]["poa_direct_after_terrain_horizon_wm2"] == 0.0
    assert result.iloc[0]["terrain_horizon_shading_loss_wm2"] == 800.0
    assert result.iloc[0]["terrain_horizon_shading_applied"]
    assert result.iloc[1]["poa_direct_after_terrain_horizon_wm2"] == 0.0
    assert np.isnan(result.iloc[2]["poa_direct_after_terrain_horizon_wm2"])
    assert not result.iloc[2]["terrain_horizon_shading_resolved"]
    assert result.iloc[3]["terrain_horizon_state"] == "no_above_horizon_direct_beam"
    assert "unresolved" in result.iloc[4]["terrain_horizon_state"]
    assert result.iloc[5]["terrain_horizon_state"] == "below_horizon_positive_direct_inconsistent"
    assert result.iloc[0]["terrain_horizon_model"] == MODEL_ID
    assert result.iloc[0]["terrain_horizon_coverage_scope"] == COVERAGE_SCOPE


def test_clear_direct_poa_and_input_immutability() -> None:
    receiver = _receiver()
    raw, zenith, azimuth = _timeseries([800.0], [20.0])
    raw_before = raw.copy(deep=True)
    centre_before = receiver.centre_enu_m
    scene = TerrainHorizonScene([receiver], [])
    first = calculate_terrain_horizon_direct_beam_shading(raw, zenith, azimuth, scene=scene)
    second = calculate_terrain_horizon_direct_beam_shading(raw, zenith, azimuth, scene=scene)
    assert first.iloc[0]["poa_direct_after_terrain_horizon_wm2"] == 800.0
    assert first.iloc[0]["terrain_horizon_shading_loss_wm2"] == 0.0
    pd.testing.assert_frame_equal(first, second)
    pd.testing.assert_frame_equal(raw, raw_before)
    assert receiver.centre_enu_m == centre_before


def test_scene_reuses_one_batched_ray_query(monkeypatch: pytest.MonkeyPatch) -> None:
    receivers = [_receiver(f"r{index}", (0.0, float(index), 0.0)) for index in range(5)]
    scene = TerrainHorizonScene(receivers, [_ridge()])
    original = scene._ray_scene.cast_first
    calls: list[int] = []

    def recording_cast(
        origins: npt.NDArray[np.float64],
        directions: npt.NDArray[np.float64],
    ) -> RayFirstHitBatch:
        calls.append(len(origins))
        return original(origins, directions)

    monkeypatch.setattr(scene._ray_scene, "cast_first", recording_cast)
    scene.calculate_visibility(apparent_solar_zenith_deg=70.0, solar_azimuth_deg=90.0)
    scene.calculate_visibility(apparent_solar_zenith_deg=20.0, solar_azimuth_deg=90.0)
    assert calls == [5, 5]


def test_below_horizon_coupling_does_not_cast_rays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = TerrainHorizonScene([_receiver()], [_ridge()])

    def unexpected_cast(*args: object, **kwargs: object) -> None:
        raise AssertionError("below-horizon coupling must not cast terrain rays")

    monkeypatch.setattr(scene, "calculate_visibility", unexpected_cast)
    raw, zenith, azimuth = _timeseries([0.0], [90.0])
    result = calculate_terrain_horizon_direct_beam_shading(raw, zenith, azimuth, scene=scene)
    assert result.iloc[0]["terrain_horizon_state"] == "no_above_horizon_direct_beam"


def test_timeseries_contract_rejects_misalignment_and_invalid_raw() -> None:
    scene = TerrainHorizonScene([_receiver()], [])
    raw, zenith, azimuth = _timeseries([1.0], [20.0])
    with pytest.raises(ValueError, match="columns"):
        calculate_terrain_horizon_direct_beam_shading(
            raw.rename(columns={"receiver": "wrong"}), zenith, azimuth, scene=scene
        )
    bad = raw.copy()
    bad.iloc[0, 0] = -1.0
    with pytest.raises(ValueError, match="non-negative"):
        calculate_terrain_horizon_direct_beam_shading(bad, zenith, azimuth, scene=scene)
