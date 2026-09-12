"""Receiver-resolved coupling of raw direct POA to 3D beam visibility.

This dormant primitive delegates all local geometric visibility calculations to
the validated rectangular-surface reference kernel.  It applies neither IAM nor
diffuse, rear, terrain, thermal, or electrical effects.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from numbers import Integral, Real

import numpy as np
import pandas as pd

from heliotelligence.physics.shading import (
    RectangularSurface3D,
    calculate_direct_beam_visibility,
)

_MODEL = "rectangular_surface_cell_center_raycast"
_OUTPUT_COLUMNS = [
    "poa_direct_raw_wm2",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "beam_visible_fraction",
    "beam_shaded_fraction",
    "poa_direct_visible_wm2",
    "poa_direct_shading_loss_wm2",
    "sample_count",
    "shaded_sample_count",
    "beam_visibility_resolved",
    "beam_shading_resolved",
    "beam_shading_applied",
    "beam_shading_state",
    "beam_shading_model",
]
_FLOAT_COLUMNS = _OUTPUT_COLUMNS[:7]
_INTEGER_COLUMNS = ["sample_count", "shaded_sample_count"]
_BOOLEAN_COLUMNS = [
    "beam_visibility_resolved",
    "beam_shading_resolved",
    "beam_shading_applied",
]
_STRING_COLUMNS = ["beam_shading_state", "beam_shading_model"]


def calculate_direct_beam_shading(
    poa_direct_raw_wm2_by_receiver: pd.DataFrame,
    apparent_solar_zenith_deg: pd.Series,
    solar_azimuth_deg: pd.Series,
    *,
    surfaces: Sequence[RectangularSurface3D],
    samples_u: int = 5,
    samples_v: int = 5,
) -> pd.DataFrame:
    """Apply reference 3D visibility to receiver-specific raw direct POA.

    Geometry is not evaluated at or below the apparent horizon.  Accordingly,
    ``sample_count`` and ``shaded_sample_count`` are missing for those rows.
    """
    if not isinstance(poa_direct_raw_wm2_by_receiver, pd.DataFrame):
        raise ValueError("poa_direct_raw_wm2_by_receiver must be a pandas DataFrame")
    if poa_direct_raw_wm2_by_receiver.shape[1] == 0:
        raise ValueError("poa_direct_raw_wm2_by_receiver must contain receivers")

    receiver_ids = list(poa_direct_raw_wm2_by_receiver.columns)
    _validate_receiver_ids(receiver_ids)
    _validate_sample_count(samples_u, "samples_u")
    _validate_sample_count(samples_v, "samples_v")
    _validate_scene(surfaces, receiver_ids)

    raw_index = _validate_datetime_index(
        poa_direct_raw_wm2_by_receiver.index,
        "poa_direct_raw_wm2_by_receiver",
    )
    _validate_series(apparent_solar_zenith_deg, "apparent_solar_zenith_deg")
    _validate_series(solar_azimuth_deg, "solar_azimuth_deg")
    _require_matching_index(
        raw_index,
        apparent_solar_zenith_deg.index,
        "apparent_solar_zenith_deg",
    )
    _require_matching_index(raw_index, solar_azimuth_deg.index, "solar_azimuth_deg")

    raw_values = _validated_raw_direct(poa_direct_raw_wm2_by_receiver)
    zenith_values = _validated_geometry(
        apparent_solar_zenith_deg, "apparent_solar_zenith_deg", upper=180.0
    )
    azimuth_values = _validated_geometry(
        solar_azimuth_deg, "solar_azimuth_deg", upper=360.0, upper_closed=False
    )

    rows: list[dict[str, object]] = []
    for time_position in range(len(raw_index)):
        zenith = zenith_values[time_position]
        azimuth = azimuth_values[time_position]
        geometry = None
        if zenith < 90.0:
            geometry = calculate_direct_beam_visibility(
                surfaces,
                receiver_ids,
                solar_zenith_deg=zenith,
                solar_azimuth_deg=azimuth,
                samples_u=samples_u,
                samples_v=samples_v,
            )
            _validate_geometry_result(
                geometry,
                receiver_ids,
                expected_sample_count=int(samples_u) * int(samples_v),
            )

        for receiver_position in range(len(receiver_ids)):
            raw_direct = raw_values[time_position, receiver_position]
            if geometry is None:
                row = _below_horizon_row(raw_direct, zenith, azimuth)
            else:
                row = _above_horizon_row(
                    raw_direct,
                    zenith,
                    azimuth,
                    geometry.iloc[receiver_position],
                )
            rows.append(row)

    if raw_index.empty:
        index = pd.MultiIndex(
            levels=[raw_index, pd.Index(receiver_ids, dtype=object)],
            codes=[[], []],
            names=[raw_index.name, "receiver_id"],
        )
    else:
        index = pd.MultiIndex.from_arrays(
            [
                raw_index.repeat(len(receiver_ids)),
                pd.Index(
                    receiver_ids * len(raw_index),
                    dtype=object,
                    name="receiver_id",
                ),
            ],
            names=[raw_index.name, "receiver_id"],
        )
    return _typed_result(rows, index)


def _validate_receiver_ids(receiver_ids: list[object]) -> None:
    for receiver_id in receiver_ids:
        if not isinstance(receiver_id, str) or not receiver_id:
            raise ValueError("receiver IDs must be non-empty strings")
    duplicates = [
        receiver_id
        for receiver_id, count in Counter(receiver_ids).items()
        if count > 1
    ]
    if duplicates:
        raise ValueError("receiver IDs must be unique")


def _validate_scene(
    surfaces: object,
    receiver_ids: list[str],
) -> None:
    if isinstance(surfaces, (str, bytes)) or not isinstance(surfaces, Sequence):
        raise ValueError("surfaces must be a sequence of RectangularSurface3D")
    if any(not isinstance(surface, RectangularSurface3D) for surface in surfaces):
        raise ValueError("surfaces must contain only RectangularSurface3D instances")
    surface_ids = [surface.id for surface in surfaces]
    duplicates = [
        surface_id
        for surface_id, count in Counter(surface_ids).items()
        if count > 1
    ]
    if duplicates:
        raise ValueError("surfaces must have unique IDs")
    missing = [receiver_id for receiver_id in receiver_ids if receiver_id not in surface_ids]
    if missing:
        raise ValueError("every receiver ID must exist in surfaces")


def _validate_sample_count(value: object, name: str) -> None:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < 1:
        raise ValueError(f"{name} must be an integer greater than or equal to 1")


def _validate_series(value: object, name: str) -> None:
    if not isinstance(value, pd.Series):
        raise ValueError(f"{name} must be a pandas Series")
    _validate_datetime_index(value.index, name)


def _validate_datetime_index(index: object, name: str) -> pd.DatetimeIndex:
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError(f"{name} must have a DatetimeIndex")
    if index.tz is None:
        raise ValueError(f"{name} index must be timezone-aware")
    if index.hasnans:
        raise ValueError(f"{name} index must not contain NaT")
    if not index.is_unique:
        raise ValueError(f"{name} index must contain unique timestamps")
    return index


def _require_matching_index(
    canonical: pd.DatetimeIndex,
    candidate: pd.Index,
    name: str,
) -> None:
    if (
        not canonical.equals(candidate)
        or candidate.tz != canonical.tz  # type: ignore[attr-defined]
        or candidate.name != canonical.name
    ):
        raise ValueError(
            f"{name} index must exactly match timestamps, order, timezone, and name"
        )


def _validated_raw_direct(frame: pd.DataFrame) -> np.ndarray:
    result = np.empty(frame.shape, dtype=float)
    for row in range(frame.shape[0]):
        for column in range(frame.shape[1]):
            value = frame.iat[row, column]
            if pd.isna(value):
                result[row, column] = np.nan
            elif (
                isinstance(value, (bool, np.bool_))
                or not isinstance(value, Real)
                or not np.isfinite(value)
                or value < 0.0
            ):
                raise ValueError(
                    "present poa_direct_raw_wm2 values must be finite, real, "
                    "non-Boolean, and non-negative"
                )
            else:
                result[row, column] = float(value)
    return result


def _validated_geometry(
    series: pd.Series,
    name: str,
    *,
    upper: float,
    upper_closed: bool = True,
) -> np.ndarray:
    values: list[float] = []
    for value in series.array:
        if (
            isinstance(value, (bool, np.bool_))
            or not isinstance(value, Real)
            or not np.isfinite(value)
        ):
            bracket = "]" if upper_closed else ")"
            raise ValueError(f"{name} values must be finite real values in [0, {upper:g}{bracket}")
        valid_upper = value <= upper if upper_closed else value < upper
        if value < 0.0 or not valid_upper:
            bracket = "]" if upper_closed else ")"
            raise ValueError(f"{name} values must be finite real values in [0, {upper:g}{bracket}")
        values.append(float(value))
    return np.asarray(values, dtype=float)


def _validate_geometry_result(
    geometry: pd.DataFrame,
    receiver_ids: list[str],
    *,
    expected_sample_count: int,
) -> None:
    expected_columns = [
        "receiver_id",
        "visible_fraction",
        "shaded_fraction",
        "sample_count",
        "shaded_sample_count",
    ]
    if geometry.columns.tolist() != expected_columns:
        raise ValueError("direct-beam visibility returned an unexpected schema")
    if geometry["receiver_id"].tolist() != receiver_ids:
        raise ValueError("direct-beam visibility returned unexpected receiver ordering")
    for row in geometry.itertuples(index=False):
        visible = row.visible_fraction
        shaded = row.shaded_fraction
        sample_count = row.sample_count
        shaded_count = row.shaded_sample_count
        if (
            not np.isfinite(visible)
            or not np.isfinite(shaded)
            or visible < 0.0
            or visible > 1.0
            or shaded < 0.0
            or shaded > 1.0
            or not np.isclose(visible + shaded, 1.0, rtol=0.0, atol=1e-12)
            or sample_count != expected_sample_count
            or isinstance(sample_count, (bool, np.bool_))
            or not isinstance(sample_count, Integral)
            or isinstance(shaded_count, (bool, np.bool_))
            or not isinstance(shaded_count, Integral)
            or shaded_count < 0
            or shaded_count > sample_count
            or not np.isclose(
                shaded,
                shaded_count / sample_count,
                rtol=0.0,
                atol=1e-12,
            )
        ):
            raise ValueError("direct-beam visibility returned inconsistent geometry")


def _above_horizon_row(
    raw_direct: float,
    zenith: float,
    azimuth: float,
    geometry: pd.Series,
) -> dict[str, object]:
    visible_fraction = float(geometry["visible_fraction"])
    shaded_fraction = float(geometry["shaded_fraction"])
    if np.isnan(raw_direct):
        visible_direct = np.nan
        shading_loss = np.nan
        shading_resolved = False
        shading_applied = False
        state = "geometry_resolved_irradiance_unresolved"
    else:
        visible_direct = raw_direct * visible_fraction
        shading_loss = raw_direct - visible_direct
        shading_resolved = True
        shading_applied = True
        state = "resolved"
    return {
        "poa_direct_raw_wm2": raw_direct,
        "apparent_solar_zenith_deg": zenith,
        "solar_azimuth_deg": azimuth,
        "beam_visible_fraction": visible_fraction,
        "beam_shaded_fraction": shaded_fraction,
        "poa_direct_visible_wm2": visible_direct,
        "poa_direct_shading_loss_wm2": shading_loss,
        "sample_count": int(geometry["sample_count"]),
        "shaded_sample_count": int(geometry["shaded_sample_count"]),
        "beam_visibility_resolved": True,
        "beam_shading_resolved": shading_resolved,
        "beam_shading_applied": shading_applied,
        "beam_shading_state": state,
        "beam_shading_model": _MODEL,
    }


def _below_horizon_row(
    raw_direct: float,
    zenith: float,
    azimuth: float,
) -> dict[str, object]:
    if np.isnan(raw_direct):
        visible_direct = np.nan
        shading_loss = np.nan
        shading_resolved = False
        state = "no_above_horizon_direct_beam_irradiance_unresolved"
    elif raw_direct == 0.0:
        visible_direct = 0.0
        shading_loss = 0.0
        shading_resolved = True
        state = "no_above_horizon_direct_beam"
    else:
        visible_direct = np.nan
        shading_loss = np.nan
        shading_resolved = False
        state = "inconsistent_below_horizon_direct_irradiance"
    return {
        "poa_direct_raw_wm2": raw_direct,
        "apparent_solar_zenith_deg": zenith,
        "solar_azimuth_deg": azimuth,
        "beam_visible_fraction": np.nan,
        "beam_shaded_fraction": np.nan,
        "poa_direct_visible_wm2": visible_direct,
        "poa_direct_shading_loss_wm2": shading_loss,
        "sample_count": pd.NA,
        "shaded_sample_count": pd.NA,
        "beam_visibility_resolved": False,
        "beam_shading_resolved": shading_resolved,
        "beam_shading_applied": False,
        "beam_shading_state": state,
        "beam_shading_model": "not_applied",
    }


def _typed_result(
    rows: list[dict[str, object]],
    index: pd.MultiIndex,
) -> pd.DataFrame:
    result = pd.DataFrame(rows, columns=_OUTPUT_COLUMNS, index=index)
    for column in _FLOAT_COLUMNS:
        result[column] = pd.array(result[column], dtype="float64")
    for column in _INTEGER_COLUMNS:
        result[column] = pd.array(result[column], dtype="Int64")
    for column in _BOOLEAN_COLUMNS:
        result[column] = pd.array(result[column], dtype="bool")
    for column in _STRING_COLUMNS:
        result[column] = pd.array(result[column], dtype="string")
    return result
