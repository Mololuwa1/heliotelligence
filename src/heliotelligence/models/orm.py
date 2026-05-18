"""SQLAlchemy ORM models for the four TimescaleDB hypertables.

Hypertable partition column is always `ts` (TIMESTAMPTZ, UTC, period-end).
All PKs are composite and include `ts` so TimescaleDB chunk exclusion works.

Quality flags
  0 = good
  1 = gap-filled
  2 = flagged (comms error, physical range violation, IQR outlier)
  3 = missing
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    DateTime,
    Double,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Index,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from heliotelligence.db.base import Base


class WeatherReading(Base):
    """Weather Station CT01 — site-level meteorological data."""

    __tablename__ = "weather_readings"

    site_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), nullable=False)
    time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Irradiance
    ghi_wm2: Mapped[float | None] = mapped_column(Double, nullable=True)   # SMP10-GHI-F
    dhi_wm2: Mapped[float | None] = mapped_column(Double, nullable=True)   # diffuse horizontal (or Erbs-derived)
    dni_wm2: Mapped[float | None] = mapped_column(Double, nullable=True)   # direct normal (or Erbs-derived)
    poa_wm2: Mapped[float | None] = mapped_column(Double, nullable=True)   # SMP10-POA-1
    poa2_wm2: Mapped[float | None] = mapped_column(Double, nullable=True)  # SMP10-RPOA-2
    ghi_b_wm2: Mapped[float | None] = mapped_column(Double, nullable=True) # SMP10-GHI-B
    ref_cell1_wm2: Mapped[float | None] = mapped_column(Double, nullable=True)

    # Temperature
    temp_amb_c: Mapped[float | None] = mapped_column(Double, nullable=True)      # avg TEMP-1/2
    temp_mod_avg_c: Mapped[float | None] = mapped_column(Double, nullable=True)  # avg PT1000-MODULE-1..6

    # Wind & precipitation
    wind_speed_ms: Mapped[float | None] = mapped_column(Double, nullable=True)
    wind_dir_deg: Mapped[float | None] = mapped_column(Double, nullable=True)
    precip_mm: Mapped[float | None] = mapped_column(Double, nullable=True)

    # Comms
    ws_com_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Source
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="met_station"
    )

    # Quality
    quality: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )

    __table_args__ = (
        PrimaryKeyConstraint("site_id", "time", name="pk_weather_readings"),
        Index("ix_weather_readings_site_ts", "site_id", time.desc()),  # type: ignore[attr-defined]
    )


class MeterReading(Base):
    """CFD Meter — site-level AC grid metering."""

    __tablename__ = "meter_readings"

    site_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), nullable=False)
    time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    p_ac_kw: Mapped[float | None] = mapped_column(Double, nullable=True)         # ACTIVE POWER
    e_exported_kwh: Mapped[float | None] = mapped_column(Double, nullable=True)  # EXPORTED ACTIVE ENERGY
    e_net_kwh: Mapped[float | None] = mapped_column(Double, nullable=True)       # TOTAL NET ACTIVE ENERGY DEL-REC
    freq_hz: Mapped[float | None] = mapped_column(Double, nullable=True)
    power_factor: Mapped[float | None] = mapped_column(Double, nullable=True)
    q_kvar: Mapped[float | None] = mapped_column(Double, nullable=True)          # REACTIVE POWER

    quality: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )

    __table_args__ = (
        PrimaryKeyConstraint("site_id", "time", name="pk_meter_readings"),
        Index("ix_meter_readings_site_ts", "site_id", time.desc()),  # type: ignore[attr-defined]
    )


class InverterReading(Base):
    """Per-inverter readings (e.g. MQA11-TB101)."""

    __tablename__ = "inverter_readings"

    site_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), nullable=False)
    inverter_id: Mapped[str] = mapped_column(String(32), nullable=False)
    time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    inv_p_ac_kw: Mapped[float | None] = mapped_column(Double, nullable=True)        # TOTAL ACTIVE POWER
    inv_e_kwh: Mapped[float | None] = mapped_column(Double, nullable=True)          # TOTAL POWER YIELDS
    inv_avail_pct: Mapped[float | None] = mapped_column(Double, nullable=True)      # Availability
    inv_avail_exc_pct: Mapped[float | None] = mapped_column(Double, nullable=True)  # Availability with Exceptions
    inv_str_avail_pct: Mapped[float | None] = mapped_column(Double, nullable=True)  # Availability Strings
    plant_irr_wm2: Mapped[float | None] = mapped_column(Double, nullable=True)      # Plant Irradiance
    inv_coms_status: Mapped[str | None] = mapped_column(String(32), nullable=True)  # COMS STATUS

    quality: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )

    __table_args__ = (
        PrimaryKeyConstraint(
            "site_id", "inverter_id", "time", name="pk_inverter_readings"
        ),
        Index(
            "ix_inverter_readings_site_inv_ts",
            "site_id",
            "inverter_id",
            time.desc(),  # type: ignore[attr-defined]
        ),
    )


class StringReading(Base):
    """Per-string readings (32 strings × N inverters)."""

    __tablename__ = "string_readings"

    site_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), nullable=False)
    inverter_id: Mapped[str] = mapped_column(String(32), nullable=False)
    string_id: Mapped[str] = mapped_column(String(16), nullable=False)
    time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    str_current_a: Mapped[float | None] = mapped_column(Double, nullable=True)      # STRING CURRENT
    str_energy_kwh: Mapped[float | None] = mapped_column(Double, nullable=True)     # Energy
    str_power_kw: Mapped[float | None] = mapped_column(Double, nullable=True)       # Power
    str_avail_pct: Mapped[float | None] = mapped_column(Double, nullable=True)      # Availability
    str_avail_exc_pct: Mapped[float | None] = mapped_column(Double, nullable=True)  # Availability with Exceptions

    quality: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )

    __table_args__ = (
        PrimaryKeyConstraint(
            "site_id", "inverter_id", "string_id", "time",
            name="pk_string_readings",
        ),
        Index(
            "ix_string_readings_site_inv_str_ts",
            "site_id",
            "inverter_id",
            "string_id",
            time.desc(),  # type: ignore[attr-defined]
        ),
    )
