"""Add inverters, site_instruments, alerts tables and application views

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-27

These tables and views existed in Timescale Cloud but were never added
to Alembic migrations. This migration brings them into Cloud SQL.
"""
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # uuid-ossp for uuid_generate_v4() default
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # ── inverters ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS inverters (
            inverter_pk         UUID        NOT NULL DEFAULT uuid_generate_v4(),
            site_id             UUID        NOT NULL,
            inverter_id         TEXT        NOT NULL,
            manufacturer        TEXT,
            model               TEXT,
            serial_number       TEXT,
            rated_power_kw      DOUBLE PRECISION,
            rated_voltage_vac   DOUBLE PRECISION,
            rated_current_aac   DOUBLE PRECISION,
            rated_voltage_vdc   DOUBLE PRECISION,
            rated_current_adc   DOUBLE PRECISION,
            efficiency_pct      DOUBLE PRECISION
                CONSTRAINT chk_eta_range CHECK (efficiency_pct BETWEEN 0 AND 100),
            num_strings         INTEGER     NOT NULL,
            inverter_type       TEXT        NOT NULL DEFAULT 'string'
                CONSTRAINT chk_inverter_type
                CHECK (inverter_type IN ('string','central','micro','hybrid')),
            pvlib_model_type    TEXT        DEFAULT 'pvwatts'
                CONSTRAINT chk_pvlib_model_type
                CHECK (pvlib_model_type IN ('sandia','pvwatts','cec') OR pvlib_model_type IS NULL),
            comms_protocol      TEXT
                CONSTRAINT chk_comms_protocol
                CHECK (comms_protocol IN ('modbus_tcp','modbus_rtu','sunspec','proprietary','unknown') OR comms_protocol IS NULL),
            scada_inverter_id   TEXT,
            pvlib_params        JSONB,
            notes               TEXT,
            created_at          TIMESTAMPTZ DEFAULT now(),
            updated_at          TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (inverter_pk)
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_inverter_site ON inverters (site_id, inverter_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_inverters_site ON inverters (site_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_inverters_scada_id ON inverters (scada_inverter_id)")

    # ── site_instruments ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS site_instruments (
            instrument_pk       UUID        NOT NULL DEFAULT uuid_generate_v4(),
            site_id             UUID,
            instrument_id       TEXT,
            instrument_type     TEXT
                CONSTRAINT chk_instrument_type
                CHECK (instrument_type IN ('pyranometer','reference_cell','thermometer','wind_sensor','rain_gauge','power_meter','other') OR instrument_type IS NULL),
            manufacturer        TEXT,
            model               TEXT,
            serial_number       TEXT,
            calibration_date    DATE,
            calibration_factor  DOUBLE PRECISION,
            measurement_plane   TEXT
                CONSTRAINT chk_measurement_plane
                CHECK (measurement_plane IN ('horizontal','poa','vertical','other') OR measurement_plane IS NULL),
            iso_class           TEXT
                CONSTRAINT chk_iso_class
                CHECK (iso_class IN ('class_a','class_b','class_c','reference') OR iso_class IS NULL),
            num_channels        INTEGER
                CONSTRAINT chk_num_channels
                CHECK (num_channels > 0 OR num_channels IS NULL),
            aggregation_rule    TEXT        NOT NULL DEFAULT 'none'
                CONSTRAINT chk_aggregation_rule
                CHECK (aggregation_rule IN ('mean','max','min','none')),
            column_mapping      JSONB       NOT NULL DEFAULT '{}',
            channel_columns     JSONB       NOT NULL DEFAULT '[]',
            notes               TEXT,
            active              BOOLEAN     DEFAULT true,
            installed_at        TIMESTAMPTZ,
            removed_at          TIMESTAMPTZ,
            created_at          TIMESTAMPTZ DEFAULT now(),
            updated_at          TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (instrument_pk)
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_instrument_site ON site_instruments (site_id, instrument_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_instruments_site ON site_instruments (site_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_instruments_type ON site_instruments (instrument_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_instruments_mapping ON site_instruments USING GIN (column_mapping)")

    # ── alerts ────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id              BIGSERIAL       PRIMARY KEY,
            site_id         UUID            NOT NULL,
            fired_at        TIMESTAMPTZ     NOT NULL DEFAULT now(),
            rule_name       TEXT            NOT NULL,
            severity        TEXT            NOT NULL,
            metric_value    DOUBLE PRECISION,
            threshold       DOUBLE PRECISION,
            message         TEXT            NOT NULL,
            acknowledged    BOOLEAN         NOT NULL DEFAULT false,
            resolved_at     TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_alerts_site_time ON alerts (site_id, fired_at DESC)")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_alerts_active
        ON alerts (site_id, fired_at DESC)
        WHERE resolved_at IS NULL
    """)

    # ── Application views (standard SQL — no TimescaleDB dependency) ──────

    # latest_readings — most recent inverter reading per site
    op.execute("""
        CREATE OR REPLACE VIEW latest_readings AS
        SELECT DISTINCT ON (site_id, inverter_id)
            site_id,
            inverter_id,
            ts,
            inv_p_ac_kw,
            inv_e_kwh,
            inv_avail_pct,
            plant_irr_wm2,
            inv_coms_status,
            quality_flag
        FROM inverter_readings
        ORDER BY site_id, inverter_id, ts DESC
    """)

    # instrument_column_map — maps instrument channels to DB columns
    op.execute("""
        CREATE OR REPLACE VIEW instrument_column_map AS
        SELECT
            si.site_id,
            si.instrument_id,
            si.instrument_type,
            m.key   AS scada_field,
            m.value AS db_column
        FROM site_instruments si
        CROSS JOIN LATERAL jsonb_each_text(si.column_mapping) AS m(key, value)
        WHERE si.active = true
    """)

    # inverter_hourly — hourly aggregation (rewritten without TimescaleDB)
    op.execute("""
        CREATE OR REPLACE VIEW inverter_hourly AS
        SELECT
            date_trunc('hour', ts)  AS hour,
            site_id,
            inverter_id,
            AVG(inv_p_ac_kw)        AS avg_p_ac_kw,
            MAX(inv_p_ac_kw)        AS max_p_ac_kw,
            AVG(inv_avail_pct)      AS avg_avail_pct,
            AVG(plant_irr_wm2)      AS avg_irr_wm2,
            COUNT(*)                AS sample_count
        FROM inverter_readings
        WHERE quality_flag = 0
        GROUP BY 1, 2, 3
    """)

    # meter_hourly — hourly meter aggregation
    op.execute("""
        CREATE OR REPLACE VIEW meter_hourly AS
        SELECT
            date_trunc('hour', ts)  AS hour,
            site_id,
            AVG(p_ac_kw)            AS avg_p_ac_kw,
            MAX(p_ac_kw)            AS max_p_ac_kw,
            SUM(e_exported_kwh)     AS total_exported_kwh,
            AVG(power_factor)       AS avg_power_factor,
            COUNT(*)                AS sample_count
        FROM meter_readings
        WHERE quality_flag = 0
        GROUP BY 1, 2
    """)

    # meter_daily — daily meter aggregation
    op.execute("""
        CREATE OR REPLACE VIEW meter_daily AS
        SELECT
            date_trunc('day', ts)   AS day,
            site_id,
            AVG(p_ac_kw)            AS avg_p_ac_kw,
            MAX(p_ac_kw)            AS peak_p_ac_kw,
            SUM(e_exported_kwh)     AS total_exported_kwh,
            AVG(power_factor)       AS avg_power_factor,
            COUNT(*)                AS sample_count
        FROM meter_readings
        WHERE quality_flag = 0
        GROUP BY 1, 2
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS meter_daily")
    op.execute("DROP VIEW IF EXISTS meter_hourly")
    op.execute("DROP VIEW IF EXISTS inverter_hourly")
    op.execute("DROP VIEW IF EXISTS instrument_column_map")
    op.execute("DROP VIEW IF EXISTS latest_readings")
    op.execute("DROP TABLE IF EXISTS alerts")
    op.execute("DROP TABLE IF EXISTS site_instruments")
    op.execute("DROP TABLE IF EXISTS inverters")
