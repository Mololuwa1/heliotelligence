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
from numbers import Integral, Real
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
HORIZON_VISIBILITY_MODEL_ID = "canonical_embree_marion_horizon_band_visibility_v1"
GROUND_VISIBILITY_MODEL_ID = "canonical_embree_flat_ground_visibility_v1"
HORIZON_COVERAGE_SCOPE = "supplied_explicit_diffuse_occluders_horizon_band_only"
GROUND_COVERAGE_SCOPE = "supplied_explicit_nonterrain_occluders_flat_lambertian_ground_plane"
HORIZON_MIN_ZENITH_DEG = 89.5
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

_COMPONENT_RESULT_COLUMNS = [
    "receiver_id",
    "receiver_normal_east",
    "receiver_normal_north",
    "receiver_normal_up",
    "surface_sample_count",
    "sky_direction_count",
    "horizon_zenith_count",
    "horizon_azimuth_count",
    "ground_direction_count",
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
    "diffuse_horizon_unobstructed_weight",
    "diffuse_horizon_visible_weight",
    "diffuse_horizon_blocked_weight",
    "diffuse_horizon_ray_count",
    "diffuse_horizon_visible_fraction",
    "diffuse_horizon_blocked_fraction",
    "diffuse_horizon_visibility_resolved",
    "diffuse_horizon_state",
    "diffuse_horizon_model",
    "diffuse_horizon_coverage_scope",
    "ground_plane_z_m",
    "diffuse_ground_unobstructed_weight",
    "diffuse_ground_visible_weight",
    "diffuse_ground_blocked_weight",
    "diffuse_ground_ray_count",
    "diffuse_ground_visible_fraction",
    "diffuse_ground_blocked_fraction",
    "diffuse_ground_visibility_resolved",
    "diffuse_ground_state",
    "diffuse_ground_model",
    "diffuse_ground_coverage_scope",
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


@dataclass(frozen=True)
class DiffuseComponentVisibility:
    """Receiver-resolved sky, horizon-band, and flat-ground geometry."""

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
        nonreceiver_blocker_ids = {item.id for item in terrain} | {item.id for item in shading}
        if target_ids & nonreceiver_blocker_ids:
            raise ValueError("target and non-receiver occluder canonical IDs must be unique")
        _require_fixed(self._receivers, "target receiver")
        _require_fixed(receiver_blockers, "receiver occluder")
        targets_by_id = {item.id: item for item in self._receivers}
        for blocker in receiver_blockers:
            target = targets_by_id.get(blocker.id)
            if target is not None and blocker != target:
                raise ValueError(
                    "receiver occluder sharing a target receiver ID must match "
                    "the same canonical PVReceiver"
                )

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
        ground_scene_objects = [
            *(RaySceneObject(f"shading:{item.id}", item.mesh) for item in eligible),
            *(RaySceneObject(f"receiver:{item.id}", item.mesh) for item in receiver_blockers),
        ]
        ground_scene_objects.sort(key=lambda item: item.object_id)
        self._receiver_occluder_ids = frozenset(item.id for item in receiver_blockers)
        self._ray_scene = MeshRayScene(tuple(scene_objects))
        self._ground_ray_scene = MeshRayScene(tuple(ground_scene_objects))
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

    def calculate_component_visibility(
        self,
        *,
        horizon_zenith_count: int,
        horizon_azimuth_count: int,
        ground_direction_count: int,
        ground_plane_z_m: float,
    ) -> DiffuseComponentVisibility:
        """Return geometric sky, horizon-band, and flat-ground visibility factors."""
        horizon_zenith_count = _positive_integer(horizon_zenith_count, "horizon_zenith_count")
        horizon_azimuth_count = _positive_integer(horizon_azimuth_count, "horizon_azimuth_count")
        ground_direction_count = _positive_integer(ground_direction_count, "ground_direction_count")
        ground_plane = _finite_real(ground_plane_z_m, "ground_plane_z_m")
        horizon_directions = _horizon_band_directions(horizon_zenith_count, horizon_azimuth_count)
        ground_directions = _lower_hemisphere_directions(ground_direction_count)
        sky = self.calculate_visibility().receivers.set_index("receiver_id")
        receiver_indices = {receiver.id: index for index, receiver in enumerate(self._receivers)}
        rows: list[dict[str, object]] = []
        for receiver in sorted(self._receivers, key=lambda item: item.id):
            receiver_index = receiver_indices[receiver.id]
            points = self._sample_points[receiver_index]
            if np.any(points[:, 2] <= ground_plane):
                raise ValueError(
                    f"receiver {receiver.id!r} surface samples must be strictly above "
                    "ground_plane_z_m"
                )
            normal = np.asarray(receiver.normal_enu, dtype=np.float64)
            exclusion = (
                f"receiver:{receiver.id}" if receiver.id in self._receiver_occluder_ids else None
            )
            horizon = self._directional_visibility(
                points,
                normal,
                horizon_directions,
                self._ray_scene,
                exclusion,
                component="horizon",
            )
            ground = self._ground_visibility(
                points,
                normal,
                ground_directions,
                ground_plane,
                exclusion,
            )
            sky_row = sky.loc[receiver.id]
            rows.append(
                {
                    "receiver_id": receiver.id,
                    "receiver_normal_east": normal[0],
                    "receiver_normal_north": normal[1],
                    "receiver_normal_up": normal[2],
                    "surface_sample_count": self._samples_per_receiver,
                    "sky_direction_count": self._sky_direction_count,
                    "horizon_zenith_count": horizon_zenith_count,
                    "horizon_azimuth_count": horizon_azimuth_count,
                    "ground_direction_count": ground_direction_count,
                    **{name: sky_row[name] for name in _RESULT_COLUMNS[6:]},
                    **horizon,
                    "ground_plane_z_m": ground_plane,
                    **ground,
                }
            )
        return DiffuseComponentVisibility(_typed_component_result(rows))

    def _directional_visibility(
        self,
        points: npt.NDArray[np.float64],
        normal: npt.NDArray[np.float64],
        directions: npt.NDArray[np.float64],
        scene: MeshRayScene,
        exclusion: str | None,
        *,
        component: str,
    ) -> dict[str, object]:
        weights_all = np.maximum(0.0, directions @ normal)
        contributing = weights_all > 0.0
        weights = weights_all[contributing]
        selected_directions = directions[contributing]
        denominator = float(len(points) * np.sum(weights))
        prefix = f"diffuse_{component}"
        if denominator <= _FRACTION_TOLERANCE:
            return _unresolved_component(
                prefix,
                "not_applicable_no_front_side_horizon_view",
                HORIZON_VISIBILITY_MODEL_ID,
                HORIZON_COVERAGE_SCOPE,
            )
        ray_count = len(points) * len(selected_directions)
        blocked_weight = 0.0
        for start in range(0, ray_count, self._max_rays_per_batch):
            stop = min(start + self._max_rays_per_batch, ray_count)
            flat = np.arange(start, stop, dtype=np.int64)
            sample_index = flat // len(selected_directions)
            direction_index = flat % len(selected_directions)
            origins = points[sample_index]
            excluded = (exclusion,) * len(origins) if exclusion is not None else None
            blocked = scene.cast_any(
                origins,
                selected_directions[direction_index],
                excluded_object_ids=excluded,
            )
            blocked_weight += float(np.sum(weights[direction_index][blocked]))
        return _resolved_component(
            prefix,
            denominator,
            blocked_weight,
            ray_count,
            HORIZON_VISIBILITY_MODEL_ID,
            HORIZON_COVERAGE_SCOPE,
        )

    def _ground_visibility(
        self,
        points: npt.NDArray[np.float64],
        normal: npt.NDArray[np.float64],
        directions: npt.NDArray[np.float64],
        ground_plane_z_m: float,
        exclusion: str | None,
    ) -> dict[str, object]:
        weights_all = np.maximum(0.0, directions @ normal)
        contributing = weights_all > 0.0
        weights = weights_all[contributing]
        selected_directions = directions[contributing]
        denominator = float(len(points) * np.sum(weights))
        if denominator <= _FRACTION_TOLERANCE:
            return _unresolved_component(
                "diffuse_ground",
                "not_applicable_no_front_side_ground_view",
                GROUND_VISIBILITY_MODEL_ID,
                GROUND_COVERAGE_SCOPE,
            )
        ray_count = len(points) * len(selected_directions)
        blocked_weight = 0.0
        for start in range(0, ray_count, self._max_rays_per_batch):
            stop = min(start + self._max_rays_per_batch, ray_count)
            flat = np.arange(start, stop, dtype=np.int64)
            sample_index = flat // len(selected_directions)
            direction_index = flat % len(selected_directions)
            origins = points[sample_index]
            ray_directions = selected_directions[direction_index]
            t_ground = (ground_plane_z_m - origins[:, 2]) / ray_directions[:, 2]
            if not np.all(np.isfinite(t_ground)) or np.any(t_ground <= 0.0):
                raise RuntimeError("ground-plane ray intersection must be finite and positive")
            excluded = (exclusion,) * len(origins) if exclusion is not None else None
            hits = self._ground_ray_scene.cast_first(
                origins,
                ray_directions,
                excluded_object_ids=excluded,
            )
            distance_tolerance = _FRACTION_TOLERANCE * np.maximum(1.0, t_ground)
            blocked = hits.hit & (hits.distance_m <= t_ground + distance_tolerance)
            blocked_weight += float(np.sum(weights[direction_index][blocked]))
        return _resolved_component(
            "diffuse_ground",
            denominator,
            blocked_weight,
            ray_count,
            GROUND_VISIBILITY_MODEL_ID,
            GROUND_COVERAGE_SCOPE,
        )


def _upper_hemisphere_directions(count: int) -> npt.NDArray[np.float64]:
    """Return deterministic midpoint Fibonacci directions with strictly positive z."""
    index = np.arange(count, dtype=np.float64)
    z = (index + 0.5) / count
    radius = np.sqrt(1.0 - z * z)
    azimuth = index * _GOLDEN_ANGLE_RAD
    return np.column_stack((radius * np.cos(azimuth), radius * np.sin(azimuth), z))


def _horizon_band_directions(zenith_count: int, azimuth_count: int) -> npt.NDArray[np.float64]:
    mu_max = float(np.cos(np.radians(HORIZON_MIN_ZENITH_DEG)))
    mu = (np.arange(zenith_count, dtype=np.float64) + 0.5) * mu_max / zenith_count
    azimuth = (np.arange(azimuth_count, dtype=np.float64) + 0.5) * 2.0 * np.pi / azimuth_count
    mu_grid, azimuth_grid = np.meshgrid(mu, azimuth, indexing="ij")
    radius = np.sqrt(1.0 - mu_grid * mu_grid)
    return np.column_stack(
        (
            (np.sin(azimuth_grid) * radius).ravel(),
            (np.cos(azimuth_grid) * radius).ravel(),
            mu_grid.ravel(),
        )
    )


def _lower_hemisphere_directions(count: int) -> npt.NDArray[np.float64]:
    index = np.arange(count, dtype=np.float64)
    z = -(index + 0.5) / count
    radius = np.sqrt(1.0 - z * z)
    azimuth = index * _GOLDEN_ANGLE_RAD
    return np.column_stack((radius * np.sin(azimuth), radius * np.cos(azimuth), z))


def _resolved_component(
    prefix: str,
    unobstructed_weight: float,
    blocked_weight: float,
    ray_count: int,
    model: str,
    coverage_scope: str,
) -> dict[str, object]:
    visible_weight = unobstructed_weight - blocked_weight
    if not np.isclose(
        visible_weight + blocked_weight,
        unobstructed_weight,
        rtol=1e-12,
        atol=_FRACTION_TOLERANCE,
    ):
        raise RuntimeError(f"{prefix} weight closure failed")
    visible_fraction = visible_weight / unobstructed_weight
    if (
        not np.isfinite(visible_fraction)
        or visible_fraction < -_FRACTION_TOLERANCE
        or visible_fraction > 1.0 + _FRACTION_TOLERANCE
    ):
        raise RuntimeError(f"{prefix} visibility is outside [0, 1]")
    visible_fraction = float(np.clip(visible_fraction, 0.0, 1.0))
    blocked_fraction = 1.0 - visible_fraction
    return {
        f"{prefix}_unobstructed_weight": unobstructed_weight,
        f"{prefix}_visible_weight": visible_weight,
        f"{prefix}_blocked_weight": blocked_weight,
        f"{prefix}_ray_count": ray_count,
        f"{prefix}_visible_fraction": visible_fraction,
        f"{prefix}_blocked_fraction": blocked_fraction,
        f"{prefix}_visibility_resolved": True,
        f"{prefix}_state": "resolved",
        f"{prefix}_model": model,
        f"{prefix}_coverage_scope": coverage_scope,
    }


def _unresolved_component(
    prefix: str, state: str, model: str, coverage_scope: str
) -> dict[str, object]:
    return {
        f"{prefix}_unobstructed_weight": 0.0,
        f"{prefix}_visible_weight": 0.0,
        f"{prefix}_blocked_weight": 0.0,
        f"{prefix}_ray_count": 0,
        f"{prefix}_visible_fraction": np.nan,
        f"{prefix}_blocked_fraction": np.nan,
        f"{prefix}_visibility_resolved": False,
        f"{prefix}_state": state,
        f"{prefix}_model": model,
        f"{prefix}_coverage_scope": coverage_scope,
    }


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


def _finite_real(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number")
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(f"{name} must be a finite real number")
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


def _typed_component_result(rows: list[dict[str, object]]) -> pd.DataFrame:
    result = pd.DataFrame(rows, columns=_COMPONENT_RESULT_COLUMNS)
    boolean_columns = (
        "diffuse_sky_visibility_resolved",
        "diffuse_horizon_visibility_resolved",
        "diffuse_ground_visibility_resolved",
    )
    integer_columns = (
        "surface_sample_count",
        "sky_direction_count",
        "horizon_zenith_count",
        "horizon_azimuth_count",
        "ground_direction_count",
        "ray_count",
        "diffuse_horizon_ray_count",
        "diffuse_ground_ray_count",
    )
    string_columns = (
        "receiver_id",
        "diffuse_sky_state",
        "diffuse_sky_model",
        "diffuse_sky_coverage_scope",
        "diffuse_horizon_state",
        "diffuse_horizon_model",
        "diffuse_horizon_coverage_scope",
        "diffuse_ground_state",
        "diffuse_ground_model",
        "diffuse_ground_coverage_scope",
    )
    for column in boolean_columns:
        result[column] = result[column].astype("bool")
    for column in integer_columns:
        result[column] = result[column].astype("int64")
    for column in string_columns:
        result[column] = result[column].astype("string")
    numeric_columns = set(result.columns) - set(boolean_columns + integer_columns + string_columns)
    for column in numeric_columns:
        result[column] = result[column].astype("float64")
    return result
