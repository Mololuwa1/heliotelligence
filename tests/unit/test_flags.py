"""Unit tests for quality.flags — pure functions, no I/O."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from heliotelligence.quality.flags import (
    QUALITY_FLAGGED,
    QUALITY_GOOD,
    apply_all_flags,
    flag_inverters,
    flag_meter,
    flag_strings,
    flag_weather,
)
from heliotelligence.models.schemas import (
    InverterReadingIn,
    MeterReadingIn,
    StringReadingIn,
    WeatherReadingIn,
)

_TS = datetime(2024, 6, 21, 12, 0, tzinfo=timezone.utc)
_SITE = "bracon-ash-001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _weather(ws_com_status: str | None = "OK") -> WeatherReadingIn:
    return WeatherReadingIn(site_id=_SITE, time=_TS, ghi_wm2=500.0, ws_com_status=ws_com_status)


def _meter() -> MeterReadingIn:
    return MeterReadingIn(site_id=_SITE, time=_TS, p_ac_kw=50.0)


def _inverter(inv_coms_status: str | None = "OK") -> InverterReadingIn:
    return InverterReadingIn(
        site_id=_SITE, inverter_id="MQA11-TB101", time=_TS,
        inv_p_ac_kw=25.0, inv_coms_status=inv_coms_status,
    )


def _string() -> StringReadingIn:
    return StringReadingIn(
        site_id=_SITE, inverter_id="MQA11-TB101", string_id="STR01",
        time=_TS, str_current_a=10.0,
    )


# ---------------------------------------------------------------------------
# flag_weather
# ---------------------------------------------------------------------------

def test_flag_weather_ok_stays_good():
    result = flag_weather([_weather("OK")])
    assert result[0].quality == QUALITY_GOOD


def test_flag_weather_non_ok_flagged():
    result = flag_weather([_weather("FAULT")])
    assert result[0].quality == QUALITY_FLAGGED


def test_flag_weather_error_string_flagged():
    result = flag_weather([_weather("ERROR")])
    assert result[0].quality == QUALITY_FLAGGED


def test_flag_weather_none_status_stays_good():
    result = flag_weather([_weather(None)])
    assert result[0].quality == QUALITY_GOOD


def test_flag_weather_lowercase_ok_stays_good():
    result = flag_weather([_weather("ok")])
    assert result[0].quality == QUALITY_GOOD


def test_flag_weather_whitespace_ok_stays_good():
    result = flag_weather([_weather("  OK  ")])
    assert result[0].quality == QUALITY_GOOD


def test_flag_weather_mixed_case_non_ok_flagged():
    result = flag_weather([_weather("Fault")])
    assert result[0].quality == QUALITY_FLAGGED


def test_flag_weather_empty_list():
    assert flag_weather([]) == []


def test_flag_weather_multiple_rows():
    rows = [_weather("OK"), _weather("FAULT"), _weather("OK"), _weather("ERROR")]
    result = flag_weather(rows)
    assert [r.quality for r in result] == [0, 2, 0, 2]


def test_flag_weather_returns_new_objects():
    """flag_weather must not mutate the input row."""
    original = _weather("FAULT")
    result = flag_weather([original])
    assert original.quality == QUALITY_GOOD  # unchanged
    assert result[0].quality == QUALITY_FLAGGED


# ---------------------------------------------------------------------------
# flag_meter
# ---------------------------------------------------------------------------

def test_flag_meter_passthrough():
    rows = [_meter(), _meter()]
    result = flag_meter(rows)
    assert len(result) == 2
    assert all(r.quality == QUALITY_GOOD for r in result)


def test_flag_meter_empty():
    assert flag_meter([]) == []


def test_flag_meter_returns_list_copy():
    rows = [_meter()]
    result = flag_meter(rows)
    assert result is not rows  # new list object


# ---------------------------------------------------------------------------
# flag_inverters
# ---------------------------------------------------------------------------

def test_flag_inverters_ok_stays_good():
    result = flag_inverters([_inverter("OK")])
    assert result[0].quality == QUALITY_GOOD


def test_flag_inverters_fault_flagged():
    result = flag_inverters([_inverter("FAULT")])
    assert result[0].quality == QUALITY_FLAGGED


def test_flag_inverters_none_status_stays_good():
    result = flag_inverters([_inverter(None)])
    assert result[0].quality == QUALITY_GOOD


def test_flag_inverters_lowercase_ok():
    result = flag_inverters([_inverter("ok")])
    assert result[0].quality == QUALITY_GOOD


def test_flag_inverters_multiple_rows():
    rows = [_inverter("OK"), _inverter("FAULT"), _inverter("OK")]
    result = flag_inverters(rows)
    assert [r.quality for r in result] == [0, 2, 0]


def test_flag_inverters_empty():
    assert flag_inverters([]) == []


def test_flag_inverters_does_not_mutate_input():
    original = _inverter("FAULT")
    result = flag_inverters([original])
    assert original.quality == QUALITY_GOOD
    assert result[0].quality == QUALITY_FLAGGED


# ---------------------------------------------------------------------------
# flag_strings
# ---------------------------------------------------------------------------

def test_flag_strings_passthrough():
    rows = [_string(), _string()]
    result = flag_strings(rows)
    assert all(r.quality == QUALITY_GOOD for r in result)


def test_flag_strings_empty():
    assert flag_strings([]) == []


# ---------------------------------------------------------------------------
# apply_all_flags
# ---------------------------------------------------------------------------

def test_apply_all_flags_returns_four_lists():
    weather, meter, inverters, strings = apply_all_flags(
        [_weather("OK"), _weather("FAULT")],
        [_meter()],
        [_inverter("OK"), _inverter("ERROR")],
        [_string()],
    )
    assert len(weather) == 2
    assert len(meter) == 1
    assert len(inverters) == 2
    assert len(strings) == 1


def test_apply_all_flags_weather_flagged():
    weather, _, _, _ = apply_all_flags(
        [_weather("FAULT")], [], [], []
    )
    assert weather[0].quality == QUALITY_FLAGGED


def test_apply_all_flags_inverter_flagged():
    _, _, inverters, _ = apply_all_flags(
        [], [], [_inverter("FAULT")], []
    )
    assert inverters[0].quality == QUALITY_FLAGGED


def test_apply_all_flags_empty_inputs():
    weather, meter, inverters, strings = apply_all_flags([], [], [], [])
    assert weather == []
    assert meter == []
    assert inverters == []
    assert strings == []
