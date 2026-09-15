"""Embree-backed ray queries over explicit canonical triangle meshes.

This adapter owns backend conversion and acceleration state. It intentionally
contains no policy deciding which site objects cast shadows.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from numbers import Real
from typing import Any

import numpy as np
import numpy.typing as npt
import trimesh
from trimesh.ray.ray_pyembree import RayMeshIntersector

from heliotelligence.geometry import TriangleMesh

DEFAULT_T_MIN_M = 1e-9

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
BoolArray = npt.NDArray[np.bool_]
_RayMeshIntersector: Any = RayMeshIntersector


def _immutable_array(value: npt.NDArray[Any], dtype: npt.DTypeLike) -> npt.NDArray[Any]:
    contiguous = np.ascontiguousarray(value, dtype=dtype)
    return np.frombuffer(contiguous.tobytes(order="C"), dtype=dtype).reshape(contiguous.shape)


@dataclass(frozen=True)
class RaySceneObject:
    """One explicitly selected canonical mesh in a ray scene."""

    object_id: str
    mesh: TriangleMesh

    def __post_init__(self) -> None:
        if not isinstance(self.object_id, str) or not self.object_id.strip():
            raise ValueError("object_id must be a non-empty string")
        if not isinstance(self.mesh, TriangleMesh):
            raise ValueError("mesh must be a canonical TriangleMesh")


@dataclass(frozen=True, eq=False)
class RayFirstHitBatch:
    """Immutable nearest valid hit for each input ray."""

    hit: BoolArray = field(repr=False)
    distance_m: FloatArray = field(repr=False)
    primitive_index: IntArray = field(repr=False)
    local_primitive_index: IntArray = field(repr=False)
    object_id: tuple[str | None, ...]

    def __post_init__(self) -> None:
        size = len(self.hit)
        if any(
            array.shape != (size,)
            for array in (self.distance_m, self.primitive_index, self.local_primitive_index)
        ) or len(self.object_id) != size:
            raise ValueError("ray result fields must have matching one-dimensional lengths")
        object.__setattr__(self, "hit", _immutable_array(self.hit, np.bool_))
        object.__setattr__(self, "distance_m", _immutable_array(self.distance_m, np.float64))
        object.__setattr__(
            self, "primitive_index", _immutable_array(self.primitive_index, np.int64)
        )
        object.__setattr__(
            self,
            "local_primitive_index",
            _immutable_array(self.local_primitive_index, np.int64),
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RayFirstHitBatch):
            return NotImplemented
        return (
            np.array_equal(self.hit, other.hit)
            and np.array_equal(self.distance_m, other.distance_m)
            and np.array_equal(self.primitive_index, other.primitive_index)
            and np.array_equal(self.local_primitive_index, other.local_primitive_index)
            and self.object_id == other.object_id
        )


@dataclass
class _MutableHits:
    hit: BoolArray
    distance_m: FloatArray
    primitive_index: IntArray
    local_primitive_index: IntArray
    object_id: list[str | None]


class MeshRayScene:
    """Reusable static Embree scene built from explicit canonical meshes."""

    def __init__(self, objects: Sequence[RaySceneObject]) -> None:
        if isinstance(objects, (str, bytes)) or not isinstance(objects, Sequence):
            raise ValueError("objects must be a sequence of RaySceneObject")
        if any(not isinstance(item, RaySceneObject) for item in objects):
            raise ValueError("objects must contain only RaySceneObject instances")
        object_tuple = tuple(objects)
        object_ids = tuple(item.object_id for item in object_tuple)
        if len(set(object_ids)) != len(object_ids):
            raise ValueError("scene object IDs must be unique")

        self._objects = object_tuple
        self._object_ids = object_ids
        nonempty = [
            (index, item)
            for index, item in enumerate(object_tuple)
            if len(item.mesh.faces)
        ]
        if not nonempty:
            self._translation = np.zeros(3, dtype=np.float64)
            self._face_object_index = np.empty(0, dtype=np.int64)
            self._face_local_index = np.empty(0, dtype=np.int64)
            self._intersector: _RayMeshIntersector | None = None
            return

        all_vertices = np.vstack([item.mesh.vertices_enu_m for _, item in nonempty])
        self._translation = (np.min(all_vertices, axis=0) + np.max(all_vertices, axis=0)) / 2.0
        vertices: list[FloatArray] = []
        faces: list[IntArray] = []
        face_object_index: list[IntArray] = []
        face_local_index: list[IntArray] = []
        vertex_offset = 0
        for object_index, item in nonempty:
            mesh = item.mesh
            triangle_vectors = mesh.vertices_enu_m[mesh.faces]
            doubled_areas = np.cross(
                triangle_vectors[:, 1] - triangle_vectors[:, 0],
                triangle_vectors[:, 2] - triangle_vectors[:, 0],
            )
            if np.any(np.all(doubled_areas == 0.0, axis=1)):
                raise ValueError(f"scene object {item.object_id!r} contains a zero-area triangle")
            vertices.append(np.asarray(mesh.vertices_enu_m - self._translation, dtype=np.float64))
            faces.append(np.asarray(mesh.faces + vertex_offset, dtype=np.int64))
            face_count = len(mesh.faces)
            face_object_index.append(np.full(face_count, object_index, dtype=np.int64))
            face_local_index.append(np.arange(face_count, dtype=np.int64))
            vertex_offset += len(mesh.vertices_enu_m)

        engine_vertices = np.vstack(vertices)
        engine_faces = np.vstack(faces)
        self._face_object_index = np.concatenate(face_object_index)
        self._face_local_index = np.concatenate(face_local_index)
        try:
            engine_mesh = trimesh.Trimesh(
                vertices=engine_vertices,
                faces=engine_faces,
                process=False,
                validate=False,
            )
            self._intersector = _RayMeshIntersector(engine_mesh)
        except Exception as exc:
            raise RuntimeError("failed to initialize the embreex ray intersector") from exc

    @property
    def object_ids(self) -> tuple[str, ...]:
        """Return scene object IDs in caller-supplied order."""
        return self._object_ids

    @property
    def scene_translation_enu_m(self) -> tuple[float, float, float]:
        """Return the deterministic private engine-origin translation."""
        return (
            float(self._translation[0]),
            float(self._translation[1]),
            float(self._translation[2]),
        )

    @property
    def primitive_count(self) -> int:
        """Return the number of triangles in the acceleration scene."""
        return len(self._face_object_index)

    def cast_first(
        self,
        origins: npt.ArrayLike,
        directions: npt.ArrayLike,
        *,
        t_min_m: float = DEFAULT_T_MIN_M,
        t_max_m: float | None = None,
        excluded_object_ids: Sequence[str | None] | None = None,
    ) -> RayFirstHitBatch:
        """Return each ray's nearest valid hit in the inclusive distance interval."""
        ray_origins, ray_directions = _validated_rays(origins, directions)
        lower, upper = _validated_bounds(t_min_m, t_max_m)
        exclusions = _validated_exclusions(excluded_object_ids, len(ray_origins))
        result = _empty_result(len(ray_origins))
        if len(ray_origins) == 0 or self._intersector is None:
            return _public_result(result)

        engine_origins = ray_origins - self._translation
        primitive = np.asarray(
            self._intersector.intersects_first(engine_origins, ray_directions),
            dtype=np.int64,
        )
        raw_hit = primitive >= 0
        raw_distance = np.full(len(ray_origins), np.inf, dtype=np.float64)
        raw_distance[raw_hit] = self._primitive_distances(
            primitive[raw_hit], engine_origins[raw_hit], ray_directions[raw_hit]
        )
        raw_object = np.full(len(ray_origins), -1, dtype=np.int64)
        raw_object[raw_hit] = self._face_object_index[primitive[raw_hit]]
        excluded = np.asarray(
            [
                raw_hit[index]
                and exclusions[index] is not None
                and self._object_ids[raw_object[index]] == exclusions[index]
                for index in range(len(ray_origins))
            ],
            dtype=np.bool_,
        )
        valid_first = (
            raw_hit
            & (raw_distance >= lower)
            & (raw_distance <= upper)
            & ~excluded
        )
        self._assign_hits(
            result,
            np.flatnonzero(valid_first),
            primitive[valid_first],
            raw_distance[valid_first],
        )

        continuation = np.flatnonzero(
            raw_hit & ((raw_distance < lower) | excluded) & (raw_distance <= upper)
        )
        if len(continuation):
            self._continue_hits(
                result,
                continuation,
                engine_origins[continuation],
                ray_directions[continuation],
                lower,
                upper,
                tuple(exclusions[index] for index in continuation),
            )
        return RayFirstHitBatch(
            result.hit,
            result.distance_m,
            result.primitive_index,
            result.local_primitive_index,
            tuple(result.object_id),
        )

    def cast_any(
        self,
        origins: npt.ArrayLike,
        directions: npt.ArrayLike,
        *,
        t_min_m: float = DEFAULT_T_MIN_M,
        t_max_m: float | None = None,
        excluded_object_ids: Sequence[str | None] | None = None,
    ) -> BoolArray:
        """Return immutable booleans equivalent to ``cast_first(...).hit``."""
        first = self.cast_first(
            origins,
            directions,
            t_min_m=t_min_m,
            t_max_m=t_max_m,
            excluded_object_ids=excluded_object_ids,
        )
        return _immutable_array(first.hit, np.bool_)

    def _primitive_distances(
        self, primitive: IntArray, origins: FloatArray, directions: FloatArray
    ) -> FloatArray:
        assert self._intersector is not None
        triangles = np.asarray(self._intersector.mesh.triangles[primitive], dtype=np.float64)
        normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
        numerator = np.einsum("ij,ij->i", triangles[:, 0] - origins, normals)
        denominator = np.einsum("ij,ij->i", directions, normals)
        return np.asarray(numerator / denominator, dtype=np.float64)

    def _assign_hits(
        self,
        result: _MutableHits,
        ray_indices: IntArray,
        primitives: IntArray,
        distances: FloatArray,
    ) -> None:
        result.hit[ray_indices] = True
        result.distance_m[ray_indices] = distances
        result.primitive_index[ray_indices] = primitives
        result.local_primitive_index[ray_indices] = self._face_local_index[primitives]
        for ray_index, primitive in zip(ray_indices, primitives, strict=True):
            result.object_id[int(ray_index)] = self._object_ids[
                self._face_object_index[int(primitive)]
            ]

    def _continue_hits(
        self,
        result: _MutableHits,
        result_indices: IntArray,
        origins: FloatArray,
        directions: FloatArray,
        lower: float,
        upper: float,
        exclusions: tuple[str | None, ...],
    ) -> None:
        assert self._intersector is not None
        primitive_raw, ray_raw, locations_raw = self._intersector.intersects_id(
            origins,
            directions,
            return_locations=True,
            multiple_hits=True,
        )
        primitives = np.asarray(primitive_raw, dtype=np.int64)
        local_rays = np.asarray(ray_raw, dtype=np.int64)
        locations = np.asarray(locations_raw, dtype=np.float64)
        distances = np.einsum(
            "ij,ij->i", locations - origins[local_rays], directions[local_rays]
        )
        order = np.lexsort((primitives, distances, local_rays))
        selected_local: list[int] = []
        selected_primitive: list[int] = []
        selected_distance: list[float] = []
        completed: set[int] = set()
        for index in order:
            local_ray = int(local_rays[index])
            if local_ray in completed:
                continue
            distance = float(distances[index])
            if distance < lower or distance > upper:
                continue
            primitive = int(primitives[index])
            object_id = self._object_ids[self._face_object_index[primitive]]
            if exclusions[local_ray] == object_id:
                continue
            completed.add(local_ray)
            selected_local.append(local_ray)
            selected_primitive.append(primitive)
            selected_distance.append(distance)
        if selected_local:
            local_array = np.asarray(selected_local, dtype=np.int64)
            self._assign_hits(
                result,
                result_indices[local_array],
                np.asarray(selected_primitive, dtype=np.int64),
                np.asarray(selected_distance, dtype=np.float64),
            )


def _validated_rays(
    origins: npt.ArrayLike, directions: npt.ArrayLike
) -> tuple[FloatArray, FloatArray]:
    for value, name in ((origins, "origins"), (directions, "directions")):
        array = np.asarray(value)
        if array.dtype.kind in "bOc":
            raise ValueError(f"{name} must contain real numeric values")
    try:
        origin_array = np.ascontiguousarray(origins, dtype=np.float64)
        direction_array = np.ascontiguousarray(directions, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError("origins and directions must contain real numeric values") from exc
    if origin_array.ndim != 2 or origin_array.shape[1:] != (3,):
        raise ValueError("origins must have shape (N, 3)")
    if direction_array.shape != origin_array.shape:
        raise ValueError("directions must have the same (N, 3) shape as origins")
    if not np.isfinite(origin_array).all() or not np.isfinite(direction_array).all():
        raise ValueError("origins and directions must be finite")
    lengths = np.linalg.norm(direction_array, axis=1)
    if np.any(lengths == 0.0):
        raise ValueError("ray directions must be non-zero")
    return origin_array.copy(), direction_array / lengths[:, None]


def _validated_bounds(t_min_m: float, t_max_m: float | None) -> tuple[float, float]:
    lower = _validated_bound(t_min_m, "t_min_m")
    upper = np.inf if t_max_m is None else _validated_bound(t_max_m, "t_max_m")
    if upper < lower:
        raise ValueError("t_max_m must be greater than or equal to t_min_m")
    return lower, upper


def _validated_bound(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a non-Boolean real value")
    result = float(value)
    if not np.isfinite(result) or result < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result


def _validated_exclusions(
    values: Sequence[str | None] | None, ray_count: int
) -> tuple[str | None, ...]:
    if values is None:
        return (None,) * ray_count
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError("excluded_object_ids must be a sequence")
    result = tuple(values)
    if len(result) != ray_count:
        raise ValueError("excluded_object_ids length must match the ray count")
    if any(
        value is not None and (not isinstance(value, str) or not value.strip())
        for value in result
    ):
        raise ValueError("excluded_object_ids entries must be non-empty strings or None")
    return result


def _empty_result(size: int) -> _MutableHits:
    return _MutableHits(
        np.zeros(size, dtype=np.bool_),
        np.full(size, np.inf, dtype=np.float64),
        np.full(size, -1, dtype=np.int64),
        np.full(size, -1, dtype=np.int64),
        [None] * size,
    )


def _public_result(result: _MutableHits) -> RayFirstHitBatch:
    return RayFirstHitBatch(
        result.hit,
        result.distance_m,
        result.primitive_index,
        result.local_primitive_index,
        tuple(result.object_id),
    )
