"""Create the sites table when needed and add config_json.

Historically ``sites`` was bootstrapped outside Alembic before this revision.
Fresh environments do not have that manual bootstrap, so the migration must
establish the base table before adding the documented JSON configuration.

Revision ID: 0002
Revises: 0001
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS sites (
            site_id          UUID             PRIMARY KEY,
            site_name        TEXT             NOT NULL,
            site_code        TEXT             NOT NULL UNIQUE,
            latitude         DOUBLE PRECISION NOT NULL,
            longitude        DOUBLE PRECISION NOT NULL,
            timezone         TEXT             NOT NULL,
            capacity_kwp     DOUBLE PRECISION NOT NULL,
            strings_per_inv  INTEGER          NOT NULL DEFAULT 32,
            subsidy_type     TEXT
        )
    """))
    op.execute(sa.text(
        "ALTER TABLE sites ADD COLUMN IF NOT EXISTS config_json JSONB"
    ))


def downgrade():
    op.execute(sa.text(
        "ALTER TABLE sites DROP COLUMN IF EXISTS config_json"
    ))
