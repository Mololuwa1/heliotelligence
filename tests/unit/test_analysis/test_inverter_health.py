"""Unit tests for heliotelligence.analysis.inverter_health.

Tests
-----
1. inv_avail_pct=0 produces an 'offline' fault event
2. inv_coms_status != 'OK' produces a 'comms_fault' event
3. Healthy inverter produces no fault events
4. Consecutive fault timestamps grouped into single fault event
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from heliotelligence.analysis.inverter_health import _compute_inverter_health

_START = datetime(2024, 6, 21, 0, tzinfo=timezone.utc)
_END = datetime(2024, 6, 22, 0, tzinfo=timezone.utc)


def _df(rows: list[tuple]) -> pd.DataFrame:
    """Build an inverter_readings DataFrame from (time, inverter_id, avail, status) rows."""
    idx = pd.DatetimeIndex([pd.Timestamp(r[0], tz="UTC") for r in rows])
    data = {
        "inverter_id": [r[1] for r in rows],
        "inv_avail_pct": [r[2] for r in rows],
        "inv_coms_status": [r[3] for r in rows],
    }
    return pd.DataFrame(data, index=idx)


# ---------------------------------------------------------------------------
# Test 1 — inv_avail_pct=0 → 'offline' fault event
# ---------------------------------------------------------------------------

def test_offline_fault_from_avail_zero():
    """A single row with inv_avail_pct=0 must produce one 'offline' fault event."""
    rows = [("2024-06-21 10:00", "inv01", 0.0, "OK")]
    df = _df(rows)

    result = _compute_inverter_health(df, _START, _END)

    assert result["fault_event_count"] >= 1
    types = [e["fault_type"] for e in result["fault_events"]]
    assert "offline" in types


def test_offline_event_has_correct_inverter_id():
    """Offline fault event must reference the correct inverter_id."""
    rows = [
        ("2024-06-21 10:00", "inv01", 100.0, "OK"),
        ("2024-06-21 10:00", "inv02", 0.0, "OK"),
    ]
    df = _df(rows)

    result = _compute_inverter_health(df, _START, _END)

    offline = [e for e in result["fault_events"] if e["fault_type"] == "offline"]
    assert len(offline) == 1
    assert offline[0]["inverter_id"] == "inv02"


# ---------------------------------------------------------------------------
# Test 2 — inv_coms_status != 'OK' → 'comms_fault' event
# ---------------------------------------------------------------------------

def test_comms_fault_from_bad_status():
    """A row with inv_coms_status='FAULT' must produce a 'comms_fault' event."""
    rows = [("2024-06-21 10:00", "inv01", 100.0, "FAULT")]
    df = _df(rows)

    result = _compute_inverter_health(df, _START, _END)

    assert result["fault_event_count"] >= 1
    types = [e["fault_type"] for e in result["fault_events"]]
    assert "comms_fault" in types


def test_comms_fault_various_non_ok_statuses():
    """Multiple non-OK status values must all produce comms_fault events."""
    rows = [
        ("2024-06-21 10:00", "inv01", 100.0, "ERROR"),
        ("2024-06-21 11:00", "inv02", 100.0, "DISCONNECTED"),
    ]
    df = _df(rows)

    result = _compute_inverter_health(df, _START, _END)

    comms = [e for e in result["fault_events"] if e["fault_type"] == "comms_fault"]
    assert len(comms) == 2


# ---------------------------------------------------------------------------
# Test 3 — Healthy inverter produces no events
# ---------------------------------------------------------------------------

def test_healthy_inverter_no_events():
    """Inverter with inv_avail_pct=100 and status='OK' must produce no fault events."""
    rows = [
        ("2024-06-21 10:00", "inv01", 100.0, "OK"),
        ("2024-06-21 11:00", "inv01", 100.0, "OK"),
        ("2024-06-21 12:00", "inv01", 100.0, "OK"),
    ]
    df = _df(rows)

    result = _compute_inverter_health(df, _START, _END)

    assert result["fault_event_count"] == 0
    assert result["fault_events"] == []


# ---------------------------------------------------------------------------
# Test 4 — Consecutive faults grouped into single event
# ---------------------------------------------------------------------------

def test_consecutive_faults_grouped():
    """Three consecutive hourly offline timestamps must produce one fault event."""
    rows = [
        ("2024-06-21 10:00", "inv01", 0.0, "OK"),
        ("2024-06-21 11:00", "inv01", 0.0, "OK"),
        ("2024-06-21 12:00", "inv01", 0.0, "OK"),
    ]
    df = _df(rows)

    result = _compute_inverter_health(df, _START, _END)

    offline = [e for e in result["fault_events"] if e["fault_type"] == "offline"]
    assert len(offline) == 1, f"Expected 1 grouped event, got {len(offline)}"
    assert offline[0]["duration_hours"] == pytest.approx(2.0)


def test_non_consecutive_faults_produce_separate_events():
    """Two offline timestamps separated by > 2 hours must produce two events."""
    rows = [
        ("2024-06-21 08:00", "inv01", 0.0, "OK"),
        ("2024-06-21 15:00", "inv01", 0.0, "OK"),  # 7-hour gap → separate event
    ]
    df = _df(rows)

    result = _compute_inverter_health(df, _START, _END)

    offline = [e for e in result["fault_events"] if e["fault_type"] == "offline"]
    assert len(offline) == 2


# ---------------------------------------------------------------------------
# Test 5 — Empty DataFrame
# ---------------------------------------------------------------------------

def test_empty_df_returns_empty_result():
    """Empty DataFrame must return zero counts and empty list without raising."""
    df = pd.DataFrame(columns=["inverter_id", "inv_avail_pct", "inv_coms_status"])

    result = _compute_inverter_health(df, _START, _END)

    assert result["inverter_count"] == 0
    assert result["fault_event_count"] == 0
    assert result["fault_events"] == []


# ---------------------------------------------------------------------------
# Test 6 — inverter_count correct
# ---------------------------------------------------------------------------

def test_inverter_count_correct():
    """inverter_count must equal the number of distinct inverter IDs."""
    rows = [
        ("2024-06-21 10:00", "inv01", 100.0, "OK"),
        ("2024-06-21 10:00", "inv02", 100.0, "OK"),
        ("2024-06-21 10:00", "inv03", 0.0, "OK"),
    ]
    df = _df(rows)

    result = _compute_inverter_health(df, _START, _END)

    assert result["inverter_count"] == 3
