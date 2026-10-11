"""Fix presentation policy separately from immutable historical story content."""
from alembic import op
import sqlalchemy as sa

revision = '0006_story_presentations'
down_revision = '0005_execution_records'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('story_presentations',
        sa.Column('story_version_id', sa.String(36), sa.ForeignKey('story_versions.id'), primary_key=True),
        sa.Column('narration_protocol', sa.String(40), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("narration_protocol = 'approved-feedback-1'", name='ck_narration_protocol'))
    op.execute("""CREATE FUNCTION protect_story_presentation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'story presentation is immutable' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql""")
    op.execute('CREATE TRIGGER immutable_story_presentation BEFORE UPDATE OR DELETE ON story_presentations '
               'FOR EACH ROW EXECUTE FUNCTION protect_story_presentation()')


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM story_tasks) OR EXISTS(SELECT 1 FROM execution_traces) "
                                 "OR EXISTS(SELECT 1 FROM runs WHERE trace_id IS NOT NULL) "
                                 "OR EXISTS(SELECT 1 FROM nodes WHERE investigation_options IS NOT NULL) "
                                 "OR EXISTS(SELECT 1 FROM llm_calls WHERE attempt_id IS NOT NULL)")):
        raise RuntimeError('cannot downgrade execution records')
    if connection.scalar(sa.text('SELECT EXISTS(SELECT 1 FROM story_presentations)')):
        raise RuntimeError('cannot downgrade presentation records')
    op.execute('DROP TRIGGER immutable_story_presentation ON story_presentations')
    op.execute('DROP FUNCTION protect_story_presentation()')
    op.drop_table('story_presentations')
