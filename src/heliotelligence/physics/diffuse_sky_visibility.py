"""Geometric front-side diffuse-sky visibility over explicit canonical geometry.

S6D v1 returns a cosine-weighted geometric sky-view factor only.  It does not
apply that factor to Perez/Perez-Driesse diffuse irradiance or compose terrain,
row, near-object, IAM, rear-side, or electrical effects.  A clear result means
clear only relative to the explicitly supplied canonical occluders.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from numbers import Integral
from typing import TypeVar

import numpy as np
import numpy.typing as npt
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.geometry import (
    PVReceiver,
    ReceiverKind,
    ShadingObject,
    ShadowRole,
    TerrainSurface,
)
from heliotelligence.physics.near_object_shading import sample_triangle_mesh
from heliotelligence.physics.ray_backend import MeshRayScene, RaySceneObject

MODEL_ID = "canonical_embree_cosine_weighted_diffuse_sky_v1"
COVERAGE_SCOPE = "supplied_explicit_diffuse_occluders_only"
_FRACTION_TOLERANCE = 1e-12
_GOLDEN_ANGLE_RAD = np.pi * (3.0 - np.sqrt(5.0))
_T = TypeVar("_T")

_RESULT_COLUMNS = [
    "receiver_id",
    "receiver_normal_east",
    "receiver_normal_north",
    "receiver_normal_up",
    "surface_sample_count",
    "sky_direction_count",
    "unobstructed_weight",
    "visible_weight",
    "blocked_weight",
    "ray_count",
    "diffuse_sky_visible_fraction",
    "diffuse_sky_blocked_fraction",
    "diffuse_sky_visibility_resolved",
    "diffuse_sky_state",
    "diffuse_sky_model",
    "diffuse_sky_coverage_scope",
]


@dataclass(frozen=True)
class DiffuseSkySceneDiagnostics:
    """Bounded scene and numerical diagnostics without mesh serialization."""

    receiver_count: int
    samples_per_receiver: int
    sky_direction_count: int
    terrain_surface_count: int
    terrain_triangle_count: int
    explicit_receiver_occluder_count: int
    eligible_shading_object_count: int
    ignored_non_occluder_count: int
    ignored_unknown_count: int
    ray_primitive_count: int
    max_rays_per_batch: int
    coverage_scope: str


@dataclass(frozen=True)
class DiffuseSkyVisibility:
    """Receiver-resolved geometric diffuse-sky visibility."""

    receivers: pd.DataFrame


class DiffuseSkyScene:
    """Reusable receiver samples, sky quadrature, and explicit Embree scene.

    Only fixed-table canonical poses are supported. Tracker runtime pose belongs
    to S6C and must be supplied through a future runtime geometry contract.
    """

    def __init__(
        self,
        receivers: Sequence[PVReceiver],
        terrain_surfaces: Sequence[TerrainSurface] = (),
        shading_objects: Sequence[ShadingObject] = (),
        receiver_occluders: Sequence[PVReceiver] = (),
        *,
        samples_per_receiver: int,
        sky_direction_count: int,
        max_rays_per_batch: int,
    ) -> None:
        self._receivers = _validated_sequence(receivers, PVReceiver, "receivers")
        terrain = _validated_sequence(terrain_surfaces, TerrainSurface, "terrain_surfaces")
        shading = _validated_sequence(shading_objects, ShadingObject, "shading_objects")
        receiver_blockers = _validated_sequence(
            receiver_occluders, PVReceiver, "receiver_occluders"
        )
        _require_unique_ids((item.id for item in self._receivers), "receiver")
        _require_unique_ids((item.id for item in terrain), "terrain surface")
        _require_unique_ids((item.id for item in shading), "shading object")
        _require_unique_ids((item.id for item in receiver_blockers), "receiver occluder")
        _require_unique_ids(
            (
                *(item.id for item in terrain),
                *(item.id for item in shading),
                *(item.id for item in receiver_blockers),
            ),
            "diffuse occluder canonical",
        )
        target_ids = {item.id for item in self._receivers}
        nonreceiver_blocker_ids = {item.id for item in terrain} | {
            item.id for item in shading
        }
        if target_ids & nonreceiver_blocker_ids:
            raise ValueError("target and non-receiver occluder canonical IDs must be unique")
        _require_fixed(self._receivers, "target receiver")
        _require_fixed(receiver_blockers, "receiver occluder")

        self._samples_per_receiver = _positive_integer(samples_per_receiver, "samples_per_receiver")
        self._sky_direction_count = _positive_integer(sky_direction_count, "sky_direction_count")
        self._max_rays_per_batch = _positive_integer(max_rays_per_batch, "max_rays_per_batch")
        self._directions = _upper_hemisphere_directions(self._sky_direction_count)

        sample_parts: list[npt.NDArray[np.float64]] = []
        for receiver in self._receivers:
            sample_parts.append(sample_triangle_mesh(receiver.mesh, self._samples_per_receiver))
        self._sample_points = (
            np.stack(sample_parts)
            if sample_parts
            else np.empty((0, self._samples_per_receiver, 3), dtype=np.float64)
        )

        eligible = tuple(item for item in shading if item.shadow_role is ShadowRole.OCCLUDER)
        scene_objects = [
            *(RaySceneObject(f"terrain:{item.id}", item.mesh) for item in terrain),
            *(RaySceneObject(f"shading:{item.id}", item.mesh) for item in eligible),
            *(RaySceneObject(f"receiver:{item.id}", item.mesh) for item in receiver_blockers),
        ]
        scene_objects.sort(key=lambda item: item.object_id)
        self._receiver_occluder_ids = frozenset(item.id for item in receiver_blockers)
        self._ray_scene = MeshRayScene(tuple(scene_objects))
        self._diagnostics = DiffuseSkySceneDiagnostics(
            receiver_count=len(self._receivers),
            samples_per_receiver=self._samples_per_receiver,
            sky_direction_count=self._sky_direction_count,
            terrain_surface_count=len(terrain),
            terrain_triangle_count=sum(len(item.mesh.faces) for item in terrain),
            explicit_receiver_occluder_count=len(receiver_blockers),
            eligible_shading_object_count=len(eligible),
            ignored_non_occluder_count=sum(
                item.shadow_role is ShadowRole.NON_OCCLUDER for item in shading
            ),
            ignored_unknown_count=sum(item.shadow_role is ShadowRole.UNKNOWN for item in shading),
            ray_primitive_count=self._ray_scene.primitive_count,
            max_rays_per_batch=self._max_rays_per_batch,
            coverage_scope=COVERAGE_SCOPE,
        )

    @property
    def receiver_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self._receivers)

    @property
    def diagnostics(self) -> DiffuseSkySceneDiagnostics:
        return self._diagnostics

    def calculate_visibility(self) -> DiffuseSkyVisibility:
        """Evaluate cosine-weighted front-side upper-sky visibility in chunks."""
        rows: list[dict[str, object]] = []
        for receiver_index, receiver in enumerate(self._receivers):
            normal = np.asarray(receiver.normal_enu, dtype=np.float64)
            direction_weights = np.maximum(0.0, self._directions @ normal)
            contributing = direction_weights > 0.0
            weights = direction_weights[contributing]
            directions = self._directions[contributing]
            denominator = float(self._samples_per_receiver * np.sum(weights))
            if not np.isfinite(denominator) or denominator <= 0.0:
                raise ValueError(f"receiver {receiver.id!r} has no front-side upper-sky exposure")

            points = self._sample_points[receiver_index]
            ray_count = len(points) * len(directions)
            blocked_weight = 0.0
            exclusion = (
                f"receiver:{receiver.id}" if receiver.id in self._receiver_occluder_ids else None
            )
            for start in range(0, ray_count, self._max_rays_per_batch):
                stop = min(start + self._max_rays_per_batch, ray_count)
                flat = np.arange(start, stop, dtype=np.int64)
                sample_index = flat // len(directions)
                direction_index = flat % len(directions)
                origins = points[sample_index]
                ray_directions = directions[direction_index]
                excluded = None
                if exclusion is not None:
                    excluded = (exclusion,) * len(origins)
                blocked = self._ray_scene.cast_any(
                    origins,
                    ray_directions,
                    excluded_object_ids=excluded,
                )
                blocked_weight += float(np.sum(weights[direction_index][blocked]))

            visible_weight = denominator - blocked_weight
            visible_fraction = visible_weight / denominator
            if (
                not np.isfinite(visible_fraction)
                or visible_fraction < -_FRACTION_TOLERANCE
                or visible_fraction > 1.0 + _FRACTION_TOLERANCE
            ):
                raise RuntimeError("diffuse-sky visibility is outside [0, 1]")
            visible_fraction = float(np.clip(visible_fraction, 0.0, 1.0))
            blocked_fraction = 1.0 - visible_fraction
            rows.append(
                {
                    "receiver_id": receiver.id,
                    "receiver_normal_east": normal[0],
                    "receiver_normal_north": normal[1],
                    "receiver_normal_up": normal[2],
                    "surface_sample_count": self._samples_per_receiver,
                    "sky_direction_count": self._sky_direction_count,
                    "unobstructed_weight": denominator,
                    "visible_weight": visible_weight,
                    "blocked_weight": blocked_weight,
                    "ray_count": ray_count,
                    "diffuse_sky_visible_fraction": visible_fraction,
                    "diffuse_sky_blocked_fraction": blocked_fraction,
                    "diffuse_sky_visibility_resolved": True,
                    "diffuse_sky_state": "resolved",
                    "diffuse_sky_model": MODEL_ID,
                    "diffuse_sky_coverage_scope": COVERAGE_SCOPE,
                }
            )
        return DiffuseSkyVisibility(_typed_result(rows))


def _upper_hemisphere_directions(count: int) -> npt.NDArray[np.float64]:
    """Return deterministic midpoint Fibonacci directions with strictly positive z."""
    index = np.arange(count, dtype=np.float64)
    z = (index + 0.5) / count
    radius = np.sqrt(1.0 - z * z)
    azimuth = index * _GOLDEN_ANGLE_RAD
    return np.column_stack((radius * np.cos(azimuth), radius * np.sin(azimuth), z))


def _require_fixed(receivers: Sequence[PVReceiver], label: str) -> None:
    for receiver in receivers:
        if receiver.receiver_kind is ReceiverKind.TRACKER_TABLE:
            raise ValueError(
                f"{label} TRACKER_TABLE requires future runtime tracker pose; "
                "S6D v1 accepts only FIXED_TABLE geometry"
            )
        if receiver.receiver_kind is not ReceiverKind.FIXED_TABLE:
            raise ValueError(f"{label} must have ReceiverKind.FIXED_TABLE")


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise ValueError(f"{name} must be a positive integer")
    result = int(value)
    if result <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return result


def _validated_sequence(value: object, kind: type[_T], name: str) -> tuple[_T, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a sequence")
    result = tuple(value)
    if any(not isinstance(item, kind) for item in result):
        raise ValueError(f"{name} must contain only {kind.__name__} values")
    return result


def _require_unique_ids(values: Iterable[str], label: str) -> None:
    ids = tuple(values)
    if any(count > 1 for count in Counter(ids).values()):
        raise ValueError(f"{label} IDs must be unique")


def _typed_result(rows: list[dict[str, object]]) -> pd.DataFrame:
    result = pd.DataFrame(rows, columns=_RESULT_COLUMNS)
    float_columns = (
        "receiver_normal_east",
        "receiver_normal_north",
        "receiver_normal_up",
        "unobstructed_weight",
        "visible_weight",
        "blocked_weight",
        "diffuse_sky_visible_fraction",
        "diffuse_sky_blocked_fraction",
    )
    integer_columns = ("surface_sample_count", "sky_direction_count", "ray_count")
    string_columns = (
        "receiver_id",
        "diffuse_sky_state",
        "diffuse_sky_model",
        "diffuse_sky_coverage_scope",
    )
    for column in float_columns:
        result[column] = result[column].astype("float64")
    for column in integer_columns:
        result[column] = result[column].astype("int64")
    for column in string_columns:
        result[column] = result[column].astype("string")
    result["diffuse_sky_visibility_resolved"] = result["diffuse_sky_visibility_resolved"].astype(
        "bool"
    )
    return result
