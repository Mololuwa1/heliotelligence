"""Tests for Solcast backfill — _normalise mapping and chunking logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from heliotelligence.collectors.solcast import _normalise, run_solcast_backfill, _CHUNK_DAYS
from heliotelligence.config.site import SiteConfig


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_site() -> SiteConfig:
    return SiteConfig(
        id="test-site-001",
        name="Test Site",
        latitude=52.56,
        longitude=1.21,
        capacity_kwp=1000.0,
        timezone="UTC",
        solcast_resource_id="test-resource-id",
    )


def _make_payload(entries: list[dict]) -> dict:
    return {"estimated_actuals": entries}


def _make_entry(**kwargs) -> dict:
    base = {
        "period_end": "2024-06-01T01:00:00+00:00",
        "ghi": 500.0,
        "dni": 400.0,
        "dhi": 100.0,
        "air_temp": 22.5,
        "wind_speed_10m": 3.8,
        "period": "PT60M",
    }
    base.update(kwargs)
    return base


# ── _normalise: field mapping ─────────────────────────────────────────────────

def test_normalise_maps_ghi():
    site = _make_site()
    rows = _normalise(_make_payload([_make_entry(ghi=550.0)]), site)
    assert rows[0].ghi_wm2 == 550.0


def test_normalise_maps_dni():
    site = _make_site()
    rows = _normalise(_make_payload([_make_entry(dni=420.0)]), site)
    assert rows[0].dni_wm2 == 420.0


def test_normalise_maps_dhi():
    site = _make_site()
    rows = _normalise(_make_payload([_make_entry(dhi=130.0)]), site)
    assert rows[0].dhi_wm2 == 130.0


def test_normalise_maps_air_temp_to_temp_amb_c():
    site = _make_site()
    rows = _normalise(_make_payload([_make_entry(air_temp=25.0)]), site)
    assert rows[0].temp_amb_c == 25.0


def test_normalise_maps_wind_speed():
    site = _make_site()
    rows = _normalise(_make_payload([_make_entry(wind_speed_10m=5.5)]), site)
    assert rows[0].wind_speed_ms == 5.5


def test_normalise_maps_period_end_to_time():
    site = _make_site()
    rows = _normalise(_make_payload([_make_entry(period_end="2024-06-15T12:00:00+00:00")]), site)
    assert rows[0].time == datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)


def test_normalise_handles_z_suffix_in_period_end():
    site = _make_site()
    rows = _normalise(_make_payload([_make_entry(period_end="2024-06-15T12:00:00Z")]), site)
    assert rows[0].time == datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)


# ── _normalise: source parameter ─────────────────────────────────────────────

def test_normalise_default_source_is_solcast():
    site = _make_site()
    rows = _normalise(_make_payload([_make_entry()]), site)
    assert rows[0].source == "solcast"


def test_normalise_source_solcast_historic():
    site = _make_site()
    rows = _normalise(_make_payload([_make_entry()]), site, source="solcast_historic")
    assert rows[0].source == "solcast_historic"


def test_normalise_source_propagates_to_all_rows():
    site = _make_site()
    entries = [_make_entry(period_end=f"2024-06-0{i}T01:00:00Z") for i in range(1, 4)]
    rows = _normalise(_make_payload(entries), site, source="solcast_historic")
    assert all(r.source == "solcast_historic" for r in rows)


# ── _normalise: edge cases ────────────────────────────────────────────────────

def test_normalise_skips_entry_missing_period_end():
    site = _make_site()
    entries = [{"ghi": 100.0, "dni": 80.0, "dhi": 20.0}]  # no period_end
    rows = _normalise(_make_payload(entries), site)
    assert rows == []


def test_normalise_empty_payload_returns_empty_list():
    site = _make_site()
    rows = _normalise({"estimated_actuals": []}, site)
    assert rows == []


def test_normalise_none_values_allowed():
    site = _make_site()
    rows = _normalise(_make_payload([_make_entry(ghi=None, dni=None, dhi=None)]), site)
    assert rows[0].ghi_wm2 is None
    assert rows[0].dni_wm2 is None
    assert rows[0].dhi_wm2 is None


# ── 31-day chunking ───────────────────────────────────────────────────────────

def test_chunk_days_constant_is_31():
    assert _CHUNK_DAYS == 31


def test_365_day_window_produces_correct_chunk_count():
    """365 days / 31 days per chunk = 12 full chunks (last chunk is shorter)."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 1, tzinfo=timezone.utc)  # 366 days (leap year 2024)
    chunks = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(days=_CHUNK_DAYS), end)
        chunks.append((chunk_start, chunk_end))
        chunk_start = chunk_end
    # 366 / 31 = 11 full + 1 partial = 12
    assert len(chunks) == 12


def test_window_shorter_than_31_days_produces_one_chunk():
    start = datetime(2024, 6, 1, tzinfo=timezone.utc)
    end = datetime(2024, 6, 15, tzinfo=timezone.utc)
    chunks = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(days=_CHUNK_DAYS), end)
        chunks.append((chunk_start, chunk_end))
        chunk_start = chunk_end
    assert len(chunks) == 1
    assert chunks[0] == (start, end)


def test_exactly_31_day_window_produces_one_chunk():
    start = datetime(2024, 6, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=31)
    chunks = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(days=_CHUNK_DAYS), end)
        chunks.append((chunk_start, chunk_end))
        chunk_start = chunk_end
    assert len(chunks) == 1


# ── run_solcast_backfill ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_solcast_backfill_returns_zero_on_empty_response():
    site = _make_site()
    start = datetime(2024, 6, 1, tzinfo=timezone.utc)
    end = datetime(2024, 6, 3, tzinfo=timezone.utc)

    with patch(
        "heliotelligence.collectors.solcast.fetch_solcast_historic",
        new=AsyncMock(return_value=[]),
    ):
        rows, chunks = await run_solcast_backfill(site, start, end)

    assert rows == 0
    assert chunks == 1


@pytest.mark.asyncio
async def test_run_solcast_backfill_raises_value_error_when_end_lte_start():
    site = _make_site()
    start = datetime(2024, 6, 5, tzinfo=timezone.utc)
    end = datetime(2024, 6, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="must be after start"):
        await run_solcast_backfill(site, start, end)


@pytest.mark.asyncio
async def test_run_solcast_backfill_equal_start_end_raises():
    site = _make_site()
    t = datetime(2024, 6, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        await run_solcast_backfill(site, t, t)


@pytest.mark.asyncio
async def test_run_solcast_backfill_calls_fetch_once_for_short_window():
    site = _make_site()
    start = datetime(2024, 6, 1, tzinfo=timezone.utc)
    end = datetime(2024, 6, 10, tzinfo=timezone.utc)

    mock_fetch = AsyncMock(return_value=[])
    with patch("heliotelligence.collectors.solcast.fetch_solcast_historic", mock_fetch):
        with patch("heliotelligence.collectors.solcast.get_session_factory"):
            await run_solcast_backfill(site, start, end)

    assert mock_fetch.call_count == 1


@pytest.mark.asyncio
async def test_run_solcast_backfill_chunks_365_day_window():
    site = _make_site()
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 1, tzinfo=timezone.utc)  # 366 days

    mock_fetch = AsyncMock(return_value=[])
    with patch("heliotelligence.collectors.solcast.fetch_solcast_historic", mock_fetch):
        with patch("heliotelligence.collectors.solcast.get_session_factory"):
            rows, chunks = await run_solcast_backfill(site, start, end)

    assert mock_fetch.call_count == 12
    assert chunks == 12
    assert rows == 0
