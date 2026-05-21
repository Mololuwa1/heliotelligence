"""Solcast live and historic radiation and weather collector.

Live endpoint:
  https://api.solcast.com.au/data/live/radiation_and_weather
  Fetches recent estimated actuals; called on a scheduled interval.

Historic endpoint:
  https://api.solcast.com.au/data/historic/radiation_and_weather
  Fetches a user-specified time window; used for backfill.

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
from datetime import datetime, timedelta, timezone

import httpx

from heliotelligence.config.settings import settings
from heliotelligence.config.site import SiteConfig
from heliotelligence.db.session import get_session_factory
from heliotelligence.ingest.upsert import upsert_weather
from heliotelligence.models.schemas import WeatherReadingIn

log = logging.getLogger(__name__)

SOLCAST_URL = "https://api.solcast.com.au/data/live/radiation_and_weather"
SOLCAST_HISTORIC_URL = "https://api.solcast.com.au/data/historic/radiation_and_weather"
MAX_RETRIES = 5
BASE_BACKOFF = 2.0  # seconds; actual wait = BASE_BACKOFF ** attempt
_CHUNK_DAYS = 31    # Solcast historic endpoint max window per request


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


def _normalise(payload: dict, site: SiteConfig, source: str = "solcast") -> list[WeatherReadingIn]:
    """Map Solcast JSON response payload → list[WeatherReadingIn].

    Field mapping
    ─────────────
    Solcast          WeatherReadingIn
    ───────────────  ────────────────
    ghi              ghi_wm2
    dni              dni_wm2
    dhi              dhi_wm2
    air_temp         temp_amb_c
    wind_speed_10m   wind_speed_ms
    period_end       ts
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
                dni_wm2=entry.get("dni"),
                dhi_wm2=entry.get("dhi"),
                temp_amb_c=entry.get("air_temp"),
                wind_speed_ms=entry.get("wind_speed_10m"),
                source=source,
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


async def fetch_solcast_historic(
    site: SiteConfig,
    start: datetime,
    end: datetime,
) -> list[WeatherReadingIn]:
    """GET historic radiation + weather for *site* over [start, end].

    Raises
    ------
    ValueError
        If end <= start.
    PermissionError
        If Solcast returns 401.
    RuntimeError
        If all retry attempts are exhausted.
    """
    if end <= start:
        raise ValueError(f"end ({end}) must be after start ({start})")

    params = {
        "latitude": site.latitude,
        "longitude": site.longitude,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "output_parameters": "ghi,dni,dhi,air_temp,wind_speed_10m",
        "period": "PT60M",
        "format": "json",
    }
    headers = {"Authorization": f"Bearer {settings.solcast_api_key}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.get(
                    SOLCAST_HISTORIC_URL, params=params, headers=headers
                )
            except httpx.RequestError as exc:
                wait = BASE_BACKOFF ** (attempt + 1)
                log.warning(
                    "Solcast historic network error for site %s (attempt %d/%d): %s"
                    " — retrying in %.0fs",
                    site.id, attempt + 1, MAX_RETRIES, exc, wait,
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(wait)
                continue

            if response.status_code == 200:
                return _normalise(response.json(), site, source="solcast_historic")

            if response.status_code == 429:
                retry_after = float(
                    response.headers.get("Retry-After", BASE_BACKOFF ** (attempt + 1))
                )
                log.warning(
                    "Solcast historic 429 rate-limited for site %s — waiting %.0fs",
                    site.id, retry_after,
                )
                await asyncio.sleep(retry_after)
                continue

            if response.status_code == 401:
                log.error(
                    "Solcast historic 401 Unauthorized for site %s"
                    " — verify SOLCAST_API_KEY", site.id
                )
                raise PermissionError(
                    f"Solcast API key invalid or missing for site {site.id}"
                )

            wait = BASE_BACKOFF ** (attempt + 1)
            log.warning(
                "Solcast historic HTTP %d for site %s (attempt %d/%d): %s"
                " — retrying in %.0fs",
                response.status_code, site.id, attempt + 1, MAX_RETRIES,
                response.text[:200], wait,
            )
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(wait)

    raise RuntimeError(
        f"Solcast historic fetch failed after {MAX_RETRIES} attempts for site {site.id}"
    )


async def run_solcast_backfill(
    site: SiteConfig,
    start: datetime,
    end: datetime,
) -> tuple[int, int]:
    """Backfill historic Solcast data for *site* over [start, end].

    Splits the window into ≤31-day chunks and calls fetch_solcast_historic
    sequentially for each.  Upserts all rows, returns (rows_upserted, chunks).

    Raises
    ------
    ValueError
        If end <= start.
    """
    if end <= start:
        raise ValueError(f"end ({end}) must be after start ({start})")

    factory = get_session_factory()
    total_rows = 0
    chunks = 0

    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(days=_CHUNK_DAYS), end)
        rows = await fetch_solcast_historic(site, chunk_start, chunk_end)
        chunks += 1

        if rows:
            async with factory() as session:
                await upsert_weather(session, rows)
                await session.commit()
            total_rows += len(rows)
            log.info(
                "Solcast backfill chunk %d: upserted %d row(s) for site %s"
                " [%s → %s]",
                chunks, len(rows), site.id,
                chunk_start.date(), chunk_end.date(),
            )
        else:
            log.info(
                "Solcast backfill chunk %d: no data for site %s [%s → %s]",
                chunks, site.id, chunk_start.date(), chunk_end.date(),
            )

        chunk_start = chunk_end

    log.info(
        "Solcast backfill complete for site %s: %d row(s) across %d chunk(s)",
        site.id, total_rows, chunks,
    )
    return total_rows, chunks
