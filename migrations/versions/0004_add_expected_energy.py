"""Add expected_energy table

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-27
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS expected_energy (
            time          TIMESTAMPTZ     NOT NULL,
            site_id       UUID            NOT NULL,
            source        TEXT            NOT NULL DEFAULT 'physics_sdm',
            p_ac_kw       DOUBLE PRECISION,
            p_dc_kw       DOUBLE PRECISION,
            p_dc_stc_kw   DOUBLE PRECISION,
            poa_total_wm2 DOUBLE PRECISION,
            t_cell_c      DOUBLE PRECISION,
            tier_used     SMALLINT,
            fit_quality   TEXT,
            quality       SMALLINT        DEFAULT 0,
            PRIMARY KEY (time, site_id, source)
        )
    """)

    # Index for time-series queries per site
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_expected_energy_site_time
        ON expected_energy (site_id, time DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS expected_energy")
