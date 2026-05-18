"""Unit tests for heliotelligence.engine.pipeline.

Tests
-----
1. run_pipeline returns dict with correct keys
2. Early exit when expected_energy already up to date (catch_up_from >= catch_up_to)
3. Early exit when no weather_readings exist for the site
4. rows_upserted and chunks_run are 0 on early exit
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from heliotelligence.config.site import InverterConfig, ModuleConfig, SiteConfig
from heliotelligence.engine.pipeline import run_pipeline


def _site() -> SiteConfig:
    return SiteConfig(
        id="site-001",
        name="Bracon Ash Test",
        latitude=52.56,
        longitude=1.21,
        altitude_m=47,
        timezone="Europe/London",
        capacity_kwp=28524.0,
        solcast_resource_id="x",
        module=ModuleConfig(
            local_module_name="JKM570N-72HL4-BDV",
            bifacial=True,
            num_strings=2076,
            modules_per_string=24,
        ),
        inverter=InverterConfig(
            pvlib_model="pvwatts",
            pnom_kwac=320.0,
            num_units=66,
            eta_nom=0.9842,
            wiring_loss_ac_pct=1.70,
            grid_limit_kwac=20000.0,
        ),
    )


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Test 1 — return dict has correct keys
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_pipeline_returns_correct_keys():
    """run_pipeline must return a dict with site_id, rows_upserted, chunks_run,
    start_time, end_time — even on early exit."""
    mock_session = AsyncMock()

    with (
        patch(
            "heliotelligence.engine.pipeline.get_latest_expected_energy_time",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "heliotelligence.engine.pipeline.get_latest_weather_time",
            new=AsyncMock(return_value=None),  # no weather → early exit
        ),
    ):
        result = await run_pipeline(_site(), mock_session)

    assert set(result.keys()) == {
        "site_id", "rows_upserted", "chunks_run", "start_time", "end_time"
    }, f"Unexpected keys: {set(result.keys())}"
    assert result["site_id"] == "site-001"


# ---------------------------------------------------------------------------
# Test 2 — Early exit when already up to date
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_early_exit_when_up_to_date():
    """When latest expected_energy >= latest weather, rows_upserted must be 0."""
    t_weather = _utc(2024, 6, 21, 12)
    t_expected = _utc(2024, 6, 21, 12)  # same → already caught up

    mock_session = AsyncMock()

    with (
        patch(
            "heliotelligence.engine.pipeline.get_latest_expected_energy_time",
            new=AsyncMock(return_value=t_expected),
        ),
        patch(
            "heliotelligence.engine.pipeline.get_latest_weather_time",
            new=AsyncMock(return_value=t_weather),
        ),
    ):
        result = await run_pipeline(_site(), mock_session)

    assert result["rows_upserted"] == 0
    assert result["chunks_run"] == 0
    assert result["start_time"] is None
    assert result["end_time"] is None


@pytest.mark.asyncio
async def test_early_exit_when_expected_ahead_of_weather():
    """When latest expected_energy > latest weather, rows_upserted must be 0."""
    t_weather = _utc(2024, 6, 21, 10)
    t_expected = _utc(2024, 6, 21, 12)  # expected is ahead of weather

    mock_session = AsyncMock()

    with (
        patch(
            "heliotelligence.engine.pipeline.get_latest_expected_energy_time",
            new=AsyncMock(return_value=t_expected),
        ),
        patch(
            "heliotelligence.engine.pipeline.get_latest_weather_time",
            new=AsyncMock(return_value=t_weather),
        ),
    ):
        result = await run_pipeline(_site(), mock_session)

    assert result["rows_upserted"] == 0
    assert result["chunks_run"] == 0


# ---------------------------------------------------------------------------
# Test 3 — Early exit when no weather exists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_early_exit_when_no_weather():
    """When weather_readings is empty, pipeline returns 0 rows without error."""
    mock_session = AsyncMock()

    with (
        patch(
            "heliotelligence.engine.pipeline.get_latest_expected_energy_time",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "heliotelligence.engine.pipeline.get_latest_weather_time",
            new=AsyncMock(return_value=None),
        ),
    ):
        result = await run_pipeline(_site(), mock_session)

    assert result["rows_upserted"] == 0
    assert result["chunks_run"] == 0


# ---------------------------------------------------------------------------
# Test 4 — Chunk processing: empty weather chunk produces 0 rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_weather_chunk_produces_zero_rows():
    """When fetch_weather returns empty DataFrame for a chunk, 0 rows are upserted."""
    t_from = _utc(2024, 6, 21, 0)
    t_to = _utc(2024, 6, 21, 2)  # 2-hour window → 1 chunk if chunk_hours=24

    mock_session = AsyncMock()

    with (
        patch(
            "heliotelligence.engine.pipeline.get_latest_expected_energy_time",
            new=AsyncMock(return_value=t_from),
        ),
        patch(
            "heliotelligence.engine.pipeline.get_latest_weather_time",
            new=AsyncMock(return_value=t_to),
        ),
        patch(
            "heliotelligence.engine.pipeline.fetch_weather",
            new=AsyncMock(return_value=pd.DataFrame()),  # empty
        ),
    ):
        result = await run_pipeline(_site(), mock_session, chunk_hours=24)

    assert result["rows_upserted"] == 0
    # chunks_run counts chunks that produced rows; empty chunk → 0
    assert result["chunks_run"] == 0
