"""Document sites table (created outside Alembic during Cloud SQL migration)

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-27

Note: The sites table was bootstrapped manually during the TimescaleDB ->
Cloud SQL migration. This migration is a no-op that records it in Alembic
history. The table already exists.
"""
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Table already exists — created manually during Cloud SQL bootstrap.
    # This migration documents it in Alembic version history only.
    pass


def downgrade() -> None:
    # Do not drop sites on downgrade — it contains live data.
    pass
