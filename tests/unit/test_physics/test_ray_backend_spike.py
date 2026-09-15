"""Deterministic correctness tests for the S5A benchmark harness."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest
from scripts.benchmark_ray_backends import benchmark_rays, grid_scene, validate_rays


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
