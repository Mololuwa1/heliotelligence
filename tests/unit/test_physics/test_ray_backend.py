"""Production contract tests for the canonical triangle-mesh ray adapter."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from importlib.metadata import version
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

import heliotelligence.physics.ray_backend as ray_backend_module
from heliotelligence.geometry import TriangleMesh
from heliotelligence.physics.ray_backend import (
    MeshRayScene,
    RaySceneObject,
)
from heliotelligence.physics.shading import (
    RectangularSurface3D,
    calculate_direct_beam_visibility_map,
    solar_direction_enu,
)


def _rectangle_mesh(
    *,
    center: tuple[float, float, float] = (0.0, 0.0, 1.0),
    span_u: float = 2.0,
    span_v: float = 2.0,
    u_axis: tuple[float, float, float] = (1.0, 0.0, 0.0),
    v_axis: tuple[float, float, float] = (0.0, 1.0, 0.0),
) -> TriangleMesh:
    centre = np.asarray(center, dtype=np.float64)
    half_u = np.asarray(u_axis, dtype=np.float64) * span_u / 2.0
    half_v = np.asarray(v_axis, dtype=np.float64) * span_v / 2.0
    vertices = np.asarray(
        (
            centre - half_u - half_v,
            centre + half_u - half_v,
            centre + half_u + half_v,
            centre - half_u + half_v,
        ),
        dtype=np.float64,
    )
    return TriangleMesh(vertices, np.asarray(((0, 1, 2), (0, 2, 3)), dtype=np.int64))


def _empty_mesh() -> TriangleMesh:
    return TriangleMesh(
        np.empty((0, 3), dtype=np.float64), np.empty((0, 3), dtype=np.int64)
    )


def _upward_ray(
    *, x: float = 0.25, y: float = 0.1, z: float = 0.0
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    return np.asarray(((x, y, z),), dtype=np.float64), np.asarray(
        ((0.0, 0.0, 1.0),), dtype=np.float64
    )


def test_selected_runtime_versions_and_backend_import() -> None:
    assert version("trimesh") == "5.1.0"
    assert version("embreex") == "4.4.0"
    intersector = ray_backend_module._RayMeshIntersector
    assert intersector.__module__ == "trimesh.ray.ray_pyembree"


def test_scene_object_requires_canonical_mesh_and_nonempty_id() -> None:
    mesh = _rectangle_mesh()
    assert RaySceneObject("a", mesh).mesh is mesh
    for invalid in ("", " "):
        with pytest.raises(ValueError, match="object_id"):
            RaySceneObject(invalid, mesh)
    with pytest.raises(ValueError, match="canonical TriangleMesh"):
        RaySceneObject("a", object())  # type: ignore[arg-type]


def test_scene_rejects_invalid_sequence_and_duplicate_ids() -> None:
    mesh = _rectangle_mesh()
    with pytest.raises(ValueError, match="sequence"):
        MeshRayScene("bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="RaySceneObject"):
        MeshRayScene([object()])  # type: ignore[list-item]
    with pytest.raises(ValueError, match="unique"):
        MeshRayScene([RaySceneObject("same", mesh), RaySceneObject("same", mesh)])


def test_deterministic_concatenation_offsets_and_ownership() -> None:
    one = TriangleMesh(
        np.asarray(((-1.0, -1.0, 1.0), (1.0, -1.0, 1.0), (0.0, 1.0, 1.0))),
        np.asarray(((0, 1, 2),), dtype=np.int64),
    )
    two = _rectangle_mesh(center=(4.0, 0.0, 2.0))
    scene = MeshRayScene([RaySceneObject("triangle", one), RaySceneObject("rectangle", two)])

    assert scene.object_ids == ("triangle", "rectangle")
    assert scene.primitive_count == 3
    origins = np.asarray(((0.0, 0.0, 0.0), (4.25, 0.1, 0.0)))
    directions = np.tile((0.0, 0.0, 1.0), (2, 1))
    result = scene.cast_first(origins, directions)

    assert result.object_id == ("triangle", "rectangle")
    np.testing.assert_array_equal(result.primitive_index, (0, 1))
    np.testing.assert_array_equal(result.local_primitive_index, (0, 0))


def test_empty_scene_and_all_empty_meshes_are_safe() -> None:
    origins = np.asarray(((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)))
    directions = np.tile((0.0, 0.0, 1.0), (2, 1))
    for scene in (
        MeshRayScene([]),
        MeshRayScene([RaySceneObject("empty", _empty_mesh())]),
    ):
        assert scene.scene_translation_enu_m == (0.0, 0.0, 0.0)
        assert scene.primitive_count == 0
        np.testing.assert_array_equal(scene.cast_any(origins, directions), (False, False))
        result = scene.cast_first(origins, directions)
        np.testing.assert_array_equal(result.hit, (False, False))
        np.testing.assert_array_equal(result.distance_m, (np.inf, np.inf))
        np.testing.assert_array_equal(result.primitive_index, (-1, -1))
        np.testing.assert_array_equal(result.local_primitive_index, (-1, -1))
        assert result.object_id == (None, None)


def test_empty_ray_batch_has_stable_results() -> None:
    scene = MeshRayScene([RaySceneObject("plane", _rectangle_mesh())])
    empty = np.empty((0, 3), dtype=np.float64)
    result = scene.cast_first(empty, empty)
    assert result.hit.shape == result.distance_m.shape == (0,)
    assert result.object_id == ()
    assert scene.cast_any(empty, empty).shape == (0,)


def test_basic_batch_hit_miss_and_normalized_distance() -> None:
    scene = MeshRayScene([RaySceneObject("plane", _rectangle_mesh())])
    origins = np.asarray(((0.25, 0.1, 0.0), (3.0, 0.0, 0.0)))
    directions = np.asarray(((0.0, 0.0, 2.0), (0.0, 0.0, 5.0)))
    result = scene.cast_first(origins, directions)

    np.testing.assert_array_equal(result.hit, (True, False))
    np.testing.assert_allclose(result.distance_m, (1.0, np.inf))
    np.testing.assert_array_equal(result.primitive_index, (0, -1))
    assert result.object_id == ("plane", None)


@pytest.mark.parametrize(
    ("origins", "directions", "message"),
    [
        (np.zeros((1, 2)), np.zeros((1, 2)), "origins"),
        (np.zeros((1, 3)), np.zeros((2, 3)), "same"),
        (np.asarray(((True, False, False),)), np.ones((1, 3)), "real numeric"),
        (np.ones((1, 3)), np.asarray(((1 + 1j, 0, 0),)), "real numeric"),
        (np.asarray(((np.nan, 0.0, 0.0),)), np.ones((1, 3)), "finite"),
        (np.zeros((1, 3)), np.asarray(((np.inf, 0.0, 0.0),)), "finite"),
        (np.zeros((1, 3)), np.zeros((1, 3)), "non-zero"),
    ],
)
def test_ray_validation(
    origins: npt.ArrayLike, directions: npt.ArrayLike, message: str
) -> None:
    scene = MeshRayScene([])
    with pytest.raises(ValueError, match=message):
        scene.cast_first(origins, directions)


@pytest.mark.parametrize("name", ["t_min_m", "t_max_m"])
@pytest.mark.parametrize("value", [True, -1.0, np.nan, np.inf, "1"])
def test_bound_validation(name: str, value: object) -> None:
    scene = MeshRayScene([])
    origins, directions = _upward_ray()
    kwargs = {name: value}
    with pytest.raises(ValueError, match=name):
        scene.cast_first(origins, directions, **kwargs)  # type: ignore[arg-type]


def test_bound_order_validation() -> None:
    scene = MeshRayScene([])
    origins, directions = _upward_ray()
    with pytest.raises(ValueError, match="greater than or equal"):
        scene.cast_first(origins, directions, t_min_m=2.0, t_max_m=1.0)


def test_multi_hit_continues_after_below_t_min_and_honours_t_max() -> None:
    scene = MeshRayScene(
        [
            RaySceneObject("near", _rectangle_mesh(center=(0.0, 0.0, 0.001))),
            RaySceneObject("far", _rectangle_mesh(center=(0.0, 0.0, 2.0))),
        ]
    )
    origins, directions = _upward_ray()

    result = scene.cast_first(origins, directions, t_min_m=0.01, t_max_m=3.0)
    assert result.object_id == ("far",)
    np.testing.assert_allclose(result.distance_m, (2.0,))
    assert not scene.cast_any(origins, directions, t_min_m=3.0)[0]
    assert not scene.cast_any(origins, directions, t_max_m=0.0005)[0]
    assert scene.cast_any(origins, directions, t_min_m=1.0, t_max_m=3.0)[0]


def test_front_and_back_faces_are_opaque() -> None:
    scene = MeshRayScene([RaySceneObject("plane", _rectangle_mesh())])
    front_origins, front_directions = _upward_ray()
    back_origins = np.asarray(((0.25, 0.1, 2.0),))
    back_directions = np.asarray(((0.0, 0.0, -1.0),))
    assert scene.cast_any(front_origins, front_directions)[0]
    assert scene.cast_any(back_origins, back_directions)[0]


def test_arbitrary_disconnected_non_watertight_triangles() -> None:
    mesh = TriangleMesh(
        np.asarray(
            (
                (-1.0, -1.0, 1.0),
                (1.0, -1.0, 1.0),
                (0.0, 1.0, 1.0),
                (3.0, -1.0, 2.0),
                (5.0, -1.0, 2.0),
                (4.0, 1.0, 3.0),
            )
        ),
        np.asarray(((0, 1, 2), (3, 4, 5)), dtype=np.int64),
    )
    scene = MeshRayScene([RaySceneObject("open", mesh)])
    origins = np.asarray(((0.0, 0.0, 0.0), (4.0, 0.0, 0.0)))
    directions = np.tile((0.0, 0.0, 1.0), (2, 1))
    result = scene.cast_first(origins, directions)
    np.testing.assert_array_equal(result.hit, (True, True))
    np.testing.assert_array_equal(result.local_primitive_index, (0, 1))


def test_exclusion_continues_to_next_object_and_unknown_is_harmless() -> None:
    scene = MeshRayScene(
        [
            RaySceneObject("source", _rectangle_mesh(center=(0.0, 0.0, 0.0))),
            RaySceneObject("occluder", _rectangle_mesh(center=(0.0, 0.0, 2.0))),
        ]
    )
    origins, directions = _upward_ray()

    zero_allowed = scene.cast_first(origins, directions, t_min_m=0.0)
    default = scene.cast_first(origins, directions)
    excluded = scene.cast_first(origins, directions, excluded_object_ids=("source",))
    unknown = scene.cast_first(origins, directions, excluded_object_ids=("absent",))

    assert zero_allowed.object_id == ("source",)
    np.testing.assert_allclose(zero_allowed.distance_m, (0.0,), atol=1e-12)
    assert default.object_id == ("occluder",)
    assert excluded.object_id == ("occluder",)
    assert unknown.object_id == ("occluder",)
    np.testing.assert_allclose(excluded.distance_m, (2.0,))


@pytest.mark.parametrize(
    "values",
    ["source", (), ("source", "extra"), ("",), (True,)],
)
def test_exclusion_validation(values: object) -> None:
    scene = MeshRayScene([RaySceneObject("source", _rectangle_mesh())])
    origins, directions = _upward_ray()
    with pytest.raises(ValueError, match="excluded_object_ids"):
        scene.cast_first(
            origins,
            directions,
            excluded_object_ids=values,  # type: ignore[arg-type]
        )


def test_first_hit_identity_exclusion_and_repeatability() -> None:
    scene = MeshRayScene(
        [
            RaySceneObject("a", _rectangle_mesh(center=(0.0, 0.0, 1.0))),
            RaySceneObject("b", _rectangle_mesh(center=(0.0, 0.0, 2.0))),
        ]
    )
    origins, directions = _upward_ray()
    first = scene.cast_first(origins, directions)
    repeated = scene.cast_first(origins, directions)
    excluded = scene.cast_first(origins, directions, excluded_object_ids=("a",))

    assert first == repeated
    assert first.object_id == ("a",)
    assert first.primitive_index[0] == 0
    assert first.local_primitive_index[0] == 0
    np.testing.assert_allclose(first.distance_m, (1.0,))
    assert excluded.object_id == ("b",)
    np.testing.assert_allclose(excluded.distance_m, (2.0,))


def test_cast_any_matches_cast_first_hit_with_bounds_and_exclusions() -> None:
    scene = MeshRayScene(
        [
            RaySceneObject("a", _rectangle_mesh(center=(0.0, 0.0, 0.001))),
            RaySceneObject("b", _rectangle_mesh(center=(0.0, 0.0, 2.0))),
        ]
    )
    origins = np.asarray(((0.25, 0.1, 0.0), (4.0, 0.0, 0.0)))
    directions = np.tile((0.0, 0.0, 1.0), (2, 1))
    np.testing.assert_array_equal(
        scene.cast_any(
            origins,
            directions,
            t_min_m=0.01,
            t_max_m=3.0,
            excluded_object_ids=("a", None),
        ),
        scene.cast_first(
            origins,
            directions,
            t_min_m=0.01,
            t_max_m=3.0,
            excluded_object_ids=("a", None),
        ).hit,
    )


def test_canonical_inputs_are_not_mutated() -> None:
    mesh = _rectangle_mesh()
    vertices_before = mesh.vertices_enu_m.copy()
    faces_before = mesh.faces.copy()
    scene_object = RaySceneObject("plane", mesh)
    scene = MeshRayScene([scene_object])
    origins, directions = _upward_ray()
    origins_before = origins.copy()
    directions_before = directions.copy()
    scene.cast_first(origins, directions)

    np.testing.assert_array_equal(mesh.vertices_enu_m, vertices_before)
    np.testing.assert_array_equal(mesh.faces, faces_before)
    assert scene_object.mesh is mesh
    assert not mesh.vertices_enu_m.flags.writeable
    assert not mesh.faces.flags.writeable
    np.testing.assert_array_equal(origins, origins_before)
    np.testing.assert_array_equal(directions, directions_before)


def test_result_is_immutable_and_cannot_mutate_scene() -> None:
    scene = MeshRayScene([RaySceneObject("plane", _rectangle_mesh())])
    origins, directions = _upward_ray()
    result = scene.cast_first(origins, directions)
    with pytest.raises(ValueError):
        result.hit.flags.writeable = True
    with pytest.raises(ValueError):
        result.distance_m[0] = 20.0
    with pytest.raises(FrozenInstanceError):
        result.object_id = (None,)  # type: ignore[misc]
    assert scene.cast_first(origins, directions).object_id == ("plane",)


@pytest.mark.parametrize("offset", [0.0, 1_000.0, 10_000_000.0])
def test_adapter_recentering_preserves_classification_and_distance(offset: float) -> None:
    scene = MeshRayScene(
        [
            RaySceneObject(
                "plane",
                _rectangle_mesh(center=(offset, offset, offset + 2.0)),
            )
        ]
    )
    origins = np.asarray(((offset + 0.25, offset + 0.1, offset),))
    directions = np.asarray(((0.0, 0.0, 1.0),))
    result = scene.cast_first(origins, directions)
    assert result.hit[0]
    np.testing.assert_allclose(result.distance_m, (2.0,), atol=1e-6)
    np.testing.assert_allclose(scene.scene_translation_enu_m, (offset, offset, offset + 2.0))


def test_rectangular_reference_oracle_equivalence() -> None:
    receiver = RectangularSurface3D(
        "receiver", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), 2.0, 2.0
    )
    blocker = RectangularSurface3D(
        "blocker", (0.55, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), 0.8, 2.4
    )
    reference = calculate_direct_beam_visibility_map(
        [receiver, blocker],
        ["receiver"],
        solar_zenith_deg=0.0,
        solar_azimuth_deg=180.0,
        samples_u=10,
        samples_v=10,
    )
    scene = MeshRayScene(
        [
            RaySceneObject(
                "blocker",
                _rectangle_mesh(
                    center=blocker.center_enu_m,
                    span_u=blocker.span_u_m,
                    span_v=blocker.span_v_m,
                ),
            )
        ]
    )
    origins = reference[["sample_east_m", "sample_north_m", "sample_up_m"]].to_numpy()
    direction = np.asarray(solar_direction_enu(0.0, 180.0))
    directions = np.tile(direction, (len(origins), 1))
    actual = scene.cast_any(origins, directions)
    expected = reference["beam_shaded"].to_numpy()
    np.testing.assert_array_equal(actual, expected)
    assert len(actual) == 100


def test_zero_area_triangle_fails_without_rewriting_faces() -> None:
    mesh = TriangleMesh(
        np.asarray(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0))),
        np.asarray(((0, 1, 2),), dtype=np.int64),
    )
    with pytest.raises(ValueError, match="zero-area"):
        MeshRayScene([RaySceneObject("line", mesh)])
    np.testing.assert_array_equal(mesh.faces, ((0, 1, 2),))


def test_acceleration_structure_is_built_once_and_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    real_intersector = ray_backend_module._RayMeshIntersector
    builds = 0

    def counting_intersector(mesh: Any) -> Any:
        nonlocal builds
        builds += 1
        return real_intersector(mesh)

    monkeypatch.setattr(ray_backend_module, "_RayMeshIntersector", counting_intersector)
    scene = MeshRayScene([RaySceneObject("plane", _rectangle_mesh())])
    origins, directions = _upward_ray()
    scene.cast_first(origins, directions)
    scene.cast_any(origins, directions)
    scene.cast_first(origins, directions)
    assert builds == 1
