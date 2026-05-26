"""Initial TimescaleDB hypertables for Heliotelligence.

Creates four hypertables partitioned by `ts` (TIMESTAMPTZ, UTC, period-end):
  - weather_readings   PK (site_id, ts)
  - meter_readings     PK (site_id, ts)
  - inverter_readings  PK (site_id, inverter_id, ts)
  - string_readings    PK (site_id, inverter_id, string_id, ts)

All `create_hypertable` calls use `if_not_exists => TRUE` so this migration
is safe to run against a DB where the hypertables already exist.

Revision ID: 0001
Revises:     (none — first migration)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── weather_readings ─────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS weather_readings (
            site_id          VARCHAR(64)       NOT NULL,
            ts               TIMESTAMPTZ       NOT NULL,

            -- Irradiance
            ghi_wm2          DOUBLE PRECISION,
            poa_wm2          DOUBLE PRECISION,
            poa2_wm2         DOUBLE PRECISION,
            ghi_b_wm2        DOUBLE PRECISION,
            ref_cell1_wm2    DOUBLE PRECISION,

            -- Temperature
            temp_amb_c       DOUBLE PRECISION,
            temp_mod_avg_c   DOUBLE PRECISION,

            -- Wind & precipitation
            wind_speed_ms    DOUBLE PRECISION,
            wind_dir_deg     DOUBLE PRECISION,
            precip_mm        DOUBLE PRECISION,

            -- Comms
            ws_com_status    VARCHAR(32),

            -- Quality
            quality_flag     SMALLINT NOT NULL DEFAULT 0,

            PRIMARY KEY (site_id, ts)
        )
    """))

    # Removed: TimescaleDB create_hypertable — migrated to plain PostgreSQL (Cloud SQL)

    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_weather_readings_site_ts "
        "ON weather_readings (site_id, ts DESC)"
    ))

    # ── meter_readings ───────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS meter_readings (
            site_id          VARCHAR(64)       NOT NULL,
            ts               TIMESTAMPTZ       NOT NULL,

            p_ac_kw          DOUBLE PRECISION,
            e_exported_kwh   DOUBLE PRECISION,
            e_net_kwh        DOUBLE PRECISION,
            freq_hz          DOUBLE PRECISION,
            power_factor     DOUBLE PRECISION,
            q_kvar           DOUBLE PRECISION,

            quality_flag     SMALLINT NOT NULL DEFAULT 0,

            PRIMARY KEY (site_id, ts)
        )
    """))

    # Removed: TimescaleDB create_hypertable — migrated to plain PostgreSQL (Cloud SQL)

    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_meter_readings_site_ts "
        "ON meter_readings (site_id, ts DESC)"
    ))

    # ── inverter_readings ────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS inverter_readings (
            site_id            VARCHAR(64)       NOT NULL,
            inverter_id        VARCHAR(32)       NOT NULL,
            ts                 TIMESTAMPTZ       NOT NULL,

            inv_p_ac_kw        DOUBLE PRECISION,
            inv_e_kwh          DOUBLE PRECISION,
            inv_avail_pct      DOUBLE PRECISION,
            inv_avail_exc_pct  DOUBLE PRECISION,
            inv_str_avail_pct  DOUBLE PRECISION,
            plant_irr_wm2      DOUBLE PRECISION,
            inv_coms_status    VARCHAR(32),

            quality_flag       SMALLINT NOT NULL DEFAULT 0,

            PRIMARY KEY (site_id, inverter_id, ts)
        )
    """))

    # Removed: TimescaleDB create_hypertable — migrated to plain PostgreSQL (Cloud SQL)

    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_inverter_readings_site_inv_ts "
        "ON inverter_readings (site_id, inverter_id, ts DESC)"
    ))

    # ── string_readings ──────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS string_readings (
            site_id            VARCHAR(64)       NOT NULL,
            inverter_id        VARCHAR(32)       NOT NULL,
            string_id          VARCHAR(16)       NOT NULL,
            ts                 TIMESTAMPTZ       NOT NULL,

            str_current_a      DOUBLE PRECISION,
            str_energy_kwh     DOUBLE PRECISION,
            str_power_kw       DOUBLE PRECISION,
            str_avail_pct      DOUBLE PRECISION,
            str_avail_exc_pct  DOUBLE PRECISION,

            quality_flag       SMALLINT NOT NULL DEFAULT 0,

            PRIMARY KEY (site_id, inverter_id, string_id, ts)
        )
    """))

    # Removed: TimescaleDB create_hypertable — migrated to plain PostgreSQL (Cloud SQL)

    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_string_readings_site_inv_str_ts "
        "ON string_readings (site_id, inverter_id, string_id, ts DESC)"
    ))


def downgrade() -> None:
    # Dropping a hypertable drops all its chunks.
    op.execute(sa.text("DROP TABLE IF EXISTS string_readings"))
    op.execute(sa.text("DROP TABLE IF EXISTS inverter_readings"))
    op.execute(sa.text("DROP TABLE IF EXISTS meter_readings"))
    op.execute(sa.text("DROP TABLE IF EXISTS weather_readings"))
