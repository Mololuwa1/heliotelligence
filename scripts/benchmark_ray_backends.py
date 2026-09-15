"""Reproducible S5A comparison of optional triangle-ray backends.

This is an engineering spike, not a production shading adapter.  Install either
``trimesh`` with ``embreex`` or ``open3d`` in an isolated environment, then run
this file.  Candidate imports are deliberately lazy so the repository acquires
no runtime dependency from the spike.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
BoolArray = npt.NDArray[np.bool_]


@dataclass(frozen=True)
class MeshScene:
    """Concatenated triangles with deterministic object ownership."""

    vertices: FloatArray
    faces: IntArray
    face_object_ids: IntArray


@dataclass(frozen=True)
class FirstHits:
    """Backend-neutral first-hit facts used by the spike."""

    hit: BoolArray
    distance_m: FloatArray
    primitive_index: IntArray
    object_id: IntArray


@dataclass(frozen=True)
class AllHits:
    """All intersections, ordered by ray then increasing distance."""

    ray_index: IntArray
    distance_m: FloatArray
    primitive_index: IntArray
    object_id: IntArray


class RayBackend(Protocol):
    """Minimum candidate behavior exercised by this spike."""

    def cast_first(self, origins: FloatArray, directions: FloatArray) -> FirstHits: ...

    def cast_all(self, origins: FloatArray, directions: FloatArray) -> AllHits: ...

    def cast_any(
        self,
        origins: FloatArray,
        directions: FloatArray,
        *,
        t_min_m: float = 0.0,
        t_max_m: float | None = None,
    ) -> BoolArray: ...


def validate_rays(
    origins: npt.ArrayLike, directions: npt.ArrayLike
) -> tuple[FloatArray, FloatArray]:
    """Return validated contiguous float64 ray arrays."""
    origins = np.asarray(origins)
    directions = np.asarray(directions)
    if origins.dtype.kind == "b" or directions.dtype.kind == "b":
        raise ValueError("rays must be real numeric arrays")
    try:
        origins = np.ascontiguousarray(origins, dtype=np.float64)
        directions = np.ascontiguousarray(directions, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError("rays must be real numeric arrays") from exc
    if origins.ndim != 2 or origins.shape[1:] != (3,) or directions.shape != origins.shape:
        raise ValueError("origins and directions must both have shape (N, 3)")
    if not np.isfinite(origins).all() or not np.isfinite(directions).all():
        raise ValueError("rays must be finite")
    lengths = np.linalg.norm(directions, axis=1)
    if np.any(lengths == 0.0):
        raise ValueError("ray directions must be non-zero")
    return origins, directions / lengths[:, None]


def grid_scene(nx: int, ny: int, *, z_m: float = 1.0, origin_m: float = 0.0) -> MeshScene:
    """Make a regular two-triangle-per-cell plane for repeatable benchmarks."""
    if nx < 1 or ny < 1:
        raise ValueError("grid dimensions must be positive")
    xx, yy = np.meshgrid(np.arange(nx + 1), np.arange(ny + 1), indexing="ij")
    vertices = np.column_stack(
        (xx.ravel() + origin_m, yy.ravel() + origin_m, np.full(xx.size, z_m))
    ).astype(np.float64)
    faces: list[tuple[int, int, int]] = []
    stride = ny + 1
    for i in range(nx):
        for j in range(ny):
            lower = i * stride + j
            faces.extend(((lower, lower + stride, lower + stride + 1),
                          (lower, lower + stride + 1, lower + 1)))
    face_array = np.asarray(faces, dtype=np.int64)
    return MeshScene(vertices, face_array, np.zeros(len(face_array), dtype=np.int64))


def rectangle_scene(
    *,
    center_enu_m: tuple[float, float, float],
    u_axis_enu: tuple[float, float, float] = (1.0, 0.0, 0.0),
    v_axis_enu: tuple[float, float, float] = (0.0, 1.0, 0.0),
    span_u_m: float = 2.0,
    span_v_m: float = 2.0,
    object_id: int = 0,
) -> MeshScene:
    """Represent a deterministic rectangle as two triangles."""
    center = np.asarray(center_enu_m, dtype=np.float64)
    half_u = np.asarray(u_axis_enu, dtype=np.float64) * span_u_m / 2.0
    half_v = np.asarray(v_axis_enu, dtype=np.float64) * span_v_m / 2.0
    vertices = np.asarray(
        (center - half_u - half_v, center + half_u - half_v,
         center + half_u + half_v, center - half_u + half_v),
        dtype=np.float64,
    )
    return MeshScene(
        vertices,
        np.asarray(((0, 1, 2), (0, 2, 3)), dtype=np.int64),
        np.full(2, object_id, dtype=np.int64),
    )


def combine_scenes(*scenes: MeshScene) -> MeshScene:
    """Concatenate logical objects while retaining deterministic face ownership."""
    if not scenes:
        return MeshScene(
            np.empty((0, 3), dtype=np.float64),
            np.empty((0, 3), dtype=np.int64),
            np.empty(0, dtype=np.int64),
        )
    vertices: list[FloatArray] = []
    faces: list[IntArray] = []
    objects: list[IntArray] = []
    offset = 0
    for scene in scenes:
        vertices.append(scene.vertices)
        faces.append(scene.faces + offset)
        objects.append(scene.face_object_ids)
        offset += len(scene.vertices)
    return MeshScene(np.vstack(vertices), np.vstack(faces), np.concatenate(objects))


def benchmark_rays(
    count: int, nx: int, ny: int, *, origin_m: float = 0.0
) -> tuple[FloatArray, FloatArray]:
    """Return seeded, non-edge upward rays, including deterministic misses."""
    rng = np.random.default_rng(20260914)
    xy = rng.uniform((0.137, 0.173), (nx - 0.137, ny - 0.173), size=(count, 2))
    xy += origin_m
    origins = np.column_stack((xy, np.zeros(count)))
    directions = np.tile((0.0, 0.0, 1.0), (count, 1))
    origins[::10, 0] = origin_m - 1.0
    return origins, directions


class TrimeshEmbreexBackend:
    """Spike-only wrapper around Trimesh's embreex intersector."""

    def __init__(self, scene: MeshScene) -> None:
        import trimesh  # type: ignore[import-not-found]
        from trimesh.ray.ray_pyembree import (  # type: ignore[import-not-found]
            RayMeshIntersector,
        )

        mesh = trimesh.Trimesh(vertices=scene.vertices, faces=scene.faces, process=False)
        self._intersector = RayMeshIntersector(mesh)
        self._objects = scene.face_object_ids

    def cast_first(self, origins: FloatArray, directions: FloatArray) -> FirstHits:
        origins, directions = validate_rays(origins, directions)
        primitive = np.asarray(
            self._intersector.intersects_first(origins, directions), dtype=np.int64
        )
        hit = primitive >= 0
        distance = np.full(len(origins), np.inf, dtype=np.float64)
        if hit.any():
            triangles = self._intersector.mesh.triangles[primitive[hit]]
            normal = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
            numerator = np.einsum("ij,ij->i", triangles[:, 0] - origins[hit], normal)
            denominator = np.einsum("ij,ij->i", directions[hit], normal)
            distance[hit] = numerator / denominator
        objects = np.full(len(origins), -1, dtype=np.int64)
        objects[hit] = self._objects[primitive[hit]]
        return FirstHits(hit, distance, primitive, objects)

    def cast_all(self, origins: FloatArray, directions: FloatArray) -> AllHits:
        origins, directions = validate_rays(origins, directions)
        primitive, ray, locations = self._intersector.intersects_id(
            origins, directions, return_locations=True, multiple_hits=True
        )
        primitive = np.asarray(primitive, dtype=np.int64)
        ray = np.asarray(ray, dtype=np.int64)
        locations = np.asarray(locations, dtype=np.float64)
        distance = np.linalg.norm(locations - origins[ray], axis=1)
        order = np.lexsort((primitive, distance, ray))
        primitive = primitive[order]
        ray = ray[order]
        distance = distance[order]
        return AllHits(ray, distance, primitive, self._objects[primitive])

    def cast_any(
        self,
        origins: FloatArray,
        directions: FloatArray,
        *,
        t_min_m: float = 0.0,
        t_max_m: float | None = None,
    ) -> BoolArray:
        origins, directions = validate_rays(origins, directions)
        hits = self.cast_all(origins, directions)
        upper = np.inf if t_max_m is None else t_max_m
        valid = (hits.distance_m >= t_min_m) & (hits.distance_m <= upper)
        result = np.zeros(len(origins), dtype=np.bool_)
        result[hits.ray_index[valid]] = True
        return result


class Open3DBackend:
    """Spike-only wrapper around Open3D RaycastingScene on CPU."""

    def __init__(self, scene: MeshScene) -> None:
        import open3d as o3d  # type: ignore[import-not-found]

        self._o3d = o3d
        self._scene = o3d.t.geometry.RaycastingScene()
        vertices = o3d.core.Tensor(scene.vertices.astype(np.float32))
        faces = o3d.core.Tensor(scene.faces.astype(np.uint32))
        self._geometry_id = int(self._scene.add_triangles(vertices, faces))
        self._objects = scene.face_object_ids

    def _rays(self, origins: FloatArray, directions: FloatArray) -> Any:
        origins, directions = validate_rays(origins, directions)
        return self._o3d.core.Tensor(np.column_stack((origins, directions)).astype(np.float32))

    def cast_first(self, origins: FloatArray, directions: FloatArray) -> FirstHits:
        rays = self._rays(origins, directions)
        answer = self._scene.cast_rays(rays)
        distance = answer["t_hit"].numpy().astype(np.float64)
        primitive_raw = answer["primitive_ids"].numpy()
        hit = np.isfinite(distance)
        primitive = np.full(len(distance), -1, dtype=np.int64)
        primitive[hit] = primitive_raw[hit].astype(np.int64)
        objects = np.full(len(distance), -1, dtype=np.int64)
        objects[hit] = self._objects[primitive[hit]]
        return FirstHits(hit, distance, primitive, objects)

    def cast_all(self, origins: FloatArray, directions: FloatArray) -> AllHits:
        rays = self._rays(origins, directions)
        answer = self._scene.list_intersections(rays)
        ray = answer["ray_ids"].numpy().astype(np.int64)
        distance = answer["t_hit"].numpy().astype(np.float64)
        primitive = answer["primitive_ids"].numpy().astype(np.int64)
        order = np.lexsort((primitive, distance, ray))
        ray = ray[order]
        distance = distance[order]
        primitive = primitive[order]
        return AllHits(ray, distance, primitive, self._objects[primitive])

    def cast_any(
        self,
        origins: FloatArray,
        directions: FloatArray,
        *,
        t_min_m: float = 0.0,
        t_max_m: float | None = None,
    ) -> BoolArray:
        rays = self._rays(origins, directions)
        upper = np.inf if t_max_m is None else t_max_m
        return np.asarray(
            self._scene.test_occlusions(rays, tnear=t_min_m, tfar=upper).numpy(),
            dtype=np.bool_,
        )


def make_backend(name: str, scene: MeshScene) -> RayBackend:
    """Build one candidate by name."""
    if name == "trimesh-embreex":
        return TrimeshEmbreexBackend(scene)
    if name == "open3d":
        return Open3DBackend(scene)
    raise ValueError(f"unknown backend: {name}")


def correctness_cases(backend: RayBackend) -> dict[str, object]:
    """Exercise independently calculable, non-edge ray cases."""
    origins = np.asarray(
        ((0.25, 0.25, 0.0), (0.75, 0.25, 0.0), (6.0, 11.0, 0.0), (0.25, 0.25, 2.0)),
        dtype=np.float64,
    )
    directions = np.asarray(((0, 0, 1), (0, 0, 1), (0, 0, 1), (0, 0, 1)), dtype=np.float64)
    first = backend.cast_first(origins, directions)
    expected = np.asarray((True, True, False, False))
    return {
        "expected_hit": expected.tolist(),
        "actual_hit": first.hit.tolist(),
        "classification_match": bool(np.array_equal(first.hit, expected)),
        "hit_distances_m": first.distance_m.tolist(),
        "primitive_indices": first.primitive_index.tolist(),
        "object_ids": first.object_id.tolist(),
        "bounded_0_5m": backend.cast_any(origins, directions, t_max_m=0.5).tolist(),
    }


def rectangular_oracle_case() -> tuple[MeshScene, FloatArray, FloatArray, BoolArray]:
    """Construct the 100-ray reference-oracle inputs independently of a candidate."""
    from heliotelligence.physics.shading import (  # type: ignore[import-untyped]
        RectangularSurface3D,
        calculate_direct_beam_visibility_map,
        solar_direction_enu,
    )

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
    scene = rectangle_scene(
        center_enu_m=blocker.center_enu_m,
        span_u_m=blocker.span_u_m,
        span_v_m=blocker.span_v_m,
        object_id=20,
    )
    origins = reference[["sample_east_m", "sample_north_m", "sample_up_m"]].to_numpy()
    direction = np.asarray(solar_direction_enu(0.0, 180.0), dtype=np.float64)
    directions = np.tile(direction, (len(origins), 1))
    expected = reference["beam_shaded"].to_numpy(dtype=np.bool_)
    return scene, origins, directions, expected


def rectangular_oracle_comparison(name: str) -> dict[str, object]:
    """Compare a 10x10 partial-blocker scene with the production reference oracle."""
    scene, origins, directions, expected = rectangular_oracle_case()
    actual = make_backend(name, scene).cast_any(origins, directions, t_min_m=1e-9)
    mismatches = np.flatnonzero(actual != expected)
    return {
        "reference_function": "calculate_direct_beam_visibility_map",
        "comparable_rays": int(len(origins)),
        "excluded_ambiguous_rays": 0,
        "mismatch_count": int(len(mismatches)),
        "mismatch_indices": mismatches.tolist(),
    }


def synthetic_correctness_suite(name: str) -> dict[str, object]:
    """Run the material S5A synthetic correctness and feasibility cases."""
    up = np.asarray(((0.0, 0.0, 1.0),), dtype=np.float64)
    down = np.asarray(((0.0, 0.0, -1.0),), dtype=np.float64)
    center = np.asarray(((0.25, 0.25, 0.0),), dtype=np.float64)
    plane = rectangle_scene(center_enu_m=(0.0, 0.0, 1.0), object_id=10)
    plane_backend = make_backend(name, plane)

    full = bool(plane_backend.cast_any(center, up)[0])
    partial_origins = np.asarray(((0.25, 0.25, 0.0), (1.25, 0.25, 0.0)))
    partial = plane_backend.cast_any(partial_origins, np.tile(up, (2, 1))).tolist()
    parallel = bool(plane_backend.cast_any(center, np.asarray(((1.0, 0.0, 0.0),)))[0])
    away = bool(plane_backend.cast_any(center, down)[0])
    close = bool(
        plane_backend.cast_any(
            np.asarray(((0.25, 0.25, 1.0 - 1e-6),)), up, t_min_m=1e-9
        )[0]
    )
    backface = bool(
        plane_backend.cast_any(np.asarray(((0.25, 0.25, 2.0),)), down, t_min_m=1e-9)[0]
    )

    rotated = rectangle_scene(
        center_enu_m=(0.0, 0.0, 1.0),
        u_axis_enu=(1.0, 0.0, 0.0),
        v_axis_enu=(0.0, 2**-0.5, 2**-0.5),
        object_id=30,
    )
    rotated_hit = bool(make_backend(name, rotated).cast_any(center, up)[0])

    arbitrary = MeshScene(
        np.asarray(((-0.5, -0.5, 1.0), (0.75, -0.5, 1.0), (0.0, 0.75, 1.0))),
        np.asarray(((0, 1, 2),), dtype=np.int64),
        np.asarray((40,), dtype=np.int64),
    )
    arbitrary_hit = bool(make_backend(name, arbitrary).cast_any(center, up)[0])

    stacked = combine_scenes(
        rectangle_scene(center_enu_m=(0.0, 0.0, 0.001), object_id=101),
        rectangle_scene(center_enu_m=(0.0, 0.0, 2.0), object_id=202),
    )
    stacked_backend = make_backend(name, stacked)
    stacked_first = stacked_backend.cast_first(center, up)
    stacked_all = stacked_backend.cast_all(center, up)
    repeated_first = stacked_backend.cast_first(center, up)
    bounded = {
        "first_below_t_min_second_valid": bool(
            stacked_backend.cast_any(center, up, t_min_m=0.01, t_max_m=3.0)[0]
        ),
        "all_below_t_min": bool(stacked_backend.cast_any(center, up, t_min_m=3.0)[0]),
        "nearest_beyond_t_max": bool(stacked_backend.cast_any(center, up, t_max_m=0.0005)[0]),
        "valid_between_bounds": bool(
            stacked_backend.cast_any(center, up, t_min_m=1.0, t_max_m=3.0)[0]
        ),
    }

    self_scene = combine_scenes(
        rectangle_scene(center_enu_m=(0.0, 0.0, 0.0), object_id=301),
        rectangle_scene(center_enu_m=(0.0, 0.0, 2.0), object_id=302),
    )
    self_hits = make_backend(name, self_scene).cast_all(center, up)
    surviving = self_hits.object_id != 301

    terrain = grid_scene(4, 5, z_m=0.5)
    terrain_hit = bool(make_backend(name, terrain).cast_any(center, up)[0])
    disconnected = combine_scenes(
        rectangle_scene(center_enu_m=(0.0, 0.0, 1.0), object_id=401),
        rectangle_scene(center_enu_m=(4.0, 0.0, 1.0), object_id=402),
    )
    disconnected_backend = make_backend(name, disconnected)
    disconnected_origins = np.asarray(((0.25, 0.25, 0.0), (4.25, 0.25, 0.0)))
    disconnected_first = disconnected_backend.cast_first(
        disconnected_origins, np.tile(up, (2, 1))
    )

    return {
        "no_occluder": {"logical_empty_result": False, "adapter_short_circuit_required": True},
        "one_rectangle": full,
        "full_blocker": full,
        "partial_blocker": partial,
        "rotated_blocker": rotated_hit,
        "multiple_disconnected_object_ids": disconnected_first.object_id.tolist(),
        "stacked_first_object_id": int(stacked_first.object_id[0]),
        "stacked_repeated_identity": bool(
            np.array_equal(stacked_first.object_id, repeated_first.object_id)
            and np.array_equal(stacked_first.primitive_index, repeated_first.primitive_index)
        ),
        "stacked_all_distances_m": stacked_all.distance_m.tolist(),
        "stacked_all_primitive_indices": stacked_all.primitive_index.tolist(),
        "stacked_all_object_ids": stacked_all.object_id.tolist(),
        "parallel_hit": parallel,
        "away_hit": away,
        "close_hit": close,
        "terrain_like_hit": terrain_hit,
        "arbitrary_triangle_hit": arbitrary_hit,
        "two_sided_backface_hit": backface,
        "bounded": bounded,
        "self_hit": {
            "distances_m": self_hits.distance_m.tolist(),
            "primitive_indices": self_hits.primitive_index.tolist(),
            "object_ids": self_hits.object_id.tolist(),
            "surviving_distances_m": self_hits.distance_m[surviving].tolist(),
            "surviving_object_ids": self_hits.object_id[surviving].tolist(),
        },
    }


def run_benchmark(
    name: str, nx: int, ny: int, ray_counts: list[int], *, origin_m: float
) -> dict[str, object]:
    """Build once and measure repeated first-hit queries."""
    scene = grid_scene(nx, ny, origin_m=origin_m)
    probe_origins = np.asarray(((origin_m + 0.25, origin_m + 0.25, 0.0),))
    probe_directions = np.asarray(((0.0, 0.0, 1.0),))
    started = time.perf_counter()
    backend = make_backend(name, scene)
    # Both engines build acceleration structures lazily on first query.
    backend.cast_first(probe_origins, probe_directions)
    build_s = time.perf_counter() - started
    results: list[dict[str, float | int]] = []
    for count in ray_counts:
        origins, directions = benchmark_rays(count, nx, ny, origin_m=origin_m)
        backend.cast_first(origins[: min(100, count)], directions[: min(100, count)])
        started = time.perf_counter()
        hits = backend.cast_first(origins, directions)
        query_s = time.perf_counter() - started
        results.append({
            "rays": count,
            "hits": int(hits.hit.sum()),
            "query_s": query_s,
            "rays_per_s": count / query_s,
        })
    return {"triangles": len(scene.faces), "build_s": build_s, "queries": results}


def main() -> int:
    """Run deterministic correctness and performance measurements."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("trimesh-embreex", "open3d"), required=True)
    parser.add_argument("--full", action="store_true", help="include the million-ray workload")
    args = parser.parse_args()
    counts = [10_000, 100_000, 1_000_000] if args.full else [10_000]
    small = grid_scene(5, 10)
    backend = make_backend(args.backend, small)
    candidate_package = "trimesh" if args.backend == "trimesh-embreex" else "open3d"
    payload = {
        "backend": args.backend,
        "versions": {
            candidate_package: version(candidate_package),
            **({"embreex": version("embreex")} if args.backend == "trimesh-embreex" else {}),
            "numpy": version("numpy"),
        },
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "correctness": correctness_cases(backend),
        "rectangular_oracle": rectangular_oracle_comparison(args.backend),
        "synthetic_correctness": synthetic_correctness_suite(args.backend),
        "small": run_benchmark(args.backend, 5, 10, counts, origin_m=0.0),
        "representative": run_benchmark(args.backend, 100, 250, counts, origin_m=0.0),
        "translated_1km": run_benchmark(args.backend, 5, 10, [10_000], origin_m=1_000.0),
        "translated_10Mm": run_benchmark(args.backend, 5, 10, [10_000], origin_m=10_000_000.0),
    }
    print(json.dumps(payload, indent=2, allow_nan=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
