"""Production tests for geometric diffuse-sky visibility."""

from __future__ import annotations

from collections.abc import Sequence

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
from heliotelligence.physics.diffuse_sky_visibility import (
    COVERAGE_SCOPE,
    GROUND_COVERAGE_SCOPE,
    GROUND_VISIBILITY_MODEL_ID,
    HORIZON_COVERAGE_SCOPE,
    HORIZON_VISIBILITY_MODEL_ID,
    MODEL_ID,
    DiffuseSkyScene,
)


def _mesh(
    vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
) -> TriangleMesh:
    return TriangleMesh(np.asarray(vertices, dtype=float), np.asarray(faces, dtype=np.int64))


def _plane(*, offset: npt.NDArray[np.float64] | None = None, reverse: bool = False) -> TriangleMesh:
    shift = np.zeros(3) if offset is None else offset
    vertices = (
        np.asarray(((-0.2, -0.2, 0.0), (0.2, -0.2, 0.0), (0.2, 0.2, 0.0), (-0.2, 0.2, 0.0))) + shift
    )
    faces = np.asarray(((0, 1, 2), (0, 2, 3)), dtype=np.int64)
    if reverse:
        faces = faces[::-1, ::-1]
    return TriangleMesh(vertices, faces)


def _receiver(
    receiver_id: str = "target",
    *,
    kind: ReceiverKind = ReceiverKind.FIXED_TABLE,
    offset: npt.NDArray[np.float64] | None = None,
    reverse: bool = False,
) -> PVReceiver:
    shift = np.zeros(3) if offset is None else offset
    return PVReceiver(
        receiver_id,
        _plane(offset=shift, reverse=reverse),
        tuple(shift),
        (0.0, 0.0, 1.0),
        kind,
    )


def _east_wall(
    *, offset: npt.NDArray[np.float64] | None = None, reverse: bool = False
) -> TriangleMesh:
    shift = np.zeros(3) if offset is None else offset
    vertices = (
        np.asarray(
            ((0.5, -100.0, -100.0), (0.5, 100.0, -100.0), (0.5, 100.0, 100.0), (0.5, -100.0, 100.0))
        )
        + shift
    )
    faces = np.asarray(((0, 1, 2), (0, 2, 3)), dtype=np.int64)
    if reverse:
        faces = faces[::-1, ::-1]
    return TriangleMesh(vertices, faces)


def _tilted_receiver(receiver_id: str = "tilted") -> PVReceiver:
    centre = np.asarray((0.0, 0.0, 2.0))
    across = np.asarray((0.0, 0.5, 0.0))
    slope = np.asarray((0.5 / np.sqrt(2.0), 0.0, -0.5 / np.sqrt(2.0)))
    vertices = np.asarray(
        (
            centre - across - slope,
            centre + across - slope,
            centre + across + slope,
            centre - across + slope,
        )
    )
    return PVReceiver(
        receiver_id,
        TriangleMesh(vertices, np.asarray(((0, 1, 2), (0, 2, 3)))),
        tuple(centre),
        (1 / np.sqrt(2.0), 0.0, 1 / np.sqrt(2.0)),
        ReceiverKind.FIXED_TABLE,
    )


def _horizontal_plate(z: float, half_size: float = 0.8) -> TriangleMesh:
    return _mesh(
        (
            (-half_size, -half_size, z),
            (half_size, -half_size, z),
            (half_size, half_size, z),
            (-half_size, half_size, z),
        ),
        ((0, 1, 2), (0, 2, 3)),
    )


def _box() -> TriangleMesh:
    vertices = [
        (-10.0, -10.0, -10.0),
        (10.0, -10.0, -10.0),
        (10.0, 10.0, -10.0),
        (-10.0, 10.0, -10.0),
        (-10.0, -10.0, 10.0),
        (10.0, -10.0, 10.0),
        (10.0, 10.0, 10.0),
        (-10.0, 10.0, 10.0),
    ]
    faces = [
        (0, 2, 1),
        (0, 3, 2),
        (4, 5, 6),
        (4, 6, 7),
        (0, 1, 5),
        (0, 5, 4),
        (1, 2, 6),
        (1, 6, 5),
        (2, 3, 7),
        (2, 7, 6),
        (3, 0, 4),
        (3, 4, 7),
    ]
    return _mesh(vertices, faces)


def _scene(
    *,
    receivers: list[PVReceiver] | None = None,
    terrain: list[TerrainSurface] | None = None,
    shading: list[ShadingObject] | None = None,
    receiver_occluders: list[PVReceiver] | None = None,
    directions: int = 512,
    batch: int = 257,
) -> DiffuseSkyScene:
    return DiffuseSkyScene(
        [_receiver()] if receivers is None else receivers,
        [] if terrain is None else terrain,
        [] if shading is None else shading,
        [] if receiver_occluders is None else receiver_occluders,
        samples_per_receiver=4,
        sky_direction_count=directions,
        max_rays_per_batch=batch,
    )


def _fraction(scene: DiffuseSkyScene) -> float:
    return float(scene.calculate_visibility().receivers.iloc[0]["diffuse_sky_visible_fraction"])


def _components(scene: DiffuseSkyScene, *, ground_plane: float = 0.0) -> pd.DataFrame:
    return scene.calculate_component_visibility(
        horizon_zenith_count=3,
        horizon_azimuth_count=72,
        ground_direction_count=512,
        ground_plane_z_m=ground_plane,
    ).receivers


def test_unobstructed_sky_and_typed_schema() -> None:
    result = _scene().calculate_visibility().receivers
    row = result.iloc[0]
    assert row["diffuse_sky_visible_fraction"] == 1.0
    assert row["diffuse_sky_blocked_fraction"] == 0.0
    assert row["diffuse_sky_model"] == MODEL_ID
    assert row["diffuse_sky_coverage_scope"] == COVERAGE_SCOPE
    assert bool(row["diffuse_sky_visibility_resolved"])
    assert str(result["ray_count"].dtype) == "int64"
    assert str(result["diffuse_sky_visible_fraction"].dtype) == "float64"


def test_complete_enclosure_blocks_finite_quadrature() -> None:
    blocker = ShadingObject("box", _box(), ShadowRole.OCCLUDER)
    assert _fraction(_scene(shading=[blocker])) == pytest.approx(0.0, abs=1e-14)


def test_partial_wall_is_symmetric_half_sky() -> None:
    blocker = ShadingObject("wall", _east_wall(), ShadowRole.OCCLUDER)
    fraction = _fraction(_scene(shading=[blocker], directions=4096, batch=701))
    assert fraction == pytest.approx(0.5, abs=0.015)


def _brute_wall_fraction(zenith_count: int = 240, azimuth_count: int = 720) -> float:
    """Independent dense angular-grid oracle for an effectively infinite east wall."""
    elevation = (np.arange(zenith_count) + 0.5) * (np.pi / 2) / zenith_count
    azimuth = (np.arange(azimuth_count) + 0.5) * 2 * np.pi / azimuth_count
    el, az = np.meshgrid(elevation, azimuth, indexing="ij")
    directions = np.stack((np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)), axis=-1)
    weights = directions[..., 2] * np.cos(el)
    visible = directions[..., 0] <= 0.0
    return float(np.sum(weights[visible]) / np.sum(weights))


def test_partial_wall_agrees_with_independent_dense_angular_oracle() -> None:
    blocker = ShadingObject("wall", _east_wall(), ShadowRole.OCCLUDER)
    production = _fraction(_scene(shading=[blocker], directions=4096, batch=333))
    assert production == pytest.approx(_brute_wall_fraction(), abs=0.015)


def test_shadow_roles_and_diagnostics() -> None:
    objects = [
        ShadingObject("yes", _east_wall(), ShadowRole.OCCLUDER),
        ShadingObject("no", _east_wall(), ShadowRole.NON_OCCLUDER),
        ShadingObject("unknown", _east_wall(), ShadowRole.UNKNOWN),
    ]
    scene = _scene(shading=objects)
    assert _fraction(scene) < 0.75
    assert scene.diagnostics.eligible_shading_object_count == 1
    assert scene.diagnostics.ignored_non_occluder_count == 1
    assert scene.diagnostics.ignored_unknown_count == 1
    assert _fraction(_scene(shading=objects[1:])) == 1.0


def test_explicit_terrain_blocks_without_s6a_coupling() -> None:
    scene = _scene(terrain=[TerrainSurface("terrain", _east_wall())])
    assert 0.25 < _fraction(scene) < 0.75
    assert scene.diagnostics.terrain_surface_count == 1
    assert scene.diagnostics.terrain_triangle_count == 2


def test_receiver_blocking_is_explicit_and_self_excluded() -> None:
    target = _receiver("target")
    blocker = PVReceiver(
        "blocker", _east_wall(), (0.5, 0.0, 0.0), (1.0, 0.0, 0.0), ReceiverKind.FIXED_TABLE
    )
    assert _fraction(_scene(receivers=[target, blocker])) == 1.0
    assert _fraction(_scene(receivers=[target], receiver_occluders=[blocker])) < 0.75
    reconstructed_target = _receiver("target")
    assert reconstructed_target == target
    assert reconstructed_target is not target
    assert _fraction(_scene(receivers=[target], receiver_occluders=[reconstructed_target])) == 1.0


def test_conflicting_receiver_occluder_identity_is_rejected() -> None:
    target = _receiver("shared")
    conflicting = PVReceiver(
        "shared",
        _east_wall(),
        (0.5, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        ReceiverKind.FIXED_TABLE,
    )
    with pytest.raises(ValueError, match="must match the same canonical PVReceiver"):
        _scene(receivers=[target], receiver_occluders=[conflicting])


@pytest.mark.parametrize(
    "kind", [ReceiverKind.TRACKER_TABLE, ReceiverKind.MODULE, ReceiverKind.UNKNOWN]
)
def test_unsupported_target_kinds_are_rejected(kind: ReceiverKind) -> None:
    with pytest.raises(ValueError, match="FIXED_TABLE|runtime tracker pose"):
        _scene(receivers=[_receiver(kind=kind)])


def test_tracker_receiver_occluder_is_rejected() -> None:
    with pytest.raises(ValueError, match="runtime tracker pose"):
        _scene(receiver_occluders=[_receiver("tracker", kind=ReceiverKind.TRACKER_TABLE)])


def test_repeated_calls_input_order_and_batch_size_are_invariant() -> None:
    terrain = TerrainSurface("terrain", _east_wall())
    distant_a = ShadingObject(
        "distant-a", _east_wall(offset=np.asarray((2.0, 0.0, 0.0))), ShadowRole.OCCLUDER
    )
    distant_b = ShadingObject(
        "distant-b", _east_wall(offset=np.asarray((4.0, 0.0, 0.0))), ShadowRole.OCCLUDER
    )
    first_scene = _scene(terrain=[terrain], shading=[distant_a, distant_b], batch=17)
    second_scene = _scene(terrain=[terrain], shading=[distant_b, distant_a], batch=10_000)
    first = first_scene.calculate_visibility().receivers
    pd.testing.assert_frame_equal(first, first_scene.calculate_visibility().receivers)
    pd.testing.assert_frame_equal(first, second_scene.calculate_visibility().receivers)


@pytest.mark.parametrize("translation", [1_000.0, 10_000_000.0])
def test_large_coordinate_translation_preserves_visibility(translation: float) -> None:
    shift = np.asarray((translation, translation, translation))
    origin = _fraction(_scene(shading=[ShadingObject("wall", _east_wall(), ShadowRole.OCCLUDER)]))
    moved = _fraction(
        _scene(
            receivers=[_receiver(offset=shift)],
            shading=[ShadingObject("wall", _east_wall(offset=shift), ShadowRole.OCCLUDER)],
        )
    )
    assert moved == pytest.approx(origin, abs=1e-12)


def test_triangle_representation_invariance() -> None:
    normal = _fraction(
        _scene(
            receivers=[_receiver(reverse=False)],
            shading=[ShadingObject("wall", _east_wall(), ShadowRole.OCCLUDER)],
        )
    )
    reversed_mesh = _fraction(
        _scene(
            receivers=[_receiver(reverse=True)],
            shading=[ShadingObject("wall", _east_wall(reverse=True), ShadowRole.OCCLUDER)],
        )
    )
    assert reversed_mesh == pytest.approx(normal, abs=1e-15)

    wall = _east_wall()
    permutation = np.asarray((2, 0, 3, 1), dtype=np.int64)
    inverse = np.empty_like(permutation)
    inverse[permutation] = np.arange(len(permutation))
    renumbered = TriangleMesh(wall.vertices_enu_m[permutation], inverse[wall.faces])
    renumbered_result = _fraction(
        _scene(shading=[ShadingObject("wall", renumbered, ShadowRole.OCCLUDER)])
    )
    assert renumbered_result == pytest.approx(normal, abs=1e-15)


def test_empty_receivers_return_stable_typed_output() -> None:
    result = _scene(receivers=[]).calculate_visibility().receivers
    assert result.empty
    assert list(result.columns)[0] == "receiver_id"
    assert str(result["diffuse_sky_visible_fraction"].dtype) == "float64"


@pytest.mark.parametrize(
    "name,value",
    [("samples_per_receiver", 0), ("sky_direction_count", True), ("max_rays_per_batch", -1)],
)
def test_invalid_controls_are_rejected(name: str, value: object) -> None:
    kwargs: dict[str, object] = {
        "samples_per_receiver": 4,
        "sky_direction_count": 16,
        "max_rays_per_batch": 32,
    }
    kwargs[name] = value
    with pytest.raises(ValueError, match="positive integer"):
        DiffuseSkyScene([_receiver()], **kwargs)  # type: ignore[arg-type]


def test_invalid_types_and_duplicate_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="PVReceiver"):
        DiffuseSkyScene(
            [object()],  # type: ignore[list-item]
            samples_per_receiver=1,
            sky_direction_count=1,
            max_rays_per_batch=1,
        )
    with pytest.raises(ValueError, match="unique"):
        _scene(receivers=[_receiver("same"), _receiver("same")])
    duplicate = ShadingObject("same", _east_wall(), ShadowRole.OCCLUDER)
    with pytest.raises(ValueError, match="unique"):
        _scene(shading=[duplicate, duplicate])
    with pytest.raises(ValueError, match="unique"):
        _scene(
            terrain=[TerrainSurface("collision", _east_wall())],
            shading=[ShadingObject("collision", _east_wall(), ShadowRole.OCCLUDER)],
        )


def test_no_upper_sky_front_exposure_fails_explicitly() -> None:
    downward = PVReceiver(
        "down", _plane(), (0.0, 0.0, 0.0), (0.0, 0.0, -1.0), ReceiverKind.FIXED_TABLE
    )
    with pytest.raises(ValueError, match="no front-side upper-sky exposure"):
        _scene(receivers=[downward]).calculate_visibility()


def test_component_visibility_preserves_existing_sky_exactly() -> None:
    blocker = ShadingObject("wall", _east_wall(), ShadowRole.OCCLUDER)
    scene = _scene(receivers=[_tilted_receiver()], shading=[blocker], directions=1024, batch=37)
    sky = scene.calculate_visibility().receivers.iloc[0]
    component = _components(scene).iloc[0]
    for column in (
        "diffuse_sky_visible_fraction",
        "diffuse_sky_blocked_fraction",
        "visible_weight",
        "blocked_weight",
        "unobstructed_weight",
    ):
        assert component[column] == sky[column]
    assert component["diffuse_sky_model"] == MODEL_ID
    assert component["diffuse_sky_coverage_scope"] == COVERAGE_SCOPE


def test_clear_component_scene_resolves_all_exposures() -> None:
    row = _components(_scene(receivers=[_tilted_receiver()])).iloc[0]
    for component in ("sky", "horizon", "ground"):
        assert row[f"diffuse_{component}_visible_fraction"] == pytest.approx(1.0)
        assert row[f"diffuse_{component}_blocked_fraction"] == pytest.approx(0.0)
        assert bool(row[f"diffuse_{component}_visibility_resolved"])
    assert row["diffuse_horizon_model"] == HORIZON_VISIBILITY_MODEL_ID
    assert row["diffuse_horizon_coverage_scope"] == HORIZON_COVERAGE_SCOPE
    assert row["diffuse_ground_model"] == GROUND_VISIBILITY_MODEL_ID
    assert row["diffuse_ground_coverage_scope"] == GROUND_COVERAGE_SCOPE


def test_horizon_terrain_blocks_but_never_enters_ground_scene() -> None:
    receiver = _tilted_receiver()
    clear = _components(_scene(receivers=[receiver])).iloc[0]
    terrain_scene = _scene(receivers=[receiver], terrain=[TerrainSurface("ridge", _east_wall())])
    first = _components(terrain_scene).iloc[0]
    second = _components(terrain_scene).iloc[0]
    assert first["diffuse_horizon_visible_fraction"] < 1.0
    assert first["diffuse_horizon_visible_fraction"] == second["diffuse_horizon_visible_fraction"]
    assert first["diffuse_ground_visible_fraction"] == clear["diffuse_ground_visible_fraction"]


def test_ground_occluder_blocks_only_before_explicit_ground_intersection() -> None:
    receiver = _tilted_receiver()
    clear = _components(_scene(receivers=[receiver])).iloc[0]
    between = ShadingObject("between", _horizontal_plate(1.0, 2.0), ShadowRole.OCCLUDER)
    blocked = _components(_scene(receivers=[receiver], shading=[between])).iloc[0]
    assert 0.0 < blocked["diffuse_ground_visible_fraction"] < 1.0
    assert blocked["diffuse_ground_visible_fraction"] < clear["diffuse_ground_visible_fraction"]

    behind = ShadingObject("behind", _horizontal_plate(-1.0, 100.0), ShadowRole.OCCLUDER)
    behind_result = _components(_scene(receivers=[receiver], shading=[behind])).iloc[0]
    assert behind_result["diffuse_ground_visible_fraction"] == pytest.approx(1.0)


def test_component_shadow_roles_and_explicit_receiver_policy() -> None:
    receiver = _tilted_receiver()
    wall = _east_wall()
    eligible = _components(
        _scene(
            receivers=[receiver],
            shading=[ShadingObject("yes", wall, ShadowRole.OCCLUDER)],
        )
    ).iloc[0]
    ignored = _components(
        _scene(
            receivers=[receiver],
            shading=[
                ShadingObject("no", wall, ShadowRole.NON_OCCLUDER),
                ShadingObject("unknown", wall, ShadowRole.UNKNOWN),
            ],
        )
    ).iloc[0]
    assert eligible["diffuse_horizon_visible_fraction"] < 1.0
    assert ignored["diffuse_horizon_visible_fraction"] == pytest.approx(1.0)

    blocker = PVReceiver(
        "blocker", wall, (0.5, 0.0, 2.0), (1.0, 0.0, 0.0), ReceiverKind.FIXED_TABLE
    )
    automatic = _components(_scene(receivers=[receiver, blocker]), ground_plane=-200.0).set_index(
        "receiver_id"
    )
    explicit = _components(
        _scene(receivers=[receiver], receiver_occluders=[blocker]), ground_plane=-200.0
    ).iloc[0]
    assert automatic.loc[receiver.id, "diffuse_horizon_visible_fraction"] == pytest.approx(1.0)
    assert explicit["diffuse_horizon_visible_fraction"] < 1.0


def test_component_self_exclusion_and_identity_validation() -> None:
    receiver = _tilted_receiver("same")
    self_result = _components(
        _scene(receivers=[receiver], receiver_occluders=[_tilted_receiver("same")])
    ).iloc[0]
    assert self_result["diffuse_horizon_visible_fraction"] == pytest.approx(1.0)
    assert self_result["diffuse_ground_visible_fraction"] == pytest.approx(1.0)
    conflicting = PVReceiver(
        "same", _east_wall(), (0.5, 0.0, 2.0), (1.0, 0.0, 0.0), ReceiverKind.FIXED_TABLE
    )
    with pytest.raises(ValueError, match="same canonical PVReceiver"):
        _scene(receivers=[receiver], receiver_occluders=[conflicting])


@pytest.mark.parametrize("value", [np.nan, np.inf, True, "0"])
def test_component_ground_plane_validation(value: object) -> None:
    with pytest.raises(ValueError, match="ground_plane_z_m"):
        _scene(receivers=[_tilted_receiver()]).calculate_component_visibility(
            horizon_zenith_count=1,
            horizon_azimuth_count=4,
            ground_direction_count=4,
            ground_plane_z_m=value,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("horizon_zenith_count", 0),
        ("horizon_azimuth_count", True),
        ("ground_direction_count", -1),
    ],
)
def test_component_direction_controls_are_positive_integers(name: str, value: object) -> None:
    controls: dict[str, object] = {
        "horizon_zenith_count": 2,
        "horizon_azimuth_count": 8,
        "ground_direction_count": 16,
        "ground_plane_z_m": 0.0,
    }
    controls[name] = value
    with pytest.raises(ValueError, match="positive integer"):
        _scene(receivers=[_tilted_receiver()]).calculate_component_visibility(
            **controls  # type: ignore[arg-type]
        )


def test_component_rejects_surface_at_or_below_ground_plane() -> None:
    with pytest.raises(ValueError, match="strictly above"):
        _components(_scene(receivers=[_tilted_receiver()]), ground_plane=2.0)


def test_horizontal_receiver_has_no_front_side_ground_view() -> None:
    row = _components(_scene(receivers=[_receiver(offset=np.asarray((0.0, 0.0, 1.0)))])).iloc[0]
    assert np.isnan(row["diffuse_ground_visible_fraction"])
    assert np.isnan(row["diffuse_ground_blocked_fraction"])
    assert not bool(row["diffuse_ground_visibility_resolved"])
    assert row["diffuse_ground_state"] == "not_applicable_no_front_side_ground_view"


def test_component_order_batch_and_face_representation_are_invariant() -> None:
    receiver_a = _tilted_receiver("a")
    receiver_b = _tilted_receiver("b")
    terrain_a = TerrainSurface("a-terrain", _east_wall())
    terrain_b = TerrainSurface(
        "b-terrain", _east_wall(offset=np.asarray((2.0, 0.0, 0.0)), reverse=True)
    )
    shading_a = ShadingObject("a-shade", _horizontal_plate(1.0, 0.3), ShadowRole.OCCLUDER)
    shading_b = ShadingObject("b-shade", _horizontal_plate(0.8, 0.2), ShadowRole.OCCLUDER)
    first = _components(
        _scene(
            receivers=[receiver_b, receiver_a],
            terrain=[terrain_b, terrain_a],
            shading=[shading_b, shading_a],
            batch=11,
        )
    )
    second = _components(
        _scene(
            receivers=[receiver_a, receiver_b],
            terrain=[terrain_a, terrain_b],
            shading=[shading_a, shading_b],
            batch=100_000,
        )
    )
    pd.testing.assert_frame_equal(first, second)
    assert first["receiver_id"].tolist() == ["a", "b"]


def test_component_empty_receivers_and_factor_closure() -> None:
    empty = _components(_scene(receivers=[]))
    assert empty.empty
    assert str(empty["diffuse_ground_visible_fraction"].dtype) == "float64"

    row = _components(
        _scene(
            receivers=[_tilted_receiver()],
            shading=[ShadingObject("plate", _horizontal_plate(1.0, 0.4), ShadowRole.OCCLUDER)],
        )
    ).iloc[0]
    for component in ("horizon", "ground"):
        assert row[f"diffuse_{component}_visible_fraction"] + row[
            f"diffuse_{component}_blocked_fraction"
        ] == pytest.approx(1.0, abs=1e-12)
        assert row[f"diffuse_{component}_visible_weight"] + row[
            f"diffuse_{component}_blocked_weight"
        ] == pytest.approx(row[f"diffuse_{component}_unobstructed_weight"], abs=1e-12)
