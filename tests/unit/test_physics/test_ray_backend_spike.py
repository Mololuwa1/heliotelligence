"""Deterministic correctness tests for the S5A benchmark harness."""

from __future__ import annotations

import importlib.util

import numpy as np
import numpy.typing as npt
import pytest
from scripts.benchmark_ray_backends import (
    TrimeshEmbreexBackend,
    benchmark_rays,
    combine_scenes,
    grid_scene,
    rectangle_scene,
    rectangular_oracle_case,
    rectangular_oracle_comparison,
    synthetic_correctness_suite,
    validate_rays,
)

_TRIMESH_EMBREEX_AVAILABLE = (
    importlib.util.find_spec("trimesh") is not None
    and importlib.util.find_spec("embreex") is not None
)


def test_grid_scene_has_deterministic_triangle_layout() -> None:
    scene = grid_scene(2, 3)

    assert scene.vertices.dtype == np.float64
    assert scene.faces.dtype == np.int64
    assert scene.vertices.shape == (12, 3)
    assert scene.faces.shape == (12, 3)
    np.testing.assert_array_equal(scene.faces[0], (0, 4, 5))
    np.testing.assert_array_equal(scene.faces[-1], (6, 11, 7))


def test_benchmark_rays_are_repeatable_and_include_misses() -> None:
    first = benchmark_rays(20, 5, 10)
    second = benchmark_rays(20, 5, 10)

    np.testing.assert_array_equal(first[0], second[0])
    np.testing.assert_array_equal(first[1], second[1])
    assert first[0][0, 0] == -1.0
    assert 0.0 < first[0][1, 0] < 5.0


def test_validate_rays_normalizes_directions() -> None:
    origins, directions = validate_rays(
        np.asarray(((0.0, 0.0, 0.0),)), np.asarray(((0.0, 0.0, 2.0),))
    )

    np.testing.assert_array_equal(origins, ((0.0, 0.0, 0.0),))
    np.testing.assert_array_equal(directions, ((0.0, 0.0, 1.0),))


@pytest.mark.parametrize(
    ("origins", "directions"),
    [
        (np.zeros((1, 2)), np.zeros((1, 2))),
        (np.asarray(((np.nan, 0.0, 0.0),)), np.asarray(((0.0, 0.0, 1.0),))),
        (np.zeros((1, 3)), np.zeros((1, 3))),
        (np.asarray(((True, False, False),)), np.asarray(((0.0, 0.0, 1.0),))),
    ],
)
def test_validate_rays_rejects_invalid_input(
    origins: npt.NDArray[np.generic], directions: npt.NDArray[np.generic]
) -> None:
    with pytest.raises(ValueError):
        validate_rays(origins, directions)


def test_grid_scene_rejects_empty_dimensions() -> None:
    with pytest.raises(ValueError):
        grid_scene(0, 1)


def test_rectangle_and_combined_scene_preserve_object_ownership() -> None:
    lower = rectangle_scene(center_enu_m=(0.0, 0.0, 1.0), object_id=11)
    upper = rectangle_scene(center_enu_m=(0.0, 0.0, 2.0), object_id=22)
    combined = combine_scenes(lower, upper)

    assert combined.vertices.shape == (8, 3)
    np.testing.assert_array_equal(combined.faces[:2], ((0, 1, 2), (0, 2, 3)))
    np.testing.assert_array_equal(combined.faces[2:], ((4, 5, 6), (4, 6, 7)))
    np.testing.assert_array_equal(combined.face_object_ids, (11, 11, 22, 22))


def test_empty_logical_scene_has_stable_shapes() -> None:
    scene = combine_scenes()

    assert scene.vertices.shape == (0, 3)
    assert scene.faces.shape == (0, 3)
    assert scene.face_object_ids.shape == (0,)


def test_rectangular_oracle_case_is_100_deterministic_non_edge_rays() -> None:
    scene, origins, directions, expected = rectangular_oracle_case()

    assert scene.faces.shape == (2, 3)
    assert origins.shape == directions.shape == (100, 3)
    np.testing.assert_array_equal(directions, np.tile((0.0, 0.0, 1.0), (100, 1)))
    assert expected.dtype == np.bool_
    assert int(expected.sum()) == 40
    np.testing.assert_array_equal(np.flatnonzero(expected), np.arange(60, 100))


@pytest.mark.skipif(
    not _TRIMESH_EMBREEX_AVAILABLE,
    reason="selected optional spike packages are not installed in the normal test environment",
)
def test_selected_backend_oracle_and_synthetic_suite() -> None:
    oracle = rectangular_oracle_comparison("trimesh-embreex")
    suite = synthetic_correctness_suite("trimesh-embreex")

    assert oracle == {
        "reference_function": "calculate_direct_beam_visibility_map",
        "comparable_rays": 100,
        "excluded_ambiguous_rays": 0,
        "mismatch_count": 0,
        "mismatch_indices": [],
    }
    assert suite["full_blocker"] is True
    assert suite["partial_blocker"] == [True, False]
    assert suite["rotated_blocker"] is True
    assert suite["multiple_disconnected_object_ids"] == [401, 402]
    assert suite["stacked_first_object_id"] == 101
    assert suite["stacked_repeated_identity"] is True
    assert suite["parallel_hit"] is False
    assert suite["away_hit"] is False
    assert suite["close_hit"] is True
    assert suite["terrain_like_hit"] is True
    assert suite["arbitrary_triangle_hit"] is True
    assert suite["two_sided_backface_hit"] is True
    assert suite["bounded"] == {
        "first_below_t_min_second_valid": True,
        "all_below_t_min": False,
        "nearest_beyond_t_max": False,
        "valid_between_bounds": True,
    }


@pytest.mark.skipif(
    not _TRIMESH_EMBREEX_AVAILABLE,
    reason="selected optional spike packages are not installed in the normal test environment",
)
def test_selected_backend_multi_hit_ownership_is_repeatable() -> None:
    scene = combine_scenes(
        rectangle_scene(center_enu_m=(0.0, 0.0, 0.001), object_id=1),
        rectangle_scene(center_enu_m=(0.0, 0.0, 2.0), object_id=2),
    )
    backend = TrimeshEmbreexBackend(scene)
    origins = np.asarray(((0.25, 0.25, 0.0),))
    directions = np.asarray(((0.0, 0.0, 1.0),))

    first = backend.cast_all(origins, directions)
    second = backend.cast_all(origins, directions)

    np.testing.assert_allclose(first.distance_m, (0.001, 2.0), atol=1e-7)
    np.testing.assert_array_equal(first.object_id, (1, 2))
    np.testing.assert_array_equal(first.primitive_index, second.primitive_index)
    assert backend.cast_any(origins, directions, t_min_m=0.01, t_max_m=3.0)[0]
