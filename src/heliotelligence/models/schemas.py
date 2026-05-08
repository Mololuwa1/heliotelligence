"""Pydantic v2 ingest schemas for the four equipment groups.

These are write-path (ingest) models only. They intentionally import nothing
from models/orm.py to avoid coupling Pydantic validation to SQLAlchemy.

All timestamps must be timezone-aware (UTC enforced at parse time in csv_parser).
Quality flag defaults to 0; quality/flags.py overwrites before upsert.
"""

from __future__ import annotations

import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class WeatherReadingIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    site_id: str
    time: AwareDatetime

    ghi_wm2: float | None = None
    poa_wm2: float | None = None
    poa2_wm2: float | None = None
    ghi_b_wm2: float | None = None
    ref_cell1_wm2: float | None = None

    temp_amb_c: float | None = None
    temp_mod_avg_c: float | None = None

    wind_speed_ms: float | None = None
    wind_dir_deg: float | None = None
    precip_mm: float | None = None

    ws_com_status: str | None = None
    source: str = "met_station"

    quality: int = Field(default=0, ge=0, le=3)


class MeterReadingIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    site_id: str
    time: AwareDatetime

    p_ac_kw: float | None = None
    e_exported_kwh: float | None = None
    e_net_kwh: float | None = None
    freq_hz: float | None = None
    power_factor: float | None = None
    q_kvar: float | None = None

    quality: int = Field(default=0, ge=0, le=3)


class InverterReadingIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    site_id: str
    inverter_id: str
    time: AwareDatetime

    inv_p_ac_kw: float | None = None
    inv_e_kwh: float | None = None
    inv_avail_pct: float | None = None
    inv_avail_exc_pct: float | None = None
    inv_str_avail_pct: float | None = None
    plant_irr_wm2: float | None = None
    inv_coms_status: str | None = None

    quality: int = Field(default=0, ge=0, le=3)


class StringReadingIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    site_id: str
    inverter_id: str
    string_id: str
    time: AwareDatetime

    str_current_a: float | None = None
    str_energy_kwh: float | None = None
    str_power_kw: float | None = None
    str_avail_pct: float | None = None
    str_avail_exc_pct: float | None = None

    quality: int = Field(default=0, ge=0, le=3)
