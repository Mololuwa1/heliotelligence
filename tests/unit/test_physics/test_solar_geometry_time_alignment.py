"""SPA at representative instants, keeping the original observation key."""

from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from heliotelligence.physics import solar_geometry_time_alignment as module
from heliotelligence.physics.solar_geometry import calculate_solar_geometry
from heliotelligence.physics.weather_time_authority import resolve_weather_time_state
from tests.unit.test_physics.test_weather_time_authority import authority, instant

COORDINATES = dict(latitude_deg=52.56, longitude_deg=1.21, altitude_m=47.0)


def test_interval_solar_geometry_equals_midpoint_not_end() -> None:
    times = pd.DatetimeIndex(["2026-06-01 11:00"], tz="Europe/London", name="observation")
    weather = resolve_weather_time_state(times, authority())
    result = module.calculate_time_aligned_solar_geometry(weather, **COORDINATES)
    reference = calculate_solar_geometry(times - pd.Timedelta(minutes=30), **COORDINATES)
    end_reference = calculate_solar_geometry(times, **COORDINATES)
    assert result.geometry.index.identical(times)
    assert result.geometry.solar_geometry_evaluation_time.iloc[0] == times[0] - pd.Timedelta(
        minutes=30
    )
    for name in reference.columns[:-1]:
        np.testing.assert_allclose(result.geometry[name], reference[name], rtol=0, atol=1e-12)
    assert (
        abs(result.geometry.solar_azimuth_deg.iloc[0] - end_reference.solar_azimuth_deg.iloc[0]) > 1
    )
    assert result.geometry.solar_position_model.iloc[0] == "nrel_spa"
    assert result.geometry.solar_geometry_time_approximation_applied.iloc[0]


def test_instantaneous_and_unsorted_empty_geometry() -> None:
    times = pd.date_range("2026-06-01 09:00", periods=3, freq="h", tz="UTC").take([2, 0, 1])
    weather = resolve_weather_time_state(times, instant())
    result = module.calculate_time_aligned_solar_geometry(weather, **COORDINATES)
    assert result.geometry.index.identical(times)
    assert result.geometry.solar_geometry_evaluation_time.tolist() == times.tolist()
    empty = module.calculate_time_aligned_solar_geometry(
        resolve_weather_time_state(times[:0], instant()), **COORDINATES
    )
    assert empty.geometry.empty


@pytest.mark.parametrize(
    "field", ["solar_zenith_deg", "solar_geometry_evaluation_time", "solar_position_model"]
)
def test_alignment_tampering_rejected(field: str) -> None:
    weather = resolve_weather_time_state(
        pd.date_range("2026-06-01", periods=1, tz="UTC"), authority()
    )
    result = module.calculate_time_aligned_solar_geometry(weather, **COORDINATES)
    frame = result.geometry.copy()
    if field == "solar_position_model":
        frame.loc[frame.index[0], field] = "other"
    elif field == "solar_geometry_evaluation_time":
        frame.loc[frame.index[0], field] += pd.Timedelta(minutes=1)
    else:
        frame.loc[frame.index[0], field] += 1
    with pytest.raises(ValueError, match="independent replay"):
        module.validate_time_aligned_solar_geometry(replace(result, geometry=frame))


def test_validator_is_independent_of_alignment_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    weather = resolve_weather_time_state(
        pd.date_range("2026-06-01", periods=1, tz="UTC"), authority()
    )
    result = module.calculate_time_aligned_solar_geometry(weather, **COORDINATES)

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("builder called")

    monkeypatch.setattr(module, "_calculate", fail)
    module.validate_time_aligned_solar_geometry(result)


def test_alignment_contract_ids_replay_canonical_nrel_spa() -> None:
    assert module.TIME_ALIGNED_SOLAR_GEOMETRY_CONTRACT_ID == (
        "admitted_weather_time_authority_to_observation_keyed_nrel_spa_solar_geometry_v1"
    )
    assert module.TIME_ALIGNED_SOLAR_GEOMETRY_MODEL_ID == (
        "explicit_evaluation_instants_observation_keyed_nrel_spa_replay_v1"
    )
    assert module.SOLAR_POSITION_MODEL_ID == "nrel_spa"
