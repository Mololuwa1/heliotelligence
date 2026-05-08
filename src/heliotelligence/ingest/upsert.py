"""Idempotent async upserts for all four hypertables.

Uses PostgreSQL INSERT ... ON CONFLICT DO UPDATE so re-running ingestion
on the same CSV is safe. The conflict target matches each table's PK.

TimescaleDB note
───────────────
ON CONFLICT DO UPDATE requires the conflict target to include the partition
column (ts). With TimescaleDB ≥ 2.11, upserts on hypertables work when
`timescaledb.enable_chunk_skipping` is enabled (default on). If running an
older version, fall back to ON CONFLICT DO NOTHING by setting the env var
UPSERT_STRATEGY=ignore.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from heliotelligence.models.orm import (
    InverterReading,
    MeterReading,
    StringReading,
    WeatherReading,
)
from heliotelligence.models.schemas import (
    InverterReadingIn,
    MeterReadingIn,
    StringReadingIn,
    WeatherReadingIn,
)

log = logging.getLogger(__name__)

# Honour env override for older TimescaleDB deployments
_UPSERT_DO_NOTHING = os.getenv("UPSERT_STRATEGY", "update").lower() == "ignore"


# ---------------------------------------------------------------------------
# Per-table upsert functions
# ---------------------------------------------------------------------------

async def upsert_weather(
    session: AsyncSession,
    rows: list[WeatherReadingIn],
) -> None:
    if not rows:
        return
    stmt = pg_insert(WeatherReading).values([r.model_dump() for r in rows])
    stmt = (
        stmt.on_conflict_do_nothing(index_elements=["time", "site_id", "source"])
        if _UPSERT_DO_NOTHING
        else stmt.on_conflict_do_update(
            index_elements=["time", "site_id", "source"],
            set_={
                c.key: c
                for c in stmt.excluded
                if c.key not in ("time", "site_id", "source")
            },
        )
    )
    await session.execute(stmt)
    log.debug("Upserted %d weather rows", len(rows))


async def upsert_meter(
    session: AsyncSession,
    rows: list[MeterReadingIn],
) -> None:
    if not rows:
        return
    stmt = pg_insert(MeterReading).values([r.model_dump() for r in rows])
    stmt = (
        stmt.on_conflict_do_nothing(index_elements=["time", "site_id"])
        if _UPSERT_DO_NOTHING
        else stmt.on_conflict_do_update(
            index_elements=["time", "site_id"],
            set_={
                c.key: c
                for c in stmt.excluded
                if c.key not in ("time", "site_id")
            },
        )
    )
    await session.execute(stmt)
    log.debug("Upserted %d meter rows", len(rows))


async def upsert_inverters(
    session: AsyncSession,
    rows: list[InverterReadingIn],
) -> None:
    if not rows:
        return
    stmt = pg_insert(InverterReading).values([r.model_dump() for r in rows])
    stmt = (
        stmt.on_conflict_do_nothing(index_elements=["time", "site_id", "inverter_id"])
        if _UPSERT_DO_NOTHING
        else stmt.on_conflict_do_update(
            index_elements=["time", "site_id", "inverter_id"],
            set_={
                c.key: c
                for c in stmt.excluded
                if c.key not in ("time", "site_id", "inverter_id")
            },
        )
    )
    await session.execute(stmt)
    log.debug("Upserted %d inverter rows", len(rows))


async def upsert_strings(
    session: AsyncSession,
    rows: list[StringReadingIn],
) -> None:
    if not rows:
        return
    stmt = pg_insert(StringReading).values([r.model_dump() for r in rows])
    stmt = (
        stmt.on_conflict_do_nothing(
            index_elements=["time", "site_id", "inverter_id", "string_id"]
        )
        if _UPSERT_DO_NOTHING
        else stmt.on_conflict_do_update(
            index_elements=["time", "site_id", "inverter_id", "string_id"],
            set_={
                c.key: c
                for c in stmt.excluded
                if c.key not in ("time", "site_id", "inverter_id", "string_id")
            },
        )
    )
    await session.execute(stmt)
    log.debug("Upserted %d string rows", len(rows))


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

async def upsert_all(
    session: AsyncSession,
    weather: list[WeatherReadingIn],
    meter: list[MeterReadingIn],
    inverters: list[InverterReadingIn],
    strings: list[StringReadingIn],
) -> None:
    """Upsert all four tables in a single transaction."""
    await upsert_weather(session, weather)
    await upsert_meter(session, meter)
    await upsert_inverters(session, inverters)
    await upsert_strings(session, strings)
    await session.commit()
    log.info(
        "Committed: %d weather, %d meter, %d inverter, %d string rows",
        len(weather), len(meter), len(inverters), len(strings),
    )
