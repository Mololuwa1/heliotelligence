"""Observation-keyed NREL-SPA geometry at explicitly admitted evaluation instants."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.physics import solar_geometry
from heliotelligence.physics.weather_time_authority import (
    WeatherTimeStateResult,
    validate_weather_time_state,
)

TIME_ALIGNED_SOLAR_GEOMETRY_CONTRACT_ID = (
    "admitted_weather_time_authority_to_observation_keyed_nrel_spa_solar_geometry_v1"
)
TIME_ALIGNED_SOLAR_GEOMETRY_MODEL_ID = (
    "explicit_evaluation_instants_observation_keyed_nrel_spa_replay_v1"
)
SOLAR_POSITION_MODEL_ID = "nrel_spa"
_GEOMETRY_COLUMNS = (
    "solar_zenith_deg",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "solar_elevation_deg",
    "apparent_solar_elevation_deg",
    "solar_position_model",
)


@dataclass(frozen=True)
class TimeAlignedSolarGeometryResult:
    geometry: pd.DataFrame
    weather_time_state: WeatherTimeStateResult
    latitude_deg: float
    longitude_deg: float
    altitude_m: float


def _calculate(
    weather: WeatherTimeStateResult,
    latitude: float,
    longitude: float,
    altitude: float,
) -> pd.DataFrame:
    evaluation = pd.DatetimeIndex(weather.states["solar_geometry_evaluation_time"])
    native = solar_geometry.calculate_solar_geometry(
        evaluation, latitude_deg=latitude, longitude_deg=longitude, altitude_m=altitude
    )
    if not (native["solar_position_model"] == SOLAR_POSITION_MODEL_ID).all():
        raise ValueError("canonical solar geometry must be nrel_spa")
    result = weather.states.copy(deep=True)
    for name in _GEOMETRY_COLUMNS:
        result[name] = native[name].to_numpy(copy=True)
    result["time_aligned_solar_geometry_resolved"] = pd.Series(True, index=result.index, dtype=bool)
    result["time_aligned_solar_geometry_contract"] = pd.Series(
        TIME_ALIGNED_SOLAR_GEOMETRY_CONTRACT_ID, index=result.index, dtype=object
    )
    result["time_aligned_solar_geometry_model"] = pd.Series(
        TIME_ALIGNED_SOLAR_GEOMETRY_MODEL_ID, index=result.index, dtype=object
    )
    return result


def calculate_time_aligned_solar_geometry(
    weather_time_state: WeatherTimeStateResult,
    *,
    latitude_deg: float,
    longitude_deg: float,
    altitude_m: float,
) -> TimeAlignedSolarGeometryResult:
    validate_weather_time_state(weather_time_state)
    geometry = _calculate(weather_time_state, latitude_deg, longitude_deg, altitude_m)
    result = TimeAlignedSolarGeometryResult(
        geometry, weather_time_state, float(latitude_deg), float(longitude_deg), float(altitude_m)
    )
    validate_time_aligned_solar_geometry(result)
    return result


def validate_time_aligned_solar_geometry(result: TimeAlignedSolarGeometryResult) -> None:
    """Direct canonical reference invocation, independent of the alignment builder."""
    if type(result) is not TimeAlignedSolarGeometryResult:
        raise TypeError("invalid aligned solar geometry result type")
    validate_weather_time_state(result.weather_time_state)
    weather = result.weather_time_state.states
    times = pd.DatetimeIndex(weather["solar_geometry_evaluation_time"])
    reference = solar_geometry.calculate_solar_geometry(
        times,
        latitude_deg=result.latitude_deg,
        longitude_deg=result.longitude_deg,
        altitude_m=result.altitude_m,
    )
    expected = weather.copy(deep=True)
    for name in _GEOMETRY_COLUMNS:
        expected[name] = reference[name].to_numpy(copy=True)
    expected["time_aligned_solar_geometry_resolved"] = pd.Series(
        True, index=weather.index, dtype=bool
    )
    expected["time_aligned_solar_geometry_contract"] = pd.Series(
        TIME_ALIGNED_SOLAR_GEOMETRY_CONTRACT_ID, index=weather.index, dtype=object
    )
    expected["time_aligned_solar_geometry_model"] = pd.Series(
        TIME_ALIGNED_SOLAR_GEOMETRY_MODEL_ID, index=weather.index, dtype=object
    )
    if not (reference["solar_position_model"] == "nrel_spa").all():
        raise ValueError("canonical solar geometry reference is not nrel_spa")
    try:
        pd.testing.assert_frame_equal(
            result.geometry, expected, check_exact=False, atol=1e-12, rtol=0
        )
    except (AssertionError, TypeError, ValueError) as exc:
        raise ValueError("time-aligned solar geometry failed independent replay") from exc
