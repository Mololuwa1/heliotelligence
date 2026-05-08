"""Solcast live radiation and weather collector.

Fetches from https://api.solcast.com.au/data/live/radiation_and_weather and
upserts to weather_readings via the shared upsert layer.

Retry policy
────────────
429  → exponential back-off; honours Retry-After header when present.
401  → logs a clear diagnostic and raises PermissionError (bad API key).
5xx / network → up to MAX_RETRIES attempts with exponential back-off.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

import httpx

from heliotelligence.config.settings import settings
from heliotelligence.config.site import SiteConfig
from heliotelligence.db.session import get_session_factory
from heliotelligence.ingest.upsert import upsert_weather
from heliotelligence.models.schemas import WeatherReadingIn

log = logging.getLogger(__name__)

SOLCAST_URL = "https://api.solcast.com.au/data/live/radiation_and_weather"
MAX_RETRIES = 5
BASE_BACKOFF = 2.0  # seconds; actual wait = BASE_BACKOFF ** attempt


async def fetch_solcast(site: SiteConfig) -> list[WeatherReadingIn]:
    """GET live radiation + weather for *site* and return normalised rows.

    Raises
    ------
    PermissionError
        If Solcast returns 401 (invalid or missing API key).
    RuntimeError
        If all retry attempts are exhausted.
    """
    params = {
        "latitude": site.latitude,
        "longitude": site.longitude,
        "output_parameters": "ghi,dni,dhi,air_temp,wind_speed_10m",
        "period": "PT60M",
    }
    headers = {"Authorization": f"Bearer {settings.solcast_api_key}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.get(SOLCAST_URL, params=params, headers=headers)
            except httpx.RequestError as exc:
                wait = BASE_BACKOFF ** (attempt + 1)
                log.warning(
                    "Solcast network error for site %s (attempt %d/%d): %s — retrying in %.0fs",
                    site.id, attempt + 1, MAX_RETRIES, exc, wait,
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(wait)
                continue

            if response.status_code == 200:
                return _normalise(response.json(), site)

            if response.status_code == 429:
                # Honour Retry-After when provided; otherwise exponential back-off
                retry_after = float(
                    response.headers.get("Retry-After", BASE_BACKOFF ** (attempt + 1))
                )
                log.warning(
                    "Solcast 429 rate-limited for site %s — waiting %.0fs",
                    site.id, retry_after,
                )
                await asyncio.sleep(retry_after)
                continue

            if response.status_code == 401:
                log.error(
                    "Solcast 401 Unauthorized for site %s — verify SOLCAST_API_KEY", site.id
                )
                raise PermissionError(
                    f"Solcast API key invalid or missing for site {site.id}"
                )

            # Any other 4xx / 5xx: log and back off before next attempt
            wait = BASE_BACKOFF ** (attempt + 1)
            log.warning(
                "Solcast HTTP %d for site %s (attempt %d/%d): %s — retrying in %.0fs",
                response.status_code, site.id, attempt + 1, MAX_RETRIES,
                response.text[:200], wait,
            )
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(wait)

    raise RuntimeError(
        f"Solcast fetch failed after {MAX_RETRIES} attempts for site {site.id}"
    )


def _normalise(payload: dict, site: SiteConfig) -> list[WeatherReadingIn]:
    """Map Solcast JSON response payload → list[WeatherReadingIn].

    Field mapping
    ─────────────
    Solcast          WeatherReadingIn
    ───────────────  ────────────────
    ghi              ghi_wm2
    air_temp         temp_amb_c
    wind_speed_10m   wind_speed_ms
    period_end       ts

    dni and dhi are requested for future schema extensions but have no
    current WeatherReadingIn columns; they are silently dropped here.
    """
    rows: list[WeatherReadingIn] = []

    for entry in payload.get("estimated_actuals", []):
        period_end_str = entry.get("period_end", "")
        if not period_end_str:
            log.warning("Solcast entry missing period_end — skipping: %s", entry)
            continue

        # Solcast uses ISO-8601 with 'Z' suffix; fromisoformat needs +00:00
        ts = datetime.fromisoformat(period_end_str.replace("Z", "+00:00"))

        rows.append(
            WeatherReadingIn(
                site_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, site.id)),
                time=ts,
                ghi_wm2=entry.get("ghi"),
                temp_amb_c=entry.get("air_temp"),
                wind_speed_ms=entry.get("wind_speed_10m"),
                source="solcast",
            )
        )

    return rows


async def run_solcast_collector(site: SiteConfig) -> int:
    """Fetch Solcast data and upsert to weather_readings.

    Returns the number of rows upserted (0 if the API returned no data).
    """
    rows = await fetch_solcast(site)
    if not rows:
        log.info("Solcast returned no data for site %s", site.id)
        return 0

    factory = get_session_factory()
    async with factory() as session:
        await upsert_weather(session, rows)
        await session.commit()

    log.info("Solcast: upserted %d row(s) for site %s", len(rows), site.id)
    return len(rows)
