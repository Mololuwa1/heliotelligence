"""
Column header normaliser for Bracon Ash SCADA CSV exports.

Datapoint name format:
    "{Site Name} - {Equipment} - {Measurement} ({Unit})"

Outputs a NormalisedColumn that tells the parser which table, equipment ID,
and DB column to route each CSV column to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------

@dataclass
class NormalisedColumn:
    equipment_type: str        # "weather" | "meter" | "inverter" | "string"
    db_column: str             # target ORM column name
    equipment_id: str | None = None   # inverter_id (for inverter + string rows)
    string_id: str | None = None      # string_id (for string rows only)
    scale: float = 1.0                # multiply raw value before storing
    skip: bool = False                # True → discard this column entirely
    is_avg_group: bool = False        # True → accumulate for row-level averaging


# ---------------------------------------------------------------------------
# Measurement → DB column mappings (strip unit suffix before lookup)
# ---------------------------------------------------------------------------

# Weather Station CT01
_WEATHER_MAP: dict[str, str] = {
    "SMP10-GHI-F":         "ghi_wm2",
    "SMP10-POA-1":         "poa_wm2",
    "SMP10-RPOA-2":        "poa2_wm2",
    "SMP10-GHI-B":         "ghi_b_wm2",
    "WS_AVG":              "wind_speed_ms",
    "WD_AVG":              "wind_dir_deg",
    "ABS_PRECIPITATION":   "precip_mm",
    "REF.CELL-1_IRRADIANCE": "ref_cell1_wm2",
    "COM STATUS":          "ws_com_status",
}

# CFD Meter
_METER_MAP: dict[str, str] = {
    "ACTIVE POWER":                        "p_ac_kw",
    "EXPORTED ACTIVE ENERGY":              "e_exported_kwh",
    "TOTAL NET ACTIVE ENERGY DEL-REC":     "e_net_kwh",
    "FREQUENCY":                           "freq_hz",
    "POWER FACTOR":                        "power_factor",
    "REACTIVE POWER":                      "q_kvar",
}

# Inverter (equipment ID like MQA11-TB101)
_INVERTER_MAP: dict[str, str] = {
    "TOTAL ACTIVE POWER":            "inv_p_ac_kw",
    "TOTAL POWER YIELDS":            "inv_e_kwh",
    "AVAILABILITY":                  "inv_avail_pct",
    "AVAILABILITY WITH EXCEPTIONS":  "inv_avail_exc_pct",
    "AVAILABILITY STRINGS":          "inv_str_avail_pct",
    "COMS STATUS":                   "inv_coms_status",
    "PLANT IRRADIANCE":              "plant_irr_wm2",
}

# String (equipment ID like MQA11-TB101-STR01)
_STRING_MAP: dict[str, str] = {
    "STRING CURRENT":                "str_current_a",
    "ENERGY":                        "str_energy_kwh",
    "POWER":                         "str_power_kw",
    "AVAILABILITY":                  "str_avail_pct",
    "AVAILABILITY WITH EXCEPTIONS":  "str_avail_exc_pct",
}

# Fields to discard regardless of equipment group
_SKIP_MEASUREMENTS: frozenset[str] = frozenset(
    {
        "PR",
        "PERFORMANCE RATIO",
        "YIELD",
        "SPECIFIC YIELD",
        "SPECIFIC POWER",
        "TOTAL YIELD",
        "ANNUAL YIELD",
    }
)

# Regex patterns for equipment classification
_RE_STRING = re.compile(
    r"^(?P<inverter>MQA\d+-TB\d+)-(?P<string>STR\d+)$", re.IGNORECASE
)
_RE_INVERTER = re.compile(r"^MQA\d+-TB\d+$", re.IGNORECASE)
_RE_TEMP_MODULE = re.compile(r"^PT1000-MODULE-\d+$", re.IGNORECASE)
_RE_TEMP_AMB = re.compile(r"^(?:AMBIENT TEMPERATURE|AMBIENT TEMP|TEMP)-\d+$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalise_column(header: str, site_name: str = "Bracon Ash") -> NormalisedColumn:
    """
    Parse a SCADA CSV column header and return a NormalisedColumn.

    Parameters
    ----------
    header:    Full column header string from the CSV.
    site_name: Site prefix to strip (default "Bracon Ash").

    Returns
    -------
    NormalisedColumn with skip=True for columns that should be discarded.
    """
    # Strip leading/trailing whitespace
    header = header.strip()

    # The timestamp column is handled by the parser directly
    if header.lower() in ("timestamp", "date/time", "datetime", "time"):
        return NormalisedColumn(equipment_type="__timestamp__", db_column="ts", skip=True)

    # Strip site prefix: "{Site Name} - "
    site_prefix = f"{site_name} - "
    if header.startswith(site_prefix):
        remainder = header[len(site_prefix):]
    else:
        remainder = header

    # Split into equipment and measurement+unit parts
    # Format: "{Equipment} - {Measurement} ({Unit})"
    parts = remainder.split(" - ", maxsplit=1)
    if len(parts) != 2:
        return NormalisedColumn(equipment_type="unknown", db_column="", skip=True)

    equipment_raw, measurement_with_unit = parts[0].strip(), parts[1].strip()

    # Strip unit suffix: "Measurement (Unit)" → "Measurement"
    measurement, _unit = _strip_unit(measurement_with_unit)

    # Skip RAPITLOG / RAPILOG equipment (typo variants tolerated)
    if re.match(r"^RAPI[T]?LOG", equipment_raw, re.IGNORECASE):
        return NormalisedColumn(equipment_type="rapitlog", db_column="", skip=True)

    # Skip pre-calculated summary fields
    if measurement.upper() in _SKIP_MEASUREMENTS:
        return NormalisedColumn(equipment_type="skip", db_column="", skip=True)

    # ── Weather Station ──────────────────────────────────────────────────────
    if "WEATHER STATION" in equipment_raw.upper():
        return _normalise_weather(equipment_raw, measurement)

    # ── CFD Meter ────────────────────────────────────────────────────────────
    if "METER" in equipment_raw.upper():
        return _normalise_meter(measurement)

    # ── String (must check before Inverter — strings have longer ID) ─────────
    str_match = _RE_STRING.match(equipment_raw)
    if str_match:
        inverter_id = str_match.group("inverter").upper()
        string_id = str_match.group("string").upper()
        return _normalise_string(measurement, inverter_id, string_id)

    # ── Inverter ─────────────────────────────────────────────────────────────
    if _RE_INVERTER.match(equipment_raw):
        return _normalise_inverter(measurement, equipment_raw.upper())

    # Unknown equipment — skip
    return NormalisedColumn(equipment_type="unknown", db_column="", skip=True)


# ---------------------------------------------------------------------------
# Equipment-specific helpers
# ---------------------------------------------------------------------------

def _normalise_weather(equipment_raw: str, measurement: str) -> NormalisedColumn:
    meas_upper = measurement.upper()

    # Temperature: PT1000-MODULE-N → averaged into temp_mod_avg_c
    if _RE_TEMP_MODULE.match(measurement):
        return NormalisedColumn(
            equipment_type="weather",
            db_column="temp_mod_avg_c",
            is_avg_group=True,
        )

    # Ambient temperature: TEMP-1, TEMP-2 → averaged into temp_amb_c
    if _RE_TEMP_AMB.match(measurement):
        return NormalisedColumn(
            equipment_type="weather",
            db_column="temp_amb_c",
            is_avg_group=True,
        )

    db_col = _WEATHER_MAP.get(measurement) or _WEATHER_MAP.get(meas_upper)
    if db_col is None:
        return NormalisedColumn(equipment_type="weather", db_column="", skip=True)

    return NormalisedColumn(equipment_type="weather", db_column=db_col)


def _normalise_meter(measurement: str) -> NormalisedColumn:
    meas_upper = measurement.upper()
    db_col = _METER_MAP.get(measurement) or _METER_MAP.get(meas_upper)
    if db_col is None:
        return NormalisedColumn(equipment_type="meter", db_column="", skip=True)
    return NormalisedColumn(equipment_type="meter", db_column=db_col)


def _normalise_inverter(measurement: str, inverter_id: str) -> NormalisedColumn:
    meas_upper = measurement.upper()
    db_col = _INVERTER_MAP.get(measurement) or _INVERTER_MAP.get(meas_upper)
    if db_col is None:
        return NormalisedColumn(equipment_type="inverter", db_column="", skip=True)
    return NormalisedColumn(
        equipment_type="inverter",
        db_column=db_col,
        equipment_id=inverter_id,
    )


def _normalise_string(measurement: str, inverter_id: str, string_id: str) -> NormalisedColumn:
    meas_upper = measurement.upper()
    db_col = _STRING_MAP.get(measurement) or _STRING_MAP.get(meas_upper)
    if db_col is None:
        return NormalisedColumn(equipment_type="string", db_column="", skip=True)
    return NormalisedColumn(
        equipment_type="string",
        db_column=db_col,
        equipment_id=inverter_id,
        string_id=string_id,
    )


def _strip_unit(s: str) -> tuple[str, str]:
    """Split 'Measurement (Unit)' into ('Measurement', 'Unit').
    Returns ('s', '') if no parenthesised unit is found."""
    m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", s)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return s.strip(), ""
