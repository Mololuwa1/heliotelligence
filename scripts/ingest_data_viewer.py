"""Bracon Ash operational dataset ingestion script.

Parses the site Excel file (.xlsx), maps columns to the four ORM schemas,
and upserts to Tiger Data via the shared upsert layer.

Usage
─────
    # Full ingest
    .venv/bin/python scripts/ingest_data_viewer.py \
        --file /path/to/data.xlsx \
        --site-id site-001

    # Dry run — validate and print counts without writing
    .venv/bin/python scripts/ingest_data_viewer.py \
        --file /path/to/data.xlsx \
        --site-id site-001 \
        --dry-run

    # Custom batch size
    .venv/bin/python scripts/ingest_data_viewer.py \
        --file /path/to/data.xlsx \
        --site-id site-001 \
        --batch-size 250
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_LONDON = ZoneInfo("Europe/London")
_POA_DAYLIGHT_THRESHOLD = 10.0   # W/m² — below this = night, avail = None
_WEATHER_PREFIX = "Bracon Ash - Weather Station CT03 - "
_INV_POWER_SUFFIX = " - TOTAL ACTIVE POWER (kW)"
_INV_YIELD_SUFFIX = " - TOTAL POWER YIELDS (kWh)"
_INV_PREFIX = "Bracon Ash - "

# Weather column → WeatherReadingIn field
_WEATHER_COL_MAP: dict[str, str] = {
    "SMP10_IRRADIANCE-POA-1 (W/m2)": "poa_wm2",
    "SMP10_IRRADIANCE-GHI-B (W/m2)": "ghi_wm2",
    "SMP10_IRRADIANCE-RPOA-2 (W/m2)": "poa2_wm2",
    "AMBIENT TEMPERATURE-1 (ºC)": "temp_amb_c",
    "PT1000-MODULE-1 (ºC)": "temp_mod_avg_c",
    "REF.CELL-1_IRRADIANCE (W/m2)": "ref_cell1_wm2",
    "WS_AVG (m/s)": "wind_speed_ms",
    "WD_AVG (º)": "wind_dir_deg",
    "ABS_PRECIPITATION (l/m2)": "precip_mm",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _to_float_or_none(val) -> float | None:
    """Convert a pandas scalar to float, returning None for NaN/missing."""
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _site_uuid(site_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, site_id))


# ── Parsing ──────────────────────────────────────────────────────────────────

def _load_excel(path: Path) -> pd.DataFrame:
    log.info("Loading Excel file: %s", path)
    df = pd.read_excel(path, sheet_name="Data", engine="openpyxl")
    log.info("Loaded %d rows, %d columns", len(df), len(df.columns))
    return df


def _parse_timestamps(df: pd.DataFrame) -> pd.Series:
    """Combine Date + Time columns, localise to Europe/London, convert to UTC."""
    combined = df["Date"].astype(str).str.strip() + " " + df["Time"].astype(str).str.strip()
    ts_local = pd.to_datetime(combined, dayfirst=True)
    ts_london = ts_local.dt.tz_localize(_LONDON, ambiguous="infer", nonexistent="shift_forward")
    return ts_london.dt.tz_convert("UTC")


def _discover_inverters(df: pd.DataFrame) -> list[tuple[str, str, str]]:
    """Return [(inverter_id, power_col, yield_col), ...] from column names."""
    pattern = re.compile(
        r"^Bracon Ash - (.+?) - TOTAL ACTIVE POWER \(kW\)$"
    )
    results = []
    for col in df.columns:
        m = pattern.match(str(col))
        if m:
            inv_id = m.group(1)
            power_col = col
            yield_col = f"Bracon Ash - {inv_id} - TOTAL POWER YIELDS (kWh)"
            if yield_col in df.columns:
                results.append((inv_id, power_col, yield_col))
            else:
                log.warning("No yield column found for inverter %s — skipping", inv_id)
    log.info("Discovered %d inverters", len(results))
    return results


def _build_weather_rows(
    df: pd.DataFrame,
    timestamps: pd.Series,
    site_uuid: str,
) -> list[dict]:
    """Build WeatherReadingIn dicts, skipping rows where all weather values are NaN."""
    from heliotelligence.models.schemas import WeatherReadingIn

    # Map full column names
    col_lookup: dict[str, str] = {}
    for suffix, field in _WEATHER_COL_MAP.items():
        full_col = _WEATHER_PREFIX + suffix
        if full_col in df.columns:
            col_lookup[full_col] = field
        else:
            log.warning("Weather column not found: %s", full_col)

    weather_cols = list(col_lookup.keys())
    rows = []
    skipped = 0

    for i, ts in enumerate(timestamps):
        vals: dict[str, float | None] = {}
        all_none = True
        for col, field in col_lookup.items():
            v = _to_float_or_none(df[col].iloc[i])
            vals[field] = v
            if v is not None:
                all_none = False

        if all_none:
            skipped += 1
            continue

        rows.append(WeatherReadingIn(
            site_id=site_uuid,
            time=ts.to_pydatetime(),
            source="met_station",
            **vals,
        ))

    if skipped:
        log.info("Skipped %d all-NaN weather rows", skipped)

    return rows


def _build_meter_rows(
    df: pd.DataFrame,
    timestamps: pd.Series,
    site_uuid: str,
    inverters: list[tuple[str, str, str]],
) -> list[dict]:
    from heliotelligence.models.schemas import MeterReadingIn

    power_cols = [power_col for _, power_col, _ in inverters]
    yield_cols = [yield_col for _, _, yield_col in inverters]

    total_power = df[power_cols].apply(pd.to_numeric, errors="coerce").sum(axis=1, skipna=True)
    total_yield = df[yield_cols].apply(pd.to_numeric, errors="coerce").sum(axis=1, skipna=True)

    rows = []
    for i, ts in enumerate(timestamps):
        rows.append(MeterReadingIn(
            site_id=site_uuid,
            time=ts.to_pydatetime(),
            p_ac_kw=_to_float_or_none(total_power.iloc[i]),
            e_exported_kwh=_to_float_or_none(total_yield.iloc[i]),
        ))

    return rows


def _build_inverter_rows(
    df: pd.DataFrame,
    timestamps: pd.Series,
    site_uuid: str,
    inverters: list[tuple[str, str, str]],
    poa_col: str | None,
) -> list[dict]:
    from heliotelligence.models.schemas import InverterReadingIn

    rows = []
    poa_series = (
        df[poa_col].apply(pd.to_numeric, errors="coerce")
        if poa_col and poa_col in df.columns
        else pd.Series([None] * len(df))
    )

    for inv_id, power_col, yield_col in inverters:
        power_series = df[power_col].apply(pd.to_numeric, errors="coerce")
        yield_series = df[yield_col].apply(pd.to_numeric, errors="coerce")

        for i, ts in enumerate(timestamps):
            power = _to_float_or_none(power_series.iloc[i])
            energy = _to_float_or_none(yield_series.iloc[i])
            poa = _to_float_or_none(poa_series.iloc[i])

            # Availability: None at night, 100.0 if generating, 0.0 if not
            if poa is None or poa <= _POA_DAYLIGHT_THRESHOLD:
                avail = None
            elif power is not None and power > 0:
                avail = 100.0
            else:
                avail = 0.0

            rows.append(InverterReadingIn(
                site_id=site_uuid,
                inverter_id=inv_id,
                time=ts.to_pydatetime(),
                inv_p_ac_kw=power,
                inv_e_kwh=energy,
                inv_avail_pct=avail,
                plant_irr_wm2=poa,
            ))

    return rows


# ── Upsert ───────────────────────────────────────────────────────────────────

async def _run_upsert(
    weather_rows,
    meter_rows,
    inverter_rows,
    batch_size: int,
) -> None:
    from heliotelligence.db.session import get_engine, get_session_factory
    from heliotelligence.ingest.upsert import upsert_weather, upsert_meter, upsert_inverters

    # NullPool: appropriate for a one-shot script
    get_engine(use_null_pool=True)
    factory = get_session_factory()

    log.info("Upserting %d weather rows...", len(weather_rows))
    async with factory() as session:
        await upsert_weather(session, weather_rows)
        await session.commit()

    log.info("Upserting %d meter rows...", len(meter_rows))
    async with factory() as session:
        await upsert_meter(session, meter_rows)
        await session.commit()

    total_inv = len(inverter_rows)
    total_batches = math.ceil(total_inv / batch_size)
    log.info("Upserting %d inverter rows in %d batches of %d...",
             total_inv, total_batches, batch_size)

    for batch_num, offset in enumerate(range(0, total_inv, batch_size), start=1):
        batch = inverter_rows[offset: offset + batch_size]
        async with factory() as session:
            await upsert_inverters(session, batch)
            await session.commit()
        if batch_num % 10 == 0 or batch_num == total_batches:
            print(f"  Upserting inverter batch {batch_num}/{total_batches}...", flush=True)


# ── Main ─────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Ingest Bracon Ash Excel operational data into Tiger Data"
    )
    p.add_argument("--file", required=True, help="Path to the .xlsx data file")
    p.add_argument(
        "--site-id", required=True,
        help="Plain-text site ID (e.g. site-001) — converted to UUID internally"
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Parse and validate only — do not write to the database"
    )
    p.add_argument(
        "--batch-size", type=int, default=500,
        help="Inverter rows per upsert batch (default: 500)"
    )
    return p.parse_args()


async def main() -> None:
    args = _parse_args()
    t_start = time.monotonic()

    file_path = Path(args.file)
    if not file_path.exists():
        raise SystemExit(f"File not found: {file_path}")

    site_id_plain = args.site_id
    site_uuid = _site_uuid(site_id_plain)
    log.info("Site: %s  (uuid: %s)", site_id_plain, site_uuid)

    # ── Load ─────────────────────────────────────────────────────────────────
    df = _load_excel(file_path)
    timestamps = _parse_timestamps(df)

    inverters = _discover_inverters(df)
    if not inverters:
        raise SystemExit("No inverter columns found — check the file format")

    poa_col = _WEATHER_PREFIX + "SMP10_IRRADIANCE-POA-1 (W/m2)"

    # ── Build rows ────────────────────────────────────────────────────────────
    log.info("Building weather rows...")
    weather_rows = _build_weather_rows(df, timestamps, site_uuid)

    log.info("Building meter rows...")
    meter_rows = _build_meter_rows(df, timestamps, site_uuid, inverters)

    log.info("Building inverter rows...")
    inverter_rows = _build_inverter_rows(df, timestamps, site_uuid, inverters, poa_col)

    n_weather = len(weather_rows)
    n_meter = len(meter_rows)
    n_inverter = len(inverter_rows)

    # ── Dry run ───────────────────────────────────────────────────────────────
    if args.dry_run:
        print()
        print("=== DRY RUN — no data written ===")
        print(f"  weather_readings  : {n_weather:,} rows")
        print(f"  meter_readings    : {n_meter:,} rows")
        print(f"  inverter_readings : {n_inverter:,} rows  "
              f"({len(inverters)} inverters × {len(df)} timestamps)")
        print(f"  Duration          : {time.monotonic() - t_start:.1f}s (parse only)")
        return

    # ── Upsert ────────────────────────────────────────────────────────────────
    await _run_upsert(weather_rows, meter_rows, inverter_rows, args.batch_size)

    elapsed = time.monotonic() - t_start
    print()
    print(f"Ingestion complete for site {site_id_plain} (uuid: {site_uuid})")
    print(f"  weather_readings  : {n_weather:,} rows")
    print(f"  meter_readings    : {n_meter:,} rows")
    print(f"  inverter_readings : {n_inverter:,} rows  "
          f"({len(inverters)} inverters × {len(df)} timestamps)")
    print(f"  Duration          : {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
