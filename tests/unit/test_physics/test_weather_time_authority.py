"""Exact weather observation identity, elapsed intervals and explicit approximation."""

from dataclasses import FrozenInstanceError, replace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from heliotelligence.physics import weather_time_authority as module


def authority(**changes: Any) -> module.WeatherTimeBasisAuthority:
    return module.WeatherTimeBasisAuthority(
        **dict(
            {
                "value_semantics": "interval_average",
                "timestamp_label": "interval_end",
                "interval_duration_seconds": 3600.0,
                "solar_geometry_evaluation_policy": "interval_midpoint_approximation",
                "parameter_source": "explicit source time specification",
                "confidence": "high",
                "method_reference": "documented hour average and representative instant",
            },
            **changes,
        )
    )


def instant() -> module.WeatherTimeBasisAuthority:
    return authority(
        value_semantics="instantaneous_snapshot",
        timestamp_label="instant",
        interval_duration_seconds=None,
        solar_geometry_evaluation_policy="observation_timestamp",
    )


def test_instantaneous_time_has_no_interval_or_approximation() -> None:
    times = pd.date_range(
        "2026-06-01 10:00", periods=2, freq="h", tz="Europe/London", name="observation"
    )
    result = module.resolve_weather_time_state(times, instant())
    assert result.states.index.identical(times)
    assert result.states.solar_geometry_evaluation_time.tolist() == times.tolist()
    assert result.states.interval_start_time.isna().all()
    assert result.states.interval_midpoint_time.isna().all()
    assert result.states.interval_end_time.isna().all()
    assert result.states.interval_duration_seconds.isna().all()
    assert not result.states.solar_geometry_time_approximation_applied.any()
    assert result.diagnostics.instantaneous_timestamp_count == 2


@pytest.mark.parametrize(
    "label,time",
    [("interval_end", "11:00"), ("interval_start", "10:00"), ("interval_midpoint", "10:30")],
)
def test_three_labels_describe_the_same_physical_hour(label: str, time: str) -> None:
    times = pd.DatetimeIndex([f"2026-06-01 {time}"], tz="Europe/London", name="observation")
    row = module.resolve_weather_time_state(times, authority(timestamp_label=label)).states.iloc[0]
    for name, clock in [
        ("interval_start_time", "10:00"),
        ("interval_midpoint_time", "10:30"),
        ("interval_end_time", "11:00"),
        ("solar_geometry_evaluation_time", "10:30"),
    ]:
        assert row[name] == pd.Timestamp(f"2026-06-01 {clock}", tz="Europe/London")
    assert row.solar_geometry_time_approximation_applied
    assert row.observation_timestamp == times[0]


@pytest.mark.parametrize("utc_time", ["2026-03-29 01:30", "2026-10-25 01:30"])
@pytest.mark.parametrize("label", ["interval_start", "interval_midpoint", "interval_end"])
def test_dst_interval_uses_physical_elapsed_time(utc_time: str, label: str) -> None:
    times = pd.DatetimeIndex([utc_time], tz="UTC", name="time").tz_convert("Europe/London")
    result = module.resolve_weather_time_state(times, authority(timestamp_label=label))
    row = result.states.iloc[0]
    assert row.interval_end_time - row.interval_start_time == pd.Timedelta(hours=1)
    assert row.interval_midpoint_time - row.interval_start_time == pd.Timedelta(minutes=30)
    assert str(row.interval_start_time.tz) == "Europe/London"
    assert result.states.index.identical(times)


@pytest.mark.parametrize(
    "changes",
    [
        {"value_semantics": "snapshot"},
        {"timestamp_label": "instant"},
        {"interval_duration_seconds": None},
        {"interval_duration_seconds": 0},
        {"interval_duration_seconds": -1},
        {"interval_duration_seconds": np.nan},
        {"interval_duration_seconds": np.inf},
        {"interval_duration_seconds": True},
        {"solar_geometry_evaluation_policy": "observation_timestamp"},
        {"parameter_source": ""},
        {"parameter_source": " padded"},
        {"method_reference": "trailing "},
        {"confidence": "HIGH"},
    ],
)
def test_invalid_authority_combinations_and_provenance(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        authority(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"timestamp_label": "interval_end"},
        {"interval_duration_seconds": 3600},
        {"solar_geometry_evaluation_policy": "interval_midpoint_approximation"},
    ],
)
def test_instantaneous_authority_cannot_claim_an_interval(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        replace(instant(), **changes)


@pytest.mark.parametrize("kind", ["naive", "duplicate", "nat", "list"])
def test_invalid_observation_index(kind: str) -> None:
    times: Any = pd.date_range("2026-06-01", periods=2, freq="h", tz="UTC")
    if kind == "naive":
        times = times.tz_localize(None)
    elif kind == "duplicate":
        times = pd.DatetimeIndex([times[0], times[0]])
    elif kind == "nat":
        times = pd.DatetimeIndex([times[0], pd.NaT])
    else:
        times = list(times)
    with pytest.raises(ValueError):
        module.resolve_weather_time_state(times, authority())


def test_order_empty_results_and_immutability() -> None:
    times = pd.date_range("2026-06-01", periods=3, freq="h", tz="UTC").take([2, 0, 1])
    result = module.resolve_weather_time_state(times, authority())
    assert result.states.index.identical(times)
    empty = module.resolve_weather_time_state(times[:0], instant())
    assert empty.states.empty and empty.diagnostics.timestamp_count == 0
    assert str(empty.states.solar_geometry_evaluation_time.dtype) == "datetime64[ns, UTC]"
    with pytest.raises(FrozenInstanceError):
        result.authority = instant()  # type: ignore[misc]


@pytest.mark.parametrize(
    "column",
    [
        "interval_start_time",
        "interval_midpoint_time",
        "interval_end_time",
        "solar_geometry_evaluation_time",
        "solar_geometry_time_approximation_applied",
        "weather_time_authority_contract",
    ],
)
def test_independent_temporal_replay_rejects_tampering(column: str) -> None:
    result = module.resolve_weather_time_state(
        pd.date_range("2026-06-01", periods=1, tz="UTC"), authority()
    )
    frame = result.states.copy()
    if column.endswith("time"):
        frame.loc[frame.index[0], column] += pd.Timedelta(minutes=1)
    elif column.endswith("applied"):
        frame.loc[frame.index[0], column] = False
    else:
        frame.loc[frame.index[0], column] = "wrong"
    with pytest.raises(ValueError, match="independent validation"):
        module.validate_weather_time_state(replace(result, states=frame))


def test_validator_does_not_call_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    result = module.resolve_weather_time_state(
        pd.date_range("2026-06-01", periods=1, tz="UTC"), authority()
    )

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("builder called")

    monkeypatch.setattr(module, "_frame", fail)
    module.validate_weather_time_state(result)
    with pytest.raises(ValueError, match="diagnostics"):
        module.validate_weather_time_state(
            replace(result, diagnostics=replace(result.diagnostics, timestamp_count=99))
        )


def test_temporal_contract_ids_and_fractional_seconds_are_explicit() -> None:
    assert module.WEATHER_TIME_AUTHORITY_CONTRACT_ID == (
        "explicit_weather_observation_interval_and_solar_geometry_evaluation_time_authority_v1"
    )
    assert module.WEATHER_TIME_AUTHORITY_MODEL_ID == (
        "instantaneous_or_interval_average_label_to_explicit_representative_solar_geometry_time_v1"
    )
    times = pd.date_range("2026-06-01", periods=1, tz="UTC")
    result = module.resolve_weather_time_state(times, authority(interval_duration_seconds=1.5))
    row = result.states.iloc[0]
    assert row.interval_end_time - row.interval_start_time == pd.Timedelta(seconds=1.5)
    assert row.interval_end_time - row.interval_midpoint_time == pd.Timedelta(seconds=0.75)
    with pytest.raises(ValueError):
        authority(interval_duration_seconds=1e-9)
