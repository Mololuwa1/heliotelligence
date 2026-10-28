"""Explicit weather observation/interval semantics, dormant from ingestion/runtime.

Midpoint geometry is an admitted approximation, not interval integration. Neither
source labels nor adjacent rows supply missing temporal authority.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from numbers import Real
from typing import Literal, cast

import pandas as pd  # type: ignore[import-untyped]

WEATHER_TIME_AUTHORITY_CONTRACT_ID = (
    "explicit_weather_observation_interval_and_solar_geometry_evaluation_time_authority_v1"
)
WEATHER_TIME_AUTHORITY_MODEL_ID = (
    "instantaneous_or_interval_average_label_to_explicit_representative_solar_geometry_time_v1"
)
Confidence = Literal["high", "medium", "low", "unknown"]


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be an exact non-empty string without padding")
    return value


@dataclass(frozen=True)
class WeatherTimeBasisAuthority:
    value_semantics: Literal["instantaneous_snapshot", "interval_average"]
    timestamp_label: Literal["instant", "interval_start", "interval_midpoint", "interval_end"]
    interval_duration_seconds: float | None
    solar_geometry_evaluation_policy: Literal[
        "observation_timestamp", "interval_midpoint_approximation"
    ]
    parameter_source: str
    confidence: Confidence
    method_reference: str

    def __post_init__(self) -> None:
        for name in (
            "value_semantics",
            "timestamp_label",
            "solar_geometry_evaluation_policy",
            "parameter_source",
            "confidence",
            "method_reference",
        ):
            _text(getattr(self, name), name)
        if self.confidence not in {"high", "medium", "low", "unknown"}:
            raise ValueError("confidence is unsupported")
        if self.value_semantics == "instantaneous_snapshot":
            if (
                self.timestamp_label != "instant"
                or self.interval_duration_seconds is not None
                or self.solar_geometry_evaluation_policy != "observation_timestamp"
            ):
                raise ValueError(
                    "instantaneous snapshots require instant/no-duration/observation_timestamp"
                )
        elif self.value_semantics == "interval_average":
            if (
                self.timestamp_label not in {"interval_start", "interval_midpoint", "interval_end"}
                or self.solar_geometry_evaluation_policy != "interval_midpoint_approximation"
            ):
                raise ValueError(
                    "interval averages require interval label and midpoint approximation"
                )
            duration = self.interval_duration_seconds
            if (
                isinstance(duration, bool)
                or not isinstance(duration, Real)
                or not math.isfinite(duration)
                or duration <= 0
            ):
                raise ValueError("interval duration must be finite, positive and non-Boolean")
            try:
                elapsed = pd.Timedelta(seconds=float(duration))
            except (OverflowError, ValueError) as exc:
                raise ValueError("interval duration is outside pandas timedelta support") from exc
            if elapsed.value <= 0 or elapsed.value % 2:
                raise ValueError(
                    "duration must support exact nanosecond interval boundaries and midpoint"
                )
        else:
            raise ValueError("unsupported weather value semantics")


_TIME_COLUMNS = (
    "observation_timestamp",
    "interval_start_time",
    "interval_midpoint_time",
    "interval_end_time",
    "solar_geometry_evaluation_time",
)
_TEXT_COLUMNS = (
    "weather_value_semantics",
    "weather_timestamp_label",
    "solar_geometry_evaluation_policy",
    "weather_time_state",
    "parameter_source",
    "confidence",
    "method_reference",
    "weather_time_authority_contract",
    "weather_time_authority_model",
)
_COLUMNS = (
    _TIME_COLUMNS
    + _TEXT_COLUMNS
    + (
        "interval_duration_seconds",
        "time_basis_resolved",
        "solar_geometry_time_approximation_applied",
    )
)


@dataclass(frozen=True)
class WeatherTimeDiagnostics:
    timestamp_count: int
    instantaneous_timestamp_count: int
    interval_average_timestamp_count: int
    approximation_timestamp_count: int


@dataclass(frozen=True)
class WeatherTimeStateResult:
    states: pd.DataFrame
    diagnostics: WeatherTimeDiagnostics
    observation_times: pd.DatetimeIndex
    authority: WeatherTimeBasisAuthority


def _admit(
    times: pd.DatetimeIndex, authority: WeatherTimeBasisAuthority
) -> WeatherTimeBasisAuthority:
    if type(times) is not pd.DatetimeIndex or times.tz is None:
        raise ValueError("observation_times must be a timezone-aware DatetimeIndex")
    if times.hasnans or not times.is_unique:
        raise ValueError("observation_times must be unique and free of NaT")
    if type(authority) is not WeatherTimeBasisAuthority:
        raise TypeError("authority must be exact WeatherTimeBasisAuthority")
    return replace(authority)


def _frame(times: pd.DatetimeIndex, authority: WeatherTimeBasisAuthority) -> pd.DataFrame:
    interval = authority.value_semantics == "interval_average"
    duration = (
        pd.Timedelta(seconds=authority.interval_duration_seconds) if interval else pd.Timedelta(0)
    )
    if not interval:
        start = midpoint = end = pd.DatetimeIndex([pd.NaT] * len(times), tz=times.tz)
    else:
        start = (
            times
            if authority.timestamp_label == "interval_start"
            else times - duration
            if authority.timestamp_label == "interval_end"
            else times - duration / 2
        )
        midpoint, end = start + duration / 2, start + duration
    result = pd.DataFrame(index=times.copy(), columns=_COLUMNS)
    for name, values in zip(
        _TIME_COLUMNS, (times, start, midpoint, end, midpoint if interval else times), strict=True
    ):
        result[name] = pd.Series(
            values, index=times, dtype=pd.DatetimeTZDtype(unit="ns", tz=times.tz)
        )
    values = (
        authority.value_semantics,
        authority.timestamp_label,
        authority.solar_geometry_evaluation_policy,
        "resolved_interval_average_midpoint_approximation"
        if interval
        else "resolved_instantaneous_weather_time",
        authority.parameter_source,
        authority.confidence,
        authority.method_reference,
        WEATHER_TIME_AUTHORITY_CONTRACT_ID,
        WEATHER_TIME_AUTHORITY_MODEL_ID,
    )
    for name, value in zip(_TEXT_COLUMNS, values, strict=True):
        result[name] = pd.Series(value, index=times, dtype=object)
    result["interval_duration_seconds"] = pd.Series(
        float(cast(float, authority.interval_duration_seconds)) if interval else math.nan,
        index=times,
        dtype=float,
    )
    result["time_basis_resolved"] = pd.Series(True, index=times, dtype=bool)
    result["solar_geometry_time_approximation_applied"] = pd.Series(
        interval, index=times, dtype=bool
    )
    return result


def resolve_weather_time_state(
    observation_times: pd.DatetimeIndex,
    authority: WeatherTimeBasisAuthority,
) -> WeatherTimeStateResult:
    authority = _admit(observation_times, authority)
    frame = _frame(observation_times, authority)
    count = len(observation_times)
    interval = authority.value_semantics == "interval_average"
    result = WeatherTimeStateResult(
        frame,
        WeatherTimeDiagnostics(
            count, 0 if interval else count, count if interval else 0, count if interval else 0
        ),
        observation_times.copy(),
        authority,
    )
    validate_weather_time_state(result)
    return result


def validate_weather_time_state(result: WeatherTimeStateResult) -> None:
    """Reconstruct boundaries in UTC elapsed time; never invoke the production builder."""
    if type(result) is not WeatherTimeStateResult:
        raise TypeError("invalid weather-time result type")
    authority = _admit(result.observation_times, result.authority)
    times = result.observation_times
    interval = authority.value_semantics == "interval_average"
    records = []
    for timestamp in times:
        start = midpoint = end = pd.NaT
        evaluation = timestamp
        if interval:
            offset = pd.Timedelta(seconds=authority.interval_duration_seconds)
            utc = timestamp.tz_convert("UTC")
            if authority.timestamp_label == "interval_start":
                beginning = utc
            elif authority.timestamp_label == "interval_end":
                beginning = utc - offset
            else:
                beginning = utc - offset / 2
            start = beginning.tz_convert(times.tz)
            midpoint = (beginning + offset / 2).tz_convert(times.tz)
            end = (beginning + offset).tz_convert(times.tz)
            evaluation = midpoint
        records.append(
            dict(zip(_TIME_COLUMNS, (timestamp, start, midpoint, end, evaluation), strict=True))
        )
    expected = pd.DataFrame(records, index=times.copy(), columns=_COLUMNS)
    for name in _TIME_COLUMNS:
        expected[name] = pd.Series(
            pd.DatetimeIndex(expected[name], tz=times.tz),
            index=times,
            dtype=pd.DatetimeTZDtype(unit="ns", tz=times.tz),
        )
    metadata = {
        "weather_value_semantics": authority.value_semantics,
        "weather_timestamp_label": authority.timestamp_label,
        "solar_geometry_evaluation_policy": authority.solar_geometry_evaluation_policy,
        "weather_time_state": "resolved_interval_average_midpoint_approximation"
        if interval
        else "resolved_instantaneous_weather_time",
        "parameter_source": authority.parameter_source,
        "confidence": authority.confidence,
        "method_reference": authority.method_reference,
        "weather_time_authority_contract": WEATHER_TIME_AUTHORITY_CONTRACT_ID,
        "weather_time_authority_model": WEATHER_TIME_AUTHORITY_MODEL_ID,
    }
    for name, value in metadata.items():
        expected[name] = pd.Series(value, index=times, dtype=object)
    expected["interval_duration_seconds"] = pd.Series(
        authority.interval_duration_seconds if interval else math.nan, index=times, dtype=float
    )
    expected["time_basis_resolved"] = pd.Series(True, index=times, dtype=bool)
    expected["solar_geometry_time_approximation_applied"] = pd.Series(
        interval, index=times, dtype=bool
    )
    try:
        pd.testing.assert_frame_equal(result.states, expected, check_exact=True)
    except (AssertionError, TypeError, ValueError) as exc:
        raise ValueError("weather-time state failed independent validation") from exc
    count = len(times)
    diagnostics = WeatherTimeDiagnostics(
        count, count if not interval else 0, count if interval else 0, count if interval else 0
    )
    if result.diagnostics != diagnostics:
        raise ValueError("weather-time diagnostics failed independent validation")
