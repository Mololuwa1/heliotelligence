"""Quality flag assignment — pure functions, no I/O.

Rules applied before upsert:
  - quality = 2 (FLAGGED) if ws_com_status != 'OK' (weather rows)
  - quality = 2 (FLAGGED) if inv_coms_status != 'OK' (inverter rows)

String and meter rows inherit no direct comms status at this stage;
their flags default to 0 and are overridden if needed in future rules.
"""

from __future__ import annotations

from heliotelligence.models.schemas import (
    InverterReadingIn,
    MeterReadingIn,
    StringReadingIn,
    WeatherReadingIn,
)

QUALITY_GOOD = 0
QUALITY_GAP_FILLED = 1
QUALITY_FLAGGED = 2
QUALITY_MISSING = 3


def flag_weather(rows: list[WeatherReadingIn]) -> list[WeatherReadingIn]:
    result: list[WeatherReadingIn] = []
    for row in rows:
        if row.ws_com_status is not None and row.ws_com_status.strip().upper() != "OK":
            row = row.model_copy(update={"quality": QUALITY_FLAGGED})
        result.append(row)
    return result


def flag_meter(rows: list[MeterReadingIn]) -> list[MeterReadingIn]:
    """Meter rows: no direct comms status column — pass through unchanged."""
    return list(rows)


def flag_inverters(rows: list[InverterReadingIn]) -> list[InverterReadingIn]:
    result: list[InverterReadingIn] = []
    for row in rows:
        if row.inv_coms_status is not None and row.inv_coms_status.strip().upper() != "OK":
            row = row.model_copy(update={"quality": QUALITY_FLAGGED})
        result.append(row)
    return result


def flag_strings(rows: list[StringReadingIn]) -> list[StringReadingIn]:
    """String rows: no direct comms status — pass through unchanged."""
    return list(rows)


def apply_all_flags(
    weather: list[WeatherReadingIn],
    meter: list[MeterReadingIn],
    inverters: list[InverterReadingIn],
    strings: list[StringReadingIn],
) -> tuple[
    list[WeatherReadingIn],
    list[MeterReadingIn],
    list[InverterReadingIn],
    list[StringReadingIn],
]:
    """Convenience wrapper: apply all flag rules in one call."""
    return (
        flag_weather(weather),
        flag_meter(meter),
        flag_inverters(inverters),
        flag_strings(strings),
    )
