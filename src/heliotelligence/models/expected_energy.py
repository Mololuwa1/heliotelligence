"""ORM model for the expected_energy TimescaleDB hypertable.

Schema
------
  time          TIMESTAMPTZ NOT NULL          — hypertable partition key
  site_id       UUID NOT NULL                 — site identifier
  p_ac_kw       DOUBLE PRECISION              — AC power after inverter + AC losses
  p_dc_kw       DOUBLE PRECISION              — DC power after SDM + DC loss cascade
  p_dc_stc_kw   DOUBLE PRECISION              — nameplate DC at STC (PR denominator)
  poa_total_wm2 DOUBLE PRECISION              — effective POA used in calculation
  t_cell_c      DOUBLE PRECISION              — cell temperature used in calculation
  tier_used     SMALLINT                      — module lookup tier 1–5
  fit_quality   TEXT                          — 'high' | 'low' | 'pvwatts'
  source        TEXT NOT NULL DEFAULT 'physics_sdm'
  quality       SMALLINT NOT NULL DEFAULT 0  — 0=good, 1=gap-filled, 2=flagged

Primary key: (time, site_id, source)
"""

from __future__ import annotations

import datetime

from sqlalchemy import DateTime, Double, Index, SmallInteger, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from heliotelligence.db.base import Base


class ExpectedEnergy(Base):
    """Expected AC/DC energy output computed by the physics SDM pipeline."""

    __tablename__ = "expected_energy"

    # --- Primary-key components (must include hypertable partition col) ------
    time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    site_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), nullable=False)
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="physics_sdm"
    )

    # --- Physics outputs -----------------------------------------------------
    p_ac_kw: Mapped[float | None] = mapped_column(Double, nullable=True)
    p_dc_kw: Mapped[float | None] = mapped_column(Double, nullable=True)
    p_dc_stc_kw: Mapped[float | None] = mapped_column(Double, nullable=True)
    poa_total_wm2: Mapped[float | None] = mapped_column(Double, nullable=True)
    t_cell_c: Mapped[float | None] = mapped_column(Double, nullable=True)

    # --- Provenance ----------------------------------------------------------
    tier_used: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    fit_quality: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Quality flag --------------------------------------------------------
    quality: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )

    __table_args__ = (
        # Unique constraint matches the ON CONFLICT target in upsert.py
        # and mirrors the index created in Tiger Data.
        Index(
            "uq_expected_energy",
            "time",
            "site_id",
            "source",
            unique=True,
        ),
        Index(
            "idx_expected_energy_site_time",
            "site_id",
            time.desc(),  # type: ignore[attr-defined]
        ),
    )
