"""Unit tests for collectors.solcast — no network, no database."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from heliotelligence.collectors.solcast import (
    MAX_RETRIES,
    _normalise,
    fetch_solcast,
    run_solcast_collector,
)
from heliotelligence.config.site import SiteConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _site() -> SiteConfig:
    return SiteConfig(
        id="bracon-ash-001",
        name="Bracon Ash",
        latitude=52.56,
        longitude=1.13,
        timezone="Europe/London",
        capacity_kwp=250.0,
        solcast_resource_id="test-resource",
        tilt_deg=25.0,
        azimuth_deg=0.0,
    )


def _solcast_payload(n: int = 3) -> dict:
    return {
        "estimated_actuals": [
            {
                "ghi": float(200 + i * 10),
                "dni": float(150 + i * 8),
                "dhi": float(50 + i * 2),
                "air_temp": 20.0 + i,
                "wind_speed_10m": 3.5,
                "period_end": f"2024-06-21T{10 + i:02d}:00:00Z",
                "period": "PT60M",
            }
            for i in range(n)
        ]
    }


def _mock_response(status_code: int, json_body: dict | None = None, headers: dict | None = None):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.headers = headers or {}
    response.text = ""
    if json_body is not None:
        response.json.return_value = json_body
    return response


# ---------------------------------------------------------------------------
# _normalise
# ---------------------------------------------------------------------------

def test_normalise_maps_ghi():
    rows = _normalise(_solcast_payload(1), _site())
    assert len(rows) == 1
    assert rows[0].ghi_wm2 == pytest.approx(200.0)


def test_normalise_maps_air_temp():
    rows = _normalise(_solcast_payload(1), _site())
    assert rows[0].temp_amb_c == pytest.approx(20.0)


def test_normalise_maps_wind_speed():
    rows = _normalise(_solcast_payload(1), _site())
    assert rows[0].wind_speed_ms == pytest.approx(3.5)


def test_normalise_sets_site_id_as_uuid():
    expected = str(uuid.uuid5(uuid.NAMESPACE_DNS, "bracon-ash-001"))
    rows = _normalise(_solcast_payload(2), _site())
    assert all(r.site_id == expected for r in rows)


def test_normalise_site_id_is_not_raw_text():
    rows = _normalise(_solcast_payload(1), _site())
    assert rows[0].site_id != "bracon-ash-001"


def test_normalise_ts_utc_aware():
    rows = _normalise(_solcast_payload(1), _site())
    assert rows[0].time.tzinfo is not None
    assert rows[0].time.utcoffset().total_seconds() == 0


def test_normalise_z_suffix_parsed():
    payload = {
        "estimated_actuals": [
            {"ghi": 300.0, "air_temp": 22.0, "wind_speed_10m": 4.0,
             "period_end": "2024-06-21T12:00:00Z", "period": "PT60M"},
        ]
    }
    rows = _normalise(payload, _site())
    assert rows[0].time == datetime(2024, 6, 21, 12, 0, tzinfo=timezone.utc)


def test_normalise_missing_period_end_skipped(caplog):
    payload = {
        "estimated_actuals": [
            {"ghi": 300.0, "air_temp": 22.0, "wind_speed_10m": 4.0,
             "period_end": "", "period": "PT60M"},
        ]
    }
    rows = _normalise(payload, _site())
    assert rows == []


def test_normalise_empty_estimated_actuals():
    assert _normalise({"estimated_actuals": []}, _site()) == []


def test_normalise_missing_key_defaults_to_none():
    payload = {
        "estimated_actuals": [
            {"period_end": "2024-06-21T10:00:00Z", "ghi": 400.0}
            # air_temp and wind_speed_10m absent
        ]
    }
    rows = _normalise(payload, _site())
    assert rows[0].temp_amb_c is None
    assert rows[0].wind_speed_ms is None


def test_normalise_multiple_rows():
    rows = _normalise(_solcast_payload(5), _site())
    assert len(rows) == 5


# ---------------------------------------------------------------------------
# fetch_solcast — 200 success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_solcast_200_returns_rows():
    payload = _solcast_payload(3)
    mock_response = _mock_response(200, payload)

    with patch("heliotelligence.collectors.solcast.settings") as mock_settings, \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_settings.solcast_api_key = "test-key"
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        rows = await fetch_solcast(_site())

    assert len(rows) == 3


# ---------------------------------------------------------------------------
# fetch_solcast — 401 raises PermissionError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_solcast_401_raises_permission_error():
    mock_response = _mock_response(401)

    with patch("heliotelligence.collectors.solcast.settings") as mock_settings, \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_settings.solcast_api_key = "bad-key"
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(PermissionError, match="API key"):
            await fetch_solcast(_site())


# ---------------------------------------------------------------------------
# fetch_solcast — 429 retries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_solcast_429_retries_then_succeeds():
    payload = _solcast_payload(2)
    rate_limited = _mock_response(429, headers={"Retry-After": "0"})
    success = _mock_response(200, payload)

    with patch("heliotelligence.collectors.solcast.settings") as mock_settings, \
         patch("heliotelligence.collectors.solcast.asyncio.sleep", new_callable=AsyncMock) as mock_sleep, \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_settings.solcast_api_key = "test-key"
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[rate_limited, success])
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        rows = await fetch_solcast(_site())

    assert len(rows) == 2
    mock_sleep.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_solcast_429_honours_retry_after_header():
    rate_limited = _mock_response(429, headers={"Retry-After": "30"})
    success = _mock_response(200, _solcast_payload(1))

    with patch("heliotelligence.collectors.solcast.settings") as mock_settings, \
         patch("heliotelligence.collectors.solcast.asyncio.sleep", new_callable=AsyncMock) as mock_sleep, \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_settings.solcast_api_key = "test-key"
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[rate_limited, success])
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await fetch_solcast(_site())

    mock_sleep.assert_called_once_with(30.0)


# ---------------------------------------------------------------------------
# fetch_solcast — network error retries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_solcast_network_error_retries_then_succeeds():
    success = _mock_response(200, _solcast_payload(1))

    with patch("heliotelligence.collectors.solcast.settings") as mock_settings, \
         patch("heliotelligence.collectors.solcast.asyncio.sleep", new_callable=AsyncMock), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_settings.solcast_api_key = "test-key"
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[httpx.ConnectError("timeout"), success]
        )
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        rows = await fetch_solcast(_site())

    assert len(rows) == 1


@pytest.mark.asyncio
async def test_fetch_solcast_exhausts_retries_raises_runtime_error():
    with patch("heliotelligence.collectors.solcast.settings") as mock_settings, \
         patch("heliotelligence.collectors.solcast.asyncio.sleep", new_callable=AsyncMock), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_settings.solcast_api_key = "test-key"
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("always fails")
        )
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(RuntimeError, match=f"after {MAX_RETRIES} attempts"):
            await fetch_solcast(_site())


# ---------------------------------------------------------------------------
# run_solcast_collector — upserts and returns row count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_solcast_collector_returns_row_count():
    rows = _normalise(_solcast_payload(4), _site())

    mock_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("heliotelligence.collectors.solcast.fetch_solcast", AsyncMock(return_value=rows)), \
         patch("heliotelligence.collectors.solcast.get_session_factory", return_value=mock_factory), \
         patch("heliotelligence.collectors.solcast.upsert_weather", AsyncMock()) as mock_upsert:
        count = await run_solcast_collector(_site())

    assert count == 4
    mock_upsert.assert_called_once()
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_run_solcast_collector_empty_returns_zero():
    with patch("heliotelligence.collectors.solcast.fetch_solcast", AsyncMock(return_value=[])):
        count = await run_solcast_collector(_site())
    assert count == 0
