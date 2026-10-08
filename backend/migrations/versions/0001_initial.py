"""Stage 1 story snapshots, immutable events and demo run delivery.

Revision ID: 0001_initial
Revises:
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "nodes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("parent_id", sa.String(36), sa.ForeignKey("nodes.id")),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("scene_id", sa.String(8), nullable=False),
        sa.Column("state_snapshot", JSONB(), nullable=False),
        sa.Column("rendered_scene", JSONB(), nullable=False),
        sa.Column("canon_version", sa.String(30), nullable=False),
        sa.Column("prompt_version", sa.String(30), nullable=False),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_nodes_session_id", "nodes", ["session_id"])
    op.create_index("ix_nodes_parent_id", "nodes", ["parent_id"])
    op.create_table(
        "turn_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("node_id", sa.String(36), sa.ForeignKey("nodes.id"), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_turn_events_node_id", "turn_events", ["node_id"])
    op.create_table(
        "runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("parent_node_id", sa.String(36), sa.ForeignKey("nodes.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("action", JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("node_id", sa.String(36), sa.ForeignKey("nodes.id")),
        sa.Column("error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "idempotency_key", name="uq_run_idempotency"),
    )
    op.create_index("ix_run_session_status", "runs", ["session_id", "status"])
    op.create_table(
        "run_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(40), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "seq", name="uq_run_event_seq"),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])


def downgrade():
    op.drop_table("run_events")
    op.drop_table("runs")
    op.drop_table("turn_events")
    op.drop_table("nodes")
    op.drop_table("sessions")
