"""Terrain-horizon direct-beam visibility from canonical receiver centres.

Only supplied canonical :class:`TerrainSurface` geometry participates. A clear
result means clear relative to that supplied geometry, not proof that the full
geographic horizon is clear. Near objects, PV rows, IAM, and diffuse/rear-side
physics are intentionally outside this mechanism.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from numbers import Real
from typing import TypeVar

import numpy as np
import numpy.typing as npt
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.geometry import PVReceiver, TerrainSurface
from heliotelligence.physics.ray_backend import MeshRayScene, RaySceneObject
from heliotelligence.physics.shading import solar_direction_enu

MODEL_ID = "canonical_terrain_embree_horizon_v1"
COVERAGE_SCOPE = "supplied_canonical_terrain_only"

_VISIBILITY_COLUMNS = [
    "receiver_id",
    "receiver_east_m",
    "receiver_north_m",
    "receiver_up_m",
    "terrain_beam_visible",
    "terrain_beam_blocked",
    "terrain_horizon_beam_visible_factor",
    "blocking_terrain_id",
    "blocking_distance_m",
]
_TIME_COLUMNS = [
    "poa_direct_raw_wm2",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "terrain_horizon_beam_visible_factor",
    "poa_direct_after_terrain_horizon_wm2",
    "terrain_horizon_shading_loss_wm2",
    "blocking_terrain_id",
    "blocking_distance_m",
    "terrain_horizon_visibility_resolved",
    "terrain_horizon_shading_resolved",
    "terrain_horizon_shading_applied",
    "terrain_horizon_state",
    "terrain_horizon_model",
    "terrain_horizon_coverage_scope",
]
_T = TypeVar("_T")


@dataclass(frozen=True)
class TerrainHorizonSceneDiagnostics:
    """Bounded diagnostics that never serialize terrain geometry."""

    receiver_count: int
    terrain_surface_count: int
    nonempty_terrain_surface_count: int
    terrain_triangle_count: int
    coverage_scope: str = COVERAGE_SCOPE


@dataclass(frozen=True)
class TerrainHorizonVisibility:
    """One receiver-resolved above-horizon terrain visibility evaluation."""

    receivers: pd.DataFrame
    apparent_solar_zenith_deg: float
    solar_azimuth_deg: float


class TerrainHorizonScene:
    """Reusable receiver centres and terrain-only Embree scene.

    Tracker receivers are evaluated at the exact canonical centre supplied by
    the caller; this class performs no runtime tracking or backtracking.
    """

    def __init__(
        self,
        receivers: Sequence[PVReceiver],
        terrain_surfaces: Sequence[TerrainSurface],
    ) -> None:
        self._receivers = _validated_sequence(receivers, PVReceiver, "receivers")
        terrain = _validated_sequence(terrain_surfaces, TerrainSurface, "terrain_surfaces")
        _require_unique_ids((item.id for item in self._receivers), "receiver")
        _require_unique_ids((item.id for item in terrain), "terrain surface")
        if self._receivers:
            self._receiver_centres = np.asarray(
                [item.centre_enu_m for item in self._receivers], dtype=np.float64
            )
        else:
            self._receiver_centres = np.empty((0, 3), dtype=np.float64)
        self._ray_scene = MeshRayScene(
            tuple(RaySceneObject(item.id, item.mesh) for item in terrain)
        )
        self._diagnostics = TerrainHorizonSceneDiagnostics(
            receiver_count=len(self._receivers),
            terrain_surface_count=len(terrain),
            nonempty_terrain_surface_count=sum(len(item.mesh.faces) > 0 for item in terrain),
            terrain_triangle_count=sum(len(item.mesh.faces) for item in terrain),
        )

    @property
    def receiver_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self._receivers)

    @property
    def diagnostics(self) -> TerrainHorizonSceneDiagnostics:
        return self._diagnostics

    def calculate_visibility(
        self, *, apparent_solar_zenith_deg: float, solar_azimuth_deg: float
    ) -> TerrainHorizonVisibility:
        """Evaluate binary terrain visibility from each canonical receiver centre."""
        zenith = _angle(apparent_solar_zenith_deg, "apparent_solar_zenith_deg", 90.0)
        azimuth = _angle(solar_azimuth_deg, "solar_azimuth_deg", 360.0)
        direction = np.asarray(solar_direction_enu(zenith, azimuth), dtype=np.float64)
        directions = np.tile(direction, (len(self._receiver_centres), 1))
        hits = self._ray_scene.cast_first(self._receiver_centres, directions)
        visible = ~hits.hit
        frame = pd.DataFrame(
            {
                "receiver_id": [item.id for item in self._receivers],
                "receiver_east_m": self._receiver_centres[:, 0].copy(),
                "receiver_north_m": self._receiver_centres[:, 1].copy(),
                "receiver_up_m": self._receiver_centres[:, 2].copy(),
                "terrain_beam_visible": visible.copy(),
                "terrain_beam_blocked": hits.hit.copy(),
                "terrain_horizon_beam_visible_factor": visible.astype(np.float64),
                "blocking_terrain_id": list(hits.object_id),
                "blocking_distance_m": hits.distance_m.copy(),
            },
            columns=_VISIBILITY_COLUMNS,
        )
        return TerrainHorizonVisibility(_typed_visibility(frame), zenith, azimuth)


def calculate_terrain_horizon_direct_beam_shading(
    poa_direct_raw_wm2_by_receiver: pd.DataFrame,
    apparent_solar_zenith_deg: pd.Series,
    solar_azimuth_deg: pd.Series,
    *,
    scene: TerrainHorizonScene,
) -> pd.DataFrame:
    """Apply supplied-terrain horizon visibility only to upstream raw direct POA."""
    if not isinstance(scene, TerrainHorizonScene):
        raise ValueError("scene must be a TerrainHorizonScene")
    raw, index, receiver_ids = _validated_timeseries_inputs(
        poa_direct_raw_wm2_by_receiver,
        apparent_solar_zenith_deg,
        solar_azimuth_deg,
        scene.receiver_ids,
    )
    zenith = _series_angles(
        apparent_solar_zenith_deg, "apparent_solar_zenith_deg", 180.0, upper_closed=True
    )
    azimuth = _series_angles(solar_azimuth_deg, "solar_azimuth_deg", 360.0)
    rows: list[dict[str, object]] = []
    for time_position in range(len(index)):
        visibility: pd.DataFrame | None = None
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
    return _typed_timeseries(rows, _receiver_time_index(index, receiver_ids))


def _validated_sequence(value: object, kind: type[_T], name: str) -> tuple[_T, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a sequence")
    result = tuple(value)
    if any(not isinstance(item, kind) for item in result):
        raise ValueError(f"{name} contains an invalid object")
    return result


def _require_unique_ids(ids: Iterable[str], label: str) -> None:
    values = tuple(ids)
    if any(count > 1 for count in Counter(values).values()):
        raise ValueError(f"{label} IDs must be unique")


def _angle(value: object, name: str, upper: float, *, upper_closed: bool = False) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real angle")
    result = float(value)
    valid_upper = result <= upper if upper_closed else result < upper
    if not np.isfinite(result) or result < 0.0 or not valid_upper:
        raise ValueError(f"{name} is outside its supported range")
    return result


def _series_angles(
    series: pd.Series, name: str, upper: float, *, upper_closed: bool = False
) -> npt.NDArray[np.float64]:
    if not isinstance(series, pd.Series):
        raise ValueError(f"{name} must be a pandas Series")
    return np.asarray(
        [_angle(value, name, upper, upper_closed=upper_closed) for value in series.array],
        dtype=np.float64,
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
    factor = float(visibility["terrain_horizon_beam_visible_factor"])
    if np.isnan(raw):
        after = loss = np.nan
        resolved = applied = False
        state = "geometry_resolved_irradiance_unresolved"
    else:
        after = raw * factor
        loss = raw - after
        resolved = True
        applied = bool(raw > 0.0 and factor == 0.0)
        state = "resolved"
    return {
        "poa_direct_raw_wm2": raw,
        "apparent_solar_zenith_deg": zenith,
        "solar_azimuth_deg": azimuth,
        "terrain_horizon_beam_visible_factor": factor,
        "poa_direct_after_terrain_horizon_wm2": after,
        "terrain_horizon_shading_loss_wm2": loss,
        "blocking_terrain_id": visibility["blocking_terrain_id"],
        "blocking_distance_m": float(visibility["blocking_distance_m"]),
        "terrain_horizon_visibility_resolved": True,
        "terrain_horizon_shading_resolved": resolved,
        "terrain_horizon_shading_applied": applied,
        "terrain_horizon_state": state,
        "terrain_horizon_model": MODEL_ID,
        "terrain_horizon_coverage_scope": COVERAGE_SCOPE,
    }


def _below_horizon_row(raw: float, zenith: float, azimuth: float) -> dict[str, object]:
    if np.isnan(raw):
        after = loss = np.nan
        resolved = False
        state = "no_above_horizon_direct_beam_irradiance_unresolved"
    elif raw == 0.0:
        after = loss = 0.0
        resolved = True
        state = "no_above_horizon_direct_beam"
    else:
        after = loss = np.nan
        resolved = False
        state = "below_horizon_positive_direct_inconsistent"
    return {
        "poa_direct_raw_wm2": raw,
        "apparent_solar_zenith_deg": zenith,
        "solar_azimuth_deg": azimuth,
        "terrain_horizon_beam_visible_factor": np.nan,
        "poa_direct_after_terrain_horizon_wm2": after,
        "terrain_horizon_shading_loss_wm2": loss,
        "blocking_terrain_id": None,
        "blocking_distance_m": np.inf,
        "terrain_horizon_visibility_resolved": False,
        "terrain_horizon_shading_resolved": resolved,
        "terrain_horizon_shading_applied": False,
        "terrain_horizon_state": state,
        "terrain_horizon_model": MODEL_ID,
        "terrain_horizon_coverage_scope": COVERAGE_SCOPE,
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


def _typed_visibility(frame: pd.DataFrame) -> pd.DataFrame:
    frame["receiver_id"] = frame["receiver_id"].astype("string")
    for column in (
        "receiver_east_m",
        "receiver_north_m",
        "receiver_up_m",
        "terrain_horizon_beam_visible_factor",
        "blocking_distance_m",
    ):
        frame[column] = frame[column].astype("float64")
    frame["terrain_beam_visible"] = frame["terrain_beam_visible"].astype("bool")
    frame["terrain_beam_blocked"] = frame["terrain_beam_blocked"].astype("bool")
    frame["blocking_terrain_id"] = frame["blocking_terrain_id"].astype("object")
    return frame


def _typed_timeseries(rows: list[dict[str, object]], index: pd.MultiIndex) -> pd.DataFrame:
    result = pd.DataFrame(rows, columns=_TIME_COLUMNS, index=index)
    for column in _TIME_COLUMNS[:6] + ["blocking_distance_m"]:
        result[column] = result[column].astype("float64")
    result["blocking_terrain_id"] = result["blocking_terrain_id"].astype("object")
    for column in (
        "terrain_horizon_visibility_resolved",
        "terrain_horizon_shading_resolved",
        "terrain_horizon_shading_applied",
    ):
        result[column] = result[column].astype("bool")
    for column in (
        "terrain_horizon_state",
        "terrain_horizon_model",
        "terrain_horizon_coverage_scope",
    ):
        result[column] = result[column].astype("string")
    return result
