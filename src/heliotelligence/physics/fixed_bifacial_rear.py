"""Raw rear-plane irradiance for regular fixed rows using pvlib infinite sheds.

This S6E v1 primitive is limited to interior-average, parallel, evenly spaced
fixed rows over level ground. It returns physical rear irradiance before IAM,
bifaciality, effective-irradiance composition, or electrical conversion.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Literal, TypeVar

import numpy as np
import numpy.typing as npt
import pandas as pd  # type: ignore[import-untyped]
from pvlib import irradiance as _pvlib_irradiance  # type: ignore[import-untyped]
from pvlib.bifacial import infinite_sheds as _infinite_sheds  # type: ignore[import-untyped]
from pvlib.tracking import calc_surface_orientation  # type: ignore[import-untyped]

from heliotelligence.geometry import PVReceiver, ReceiverKind
from heliotelligence.physics.fixed_inter_row_shading import FixedRowArrayDefinition

MODEL_ID = "pvlib_infinite_sheds_fixed_rear_v1"
COVERAGE_SCOPE = "regular_parallel_fixed_rows_level_ground_infinite_sheds_interior"
RearDiffuseModel = Literal["isotropic", "haydavies"]
_GEOMETRY_RTOL = 1e-12
_GEOMETRY_ATOL = 1e-12
_NORMAL_ATOL = 1e-10
_CLOSURE_ATOL = 1e-9
_T = TypeVar("_T")

_COLUMNS = [
    "ghi_wm2",
    "dhi_wm2",
    "dni_wm2",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "dni_extra_wm2",
    "fixed_row_array_id",
    "row_rotation_deg",
    "axis_azimuth_deg",
    "surface_tilt_deg",
    "surface_azimuth_deg",
    "rear_surface_tilt_deg",
    "rear_surface_azimuth_deg",
    "collector_width_m",
    "pitch_m",
    "gcr",
    "row_center_height_m",
    "albedo",
    "poa_rear_direct_raw_wm2",
    "poa_rear_circumsolar_diffuse_raw_wm2",
    "poa_rear_sky_diffuse_raw_wm2",
    "poa_rear_ground_diffuse_raw_wm2",
    "poa_rear_diffuse_raw_wm2",
    "poa_rear_global_raw_wm2",
    "rear_direct_shaded_fraction",
    "rear_irradiance_resolved",
    "rear_irradiance_state",
    "rear_irradiance_model",
    "rear_diffuse_model",
    "rear_coverage_scope",
]


@dataclass(frozen=True)
class FixedBifacialRearParameters:
    """S6E-specific level-ground parameters for one explicit fixed-row array."""

    array_id: str
    row_center_height_m: float
    albedo: float

    def __post_init__(self) -> None:
        _required_text(self.array_id, "array_id")
        object.__setattr__(
            self,
            "row_center_height_m",
            _bounded_real(
                self.row_center_height_m,
                "row_center_height_m",
                0.0,
                np.inf,
                lower_open=True,
            ),
        )
        object.__setattr__(
            self,
            "albedo",
            _bounded_real(self.albedo, "albedo", 0.0, 1.0),
        )


@dataclass(frozen=True)
class FixedBifacialRearSceneDiagnostics:
    """Bounded regular-array diagnostics without canonical mesh serialization."""

    receiver_count: int
    array_count: int
    row_count: int
    regular_blocking_pair_count: int
    view_factor_points: int
    coverage_scope: str


@dataclass(frozen=True)
class FixedBifacialRearArrayOpticalGeometry:
    """Immutable validated infinite-sheds geometry for downstream rear optics."""

    array_id: str
    receiver_ids: tuple[str, ...]
    row_rotation_deg: float
    axis_azimuth_deg: float
    surface_tilt_deg: float
    surface_azimuth_deg: float
    rear_surface_tilt_deg: float
    rear_surface_azimuth_deg: float
    collector_width_m: float
    pitch_m: float
    gcr: float
    row_center_height_m: float
    albedo: float


@dataclass(frozen=True)
class _ArraySummary:
    array_id: str
    receiver_ids: tuple[str, ...]
    row_rotation_deg: float
    axis_azimuth_deg: float
    surface_tilt_deg: float
    surface_azimuth_deg: float
    rear_surface_tilt_deg: float
    rear_surface_azimuth_deg: float
    collector_width_m: float
    pitch_m: float
    gcr: float
    row_center_height_m: float
    albedo: float


class FixedBifacialRearScene:
    """Prevalidated regular fixed-row arrays for rear infinite-sheds irradiance."""

    def __init__(
        self,
        receivers: Sequence[PVReceiver],
        arrays: Sequence[FixedRowArrayDefinition],
        rear_parameters: Sequence[FixedBifacialRearParameters],
        *,
        view_factor_points: int,
    ) -> None:
        self._receivers = _validated_sequence(receivers, PVReceiver, "receivers")
        array_values = _validated_sequence(arrays, FixedRowArrayDefinition, "arrays")
        parameter_values = _validated_sequence(
            rear_parameters, FixedBifacialRearParameters, "rear_parameters"
        )
        self._view_factor_points = _positive_integer(view_factor_points, "view_factor_points")
        receiver_ids = tuple(item.id for item in self._receivers)
        _require_unique(receiver_ids, "receiver IDs")
        _require_unique((item.array_id for item in array_values), "array IDs")
        _require_unique((item.array_id for item in parameter_values), "parameter array IDs")
        all_rows = tuple(row for array in array_values for row in array.rows)
        _require_unique((row.row_id for row in all_rows), "row IDs")
        assignments = tuple(identifier for row in all_rows for identifier in row.receiver_ids)
        _require_unique(assignments, "receiver assignments")
        if set(assignments) != set(receiver_ids):
            raise ValueError("every supplied receiver must be assigned exactly once")
        if not set(assignments).issubset(receiver_ids):
            raise ValueError("row definitions contain unknown receiver IDs")
        _require_fixed_receivers(self._receivers)

        parameters_by_id = {item.array_id: item for item in parameter_values}
        if set(parameters_by_id) != {item.array_id for item in array_values}:
            raise ValueError("each fixed-row array requires exactly one rear-parameter object")
        receivers_by_id = {item.id: item for item in self._receivers}
        summaries: list[_ArraySummary] = []
        for array in array_values:
            summary = _validated_array_summary(array, parameters_by_id[array.array_id])
            for receiver_id in summary.receiver_ids:
                _require_normal_consistency(receivers_by_id[receiver_id], summary)
            summaries.append(summary)
        self._summaries = tuple(summaries)
        self._receiver_summary = {
            receiver_id: summary
            for summary in self._summaries
            for receiver_id in summary.receiver_ids
        }
        self._diagnostics = FixedBifacialRearSceneDiagnostics(
            receiver_count=len(self._receivers),
            array_count=len(array_values),
            row_count=len(all_rows),
            regular_blocking_pair_count=sum(len(item.blocking_pairs) for item in array_values),
            view_factor_points=self._view_factor_points,
            coverage_scope=COVERAGE_SCOPE,
        )

    @property
    def receiver_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self._receivers)

    @property
    def diagnostics(self) -> FixedBifacialRearSceneDiagnostics:
        return self._diagnostics

    @property
    def optical_geometry(self) -> tuple[FixedBifacialRearArrayOpticalGeometry, ...]:
        """Return deterministic immutable geometry without changing S6E physics."""
        return tuple(
            FixedBifacialRearArrayOpticalGeometry(
                array_id=summary.array_id,
                receiver_ids=summary.receiver_ids,
                row_rotation_deg=summary.row_rotation_deg,
                axis_azimuth_deg=summary.axis_azimuth_deg,
                surface_tilt_deg=summary.surface_tilt_deg,
                surface_azimuth_deg=summary.surface_azimuth_deg,
                rear_surface_tilt_deg=summary.rear_surface_tilt_deg,
                rear_surface_azimuth_deg=summary.rear_surface_azimuth_deg,
                collector_width_m=summary.collector_width_m,
                pitch_m=summary.pitch_m,
                gcr=summary.gcr,
                row_center_height_m=summary.row_center_height_m,
                albedo=summary.albedo,
            )
            for summary in sorted(self._summaries, key=lambda item: item.array_id)
        )


def calculate_fixed_bifacial_rear_irradiance(
    ghi_wm2: pd.Series,
    dhi_wm2: pd.Series,
    dni_wm2: pd.Series,
    apparent_solar_zenith_deg: pd.Series,
    solar_azimuth_deg: pd.Series,
    *,
    scene: FixedBifacialRearScene,
    model: RearDiffuseModel,
) -> pd.DataFrame:
    """Return receiver-resolved raw rear irradiance without IAM or bifaciality."""
    if not isinstance(scene, FixedBifacialRearScene):
        raise ValueError("scene must be a FixedBifacialRearScene")
    if model not in ("isotropic", "haydavies"):
        raise ValueError("model must be 'isotropic' or 'haydavies'")
    index = _validated_indexed_inputs(
        ghi_wm2,
        dhi_wm2,
        dni_wm2,
        apparent_solar_zenith_deg,
        solar_azimuth_deg,
    )
    ghi = _irradiance_values(ghi_wm2, "ghi_wm2")
    dhi = _irradiance_values(dhi_wm2, "dhi_wm2")
    dni = _irradiance_values(dni_wm2, "dni_wm2")
    zenith = _angle_values(apparent_solar_zenith_deg, "apparent_solar_zenith_deg", 180.0, True)
    azimuth = _angle_values(solar_azimuth_deg, "solar_azimuth_deg", 360.0, False)
    complete = ~(np.isnan(ghi) | np.isnan(dhi) | np.isnan(dni))
    dni_extra = np.full(len(index), np.nan, dtype=np.float64)
    if model == "haydavies" and len(index):
        dni_extra[:] = np.asarray(_pvlib_irradiance.get_extra_radiation(index), dtype=np.float64)

    by_array: dict[str, dict[str, npt.NDArray[np.float64]]] = {}
    if np.any(complete):
        for summary in scene._summaries:
            raw = _infinite_sheds.get_irradiance_poa(
                summary.rear_surface_tilt_deg,
                summary.rear_surface_azimuth_deg,
                zenith[complete],
                azimuth[complete],
                summary.gcr,
                summary.row_center_height_m,
                summary.pitch_m,
                ghi[complete],
                dhi[complete],
                dni[complete],
                summary.albedo,
                model=model,
                dni_extra=dni_extra[complete] if model == "haydavies" else None,
                iam=1.0,
                npoints=scene._view_factor_points,
                vectorize=False,
            )
            by_array[summary.array_id] = _classified_pvlib_output(
                raw,
                np.count_nonzero(complete),
                summary,
                zenith[complete],
                azimuth[complete],
                dni[complete],
                model,
            )
    return _result_frame(
        scene,
        index,
        ghi,
        dhi,
        dni,
        zenith,
        azimuth,
        dni_extra,
        complete,
        by_array,
        model,
    )


def _validated_array_summary(
    array: FixedRowArrayDefinition, parameters: FixedBifacialRearParameters
) -> _ArraySummary:
    if not np.isclose(array.axis_tilt_deg, 0.0, rtol=0.0, atol=_GEOMETRY_ATOL):
        raise ValueError("S6E v1 requires horizontal row axes")
    rows = array.rows
    if len(rows) < 2:
        raise ValueError("infinite-sheds arrays require at least two rows")
    pairs = array.blocking_pairs
    if len(pairs) != len(rows) - 1:
        raise ValueError("infinite-sheds topology must be one regular linear row chain")
    row_ids = {row.row_id for row in rows}
    indegree = {identifier: 0 for identifier in row_ids}
    outgoing: dict[str, str] = {}
    for pair in pairs:
        if not np.isclose(pair.cross_axis_slope_deg, 0.0, rtol=0.0, atol=_GEOMETRY_ATOL):
            raise ValueError("S6E v1 requires zero cross-axis slope")
        indegree[pair.positive_side_row_id] += 1
        if pair.negative_side_row_id in outgoing:
            raise ValueError("infinite-sheds topology must not branch")
        outgoing[pair.negative_side_row_id] = pair.positive_side_row_id
    sources = [identifier for identifier in row_ids if indegree[identifier] == 0]
    sinks = [identifier for identifier in row_ids if identifier not in outgoing]
    if len(sources) != 1 or len(sinks) != 1 or any(value > 1 for value in indegree.values()):
        raise ValueError("infinite-sheds topology must be one regular linear row chain")
    visited: set[str] = set()
    current = sources[0]
    while current not in visited:
        visited.add(current)
        if current not in outgoing:
            break
        current = outgoing[current]
    if visited != row_ids or current != sinks[0]:
        raise ValueError("infinite-sheds topology must be one connected linear row chain")

    pitches = np.asarray([pair.pitch_m for pair in pairs], dtype=np.float64)
    widths = np.asarray([row.collector_width_m for row in rows], dtype=np.float64)
    rotations = np.asarray([row.row_rotation_deg for row in rows], dtype=np.float64)
    _require_uniform(pitches, "pitch")
    _require_uniform(widths, "collector width")
    _require_uniform(rotations, "row rotation")
    pitch = float(pitches[0])
    width = float(widths[0])
    rotation = float(rotations[0])
    gcr = width / pitch
    if not np.isfinite(gcr) or not 0.0 < gcr <= 1.0:
        raise ValueError("collector width / pitch GCR must be within (0, 1]")
    orientation = calc_surface_orientation(
        tracker_theta=rotation,
        axis_tilt=0.0,
        axis_azimuth=array.axis_azimuth_deg,
    )
    surface_tilt = float(np.asarray(orientation["surface_tilt"]).reshape(-1)[0])
    surface_azimuth = float(np.asarray(orientation["surface_azimuth"]).reshape(-1)[0])
    rear_tilt = 180.0 - surface_tilt
    rear_azimuth = (surface_azimuth + 180.0) % 360.0
    half_vertical_extent = 0.5 * width * np.sin(np.radians(surface_tilt))
    if parameters.row_center_height_m - half_vertical_extent < -_GEOMETRY_ATOL:
        raise ValueError("fixed-row collector surface must not penetrate level ground")
    return _ArraySummary(
        array.array_id,
        tuple(identifier for row in rows for identifier in row.receiver_ids),
        rotation,
        array.axis_azimuth_deg,
        surface_tilt,
        surface_azimuth,
        rear_tilt,
        rear_azimuth,
        width,
        pitch,
        gcr,
        parameters.row_center_height_m,
        parameters.albedo,
    )


def _require_normal_consistency(receiver: PVReceiver, summary: _ArraySummary) -> None:
    tilt = np.radians(summary.surface_tilt_deg)
    azimuth = np.radians(summary.surface_azimuth_deg)
    expected = np.asarray(
        (np.sin(tilt) * np.sin(azimuth), np.sin(tilt) * np.cos(azimuth), np.cos(tilt))
    )
    if not np.allclose(receiver.normal_enu, expected, rtol=0.0, atol=_NORMAL_ATOL):
        raise ValueError("canonical receiver normal conflicts with fixed-row orientation")


def _classified_pvlib_output(
    raw: dict[str, object],
    count: int,
    summary: _ArraySummary,
    zenith: npt.NDArray[np.float64],
    azimuth: npt.NDArray[np.float64],
    original_dni: npt.NDArray[np.float64],
    model: RearDiffuseModel,
) -> dict[str, npt.NDArray[np.float64]]:
    """Validate pvlib energy and classify Hay-Davies circumsolar as diffuse."""
    keys = (
        "poa_direct",
        "poa_sky_diffuse",
        "poa_ground_diffuse",
        "poa_diffuse",
        "poa_global",
        "shaded_fraction",
    )
    output: dict[str, npt.NDArray[np.float64]] = {}
    for key in keys:
        values = np.broadcast_to(np.asarray(raw[key], dtype=np.float64), (count,)).copy()
        if not np.isfinite(values).all() or np.any(values < -_CLOSURE_ATOL):
            raise RuntimeError("pvlib returned invalid rear irradiance output")
        output[key] = values
    if np.any(output["shaded_fraction"] > 1.0 + _CLOSURE_ATOL):
        raise RuntimeError("pvlib returned invalid rear direct shaded fraction")
    if not np.allclose(
        output["poa_diffuse"],
        output["poa_sky_diffuse"] + output["poa_ground_diffuse"],
        rtol=1e-12,
        atol=_CLOSURE_ATOL,
    ) or not np.allclose(
        output["poa_global"],
        output["poa_direct"] + output["poa_diffuse"],
        rtol=1e-12,
        atol=_CLOSURE_ATOL,
    ):
        raise RuntimeError("pvlib rear irradiance components do not close")
    shaded = np.clip(output["shaded_fraction"], 0.0, 1.0)
    if model == "haydavies":
        unshaded_beam = np.asarray(
            _pvlib_irradiance.beam_component(
                summary.rear_surface_tilt_deg,
                summary.rear_surface_azimuth_deg,
                zenith,
                azimuth,
                original_dni,
            ),
            dtype=np.float64,
        )
        true_beam = unshaded_beam * (1.0 - shaded)
        circumsolar = output["poa_direct"] - true_beam
        if np.any(circumsolar < -_CLOSURE_ATOL):
            raise RuntimeError("pvlib Hay-Davies circumsolar classification is negative")
        circumsolar = np.maximum(circumsolar, 0.0)
    else:
        true_beam = output["poa_direct"].copy()
        circumsolar = np.zeros(count, dtype=np.float64)
    sky = output["poa_sky_diffuse"] + circumsolar
    ground = output["poa_ground_diffuse"].copy()
    diffuse = sky + ground
    global_total = true_beam + diffuse
    if not np.allclose(
        true_beam + circumsolar,
        output["poa_direct"],
        rtol=1e-12,
        atol=_CLOSURE_ATOL,
    ) or not np.allclose(
        global_total,
        output["poa_global"],
        rtol=1e-12,
        atol=_CLOSURE_ATOL,
    ):
        raise RuntimeError("corrected rear irradiance classification does not conserve energy")
    return {
        "direct": true_beam,
        "circumsolar": circumsolar,
        "sky": sky,
        "ground": ground,
        "diffuse": diffuse,
        "global": global_total,
        "shaded_fraction": shaded,
    }


def _result_frame(
    scene: FixedBifacialRearScene,
    index: pd.DatetimeIndex,
    ghi: npt.NDArray[np.float64],
    dhi: npt.NDArray[np.float64],
    dni: npt.NDArray[np.float64],
    zenith: npt.NDArray[np.float64],
    azimuth: npt.NDArray[np.float64],
    dni_extra: npt.NDArray[np.float64],
    complete: npt.NDArray[np.bool_],
    by_array: dict[str, dict[str, npt.NDArray[np.float64]]],
    model: RearDiffuseModel,
) -> pd.DataFrame:
    receiver_ids = list(scene.receiver_ids)
    shape = (len(index), len(receiver_ids))
    columns: dict[str, object] = {}
    for name, values in (("ghi_wm2", ghi), ("dhi_wm2", dhi), ("dni_wm2", dni)):
        columns[name] = np.repeat(values, len(receiver_ids))
    columns["apparent_solar_zenith_deg"] = np.repeat(zenith, len(receiver_ids))
    columns["solar_azimuth_deg"] = np.repeat(azimuth, len(receiver_ids))
    columns["dni_extra_wm2"] = np.repeat(dni_extra, len(receiver_ids))
    float_static = {name: np.full(shape, np.nan) for name in _COLUMNS[7:18]}
    result_values = {name: np.full(shape, np.nan) for name in _COLUMNS[18:25]}
    array_ids = np.full(shape, None, dtype=object)
    for position, receiver_id in enumerate(receiver_ids):
        summary = scene._receiver_summary[receiver_id]
        array_ids[:, position] = summary.array_id
        static_values = (
            summary.row_rotation_deg,
            summary.axis_azimuth_deg,
            summary.surface_tilt_deg,
            summary.surface_azimuth_deg,
            summary.rear_surface_tilt_deg,
            summary.rear_surface_azimuth_deg,
            summary.collector_width_m,
            summary.pitch_m,
            summary.gcr,
            summary.row_center_height_m,
            summary.albedo,
        )
        for name, value in zip(_COLUMNS[7:18], static_values, strict=True):
            float_static[name][:, position] = value
        if np.any(complete):
            output = by_array[summary.array_id]
            for name, key in zip(
                _COLUMNS[18:25],
                (
                    "direct",
                    "circumsolar",
                    "sky",
                    "ground",
                    "diffuse",
                    "global",
                    "shaded_fraction",
                ),
                strict=True,
            ):
                result_values[name][complete, position] = output[key]
    columns["fixed_row_array_id"] = array_ids.ravel()
    columns.update({name: values.ravel() for name, values in float_static.items()})
    columns.update({name: values.ravel() for name, values in result_values.items()})
    resolved = np.broadcast_to(complete[:, None], shape).copy()
    columns["rear_irradiance_resolved"] = resolved.ravel()
    state = np.full(shape, "unresolved_missing_irradiance", dtype=object)
    state[resolved] = "resolved"
    columns["rear_irradiance_state"] = state.ravel()
    size = shape[0] * shape[1]
    columns["rear_irradiance_model"] = np.full(size, MODEL_ID, dtype=object)
    columns["rear_diffuse_model"] = np.full(size, model, dtype=object)
    columns["rear_coverage_scope"] = np.full(size, COVERAGE_SCOPE, dtype=object)
    result = pd.DataFrame(
        columns, columns=_COLUMNS, index=_receiver_time_index(index, receiver_ids)
    )
    return _typed_result(result)


def _validated_indexed_inputs(*series: pd.Series) -> pd.DatetimeIndex:
    if any(not isinstance(item, pd.Series) for item in series):
        raise ValueError("all irradiance and solar inputs must be pandas Series")
    index = series[0].index
    if not isinstance(index, pd.DatetimeIndex) or index.tz is None:
        raise ValueError("inputs require a timezone-aware DatetimeIndex")
    if not index.is_unique or index.hasnans:
        raise ValueError("timestamps must be unique and contain no NaT")
    if any(not item.index.equals(index) or item.index.name != index.name for item in series[1:]):
        raise ValueError("all input Series must have identical timestamp indexes and names")
    return index


def _irradiance_values(series: pd.Series, name: str) -> npt.NDArray[np.float64]:
    values = np.empty(len(series), dtype=np.float64)
    for index, value in enumerate(series.array):
        if pd.isna(value):
            values[index] = np.nan
        elif isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
            raise ValueError(f"{name} values must be finite non-negative real values or NaN")
        else:
            values[index] = float(value)
            if not np.isfinite(values[index]) or values[index] < 0.0:
                raise ValueError(f"{name} values must be finite non-negative real values or NaN")
    return values


def _angle_values(
    series: pd.Series, name: str, upper: float, upper_closed: bool
) -> npt.NDArray[np.float64]:
    return np.asarray(
        [
            _bounded_real(value, name, 0.0, upper, upper_closed=upper_closed)
            for value in series.array
        ],
        dtype=np.float64,
    )


def _receiver_time_index(index: pd.DatetimeIndex, receiver_ids: list[str]) -> pd.MultiIndex:
    return pd.MultiIndex.from_arrays(
        [index.repeat(len(receiver_ids)), receiver_ids * len(index)],
        names=[index.name, "receiver_id"],
    )


def _typed_result(result: pd.DataFrame) -> pd.DataFrame:
    float_columns = _COLUMNS[:6] + _COLUMNS[7:25]
    for column in float_columns:
        result[column] = result[column].astype("float64")
    result["rear_irradiance_resolved"] = result["rear_irradiance_resolved"].astype("bool")
    for column in (
        "fixed_row_array_id",
        "rear_irradiance_state",
        "rear_irradiance_model",
        "rear_diffuse_model",
        "rear_coverage_scope",
    ):
        result[column] = result[column].astype("string")
    return result


def _require_fixed_receivers(receivers: Sequence[PVReceiver]) -> None:
    for receiver in receivers:
        if receiver.receiver_kind is ReceiverKind.TRACKER_TABLE:
            raise ValueError("TRACKER_TABLE runtime pose belongs to S6C and is outside S6E v1")
        if receiver.receiver_kind is not ReceiverKind.FIXED_TABLE:
            raise ValueError("S6E v1 accepts only FIXED_TABLE receivers")


def _require_uniform(values: npt.NDArray[np.float64], label: str) -> None:
    if not np.allclose(values, values[0], rtol=_GEOMETRY_RTOL, atol=_GEOMETRY_ATOL):
        raise ValueError(f"infinite-sheds arrays require uniform {label}")


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or int(value) <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _bounded_real(
    value: object,
    name: str,
    lower: float,
    upper: float,
    *,
    lower_open: bool = False,
    upper_closed: bool = True,
) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real value")
    result = float(value)
    lower_valid = result > lower if lower_open else result >= lower
    upper_valid = result <= upper if upper_closed else result < upper
    if not np.isfinite(result) or not lower_valid or not upper_valid:
        raise ValueError(f"{name} is outside its supported range")
    return result


def _required_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _validated_sequence(value: object, kind: type[_T], name: str) -> tuple[_T, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a sequence")
    result = tuple(value)
    if any(not isinstance(item, kind) for item in result):
        raise ValueError(f"{name} must contain only {kind.__name__} values")
    return result


def _require_unique(values: Iterable[object], label: str) -> None:
    items = tuple(values)
    if any(count > 1 for count in Counter(items).values()):
        raise ValueError(f"{label} must be unique")
