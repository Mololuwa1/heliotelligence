"""Unit tests for ingest.csv_parser — uses bracon_ash_sample.csv fixture."""

from __future__ import annotations

import textwrap
from io import StringIO
from pathlib import Path

import pandas as pd
import pytest

from heliotelligence.ingest.csv_parser import (
    _detect_interval,
    _find_timestamp_column,
    parse_csv,
)


SITE_ID = "bracon-ash-001"
SITE_NAME = "Bracon Ash"


# ---------------------------------------------------------------------------
# _find_timestamp_column
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("col_name", ["Timestamp", "timestamp", "Date/Time", "datetime", "time"])
def test_find_timestamp_column_aliases(col_name: str):
    df = pd.DataFrame({col_name: ["2024-01-01"], "other": [1.0]})
    assert _find_timestamp_column(df) == col_name


def test_find_timestamp_column_returns_none_when_absent():
    df = pd.DataFrame({"A": [1], "B": [2]})
    assert _find_timestamp_column(df) is None


def test_find_timestamp_column_case_insensitive():
    df = pd.DataFrame({"TIMESTAMP": ["2024-01-01"]})
    assert _find_timestamp_column(df) == "TIMESTAMP"


# ---------------------------------------------------------------------------
# _detect_interval
# ---------------------------------------------------------------------------

def _ts_series(*times: str) -> pd.Series:
    return pd.Series(pd.to_datetime(list(times)))


def test_detect_interval_60min():
    s = _ts_series("2024-01-01 00:00", "2024-01-01 01:00", "2024-01-01 02:00")
    assert _detect_interval(s) == pd.Timedelta(minutes=60)


def test_detect_interval_30min():
    s = _ts_series(
        "2024-01-01 00:00", "2024-01-01 00:30",
        "2024-01-01 01:00", "2024-01-01 01:30",
    )
    assert _detect_interval(s) == pd.Timedelta(minutes=30)


def test_detect_interval_15min():
    times = [f"2024-01-01 {h:02d}:{m:02d}" for h in range(2) for m in (0, 15, 30, 45)]
    s = _ts_series(*times)
    assert _detect_interval(s) == pd.Timedelta(minutes=15)


def test_detect_interval_5min():
    times = [f"2024-01-01 00:{m:02d}" for m in range(0, 60, 5)]
    s = _ts_series(*times)
    assert _detect_interval(s) == pd.Timedelta(minutes=5)


def test_detect_interval_single_row_returns_default():
    s = _ts_series("2024-01-01 00:00")
    # Single row → diffs empty → default 5 minutes
    assert _detect_interval(s) == pd.Timedelta(minutes=5)


# ---------------------------------------------------------------------------
# parse_csv — row counts
# ---------------------------------------------------------------------------

def test_parse_csv_returns_all_four_groups(bracon_ash_csv: Path):
    weather, meter, inverters, strings = parse_csv(bracon_ash_csv, SITE_ID, SITE_NAME)
    assert len(weather) == 24, "one weather row per CSV row"
    assert len(meter) == 24, "one meter row per CSV row"
    # 2 inverters × 24 hours
    assert len(inverters) == 48, "two inverter rows per CSV row"
    # 4 strings × 24 hours
    assert len(strings) == 96, "four string rows per CSV row"


# ---------------------------------------------------------------------------
# parse_csv — timestamps are UTC and period-END shifted
# ---------------------------------------------------------------------------

def test_parse_csv_timestamps_are_utc_aware(bracon_ash_csv: Path):
    weather, _, _, _ = parse_csv(bracon_ash_csv, SITE_ID, SITE_NAME)
    for row in weather:
        assert row.time.tzinfo is not None
        assert str(row.time.tzinfo) in ("UTC", "UTC+00:00") or row.time.utcoffset().total_seconds() == 0


def test_parse_csv_first_timestamp_period_end_shifted(bracon_ash_csv: Path):
    """First CSV row is 2024-06-21 00:00 BST (UTC+1) = 2024-06-20 23:00 UTC.
    Period-end shift +1h → 2024-06-21 00:00 UTC."""
    weather, _, _, _ = parse_csv(bracon_ash_csv, SITE_ID, SITE_NAME)
    first_ts = min(r.time for r in weather)
    assert first_ts.year == 2024
    assert first_ts.month == 6
    assert first_ts.day == 21
    assert first_ts.hour == 0
    assert first_ts.minute == 0


def test_parse_csv_timestamps_monotonically_increasing(bracon_ash_csv: Path):
    weather, _, _, _ = parse_csv(bracon_ash_csv, SITE_ID, SITE_NAME)
    ts_list = sorted(r.time for r in weather)
    for i in range(1, len(ts_list)):
        assert ts_list[i] > ts_list[i - 1]


def test_parse_csv_interval_is_one_hour(bracon_ash_csv: Path):
    weather, _, _, _ = parse_csv(bracon_ash_csv, SITE_ID, SITE_NAME)
    ts_list = sorted(r.time for r in weather)
    diffs = {(ts_list[i] - ts_list[i - 1]).total_seconds() for i in range(1, len(ts_list))}
    assert diffs == {3600.0}


# ---------------------------------------------------------------------------
# parse_csv — field values
# ---------------------------------------------------------------------------

def test_parse_csv_site_id_set(bracon_ash_csv: Path):
    weather, meter, inverters, strings = parse_csv(bracon_ash_csv, SITE_ID, SITE_NAME)
    assert all(r.site_id == SITE_ID for r in weather)
    assert all(r.site_id == SITE_ID for r in meter)
    assert all(r.site_id == SITE_ID for r in inverters)
    assert all(r.site_id == SITE_ID for r in strings)


def test_parse_csv_ghi_peak_row(bracon_ash_csv: Path):
    """Hour 12 BST (peak day) should have GHI = 755 W/m²."""
    weather, _, _, _ = parse_csv(bracon_ash_csv, SITE_ID, SITE_NAME)
    # Peak row: 2024-06-21 12:00 BST = 2024-06-21 11:00 UTC period-end = 12:00 UTC
    peak = next(r for r in weather if r.time.hour == 12 and r.time.day == 21)
    assert peak.ghi_wm2 == pytest.approx(755.0)


def test_parse_csv_night_row_ghi_zero(bracon_ash_csv: Path):
    """Hour 00:00 BST row should have GHI = 0."""
    weather, _, _, _ = parse_csv(bracon_ash_csv, SITE_ID, SITE_NAME)
    night = next(r for r in weather if r.time.hour == 0 and r.time.day == 21)
    assert night.ghi_wm2 == pytest.approx(0.0)


def test_parse_csv_module_temp_averaged(bracon_ash_csv: Path):
    """PT1000-MODULE-1 and PT1000-MODULE-2 must be averaged into temp_mod_avg_c.
    At 12:00 BST row: mod1=38.0, mod2=40.0 → avg=39.0."""
    weather, _, _, _ = parse_csv(bracon_ash_csv, SITE_ID, SITE_NAME)
    peak = next(r for r in weather if r.time.hour == 12 and r.time.day == 21)
    assert peak.temp_mod_avg_c == pytest.approx(39.0)


def test_parse_csv_inverter_ids_present(bracon_ash_csv: Path):
    _, _, inverters, _ = parse_csv(bracon_ash_csv, SITE_ID, SITE_NAME)
    ids = {r.inverter_id for r in inverters}
    assert "MQA11-TB101" in ids
    assert "MQA11-TB102" in ids


def test_parse_csv_string_ids_present(bracon_ash_csv: Path):
    _, _, _, strings = parse_csv(bracon_ash_csv, SITE_ID, SITE_NAME)
    keys = {(r.inverter_id, r.string_id) for r in strings}
    assert ("MQA11-TB101", "STR01") in keys
    assert ("MQA11-TB101", "STR02") in keys
    assert ("MQA11-TB102", "STR01") in keys
    assert ("MQA11-TB102", "STR02") in keys


def test_parse_csv_meter_frequency(bracon_ash_csv: Path):
    _, meter, _, _ = parse_csv(bracon_ash_csv, SITE_ID, SITE_NAME)
    # All daytime rows have freq_hz set; check a specific one
    row_12 = next(r for r in meter if r.time.hour == 12)
    assert row_12.freq_hz == pytest.approx(50.01)


# ---------------------------------------------------------------------------
# parse_csv — comms status preserved (quality flagging is in flags.py)
# ---------------------------------------------------------------------------

def test_parse_csv_com_status_preserved(bracon_ash_csv: Path):
    """COM STATUS = FAULT at BST 10:00 must reach ws_com_status."""
    weather, _, _, _ = parse_csv(bracon_ash_csv, SITE_ID, SITE_NAME)
    # BST 10:00 = UTC 09:00 + 1h interval = UTC 10:00
    fault_row = next(r for r in weather if r.time.hour == 10 and r.time.day == 21)
    assert fault_row.ws_com_status == "FAULT"


def test_parse_csv_inverter_coms_fault_preserved(bracon_ash_csv: Path):
    """COMS STATUS = FAULT for MQA11-TB101 at BST 14:00 must be preserved."""
    _, _, inverters, _ = parse_csv(bracon_ash_csv, SITE_ID, SITE_NAME)
    # BST 14:00 → UTC 13:00 + 1h = UTC 14:00
    fault_rows = [
        r for r in inverters
        if r.time.hour == 14 and r.time.day == 21 and r.inverter_id == "MQA11-TB101"
    ]
    assert len(fault_rows) == 1
    assert fault_rows[0].inv_coms_status == "FAULT"


# ---------------------------------------------------------------------------
# parse_csv — missing timestamp column raises
# ---------------------------------------------------------------------------

def test_parse_csv_no_timestamp_raises(tmp_path: Path):
    csv_file = tmp_path / "bad.csv"
    csv_file.write_text("A,B\n1,2\n3,4\n")
    with pytest.raises(ValueError, match="No timestamp column"):
        parse_csv(csv_file, SITE_ID, SITE_NAME)


# ---------------------------------------------------------------------------
# parse_csv — NaN values in numeric columns don't crash
# ---------------------------------------------------------------------------

def test_parse_csv_nan_values_skipped(tmp_path: Path):
    """A CSV with some NaN numeric cells should not raise."""
    content = textwrap.dedent("""\
        Timestamp,Bracon Ash - WEATHER STATION CT01 - SMP10-GHI-F (W/m²),Bracon Ash - CFD METER - ACTIVE POWER (kW)
        2024-06-21 06:00,,5.0
        2024-06-21 07:00,210.0,
    """)
    csv_file = tmp_path / "nan_test.csv"
    csv_file.write_text(content)
    weather, meter, _, _ = parse_csv(csv_file, SITE_ID, SITE_NAME)
    # Row 1: GHI is NaN → weather_scalars empty for ghi, but meter has p_ac_kw
    # Row 2: meter is NaN → meter_scalars empty, but weather has ghi
    assert len(weather) + len(meter) >= 1  # at least some rows parsed


# ---------------------------------------------------------------------------
# parse_csv — deduplication (inverter + string)
# ---------------------------------------------------------------------------

def test_parse_csv_inverter_deduplication(tmp_path: Path):
    """Duplicate (inverter_id, ts) keeps the last entry."""
    content = (
        "Timestamp,"
        "Bracon Ash - MQA11-TB101 - TOTAL ACTIVE POWER (kW),"
        "Bracon Ash - MQA11-TB101 - TOTAL POWER YIELDS (kWh)\n"
        "2024-06-21 12:00,25.0,600.0\n"
        "2024-06-21 12:00,30.0,605.0\n"  # same timestamp again
    )
    csv_file = tmp_path / "dup_inv.csv"
    csv_file.write_text(content)
    _, _, inverters, _ = parse_csv(csv_file, SITE_ID, SITE_NAME)
    assert len(inverters) == 1
    assert inverters[0].inv_p_ac_kw == pytest.approx(30.0)
