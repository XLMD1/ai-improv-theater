"""Record model usage and estimated spend.

Revision ID: 0003_llm_calls
Revises: 0002_session_provider
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_llm_calls"
down_revision = "0002_session_provider"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_cny", sa.Numeric(12, 6), nullable=False),
        sa.Column("price_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_llm_calls_run_id", "llm_calls", ["run_id"])


def downgrade():
    op.drop_table("llm_calls")
