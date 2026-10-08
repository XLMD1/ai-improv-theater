"""Pin provider and model on each story session.

Revision ID: 0002_session_provider
Revises: 0001_initial
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_session_provider"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sessions", sa.Column("provider", sa.String(20), server_default="demo", nullable=False))
    op.add_column("sessions", sa.Column("model_id", sa.String(100), server_default="demo", nullable=False))
    op.alter_column("sessions", "provider", server_default=None)
    op.alter_column("sessions", "model_id", server_default=None)


def downgrade():
    op.drop_column("sessions", "model_id")
    op.drop_column("sessions", "provider")
