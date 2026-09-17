"""Analytical fixed inter-row direct-beam shading over explicit row topology.

This module implements the one-dimensional parallel-row mechanism only. S6B
v1 requires equal collector width within every explicit blocking pair because
pvlib's analytical model accepts one collector-width parameter. It does not
infer rows from canonical geometry and applies no terrain, near-object, tracker,
diffuse, rear-side, IAM, or electrical model.

The positive cross-axis side is 90 degrees clockwise from ``axis_azimuth_deg``
when projected horizontally. A positive projected solar zenith therefore makes
the positive-side row the blocker of the negative-side row; a negative value
reverses those roles.
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
from pvlib import shading as _pvlib_shading  # type: ignore[import-untyped]

from heliotelligence.geometry import PVReceiver, ReceiverKind

MODEL_ID = "pvlib_shaded_fraction1d_fixed_inter_row_v1"
_BOUND_TOLERANCE = 1e-12
_SIDE_TOLERANCE_DEG = 1e-12
_PAIR_WIDTH_RTOL = 1e-12
_PAIR_WIDTH_ATOL_M = 1e-12
_T = TypeVar("_T")

_VISIBILITY_COLUMNS = [
    "receiver_id",
    "fixed_row_array_id",
    "fixed_row_id",
    "row_rotation_deg",
    "collector_width_m",
    "projected_solar_zenith_deg",
    "fixed_inter_row_beam_visible_fraction",
    "fixed_inter_row_beam_shaded_fraction",
    "shading_row_id",
    "shading_pitch_m",
    "cross_axis_slope_deg",
    "sunward_side",
    "fixed_inter_row_model",
]
_TIME_COLUMNS = [
    "poa_direct_raw_wm2",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "projected_solar_zenith_deg",
    "fixed_inter_row_beam_visible_fraction",
    "fixed_inter_row_beam_shaded_fraction",
    "poa_direct_after_fixed_inter_row_wm2",
    "fixed_inter_row_shading_loss_wm2",
    "shading_row_id",
    "shading_pitch_m",
    "cross_axis_slope_deg",
    "sunward_side",
    "fixed_row_id",
    "fixed_row_array_id",
    "fixed_inter_row_visibility_resolved",
    "fixed_inter_row_shading_resolved",
    "fixed_inter_row_shading_applied",
    "fixed_inter_row_state",
    "fixed_inter_row_model",
]


@dataclass(frozen=True)
class FixedRowDefinition:
    """One validated physical row of canonical fixed-table receivers."""

    row_id: str
    receiver_ids: tuple[str, ...]
    row_rotation_deg: float
    collector_width_m: float

    def __post_init__(self) -> None:
        _required_text(self.row_id, "row_id")
        if not isinstance(self.receiver_ids, tuple) or not self.receiver_ids:
            raise ValueError("receiver_ids must be a non-empty tuple")
        for receiver_id in self.receiver_ids:
            _required_text(receiver_id, "receiver_id")
        _require_unique(self.receiver_ids, "receiver IDs within a row")
        object.__setattr__(
            self,
            "row_rotation_deg",
            _bounded_real(self.row_rotation_deg, "row_rotation_deg", -180.0, 180.0),
        )
        object.__setattr__(
            self,
            "collector_width_m",
            _positive_real(self.collector_width_m, "collector_width_m"),
        )


@dataclass(frozen=True)
class FixedRowBlockingPair:
    """One explicit negative-side to positive-side row relationship."""

    negative_side_row_id: str
    positive_side_row_id: str
    pitch_m: float
    cross_axis_slope_deg: float = 0.0

    def __post_init__(self) -> None:
        _required_text(self.negative_side_row_id, "negative_side_row_id")
        _required_text(self.positive_side_row_id, "positive_side_row_id")
        if self.negative_side_row_id == self.positive_side_row_id:
            raise ValueError("a blocking pair must contain two different rows")
        object.__setattr__(self, "pitch_m", _positive_real(self.pitch_m, "pitch_m"))
        object.__setattr__(
            self,
            "cross_axis_slope_deg",
            _open_symmetric_angle(self.cross_axis_slope_deg, "cross_axis_slope_deg"),
        )


@dataclass(frozen=True)
class FixedRowArrayDefinition:
    """One independent parallel fixed-row array with explicit topology."""

    array_id: str
    axis_azimuth_deg: float
    axis_tilt_deg: float
    rows: tuple[FixedRowDefinition, ...]
    blocking_pairs: tuple[FixedRowBlockingPair, ...]
    surface_to_axis_offset_m: float = 0.0

    def __post_init__(self) -> None:
        _required_text(self.array_id, "array_id")
        object.__setattr__(
            self,
            "axis_azimuth_deg",
            _bounded_real(
                self.axis_azimuth_deg, "axis_azimuth_deg", 0.0, 360.0, upper_closed=False
            ),
        )
        object.__setattr__(
            self,
            "axis_tilt_deg",
            _bounded_real(self.axis_tilt_deg, "axis_tilt_deg", 0.0, 90.0),
        )
        object.__setattr__(
            self,
            "surface_to_axis_offset_m",
            _nonnegative_real(self.surface_to_axis_offset_m, "surface_to_axis_offset_m"),
        )
        if not isinstance(self.rows, tuple) or not self.rows:
            raise ValueError("rows must be a non-empty tuple")
        if any(not isinstance(row, FixedRowDefinition) for row in self.rows):
            raise ValueError("rows must contain only FixedRowDefinition values")
        if not isinstance(self.blocking_pairs, tuple) or any(
            not isinstance(pair, FixedRowBlockingPair) for pair in self.blocking_pairs
        ):
            raise ValueError("blocking_pairs must be a tuple of FixedRowBlockingPair values")
        row_ids = tuple(row.row_id for row in self.rows)
        _require_unique(row_ids, "row IDs within an array")
        row_id_set = set(row_ids)
        rows_by_id = {row.row_id: row for row in self.rows}
        pair_keys: list[tuple[str, str]] = []
        for pair in self.blocking_pairs:
            if (
                pair.negative_side_row_id not in row_id_set
                or pair.positive_side_row_id not in row_id_set
            ):
                raise ValueError("blocking pairs must refer to rows in their array")
            negative_width = rows_by_id[pair.negative_side_row_id].collector_width_m
            positive_width = rows_by_id[pair.positive_side_row_id].collector_width_m
            if not np.isclose(
                negative_width,
                positive_width,
                rtol=_PAIR_WIDTH_RTOL,
                atol=_PAIR_WIDTH_ATOL_M,
            ):
                raise ValueError("fixed-row blocking pairs require equal collector widths")
            pair_keys.append((pair.negative_side_row_id, pair.positive_side_row_id))
        _require_unique(pair_keys, "blocking pairs")
        _require_acyclic_row_order(row_ids, pair_keys)


@dataclass(frozen=True)
class FixedInterRowVisibility:
    """Receiver-resolved fixed-row visibility for one solar state."""

    receivers: pd.DataFrame
    apparent_solar_zenith_deg: float
    solar_azimuth_deg: float


@dataclass(frozen=True)
class _RowResult:
    projected: npt.NDArray[np.float64]
    shaded: npt.NDArray[np.float64]
    shading_row: npt.NDArray[np.object_]
    pitch: npt.NDArray[np.float64]
    slope: npt.NDArray[np.float64]
    side: npt.NDArray[np.object_]


class FixedInterRowScene:
    """Prevalidated explicit fixed-row topology and vectorized analytical model."""

    def __init__(
        self,
        receivers: Sequence[PVReceiver],
        arrays: Sequence[FixedRowArrayDefinition],
    ) -> None:
        self._receivers = _validated_sequence(receivers, PVReceiver, "receivers")
        array_values = _validated_sequence(arrays, FixedRowArrayDefinition, "arrays")
        receiver_ids = tuple(receiver.id for receiver in self._receivers)
        _require_unique(receiver_ids, "receiver IDs")
        if any(
            receiver.receiver_kind is not ReceiverKind.FIXED_TABLE for receiver in self._receivers
        ):
            raise ValueError("S6B accepts only FIXED_TABLE receivers")
        _require_unique((array.array_id for array in array_values), "array IDs")
        all_rows = tuple(row for array in array_values for row in array.rows)
        _require_unique((row.row_id for row in all_rows), "row IDs across arrays")
        assignments = tuple(receiver_id for row in all_rows for receiver_id in row.receiver_ids)
        _require_unique(assignments, "receiver assignments")
        if set(assignments) != set(receiver_ids):
            raise ValueError("every supplied receiver must be assigned to exactly one row")
        if not set(assignments).issubset(receiver_ids):
            raise ValueError("row definitions contain unknown receiver IDs")

        self._arrays = array_values
        self._rows = {row.row_id: row for row in all_rows}
        self._row_array = {row.row_id: array for array in array_values for row in array.rows}
        self._receiver_row = {
            receiver_id: row for row in all_rows for receiver_id in row.receiver_ids
        }

    @property
    def receiver_ids(self) -> tuple[str, ...]:
        return tuple(receiver.id for receiver in self._receivers)

    def calculate_visibility(
        self, *, apparent_solar_zenith_deg: float, solar_azimuth_deg: float
    ) -> FixedInterRowVisibility:
        """Evaluate row fractions for one above-horizon solar state."""
        zenith = _angle(apparent_solar_zenith_deg, "apparent_solar_zenith_deg", 90.0)
        azimuth = _angle(solar_azimuth_deg, "solar_azimuth_deg", 360.0)
        results = self._evaluate_rows(
            np.asarray([zenith], dtype=np.float64),
            np.asarray([azimuth], dtype=np.float64),
        )
        rows: list[dict[str, object]] = []
        for receiver in self._receivers:
            row = self._receiver_row[receiver.id]
            array = self._row_array[row.row_id]
            result = results[row.row_id]
            shaded = float(result.shaded[0])
            rows.append(
                {
                    "receiver_id": receiver.id,
                    "fixed_row_array_id": array.array_id,
                    "fixed_row_id": row.row_id,
                    "row_rotation_deg": row.row_rotation_deg,
                    "collector_width_m": row.collector_width_m,
                    "projected_solar_zenith_deg": float(result.projected[0]),
                    "fixed_inter_row_beam_visible_fraction": 1.0 - shaded,
                    "fixed_inter_row_beam_shaded_fraction": shaded,
                    "shading_row_id": result.shading_row[0],
                    "shading_pitch_m": float(result.pitch[0]),
                    "cross_axis_slope_deg": float(result.slope[0]),
                    "sunward_side": result.side[0],
                    "fixed_inter_row_model": MODEL_ID,
                }
            )
        return FixedInterRowVisibility(_typed_visibility(rows), zenith, azimuth)

    def _evaluate_rows(
        self,
        zenith: npt.NDArray[np.float64],
        azimuth: npt.NDArray[np.float64],
    ) -> dict[str, _RowResult]:
        """Vectorize pvlib over timestamps, looping only arrays and explicit pairs."""
        count = len(zenith)
        output: dict[str, _RowResult] = {}
        for array in self._arrays:
            projected = np.asarray(
                _pvlib_shading.projected_solar_zenith_angle(
                    zenith, azimuth, array.axis_tilt_deg, array.axis_azimuth_deg
                ),
                dtype=np.float64,
            )
            side = np.full(count, "axis_plane", dtype=object)
            side[projected > _SIDE_TOLERANCE_DEG] = "positive"
            side[projected < -_SIDE_TOLERANCE_DEG] = "negative"
            for row in array.rows:
                output[row.row_id] = _RowResult(
                    projected.copy(),
                    np.zeros(count, dtype=np.float64),
                    np.full(count, None, dtype=object),
                    np.full(count, np.nan, dtype=np.float64),
                    np.full(count, np.nan, dtype=np.float64),
                    side.copy(),
                )

            for pair in sorted(
                array.blocking_pairs,
                key=lambda item: (
                    item.negative_side_row_id,
                    item.positive_side_row_id,
                    item.pitch_m,
                    item.cross_axis_slope_deg,
                ),
            ):
                positive = projected > _SIDE_TOLERANCE_DEG
                negative = projected < -_SIDE_TOLERANCE_DEG
                self._apply_pair(
                    output,
                    array,
                    pair,
                    target_row_id=pair.negative_side_row_id,
                    blocker_row_id=pair.positive_side_row_id,
                    active=positive,
                    zenith=zenith,
                    azimuth=azimuth,
                )
                self._apply_pair(
                    output,
                    array,
                    pair,
                    target_row_id=pair.positive_side_row_id,
                    blocker_row_id=pair.negative_side_row_id,
                    active=negative,
                    zenith=zenith,
                    azimuth=azimuth,
                )
        return output

    def _apply_pair(
        self,
        output: dict[str, _RowResult],
        array: FixedRowArrayDefinition,
        pair: FixedRowBlockingPair,
        *,
        target_row_id: str,
        blocker_row_id: str,
        active: npt.NDArray[np.bool_],
        zenith: npt.NDArray[np.float64],
        azimuth: npt.NDArray[np.float64],
    ) -> None:
        if not np.any(active):
            return
        target = self._rows[target_row_id]
        blocker = self._rows[blocker_row_id]
        candidate = np.zeros(len(zenith), dtype=np.float64)
        raw = np.asarray(
            _call_shaded_fraction1d(
                solar_zenith=zenith[active],
                solar_azimuth=azimuth[active],
                axis_azimuth=array.axis_azimuth_deg,
                shaded_row_rotation=target.row_rotation_deg,
                shading_row_rotation=blocker.row_rotation_deg,
                collector_width=target.collector_width_m,
                pitch=pair.pitch_m,
                axis_tilt=array.axis_tilt_deg,
                surface_to_axis_offset=array.surface_to_axis_offset_m,
                cross_axis_slope=pair.cross_axis_slope_deg,
            ),
            dtype=np.float64,
        )
        candidate[active] = _validated_fraction(raw)
        current = output[target_row_id]
        greater = candidate > current.shaded + _BOUND_TOLERANCE
        equal = active & np.isclose(candidate, current.shaded, rtol=0.0, atol=_BOUND_TOLERANCE)
        tie = np.asarray(
            [
                equal[index]
                and candidate[index] > 0.0
                and (
                    current.shading_row[index] is None
                    or blocker_row_id < str(current.shading_row[index])
                )
                for index in range(len(candidate))
            ],
            dtype=np.bool_,
        )
        selected = active & (greater | tie)
        current.shaded[selected] = candidate[selected]
        current.shading_row[selected] = blocker_row_id
        current.pitch[selected] = pair.pitch_m
        current.slope[selected] = pair.cross_axis_slope_deg


def calculate_fixed_inter_row_direct_beam_shading(
    poa_direct_raw_wm2_by_receiver: pd.DataFrame,
    apparent_solar_zenith_deg: pd.Series,
    solar_azimuth_deg: pd.Series,
    *,
    scene: FixedInterRowScene,
) -> pd.DataFrame:
    """Apply fixed inter-row visibility only to receiver-resolved raw direct POA."""
    if not isinstance(scene, FixedInterRowScene):
        raise ValueError("scene must be a FixedInterRowScene")
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
    above = zenith < 90.0
    geometry: dict[str, _RowResult] = {}
    if np.any(above):
        geometry = scene._evaluate_rows(zenith[above], azimuth[above])
    above_position = np.full(len(index), -1, dtype=np.int64)
    above_position[above] = np.arange(np.count_nonzero(above), dtype=np.int64)
    return _vectorized_timeseries_result(
        raw,
        zenith,
        azimuth,
        above,
        above_position,
        geometry,
        scene,
        index,
        receiver_ids,
    )


def _vectorized_timeseries_result(
    raw: npt.NDArray[np.float64],
    zenith: npt.NDArray[np.float64],
    azimuth: npt.NDArray[np.float64],
    above: npt.NDArray[np.bool_],
    above_position: npt.NDArray[np.int64],
    geometry: dict[str, _RowResult],
    scene: FixedInterRowScene,
    index: pd.DatetimeIndex,
    receiver_ids: list[str],
) -> pd.DataFrame:
    """Broadcast vectorized row states to receivers without timestamp loops."""
    time_count, receiver_count = raw.shape
    shape = (time_count, receiver_count)
    projected = np.full(shape, np.nan, dtype=np.float64)
    shaded = np.full(shape, np.nan, dtype=np.float64)
    visible = np.full(shape, np.nan, dtype=np.float64)
    pitch = np.full(shape, np.nan, dtype=np.float64)
    slope = np.full(shape, np.nan, dtype=np.float64)
    shading_row = np.full(shape, None, dtype=object)
    side = np.full(shape, None, dtype=object)
    row_ids = np.full(shape, None, dtype=object)
    array_ids = np.full(shape, None, dtype=object)
    active_positions = above_position[above]
    for receiver_position, receiver_id in enumerate(receiver_ids):
        row = scene._receiver_row[receiver_id]
        array = scene._row_array[row.row_id]
        result = geometry.get(row.row_id)
        if result is not None:
            projected[above, receiver_position] = result.projected[active_positions]
            shaded[above, receiver_position] = result.shaded[active_positions]
            visible[above, receiver_position] = 1.0 - result.shaded[active_positions]
            pitch[above, receiver_position] = result.pitch[active_positions]
            slope[above, receiver_position] = result.slope[active_positions]
            shading_row[above, receiver_position] = result.shading_row[active_positions]
            side[above, receiver_position] = result.side[active_positions]
            row_ids[above, receiver_position] = row.row_id
            array_ids[above, receiver_position] = array.array_id

    after = np.full(shape, np.nan, dtype=np.float64)
    loss = np.full(shape, np.nan, dtype=np.float64)
    visibility_resolved = np.broadcast_to(above[:, None], shape).copy()
    shading_resolved = visibility_resolved & ~np.isnan(raw)
    after[shading_resolved] = raw[shading_resolved] * visible[shading_resolved]
    loss[shading_resolved] = raw[shading_resolved] - after[shading_resolved]
    applied = shading_resolved & (raw > 0.0) & (shaded > 0.0)
    state = np.full(shape, "below_horizon_positive_direct_inconsistent", dtype=object)
    state[above[:, None] & np.isnan(raw)] = "geometry_resolved_irradiance_unresolved"
    state[shading_resolved] = "resolved"
    below_zero = ~above[:, None] & (raw == 0.0)
    below_nan = ~above[:, None] & np.isnan(raw)
    after[below_zero] = 0.0
    loss[below_zero] = 0.0
    shading_resolved[below_zero] = True
    state[below_zero] = "no_above_horizon_direct_beam"
    state[below_nan] = "no_above_horizon_direct_beam_irradiance_unresolved"

    columns: dict[str, object] = {
        "poa_direct_raw_wm2": raw.ravel(),
        "apparent_solar_zenith_deg": np.repeat(zenith, receiver_count),
        "solar_azimuth_deg": np.repeat(azimuth, receiver_count),
        "projected_solar_zenith_deg": projected.ravel(),
        "fixed_inter_row_beam_visible_fraction": visible.ravel(),
        "fixed_inter_row_beam_shaded_fraction": shaded.ravel(),
        "poa_direct_after_fixed_inter_row_wm2": after.ravel(),
        "fixed_inter_row_shading_loss_wm2": loss.ravel(),
        "shading_row_id": shading_row.ravel(),
        "shading_pitch_m": pitch.ravel(),
        "cross_axis_slope_deg": slope.ravel(),
        "sunward_side": side.ravel(),
        "fixed_row_id": row_ids.ravel(),
        "fixed_row_array_id": array_ids.ravel(),
        "fixed_inter_row_visibility_resolved": visibility_resolved.ravel(),
        "fixed_inter_row_shading_resolved": shading_resolved.ravel(),
        "fixed_inter_row_shading_applied": applied.ravel(),
        "fixed_inter_row_state": state.ravel(),
        "fixed_inter_row_model": np.full(raw.size, MODEL_ID, dtype=object),
    }
    return _typed_timeseries(columns, _receiver_time_index(index, receiver_ids))


def _validated_fraction(value: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    if (
        not np.isfinite(value).all()
        or np.any(value < -_BOUND_TOLERANCE)
        or np.any(value > 1.0 + _BOUND_TOLERANCE)
    ):
        raise RuntimeError("pvlib returned an invalid fixed inter-row shaded fraction")
    return np.clip(value, 0.0, 1.0)


def _call_shaded_fraction1d(**kwargs: object) -> object:
    """Narrow test seam around the selected pvlib analytical implementation."""
    return _pvlib_shading.shaded_fraction1d(**kwargs)


def _required_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _bounded_real(
    value: object,
    name: str,
    lower: float,
    upper: float,
    *,
    upper_closed: bool = True,
) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real value")
    result = float(value)
    valid_upper = result <= upper if upper_closed else result < upper
    if not np.isfinite(result) or result < lower or not valid_upper:
        raise ValueError(f"{name} is outside its supported range")
    return result


def _positive_real(value: object, name: str) -> float:
    result = _bounded_real(value, name, 0.0, np.inf)
    if result == 0.0:
        raise ValueError(f"{name} must be positive")
    return result


def _nonnegative_real(value: object, name: str) -> float:
    return _bounded_real(value, name, 0.0, np.inf)


def _open_symmetric_angle(value: object, name: str) -> float:
    result = _bounded_real(value, name, -90.0, 90.0, upper_closed=False)
    if result == -90.0:
        raise ValueError(f"{name} is outside its supported range")
    return result


def _require_unique(values: Iterable[object], label: str) -> None:
    items = tuple(values)
    if any(count > 1 for count in Counter(items).values()):
        raise ValueError(f"{label} must be unique")


def _require_acyclic_row_order(row_ids: tuple[str, ...], pair_keys: list[tuple[str, str]]) -> None:
    """Require a consistent negative-to-positive cross-axis partial order."""
    outgoing = {row_id: set[str]() for row_id in row_ids}
    indegree = {row_id: 0 for row_id in row_ids}
    for negative_row_id, positive_row_id in pair_keys:
        outgoing[negative_row_id].add(positive_row_id)
        indegree[positive_row_id] += 1
    ready = sorted(row_id for row_id, count in indegree.items() if count == 0)
    visited = 0
    while ready:
        row_id = ready.pop(0)
        visited += 1
        for positive_row_id in sorted(outgoing[row_id]):
            indegree[positive_row_id] -= 1
            if indegree[positive_row_id] == 0:
                ready.append(positive_row_id)
                ready.sort()
    if visited != len(row_ids):
        raise ValueError("fixed-row blocking-pair topology must be acyclic")


def _validated_sequence(value: object, kind: type[_T], name: str) -> tuple[_T, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a sequence")
    result = tuple(value)
    if any(not isinstance(item, kind) for item in result):
        raise ValueError(f"{name} contains an invalid object")
    return result


def _angle(value: object, name: str, upper: float) -> float:
    return _bounded_real(value, name, 0.0, upper, upper_closed=False)


def _series_angles(
    series: pd.Series, name: str, upper: float, *, upper_closed: bool = False
) -> npt.NDArray[np.float64]:
    if not isinstance(series, pd.Series):
        raise ValueError(f"{name} must be a pandas Series")
    return np.asarray(
        [
            _bounded_real(value, name, 0.0, upper, upper_closed=upper_closed)
            for value in series.array
        ],
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


def _typed_visibility(rows: list[dict[str, object]]) -> pd.DataFrame:
    result = pd.DataFrame(rows, columns=_VISIBILITY_COLUMNS)
    for column in (
        "row_rotation_deg",
        "collector_width_m",
        "projected_solar_zenith_deg",
        "fixed_inter_row_beam_visible_fraction",
        "fixed_inter_row_beam_shaded_fraction",
        "shading_pitch_m",
        "cross_axis_slope_deg",
    ):
        result[column] = result[column].astype("float64")
    for column in (
        "receiver_id",
        "fixed_row_array_id",
        "fixed_row_id",
        "sunward_side",
        "fixed_inter_row_model",
    ):
        result[column] = result[column].astype("string")
    result["shading_row_id"] = pd.Series(
        [None if pd.isna(value) else value for value in result["shading_row_id"]],
        dtype=object,
    )
    return result


def _typed_timeseries(columns: dict[str, object], index: pd.MultiIndex) -> pd.DataFrame:
    result = pd.DataFrame(columns, columns=_TIME_COLUMNS, index=index)
    for column in _TIME_COLUMNS[:8] + ["shading_pitch_m", "cross_axis_slope_deg"]:
        result[column] = result[column].astype("float64")
    result["shading_row_id"] = pd.Series(
        [None if pd.isna(value) else value for value in result["shading_row_id"]],
        index=index,
        dtype=object,
    )
    for column in (
        "sunward_side",
        "fixed_row_id",
        "fixed_row_array_id",
        "fixed_inter_row_state",
        "fixed_inter_row_model",
    ):
        result[column] = result[column].astype("string")
    for column in (
        "fixed_inter_row_visibility_resolved",
        "fixed_inter_row_shading_resolved",
        "fixed_inter_row_shading_applied",
    ):
        result[column] = result[column].astype("bool")
    return result
