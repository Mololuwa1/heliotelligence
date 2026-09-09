"""Tests for the NREL SPA solar-geometry foundation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib.solarposition
import pytest

from heliotelligence.physics.solar_geometry import calculate_solar_geometry

_OUTPUT_COLUMNS = [
    "solar_zenith_deg",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "solar_elevation_deg",
    "apparent_solar_elevation_deg",
    "solar_position_model",
]
_REFERENCE_COLUMNS = {
    "solar_zenith_deg": "zenith",
    "apparent_solar_zenith_deg": "apparent_zenith",
    "solar_azimuth_deg": "azimuth",
    "solar_elevation_deg": "elevation",
    "apparent_solar_elevation_deg": "apparent_elevation",
}


def _calculate(
    times: pd.DatetimeIndex,
    *,
    latitude: float = 52.56,
    longitude: float = 1.21,
    altitude: float = 47.0,
) -> pd.DataFrame:
    return calculate_solar_geometry(
        times,
        latitude_deg=latitude,
        longitude_deg=longitude,
        altitude_m=altitude,
    )


def _assert_matches_pvlib(
    result: pd.DataFrame,
    times: pd.DatetimeIndex,
    *,
    latitude: float,
    longitude: float,
    altitude: float,
) -> None:
    expected = pvlib.solarposition.get_solarposition(
        times,
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
        method="nrel_numpy",
    )
    for actual_column, reference_column in _REFERENCE_COLUMNS.items():
        np.testing.assert_allclose(
            result[actual_column].to_numpy(),
            expected[reference_column].to_numpy(),
            rtol=0.0,
            atol=1e-12,
        )


@pytest.mark.parametrize(
    ("latitude", "longitude", "altitude", "timezone", "timestamps"),
    [
        (
            52.56,
            1.21,
            47.0,
            "Europe/London",
            [
                "2026-06-21 05:00",
                "2026-06-21 12:00",
                "2026-06-21 20:00",
                "2026-12-21 12:00",
                "2026-12-21 23:00",
            ],
        ),
        (
            -33.87,
            151.21,
            58.0,
            "Australia/Sydney",
            [
                "2026-01-15 07:00",
                "2026-01-15 13:00",
                "2026-01-15 19:00",
                "2026-07-15 12:00",
                "2026-07-15 23:00",
            ],
        ),
    ],
)
def test_geometry_matches_public_pvlib_nrel_spa_for_locations_and_seasons(
    latitude: float,
    longitude: float,
    altitude: float,
    timezone: str,
    timestamps: list[str],
) -> None:
    times = pd.DatetimeIndex(timestamps, tz=timezone, name="time")
    result = _calculate(
        times,
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
    )
    _assert_matches_pvlib(
        result,
        times,
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
    )
    assert result.index.equals(times)
    assert result["solar_position_model"].tolist() == ["nrel_spa"] * len(times)


def test_nighttime_geometry_is_not_clamped_to_the_horizon() -> None:
    times = pd.DatetimeIndex(["2026-06-21 00:00"], tz="Europe/London")
    result = _calculate(times)
    assert result.iloc[0]["solar_zenith_deg"] > 90.0
    assert result.iloc[0]["solar_elevation_deg"] < 0.0


def test_geometric_and_apparent_elevation_are_zenith_complements() -> None:
    times = pd.DatetimeIndex(
        ["2026-06-21 04:30", "2026-06-21 12:00", "2026-12-21 12:00"],
        tz="Europe/London",
    )
    result = _calculate(times)
    np.testing.assert_allclose(
        result["solar_elevation_deg"],
        90.0 - result["solar_zenith_deg"],
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        result["apparent_solar_elevation_deg"],
        90.0 - result["apparent_solar_zenith_deg"],
        rtol=0.0,
        atol=1e-12,
    )


def test_solar_azimuth_preserves_pvlib_north_zero_east_ninety_convention() -> None:
    times = pd.DatetimeIndex(
        ["2026-06-21 07:00", "2026-06-21 12:00", "2026-06-21 19:00"],
        tz="Europe/London",
    )
    result = _calculate(times)
    expected = pvlib.solarposition.get_solarposition(
        times,
        latitude=52.56,
        longitude=1.21,
        altitude=47.0,
        method="nrel_numpy",
    )
    np.testing.assert_allclose(result["solar_azimuth_deg"], expected["azimuth"])
    assert result["solar_azimuth_deg"].between(0.0, 360.0, inclusive="left").all()


def test_utc_and_local_time_for_same_instants_are_physically_equivalent() -> None:
    local_times = pd.DatetimeIndex(
        ["2026-01-15 12:00", "2026-06-21 12:00"],
        tz="Europe/London",
    )
    utc_times = local_times.tz_convert("UTC")
    local_result = _calculate(local_times)
    utc_result = _calculate(utc_times)
    np.testing.assert_allclose(
        local_result[list(_REFERENCE_COLUMNS)],
        utc_result[list(_REFERENCE_COLUMNS)],
        rtol=0.0,
        atol=1e-12,
    )


def test_dst_equivalent_instants_require_no_manual_offset() -> None:
    london = pd.DatetimeIndex(["2026-07-01 12:00"], tz="Europe/London")
    utc = pd.DatetimeIndex(["2026-07-01 11:00"], tz="UTC")
    np.testing.assert_allclose(
        _calculate(london)[list(_REFERENCE_COLUMNS)],
        _calculate(utc)[list(_REFERENCE_COLUMNS)],
        rtol=0.0,
        atol=1e-12,
    )


def test_irregular_unsorted_timestamps_preserve_exact_index_and_order() -> None:
    times = pd.DatetimeIndex(
        ["2026-06-21 12:07", "2026-06-21 05:01", "2026-06-21 18:43"],
        tz="UTC",
        name="physical_time",
    )
    before = times.copy()
    result = _calculate(times)
    assert result.index.equals(times)
    assert result.index.name == "physical_time"
    assert str(result.index.tz) == "UTC"
    assert times.equals(before)


@pytest.mark.parametrize("latitude", [-90.0, 90.0])
def test_latitude_boundaries_are_accepted(latitude: float) -> None:
    times = pd.DatetimeIndex(["2026-03-20 12:00"], tz="UTC")
    result = _calculate(times, latitude=latitude, longitude=0.0)
    assert result.index.equals(times)


@pytest.mark.parametrize("latitude", [-90.0001, 90.0001, np.nan, np.inf, -np.inf, True])
def test_invalid_latitude_is_rejected(latitude: object) -> None:
    times = pd.DatetimeIndex(["2026-06-21 12:00"], tz="UTC")
    with pytest.raises(ValueError, match="latitude_deg"):
        calculate_solar_geometry(
            times,
            latitude_deg=latitude,  # type: ignore[arg-type]
            longitude_deg=0.0,
            altitude_m=0.0,
        )


@pytest.mark.parametrize(
    "longitude",
    [-180.0001, 180.0001, 181.0, np.nan, np.inf, -np.inf, True],
)
def test_invalid_longitude_is_rejected_without_wrapping(longitude: object) -> None:
    times = pd.DatetimeIndex(["2026-06-21 12:00"], tz="UTC")
    with pytest.raises(ValueError, match="longitude_deg"):
        calculate_solar_geometry(
            times,
            latitude_deg=0.0,
            longitude_deg=longitude,  # type: ignore[arg-type]
            altitude_m=0.0,
        )


@pytest.mark.parametrize("altitude", [np.nan, np.inf, -np.inf, True, "47"])
def test_invalid_altitude_is_rejected(altitude: object) -> None:
    times = pd.DatetimeIndex(["2026-06-21 12:00"], tz="UTC")
    with pytest.raises(ValueError, match="altitude_m"):
        calculate_solar_geometry(
            times,
            latitude_deg=0.0,
            longitude_deg=0.0,
            altitude_m=altitude,  # type: ignore[arg-type]
        )


def test_negative_altitude_is_allowed_and_matches_pvlib() -> None:
    times = pd.DatetimeIndex(["2026-06-21 12:00"], tz="Asia/Jerusalem")
    result = _calculate(times, latitude=31.5, longitude=35.5, altitude=-430.0)
    _assert_matches_pvlib(
        result,
        times,
        latitude=31.5,
        longitude=35.5,
        altitude=-430.0,
    )


@pytest.mark.parametrize("times", [[pd.Timestamp("2026-01-01")], "2026-01-01", 1])
def test_times_must_be_a_datetime_index(times: object) -> None:
    with pytest.raises(ValueError, match="pandas DatetimeIndex"):
        calculate_solar_geometry(
            times,  # type: ignore[arg-type]
            latitude_deg=0.0,
            longitude_deg=0.0,
            altitude_m=0.0,
        )


def test_timezone_naive_times_are_rejected() -> None:
    times = pd.DatetimeIndex(["2026-06-21 12:00"])
    with pytest.raises(ValueError, match="timezone-aware"):
        _calculate(times)


@pytest.mark.parametrize(
    "times",
    [
        pd.DatetimeIndex([pd.NaT], tz="UTC"),
        pd.DatetimeIndex(["2026-06-21 12:00", pd.NaT], tz="UTC"),
    ],
)
def test_missing_timestamps_are_rejected(times: pd.DatetimeIndex) -> None:
    with pytest.raises(ValueError, match="NaT"):
        _calculate(times)


def test_duplicate_timestamps_are_rejected() -> None:
    times = pd.DatetimeIndex(
        ["2026-06-21 12:00", "2026-06-21 12:00"],
        tz="UTC",
    )
    with pytest.raises(ValueError, match="duplicate"):
        _calculate(times)


def test_empty_input_returns_exact_typed_schema_and_index() -> None:
    times = pd.DatetimeIndex([], tz="Europe/London", name="physical_time")
    result = _calculate(times)
    assert result.empty
    assert list(result.columns) == _OUTPUT_COLUMNS
    assert result.index.equals(times)
    assert result.index.name == "physical_time"
    assert str(result.index.tz) == "Europe/London"
    for column in _OUTPUT_COLUMNS[:-1]:
        assert pd.api.types.is_float_dtype(result[column])
    assert pd.api.types.is_string_dtype(result["solar_position_model"])


def test_input_datetime_index_is_not_mutated() -> None:
    times = pd.DatetimeIndex(
        ["2026-06-21 12:00", "2026-06-21 09:17"],
        tz="Europe/London",
        name="timestamp",
    )
    before = times.copy()
    _calculate(times)
    assert times.equals(before)
    assert times.name == before.name
    assert times.tz == before.tz
