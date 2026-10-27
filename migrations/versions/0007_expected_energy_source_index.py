"""Index isolated expected-model windows and latest timestamps.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Match the existing descending-time index style; retain the site/time index.
    op.execute(
        "CREATE INDEX idx_expected_energy_site_source_time "
        "ON expected_energy (site_id, source, time DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX idx_expected_energy_site_source_time")
