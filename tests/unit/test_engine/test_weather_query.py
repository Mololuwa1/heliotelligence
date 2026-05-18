"""Unit tests for heliotelligence.engine.weather_query.

Tests
-----
1. Empty DataFrame returned when no DB rows exist in the window
2. Erbs derivation runs when dhi_wm2 and dni_wm2 are NULL
3. Rows with NULL ghi, dhi, dni AND NULL poa are dropped
4. fetch_weather respects quality filter
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from heliotelligence.config.site import ModuleConfig, SiteConfig, InverterConfig
from heliotelligence.engine.weather_query import _apply_erbs, fetch_weather


def _site() -> SiteConfig:
    return SiteConfig(
        id="site-001",
        name="Test Site",
        latitude=52.56,
        longitude=1.21,
        altitude_m=47,
        timezone="Europe/London",
        capacity_kwp=1000.0,
        solcast_resource_id="x",
    )


def _utc(y, m, d, h=0) -> datetime:
    return datetime(y, m, d, h, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Test 1 — Empty DataFrame returned when no rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_dataframe_when_no_rows():
    """fetch_weather returns an empty DataFrame (not an error) when no rows found."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_session.execute.return_value = mock_result

    site = _site()
    df = await fetch_weather(
        site,
        start=_utc(2024, 6, 1),
        end=_utc(2024, 6, 2),
        session=mock_session,
    )

    assert isinstance(df, pd.DataFrame)
    assert df.empty
    assert "ghi_wm2" in df.columns
    assert "dhi_wm2" in df.columns
    assert "poa_wm2" in df.columns


# ---------------------------------------------------------------------------
# Test 2 — Erbs derivation runs when dhi/dni are NULL
# ---------------------------------------------------------------------------

def test_apply_erbs_fills_dhi_and_dni():
    """_apply_erbs should populate dhi_wm2 and dni_wm2 from ghi_wm2."""
    site = _site()
    idx = pd.date_range("2024-06-21 10:00", periods=4, freq="h", tz="UTC")
    df = pd.DataFrame(
        {
            "ghi_wm2": [400.0, 600.0, 500.0, 200.0],
            "dhi_wm2": [None, None, None, None],
            "dni_wm2": [None, None, None, None],
            "poa_wm2": [None, None, None, None],
            "temp_amb_c": [15.0, 18.0, 17.0, 12.0],
            "temp_mod_avg_c": [None, None, None, None],
            "wind_speed_ms": [2.0, 1.5, 2.5, 3.0],
        },
        index=idx,
    )
    mask = pd.Series(True, index=idx)

    result = _apply_erbs(df, mask, site)

    # Erbs should produce non-null, physically plausible values
    assert result["dhi_wm2"].notna().all(), "dhi_wm2 should be filled by Erbs"
    assert result["dni_wm2"].notna().all(), "dni_wm2 should be filled by Erbs"
    # DHI must be non-negative and <= GHI
    assert (result["dhi_wm2"] >= 0).all()
    assert (result["dhi_wm2"] <= result["ghi_wm2"] + 1e-3).all()


# ---------------------------------------------------------------------------
# Test 3 — Rows with all NULL irradiance are dropped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rows_with_all_null_irradiance_dropped():
    """Rows where ghi, dhi, dni, and poa are all NULL must be dropped."""
    site = _site()

    # Simulate two rows: one useful (has GHI), one all-null
    mock_rows = [
        # time, ghi, dhi, dni, poa, t_amb, t_mod, wind, quality
        (
            datetime(2024, 6, 21, 10, tzinfo=timezone.utc),
            600.0, None, None, None, 20.0, None, 2.0, 0,
        ),
        (
            datetime(2024, 6, 21, 11, tzinfo=timezone.utc),
            None, None, None, None, 20.0, None, 2.0, 0,  # all irradiance NULL
        ),
    ]

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = mock_rows
    mock_session.execute.return_value = mock_result

    df = await fetch_weather(
        site,
        start=_utc(2024, 6, 21, 10),
        end=_utc(2024, 6, 21, 12),
        session=mock_session,
    )

    # Only the row with GHI should survive (the all-null row is dropped)
    assert len(df) == 1, (
        f"Expected 1 row after dropping all-null irradiance row, got {len(df)}"
    )
    assert df["ghi_wm2"].iloc[0] == pytest.approx(600.0)


# ---------------------------------------------------------------------------
# Test 4 — get_latest functions return None when table is empty
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_latest_expected_energy_time_none_when_empty():
    """get_latest_expected_energy_time returns None when no rows exist."""
    from heliotelligence.engine.weather_query import get_latest_expected_energy_time

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = (None,)
    mock_session.execute.return_value = mock_result

    result = await get_latest_expected_energy_time("site-001", mock_session)
    assert result is None


@pytest.mark.asyncio
async def test_get_latest_weather_time_none_when_empty():
    """get_latest_weather_time returns None when no rows exist."""
    from heliotelligence.engine.weather_query import get_latest_weather_time

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = (None,)
    mock_session.execute.return_value = mock_result

    result = await get_latest_weather_time("site-001", mock_session)
    assert result is None
