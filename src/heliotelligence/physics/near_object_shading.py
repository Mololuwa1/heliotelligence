"""Near-object direct-beam shading over canonical triangle geometry.

Only explicitly classified ``ShadowRole.OCCLUDER`` objects enter the ray
scene. PV receivers are sampled receiving surfaces, and terrain is outside
this mechanism. Tracker meshes are used in exactly the pose supplied by the
caller; runtime tracking and backtracking are not implemented here.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral, Real
from typing import TypeVar

import numpy as np
import numpy.typing as npt
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.geometry import PVReceiver, ShadingObject, ShadowRole, TriangleMesh
from heliotelligence.physics.ray_backend import MeshRayScene, RaySceneObject
from heliotelligence.physics.shading import solar_direction_enu

MODEL_ID = "canonical_triangle_embree_near_object_v1"

_SAMPLE_COLUMNS = [
    "receiver_id",
    "sample_index",
    "sample_east_m",
    "sample_north_m",
    "sample_up_m",
    "sample_weight_fraction",
    "beam_visible",
    "beam_shaded",
    "blocking_object_id",
    "blocking_distance_m",
]
_RECEIVER_COLUMNS = [
    "receiver_id",
    "visible_fraction",
    "shaded_fraction",
    "sample_count",
    "shaded_sample_count",
]
_TIME_COLUMNS = [
    "poa_direct_raw_wm2",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "near_object_beam_visible_fraction",
    "near_object_beam_shaded_fraction",
    "poa_direct_near_object_visible_wm2",
    "near_object_shading_loss_wm2",
    "sample_count",
    "shaded_sample_count",
    "near_object_visibility_resolved",
    "near_object_shading_resolved",
    "near_object_shading_applied",
    "near_object_shading_state",
    "near_object_shading_model",
]
_GOLDEN_CONJUGATE = (np.sqrt(5.0) - 1.0) / 2.0
_SQRT2_CONJUGATE = np.sqrt(2.0) - 1.0
_T = TypeVar("_T")


@dataclass(frozen=True)
class NearObjectSceneDiagnostics:
    """Bounded scene membership diagnostics without mesh serialization."""

    receiver_count: int
    samples_per_receiver: int
    eligible_occluder_count: int
    ignored_non_occluder_count: int
    ignored_unknown_count: int
    ray_primitive_count: int


@dataclass(frozen=True)
class NearObjectBeamVisibility:
    """One above-horizon sample and receiver visibility evaluation."""

    samples: pd.DataFrame
    receivers: pd.DataFrame
    apparent_solar_zenith_deg: float
    solar_azimuth_deg: float


class NearObjectBeamScene:
    """Reusable samples and Embree scene for near-object direct beam queries."""

    def __init__(
        self,
        receivers: Sequence[PVReceiver],
        shading_objects: Sequence[ShadingObject],
        *,
        samples_per_receiver: int,
    ) -> None:
        self._receivers = _validated_sequence(receivers, PVReceiver, "receivers")
        shading = _validated_sequence(shading_objects, ShadingObject, "shading_objects")
        _require_unique_ids((receiver.id for receiver in self._receivers), "receiver")
        _require_unique_ids((item.id for item in shading), "shading object")
        self._samples_per_receiver = _positive_integer(
            samples_per_receiver, "samples_per_receiver"
        )

        sample_parts: list[npt.NDArray[np.float64]] = []
        receiver_indices: list[npt.NDArray[np.int64]] = []
        sample_indices: list[npt.NDArray[np.int64]] = []
        for receiver_index, receiver in enumerate(self._receivers):
            points = sample_triangle_mesh(receiver.mesh, self._samples_per_receiver)
            sample_parts.append(points)
            receiver_indices.append(
                np.full(self._samples_per_receiver, receiver_index, dtype=np.int64)
            )
            sample_indices.append(np.arange(self._samples_per_receiver, dtype=np.int64))
        if sample_parts:
            self._sample_points = np.vstack(sample_parts)
            self._sample_receiver_index = np.concatenate(receiver_indices)
            self._sample_index = np.concatenate(sample_indices)
        else:
            self._sample_points = np.empty((0, 3), dtype=np.float64)
            self._sample_receiver_index = np.empty(0, dtype=np.int64)
            self._sample_index = np.empty(0, dtype=np.int64)

        occluders = tuple(item for item in shading if item.shadow_role is ShadowRole.OCCLUDER)
        self._ray_scene = MeshRayScene(
            tuple(RaySceneObject(item.id, item.mesh) for item in occluders)
        )
        self._diagnostics = NearObjectSceneDiagnostics(
            receiver_count=len(self._receivers),
            samples_per_receiver=self._samples_per_receiver,
            eligible_occluder_count=len(occluders),
            ignored_non_occluder_count=sum(
                item.shadow_role is ShadowRole.NON_OCCLUDER for item in shading
            ),
            ignored_unknown_count=sum(item.shadow_role is ShadowRole.UNKNOWN for item in shading),
            ray_primitive_count=self._ray_scene.primitive_count,
        )

    @property
    def receiver_ids(self) -> tuple[str, ...]:
        return tuple(receiver.id for receiver in self._receivers)

    @property
    def samples_per_receiver(self) -> int:
        return self._samples_per_receiver

    @property
    def diagnostics(self) -> NearObjectSceneDiagnostics:
        return self._diagnostics

    def calculate_visibility(
        self, *, apparent_solar_zenith_deg: float, solar_azimuth_deg: float
    ) -> NearObjectBeamVisibility:
        """Cast every precomputed receiver sample toward an above-horizon sun."""
        zenith = _angle(apparent_solar_zenith_deg, "apparent_solar_zenith_deg", 90.0, False)
        azimuth = _angle(solar_azimuth_deg, "solar_azimuth_deg", 360.0, False)
        direction = np.asarray(solar_direction_enu(zenith, azimuth), dtype=np.float64)
        directions = np.tile(direction, (len(self._sample_points), 1))
        hits = self._ray_scene.cast_first(self._sample_points, directions)
        visible = ~hits.hit
        weights = np.full(
            len(self._sample_points), 1.0 / self._samples_per_receiver, dtype=np.float64
        )
        sample_rows = {
            "receiver_id": [
                self._receivers[index].id for index in self._sample_receiver_index
            ],
            "sample_index": self._sample_index.copy(),
            "sample_east_m": self._sample_points[:, 0].copy(),
            "sample_north_m": self._sample_points[:, 1].copy(),
            "sample_up_m": self._sample_points[:, 2].copy(),
            "sample_weight_fraction": weights,
            "beam_visible": visible.copy(),
            "beam_shaded": hits.hit.copy(),
            "blocking_object_id": list(hits.object_id),
            "blocking_distance_m": hits.distance_m.copy(),
        }
        samples = pd.DataFrame(sample_rows, columns=_SAMPLE_COLUMNS)
        samples = _typed_samples(samples)
        receiver_rows: list[dict[str, object]] = []
        for receiver_index, receiver in enumerate(self._receivers):
            mask = self._sample_receiver_index == receiver_index
            shaded_count = int(np.count_nonzero(hits.hit[mask]))
            shaded_fraction = float(np.sum(weights[mask] * hits.hit[mask]))
            receiver_rows.append(
                {
                    "receiver_id": receiver.id,
                    "visible_fraction": 1.0 - shaded_fraction,
                    "shaded_fraction": shaded_fraction,
                    "sample_count": self._samples_per_receiver,
                    "shaded_sample_count": shaded_count,
                }
            )
        receivers = pd.DataFrame(receiver_rows, columns=_RECEIVER_COLUMNS)
        receivers = _typed_receivers(receivers)
        return NearObjectBeamVisibility(samples, receivers, zenith, azimuth)


def sample_triangle_mesh(
    mesh: TriangleMesh, samples_per_receiver: int
) -> npt.NDArray[np.float64]:
    """Return deterministic equal-weight, area-stratified surface samples."""
    if not isinstance(mesh, TriangleMesh):
        raise ValueError("mesh must be a canonical TriangleMesh")
    count = _positive_integer(samples_per_receiver, "samples_per_receiver")
    if len(mesh.faces) == 0:
        raise ValueError("receiver mesh must be non-empty")
    triangles = mesh.vertices_enu_m[mesh.faces]
    doubled_area_vectors = np.cross(
        triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    )
    areas = np.linalg.norm(doubled_area_vectors, axis=1) / 2.0
    if not np.isfinite(areas).all() or float(np.sum(areas)) <= 0.0:
        raise ValueError("receiver mesh must have positive finite surface area")
    cumulative = np.cumsum(areas) / np.sum(areas)
    strata = (np.arange(count, dtype=np.float64) + 0.5) / count
    triangle_indices = np.searchsorted(cumulative, strata, side="left")
    sequence_index = np.arange(count, dtype=np.float64) + 0.5
    u = np.mod(sequence_index * _GOLDEN_CONJUGATE, 1.0)
    v = np.mod(sequence_index * _SQRT2_CONJUGATE, 1.0)
    root_u = np.sqrt(u)
    barycentric = np.column_stack((1.0 - root_u, root_u * (1.0 - v), root_u * v))
    selected = triangles[triangle_indices]
    return np.asarray(np.einsum("ni,nij->nj", barycentric, selected), dtype=np.float64)


def calculate_near_object_direct_beam_shading(
    poa_direct_raw_wm2_by_receiver: pd.DataFrame,
    apparent_solar_zenith_deg: pd.Series,
    solar_azimuth_deg: pd.Series,
    *,
    scene: NearObjectBeamScene,
) -> pd.DataFrame:
    """Apply near-object visibility only to receiver-resolved raw direct POA."""
    if not isinstance(scene, NearObjectBeamScene):
        raise ValueError("scene must be a NearObjectBeamScene")
    raw, index, receiver_ids = _validated_timeseries_inputs(
        poa_direct_raw_wm2_by_receiver,
        apparent_solar_zenith_deg,
        solar_azimuth_deg,
        scene.receiver_ids,
    )
    zenith = _series_angles(apparent_solar_zenith_deg, "apparent_solar_zenith_deg", 180.0)
    azimuth = _series_angles(solar_azimuth_deg, "solar_azimuth_deg", 360.0, False)
    rows: list[dict[str, object]] = []
    for time_position in range(len(index)):
        visibility = None
        if zenith[time_position] < 90.0:
            visibility = scene.calculate_visibility(
                apparent_solar_zenith_deg=zenith[time_position],
                solar_azimuth_deg=azimuth[time_position],
            ).receivers
        for receiver_position, _receiver_id in enumerate(receiver_ids):
            raw_direct = raw[time_position, receiver_position]
            if visibility is None:
                row = _below_horizon_row(raw_direct, zenith[time_position], azimuth[time_position])
            else:
                row = _above_horizon_row(
                    raw_direct,
                    zenith[time_position],
                    azimuth[time_position],
                    visibility.iloc[receiver_position],
                )
            rows.append(row)
    multi_index = _receiver_time_index(index, receiver_ids)
    return _typed_timeseries(rows, multi_index)


def couple_sample_near_object_direct_beam(
    visibility: NearObjectBeamVisibility,
    poa_direct_raw_wm2_by_receiver: Mapping[str, float],
) -> pd.DataFrame:
    """Attach sample-level direct irradiance while preserving spatial visibility."""
    if not isinstance(visibility, NearObjectBeamVisibility):
        raise ValueError("visibility must be NearObjectBeamVisibility")
    expected = tuple(visibility.receivers["receiver_id"].tolist())
    if set(poa_direct_raw_wm2_by_receiver) != set(expected):
        raise ValueError("raw direct mapping must contain exactly the visibility receivers")
    raw_values = {
        receiver_id: _raw_value(value)
        for receiver_id, value in poa_direct_raw_wm2_by_receiver.items()
    }
    result = visibility.samples.copy(deep=True)
    raw = np.asarray([raw_values[item] for item in result["receiver_id"]], dtype=np.float64)
    visible = np.where(result["beam_visible"].to_numpy(dtype=bool), raw, 0.0)
    visible[np.isnan(raw)] = np.nan
    loss = raw - visible
    result["poa_direct_raw_wm2"] = raw
    result["poa_direct_near_object_visible_wm2"] = visible
    result["near_object_shading_loss_wm2"] = loss
    return result


def _validated_sequence(value: object, kind: type[_T], name: str) -> tuple[_T, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a sequence")
    result = tuple(value)
    if any(not isinstance(item, kind) for item in result):
        raise ValueError(f"{name} contains an invalid object")
    return result


def _require_unique_ids(ids: Iterable[str], label: str) -> None:
    values: tuple[str, ...] = tuple(ids)
    duplicates = sorted(item for item, count in Counter(values).items() if count > 1)
    if duplicates:
        raise ValueError(f"{label} IDs must be unique")


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < 1:
        raise ValueError(f"{name} must be an integer greater than or equal to 1")
    return int(value)


def _angle(value: object, name: str, upper: float, upper_closed: bool) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real angle")
    result = float(value)
    valid_upper = result <= upper if upper_closed else result < upper
    if not np.isfinite(result) or result < 0.0 or not valid_upper:
        raise ValueError(f"{name} is outside its supported range")
    return result


def _series_angles(
    series: pd.Series, name: str, upper: float, closed: bool = True
) -> npt.NDArray[np.float64]:
    return np.asarray(
        [_angle(value, name, upper, closed) for value in series.array], dtype=np.float64
    )


def _validated_timeseries_inputs(
    frame: pd.DataFrame,
    zenith: pd.Series,
    azimuth: pd.Series,
    scene_receiver_ids: tuple[str, ...],
) -> tuple[npt.NDArray[np.float64], pd.DatetimeIndex, list[str]]:
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("poa_direct_raw_wm2_by_receiver must be a pandas DataFrame")
    receiver_ids = list(frame.columns)
    if tuple(receiver_ids) != scene_receiver_ids:
        raise ValueError("raw direct receiver columns must exactly match scene receiver order")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("raw direct input must have a timezone-aware DatetimeIndex")
    if not frame.index.is_unique or frame.index.hasnans:
        raise ValueError("raw direct timestamps must be unique and contain no NaT")
    for value, name in ((zenith, "apparent_solar_zenith_deg"), (azimuth, "solar_azimuth_deg")):
        if not isinstance(value, pd.Series) or not value.index.equals(frame.index):
            raise ValueError(f"{name} must be a Series with the exact raw-direct index")
    raw = np.empty(frame.shape, dtype=np.float64)
    for row in range(frame.shape[0]):
        for column in range(frame.shape[1]):
            raw[row, column] = _raw_value(frame.iat[row, column])
    return raw, frame.index, receiver_ids


def _raw_value(value: object) -> float:
    if pd.isna(value):
        return np.nan
    if (
        isinstance(value, (bool, np.bool_))
        or not isinstance(value, Real)
        or not np.isfinite(float(value))
        or float(value) < 0.0
    ):
        raise ValueError("present raw direct values must be finite, real, and non-negative")
    return float(value)


def _above_horizon_row(
    raw: float, zenith: float, azimuth: float, visibility: pd.Series
) -> dict[str, object]:
    visible_fraction = float(visibility["visible_fraction"])
    shaded_fraction = float(visibility["shaded_fraction"])
    if np.isnan(raw):
        visible_direct = np.nan
        loss = np.nan
        resolved = False
        applied = False
        state = "geometry_resolved_irradiance_unresolved"
    else:
        visible_direct = raw * visible_fraction
        loss = raw - visible_direct
        resolved = True
        applied = bool(raw > 0.0 and shaded_fraction > 0.0)
        state = "resolved"
    return {
        "poa_direct_raw_wm2": raw,
        "apparent_solar_zenith_deg": zenith,
        "solar_azimuth_deg": azimuth,
        "near_object_beam_visible_fraction": visible_fraction,
        "near_object_beam_shaded_fraction": shaded_fraction,
        "poa_direct_near_object_visible_wm2": visible_direct,
        "near_object_shading_loss_wm2": loss,
        "sample_count": int(visibility["sample_count"]),
        "shaded_sample_count": int(visibility["shaded_sample_count"]),
        "near_object_visibility_resolved": True,
        "near_object_shading_resolved": resolved,
        "near_object_shading_applied": applied,
        "near_object_shading_state": state,
        "near_object_shading_model": MODEL_ID,
    }


def _below_horizon_row(raw: float, zenith: float, azimuth: float) -> dict[str, object]:
    if np.isnan(raw):
        visible = loss = np.nan
        resolved = False
        state = "no_above_horizon_direct_beam_irradiance_unresolved"
    elif raw == 0.0:
        visible = loss = 0.0
        resolved = True
        state = "no_above_horizon_direct_beam"
    else:
        visible = loss = np.nan
        resolved = False
        state = "below_horizon_positive_direct_inconsistent"
    return {
        "poa_direct_raw_wm2": raw,
        "apparent_solar_zenith_deg": zenith,
        "solar_azimuth_deg": azimuth,
        "near_object_beam_visible_fraction": np.nan,
        "near_object_beam_shaded_fraction": np.nan,
        "poa_direct_near_object_visible_wm2": visible,
        "near_object_shading_loss_wm2": loss,
        "sample_count": pd.NA,
        "shaded_sample_count": pd.NA,
        "near_object_visibility_resolved": False,
        "near_object_shading_resolved": resolved,
        "near_object_shading_applied": False,
        "near_object_shading_state": state,
        "near_object_shading_model": MODEL_ID,
    }


def _receiver_time_index(index: pd.DatetimeIndex, receiver_ids: list[str]) -> pd.MultiIndex:
    if index.empty:
        return pd.MultiIndex.from_arrays(
            [pd.DatetimeIndex([], tz=index.tz, name=index.name), pd.Index([], dtype=object)],
            names=[index.name, "receiver_id"],
        )
    return pd.MultiIndex.from_arrays(
        [index.repeat(len(receiver_ids)), receiver_ids * len(index)],
        names=[index.name, "receiver_id"],
    )


def _typed_timeseries(rows: list[dict[str, object]], index: pd.MultiIndex) -> pd.DataFrame:
    result = pd.DataFrame(rows, columns=_TIME_COLUMNS, index=index)
    for column in _TIME_COLUMNS[:7]:
        result[column] = result[column].astype("float64")
    for column in ("sample_count", "shaded_sample_count"):
        result[column] = result[column].astype("Int64")
    for column in (
        "near_object_visibility_resolved",
        "near_object_shading_resolved",
        "near_object_shading_applied",
    ):
        result[column] = result[column].astype("bool")
    for column in ("near_object_shading_state", "near_object_shading_model"):
        result[column] = result[column].astype("string")
    return result


def _typed_samples(frame: pd.DataFrame) -> pd.DataFrame:
    frame["receiver_id"] = frame["receiver_id"].astype("string")
    frame["sample_index"] = frame["sample_index"].astype("int64")
    for column in (
        "sample_east_m",
        "sample_north_m",
        "sample_up_m",
        "sample_weight_fraction",
        "blocking_distance_m",
    ):
        frame[column] = frame[column].astype("float64")
    frame["beam_visible"] = frame["beam_visible"].astype("bool")
    frame["beam_shaded"] = frame["beam_shaded"].astype("bool")
    frame["blocking_object_id"] = frame["blocking_object_id"].astype("object")
    return frame


def _typed_receivers(frame: pd.DataFrame) -> pd.DataFrame:
    frame["receiver_id"] = frame["receiver_id"].astype("string")
    frame["visible_fraction"] = frame["visible_fraction"].astype("float64")
    frame["shaded_fraction"] = frame["shaded_fraction"].astype("float64")
    frame["sample_count"] = frame["sample_count"].astype("int64")
    frame["shaded_sample_count"] = frame["shaded_sample_count"].astype("int64")
    return frame
