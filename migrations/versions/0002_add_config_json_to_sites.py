"""Add config_json to sites table

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
    op.add_column('sites', sa.Column('config_json', JSONB, nullable=True))


def downgrade():
    op.drop_column('sites', 'config_json')
