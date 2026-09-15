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


class RayBackend(Protocol):
    """Minimum candidate behavior exercised by this spike."""

    def cast_first(self, origins: FloatArray, directions: FloatArray) -> FirstHits: ...

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

    def cast_any(
        self,
        origins: FloatArray,
        directions: FloatArray,
        *,
        t_min_m: float = 0.0,
        t_max_m: float | None = None,
    ) -> BoolArray:
        first = self.cast_first(origins, directions)
        upper = np.inf if t_max_m is None else t_max_m
        return first.hit & (first.distance_m >= t_min_m) & (first.distance_m <= upper)


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
        "small": run_benchmark(args.backend, 5, 10, counts, origin_m=0.0),
        "representative": run_benchmark(args.backend, 100, 250, counts, origin_m=0.0),
        "translated_1km": run_benchmark(args.backend, 5, 10, [10_000], origin_m=1_000.0),
        "translated_10Mm": run_benchmark(args.backend, 5, 10, [10_000], origin_m=10_000_000.0),
    }
    print(json.dumps(payload, indent=2, allow_nan=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
