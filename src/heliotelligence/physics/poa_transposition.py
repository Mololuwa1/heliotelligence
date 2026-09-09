"""Raw front-side POA transposition delegated to pvlib reference models.

This dormant primitive consumes resolved horizontal irradiance and R1A apparent
solar geometry.  It exposes pre-IAM, unshaded, front-side POA components for an
explicitly selected Perez or Perez-Driesse model without filling missing
irradiance or applying downstream optical, shading, bifacial, or electrical
effects.
"""

from __future__ import annotations

from numbers import Real
from typing import Literal

import numpy as np
import pandas as pd
import pvlib.irradiance

TranspositionModel = Literal["perez", "perez-driesse"]

_OUTPUT_COLUMNS = [
    "ghi_wm2",
    "dhi_wm2",
    "dni_wm2",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "dni_extra_wm2",
    "aoi_deg",
    "poa_direct_raw_wm2",
    "poa_sky_diffuse_raw_wm2",
    "poa_ground_diffuse_raw_wm2",
    "poa_diffuse_raw_wm2",
    "poa_global_raw_wm2",
    "poa_transposition_resolved",
    "transposition_applied",
    "transposition_state",
    "transposition_model",
]


def calculate_raw_poa_transposition(
    ghi_wm2: pd.Series,
    dhi_wm2: pd.Series,
    dni_wm2: pd.Series,
    apparent_solar_zenith_deg: pd.Series,
    solar_azimuth_deg: pd.Series,
    *,
    surface_tilt_deg: float,
    surface_azimuth_deg: float,
    albedo: float,
    model: TranspositionModel,
) -> pd.DataFrame:
    """Calculate raw, unshaded, pre-IAM front-side POA irradiance."""
    inputs = (
        ghi_wm2,
        dhi_wm2,
        dni_wm2,
        apparent_solar_zenith_deg,
        solar_azimuth_deg,
    )
    _validate_inputs(inputs)
    _validate_bounded_scalar(surface_tilt_deg, "surface_tilt_deg", 0.0, 180.0)
    _validate_bounded_scalar(
        surface_azimuth_deg, "surface_azimuth_deg", 0.0, 360.0
    )
    _validate_bounded_scalar(albedo, "albedo", 0.0, 1.0)
    if model not in ("perez", "perez-driesse"):
        raise ValueError("model must be 'perez' or 'perez-driesse'")

    index = ghi_wm2.index
    if index.empty:
        return _empty_result(index)

    ghi = _numeric_irradiance(ghi_wm2)
    dhi = _numeric_irradiance(dhi_wm2)
    dni = _numeric_irradiance(dni_wm2)
    apparent_zenith = apparent_solar_zenith_deg.astype(float).copy()
    solar_azimuth = solar_azimuth_deg.astype(float).copy()

    dni_extra = pd.Series(
        pvlib.irradiance.get_extra_radiation(index), index=index, dtype=float
    )
    aoi = pd.Series(
        pvlib.irradiance.aoi(
            surface_tilt=surface_tilt_deg,
            surface_azimuth=surface_azimuth_deg,
            solar_zenith=apparent_zenith,
            solar_azimuth=solar_azimuth,
        ),
        index=index,
        dtype=float,
    )

    resolved = ghi.notna() & dhi.notna() & dni.notna()
    poa_columns = {
        name: pd.Series(np.nan, index=index, dtype=float)
        for name in _OUTPUT_COLUMNS[7:12]
    }
    if resolved.any():
        poa = pvlib.irradiance.get_total_irradiance(
            surface_tilt=surface_tilt_deg,
            surface_azimuth=surface_azimuth_deg,
            solar_zenith=apparent_zenith.loc[resolved],
            solar_azimuth=solar_azimuth.loc[resolved],
            dni=dni.loc[resolved],
            ghi=ghi.loc[resolved],
            dhi=dhi.loc[resolved],
            dni_extra=dni_extra.loc[resolved],
            albedo=albedo,
            model=model,
            model_perez="allsitescomposite1990",
        )
        mappings = {
            "poa_direct_raw_wm2": "poa_direct",
            "poa_sky_diffuse_raw_wm2": "poa_sky_diffuse",
            "poa_ground_diffuse_raw_wm2": "poa_ground_diffuse",
            "poa_diffuse_raw_wm2": "poa_diffuse",
            "poa_global_raw_wm2": "poa_global",
        }
        for output_name, pvlib_name in mappings.items():
            poa_columns[output_name].loc[resolved] = poa[pvlib_name]

    state = pd.Series("unresolved_irradiance", index=index, dtype=str)
    state.loc[resolved] = "transposed"
    model_used = pd.Series("not_applied", index=index, dtype=str)
    model_used.loc[resolved] = model

    return pd.DataFrame(
        {
            "ghi_wm2": ghi,
            "dhi_wm2": dhi,
            "dni_wm2": dni,
            "apparent_solar_zenith_deg": apparent_zenith,
            "solar_azimuth_deg": solar_azimuth,
            "dni_extra_wm2": dni_extra,
            "aoi_deg": aoi,
            **poa_columns,
            "poa_transposition_resolved": resolved.astype(bool),
            "transposition_applied": resolved.astype(bool),
            "transposition_state": state,
            "transposition_model": model_used,
        },
        index=index,
        columns=_OUTPUT_COLUMNS,
    )


def _validate_inputs(inputs: tuple[object, object, object, object, object]) -> None:
    names = (
        "ghi_wm2",
        "dhi_wm2",
        "dni_wm2",
        "apparent_solar_zenith_deg",
        "solar_azimuth_deg",
    )
    for value, name in zip(inputs, names, strict=True):
        if not isinstance(value, pd.Series):
            raise ValueError(f"{name} must be a pandas Series")
        _validate_index(value.index, name)

    index = inputs[0].index  # type: ignore[union-attr]
    if any(
        not value.index.equals(index) or value.index.name != index.name
        for value in inputs[1:]  # type: ignore[union-attr]
    ):
        raise ValueError(
            "input Series indexes must match exactly; index names must match exactly"
        )

    for value, name in zip(inputs[:3], names[:3], strict=True):
        _validate_irradiance(value, name)  # type: ignore[arg-type]
    _validate_geometry(inputs[3], "apparent_solar_zenith_deg", 0.0, 180.0)  # type: ignore[arg-type]
    _validate_geometry(inputs[4], "solar_azimuth_deg", 0.0, 360.0)  # type: ignore[arg-type]


def _validate_index(index: pd.Index, series_name: str) -> None:
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError(f"{series_name} index must be a pandas DatetimeIndex")
    if index.tz is None:
        raise ValueError(f"{series_name} index must be timezone-aware")
    if index.hasnans:
        raise ValueError(f"{series_name} index must not contain NaT")
    if index.has_duplicates:
        raise ValueError(f"{series_name} index must not contain duplicate timestamps")


def _validate_irradiance(series: pd.Series, name: str) -> None:
    for value in series.array:
        if pd.isna(value):
            continue
        if (
            isinstance(value, (bool, np.bool_))
            or not isinstance(value, Real)
            or not np.isfinite(value)
        ):
            raise ValueError(f"{name} present values must be finite real numbers")
        if value < 0:
            raise ValueError(f"{name} present values must be non-negative")


def _validate_geometry(
    series: pd.Series, name: str, minimum: float, maximum: float
) -> None:
    for value in series.array:
        if (
            pd.isna(value)
            or isinstance(value, (bool, np.bool_))
            or not isinstance(value, Real)
            or not np.isfinite(value)
        ):
            raise ValueError(f"{name} values must be finite real numbers")
        if value < minimum or value > maximum:
            raise ValueError(f"{name} values must be between {minimum:g} and {maximum:g}")


def _validate_bounded_scalar(
    value: object, name: str, minimum: float, maximum: float
) -> None:
    if (
        isinstance(value, (bool, np.bool_))
        or not isinstance(value, Real)
        or not np.isfinite(value)
    ):
        raise ValueError(f"{name} must be a finite real number")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")


def _numeric_irradiance(series: pd.Series) -> pd.Series:
    return pd.Series(
        (np.nan if pd.isna(value) else float(value) for value in series.array),
        index=series.index,
        dtype=float,
    )


def _empty_result(index: pd.DatetimeIndex) -> pd.DataFrame:
    values = {
        **{
            name: pd.Series(index=index, dtype=float)
            for name in _OUTPUT_COLUMNS[:12]
        },
        **{
            name: pd.Series(index=index, dtype=bool)
            for name in _OUTPUT_COLUMNS[12:14]
        },
        **{
            name: pd.Series(index=index, dtype=str)
            for name in _OUTPUT_COLUMNS[14:]
        },
    }
    return pd.DataFrame(values, index=index, columns=_OUTPUT_COLUMNS)
