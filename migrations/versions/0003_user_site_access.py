"""Add user_site_access table

Revision ID: 0003
Revises: 0002
"""

from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_site_access',
        sa.Column('uid', sa.Text, nullable=False),
        sa.Column('site_id', sa.Text, nullable=False),
        sa.Column('role', sa.Text, nullable=False, server_default='viewer'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('uid', 'site_id'),
    )


def downgrade():
    op.drop_table('user_site_access')
