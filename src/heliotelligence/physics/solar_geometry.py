"""Site-agnostic solar geometry from pvlib's NREL SPA implementation.

This module exposes astronomical and apparent solar position for explicit,
timezone-aware physical instants.  It delegates to
``pvlib.solarposition.get_solarposition`` with ``method="nrel_numpy"`` and
does not clamp below-horizon geometry.

No measured atmospheric pressure or temperature is fabricated.  With altitude
supplied and pressure omitted, pvlib derives a standard pressure from altitude;
its documented default temperature of 12 degrees Celsius is retained for the
apparent/refraction calculation.  Those inputs may become explicit in a later
validated refinement if benchmarking evidence requires it.

This foundation is dormant from production.  Horizontal irradiance component
resolution, POA transposition, optical effects, shading coupling, diffuse and
bifacial refinement, effective irradiance composition, and thermal/module
integration remain required queued increments.
"""

from __future__ import annotations

from numbers import Real

import numpy as np
import pandas as pd
import pvlib.solarposition

_SOLAR_POSITION_MODEL = "nrel_spa"
_OUTPUT_COLUMNS = [
    "solar_zenith_deg",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "solar_elevation_deg",
    "apparent_solar_elevation_deg",
    "solar_position_model",
]


def calculate_solar_geometry(
    times: pd.DatetimeIndex,
    *,
    latitude_deg: float,
    longitude_deg: float,
    altitude_m: float,
) -> pd.DataFrame:
    """Calculate NREL SPA solar geometry at explicit physical instants."""
    _validate_times(times)
    _validate_coordinate(latitude_deg, "latitude_deg", minimum=-90.0, maximum=90.0)
    _validate_coordinate(
        longitude_deg,
        "longitude_deg",
        minimum=-180.0,
        maximum=180.0,
    )
    _validate_finite_real(altitude_m, "altitude_m")

    if times.empty:
        return _empty_solar_geometry_result(times)

    solar_position = pvlib.solarposition.get_solarposition(
        times,
        latitude=float(latitude_deg),
        longitude=float(longitude_deg),
        altitude=float(altitude_m),
        method="nrel_numpy",
    )

    return pd.DataFrame(
        {
            "solar_zenith_deg": pd.Series(
                solar_position["zenith"], index=times, dtype=float
            ),
            "apparent_solar_zenith_deg": pd.Series(
                solar_position["apparent_zenith"], index=times, dtype=float
            ),
            "solar_azimuth_deg": pd.Series(
                solar_position["azimuth"], index=times, dtype=float
            ),
            "solar_elevation_deg": pd.Series(
                solar_position["elevation"], index=times, dtype=float
            ),
            "apparent_solar_elevation_deg": pd.Series(
                solar_position["apparent_elevation"], index=times, dtype=float
            ),
            "solar_position_model": pd.Series(
                _SOLAR_POSITION_MODEL,
                index=times,
                dtype=str,
            ),
        },
        index=times,
        columns=_OUTPUT_COLUMNS,
    )


def _validate_times(times: object) -> None:
    """Require unique, timezone-aware physical instants without changing them."""
    if not isinstance(times, pd.DatetimeIndex):
        raise ValueError("times must be a pandas DatetimeIndex")
    if times.tz is None:
        raise ValueError("times must be timezone-aware")
    if times.hasnans:
        raise ValueError("times must not contain NaT")
    if times.has_duplicates:
        raise ValueError("times must not contain duplicate timestamps")


def _validate_finite_real(value: object, name: str) -> None:
    """Reject booleans, non-real values, and non-finite real values."""
    if isinstance(value, bool) or not isinstance(value, Real) or not np.isfinite(value):
        raise ValueError(f"{name} must be a finite real number")


def _validate_coordinate(
    value: object,
    name: str,
    *,
    minimum: float,
    maximum: float,
) -> None:
    """Validate one finite geographic coordinate without normalization."""
    _validate_finite_real(value, name)
    if value < minimum or value > maximum:  # type: ignore[operator]
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")


def _empty_solar_geometry_result(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Return the stable empty public schema while preserving the exact index."""
    return pd.DataFrame(
        {
            "solar_zenith_deg": pd.Series(index=index, dtype=float),
            "apparent_solar_zenith_deg": pd.Series(index=index, dtype=float),
            "solar_azimuth_deg": pd.Series(index=index, dtype=float),
            "solar_elevation_deg": pd.Series(index=index, dtype=float),
            "apparent_solar_elevation_deg": pd.Series(index=index, dtype=float),
            "solar_position_model": pd.Series(index=index, dtype=str),
        },
        index=index,
        columns=_OUTPUT_COLUMNS,
    )
