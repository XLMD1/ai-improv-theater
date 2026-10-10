"""Versioned stories with nullable legacy associations and immutable definitions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_story_versions"
down_revision = "0003_llm_calls"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "story_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("story_id", sa.String(36), nullable=False),
        sa.Column("story_version", sa.String(30), nullable=False),
        sa.Column("schema_version", sa.String(30), nullable=False),
        sa.Column("engine_version", sa.String(30), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("approval_status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("story_id", "story_version", name="uq_story_version_identity"),
        sa.CheckConstraint("approval_status IN ('draft','approved')", name="ck_story_approval_status"),
    )
    op.add_column("sessions", sa.Column("story_version_id", sa.String(36), nullable=True))
    op.add_column("sessions", sa.Column("engine_version", sa.String(30), nullable=True))
    op.add_column("sessions", sa.Column("mode", sa.String(20), nullable=True))
    op.create_foreign_key("fk_session_story_version", "sessions", "story_versions", ["story_version_id"], ["id"])
    op.add_column("nodes", sa.Column("story_version_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_node_story_version", "nodes", "story_versions", ["story_version_id"], ["id"])
    op.alter_column("nodes", "scene_id", existing_type=sa.String(8), type_=sa.String(64), existing_nullable=False)
    op.execute("""
        CREATE FUNCTION protect_story_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'immutable story version' USING ERRCODE = '23514';
          END IF;
          IF ROW(NEW.id,NEW.story_id,NEW.story_version,NEW.schema_version,NEW.engine_version,
                 NEW.definition,NEW.content_hash,NEW.created_at)
             IS DISTINCT FROM
             ROW(OLD.id,OLD.story_id,OLD.story_version,OLD.schema_version,OLD.engine_version,
                 OLD.definition,OLD.content_hash,OLD.created_at) THEN
            RAISE EXCEPTION 'immutable story definition' USING ERRCODE = '23514';
          END IF;
          IF OLD.approval_status = 'approved' AND NEW.approval_status <> 'approved' THEN
            RAISE EXCEPTION 'approval cannot be revoked in place' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END; $$
    """)
    op.execute("CREATE TRIGGER story_version_immutable BEFORE UPDATE OR DELETE ON story_versions "
               "FOR EACH ROW EXECUTE FUNCTION protect_story_version()")


def downgrade():
    # Never silently truncate a new location ID when returning to the legacy schema.
    connection = op.get_bind()
    if connection.scalar(sa.text(
        "SELECT EXISTS(SELECT 1 FROM story_versions) "
        "OR EXISTS(SELECT 1 FROM sessions WHERE story_version_id IS NOT NULL OR engine_version IS NOT NULL OR mode IS NOT NULL) "
        "OR EXISTS(SELECT 1 FROM nodes WHERE story_version_id IS NOT NULL)"
    )):
        raise RuntimeError("cannot downgrade investigation records")
    if connection.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM nodes WHERE length(scene_id)>8)")):
        raise RuntimeError("cannot downgrade nodes with investigation location IDs")
    op.execute("DROP TRIGGER story_version_immutable ON story_versions")
    op.execute("DROP FUNCTION protect_story_version()")
    op.drop_constraint("fk_node_story_version", "nodes", type_="foreignkey")
    op.drop_column("nodes", "story_version_id")
    op.drop_constraint("fk_session_story_version", "sessions", type_="foreignkey")
    op.drop_column("sessions", "mode")
    op.drop_column("sessions", "engine_version")
    op.drop_column("sessions", "story_version_id")
    op.alter_column("nodes", "scene_id", existing_type=sa.String(64), type_=sa.String(8), existing_nullable=False)
    op.drop_table("story_versions")
