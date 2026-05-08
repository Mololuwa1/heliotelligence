"""SCADA CSV parser for Bracon Ash export format.

Column header format:
    "{Site Name} - {Equipment} - {Measurement} ({Unit})"

Timestamps in the CSV are assumed to be LOCAL time (Europe/London) and
period-START convention. The parser:
  1. Detects the sampling interval from the median timestamp diff.
  2. Converts to UTC period-END by adding one interval.
  3. Routes each column to the correct Pydantic schema via the normaliser.
  4. Averages multi-column groups (temp_mod_avg_c, temp_amb_c).
  5. Returns four lists of validated ingest schemas.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import ValidationError

from heliotelligence.ingest.normaliser import NormalisedColumn, normalise_column
from heliotelligence.models.schemas import (
    InverterReadingIn,
    MeterReadingIn,
    StringReadingIn,
    WeatherReadingIn,
)

log = logging.getLogger(__name__)

_SITE_TIMEZONE = "Europe/London"
_TIMESTAMP_ALIASES = frozenset(
    {"timestamp", "date/time", "datetime", "time", "date time"}
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_csv(
    path: Path,
    site_id: str,
    site_name: str = "Bracon Ash",
    source_tz: str = _SITE_TIMEZONE,
) -> tuple[
    list[WeatherReadingIn],
    list[MeterReadingIn],
    list[InverterReadingIn],
    list[StringReadingIn],
]:
    """Parse a SCADA CSV file and return four lists of validated ingest models.

    Parameters
    ----------
    path:       Path to the CSV file.
    site_id:    Site identifier stored in every row (e.g. "bracon-ash-001").
    site_name:  Site name prefix used in column headers.
    source_tz:  IANA timezone of the raw timestamps (period-start, local time).
    """
    df = pd.read_csv(path, low_memory=False)

    # ── Locate timestamp column ──────────────────────────────────────────────
    ts_col = _find_timestamp_column(df)
    if ts_col is None:
        raise ValueError(f"No timestamp column found in {path}. Columns: {list(df.columns)}")

    # Parse, localise to source_tz, convert to UTC, shift to period-END
    raw_ts = pd.to_datetime(df[ts_col], format="%Y-%m-%d %H:%M", utc=False)
    interval = _detect_interval(raw_ts)

    utc_ts: pd.Series = (
        raw_ts
        .dt.tz_localize(source_tz, ambiguous="infer", nonexistent="shift_forward")
        .dt.tz_convert("UTC")
        + interval          # period-start → period-end
    )
    df[ts_col] = utc_ts

    # ── Normalise all non-timestamp columns ──────────────────────────────────
    col_meta: dict[str, NormalisedColumn] = {}
    for col in df.columns:
        if col == ts_col:
            continue
        col_meta[col] = normalise_column(col, site_name)

    # ── Build rows ────────────────────────────────────────────────────────────
    weather_rows: list[WeatherReadingIn] = []
    meter_rows: list[MeterReadingIn] = []
    inverter_rows: dict[tuple[str, str], list] = defaultdict(list)  # (inverter_id, ts) → partial dicts
    string_rows: dict[tuple[str, str, str], list] = defaultdict(list)

    for _, row in df.iterrows():
        ts = row[ts_col]
        if pd.isna(ts):
            continue

        # Accumulate per-row column values grouped by destination
        weather_vals: dict[str, list[float]] = defaultdict(list)  # for avg groups
        weather_scalars: dict[str, object] = {}
        meter_scalars: dict[str, object] = {}
        # inverter: keyed by inverter_id
        inv_scalars: dict[str, dict[str, object]] = defaultdict(dict)
        # string: keyed by (inverter_id, string_id)
        str_scalars: dict[tuple[str, str], dict[str, object]] = defaultdict(dict)

        for col, meta in col_meta.items():
            if meta.skip:
                continue
            raw_val = row[col]
            if pd.isna(raw_val):
                continue

            val = float(raw_val) * meta.scale if isinstance(raw_val, (int, float, np.number)) else raw_val

            if meta.equipment_type == "weather":
                if meta.is_avg_group:
                    weather_vals[meta.db_column].append(float(val))
                else:
                    weather_scalars[meta.db_column] = val

            elif meta.equipment_type == "meter":
                meter_scalars[meta.db_column] = val

            elif meta.equipment_type == "inverter" and meta.equipment_id:
                inv_scalars[meta.equipment_id][meta.db_column] = val

            elif meta.equipment_type == "string" and meta.equipment_id and meta.string_id:
                str_scalars[(meta.equipment_id, meta.string_id)][meta.db_column] = val

        # Resolve averaged groups
        for db_col, values in weather_vals.items():
            if values:
                weather_scalars[db_col] = float(np.nanmean(values))

        # Build WeatherReadingIn
        if weather_scalars:
            try:
                weather_rows.append(
                    WeatherReadingIn(site_id=site_id, time=ts, **weather_scalars)
                )
            except ValidationError as exc:
                log.warning("Weather row validation failed at %s: %s", ts, exc)

        # Build MeterReadingIn
        if meter_scalars:
            try:
                meter_rows.append(
                    MeterReadingIn(site_id=site_id, time=ts, **meter_scalars)
                )
            except ValidationError as exc:
                log.warning("Meter row validation failed at %s: %s", ts, exc)

        # Build InverterReadingIn
        for inv_id, fields in inv_scalars.items():
            try:
                inverter_rows[(inv_id, str(ts))].append(
                    InverterReadingIn(
                        site_id=site_id, inverter_id=inv_id, time=ts, **fields
                    )
                )
            except ValidationError as exc:
                log.warning("Inverter row validation failed at %s/%s: %s", inv_id, ts, exc)

        # Build StringReadingIn
        for (inv_id, str_id), fields in str_scalars.items():
            try:
                string_rows[(inv_id, str_id, str(ts))].append(
                    StringReadingIn(
                        site_id=site_id,
                        inverter_id=inv_id,
                        string_id=str_id,
                        time=ts,
                        **fields,
                    )
                )
            except ValidationError as exc:
                log.warning(
                    "String row validation failed at %s/%s/%s: %s",
                    inv_id, str_id, ts, exc,
                )

    # Flatten deduplicated inverter/string dicts (keep last entry per key)
    flat_inverters = [entries[-1] for entries in inverter_rows.values()]
    flat_strings = [entries[-1] for entries in string_rows.values()]

    log.info(
        "Parsed %s: %d weather, %d meter, %d inverter, %d string rows",
        path.name,
        len(weather_rows),
        len(meter_rows),
        len(flat_inverters),
        len(flat_strings),
    )
    return weather_rows, meter_rows, flat_inverters, flat_strings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_timestamp_column(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        if col.strip().lower() in _TIMESTAMP_ALIASES:
            return col
    return None


def _detect_interval(ts_series: pd.Series) -> pd.Timedelta:
    """Infer the sampling interval from the median diff between timestamps."""
    diffs = pd.to_datetime(ts_series, dayfirst=False).diff().dropna()
    if diffs.empty:
        return pd.Timedelta(minutes=5)  # safe default
    median = diffs.median()
    # Snap to nearest sensible interval
    for candidate_min in (1, 5, 10, 15, 30, 60):
        if abs(median - pd.Timedelta(minutes=candidate_min)) < pd.Timedelta(seconds=30):
            return pd.Timedelta(minutes=candidate_min)
    return median
