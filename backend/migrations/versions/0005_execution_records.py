"""Creation tasks and audit records without changing legacy saved content."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0005_execution_records'
down_revision = '0004_story_versions'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('nodes', sa.Column('investigation_options', JSONB(), nullable=True))
    op.add_column('runs', sa.Column('trace_id', sa.String(36), nullable=True))
    op.add_column('runs', sa.Column('trace_seq', sa.Integer(), nullable=False, server_default='0'))
    op.alter_column('runs', 'trace_seq', server_default=None)
    op.create_table('story_tasks',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('sessions.id'), nullable=False),
        sa.Column('story_id', sa.String(36), nullable=False),
        sa.Column('source_task_id', sa.String(36), sa.ForeignKey('story_tasks.id'), nullable=True),
        sa.Column('idempotency_key', sa.String(80), nullable=False),
        sa.Column('request', JSONB(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('stage', sa.String(30), nullable=False),
        sa.Column('checkpoint', JSONB(), nullable=False),
        sa.Column('repair_count', sa.Integer(), nullable=False),
        sa.Column('candidate_version_id', sa.String(36), sa.ForeignKey('story_versions.id'), nullable=True),
        sa.Column('root_node_id', sa.String(36), sa.ForeignKey('nodes.id'), nullable=True),
        sa.Column('trace_id', sa.String(36), nullable=True),
        sa.Column('trace_seq', sa.Integer(), nullable=False),
        sa.Column('error_code', sa.String(80), nullable=True),
        sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('session_id', 'idempotency_key', name='uq_creation_key'))
    op.create_index('ix_story_tasks_session_id', 'story_tasks', ['session_id'])
    op.create_table('story_task_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_id', sa.String(36), sa.ForeignKey('story_tasks.id'), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('event', sa.String(40), nullable=False),
        sa.Column('payload', JSONB(), nullable=False),
        sa.UniqueConstraint('task_id', 'seq', name='uq_creation_event_seq'))
    for field in ('run_id', 'input_tokens', 'output_tokens', 'estimated_cost_cny'):
        op.alter_column('llm_calls', field, nullable=True)
    for field in ('trace_id', 'span_id', 'attempt_id'):
        op.add_column('llm_calls', sa.Column(field, sa.String(36), nullable=True))
    op.add_column('llm_calls', sa.Column('creation_task_id', sa.String(36), sa.ForeignKey('story_tasks.id'), nullable=True))
    for field, value in [('call_status', 'completed'), ('usage_status', 'known')]:
        op.add_column('llm_calls', sa.Column(field, sa.String(30), nullable=False, server_default=value))
        op.alter_column('llm_calls', field, server_default=None)
    op.create_unique_constraint('uq_llm_calls_attempt_id', 'llm_calls', ['attempt_id'])
    task_constraint = '(run_id IS NOT NULL AND creation_task_id IS NULL) OR (run_id IS NULL AND creation_task_id IS NOT NULL)'
    op.create_check_constraint('ck_call_task', 'llm_calls', task_constraint)
    op.create_table('execution_traces',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('trace_id', sa.String(36), nullable=False),
        sa.Column('span_id', sa.String(36), nullable=True),
        sa.Column('parent_span_id', sa.String(36), nullable=True),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('runs.id'), nullable=True),
        sa.Column('creation_task_id', sa.String(36), sa.ForeignKey('story_tasks.id'), nullable=True),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('sessions.id'), nullable=False),
        sa.Column('node_id', sa.String(36), sa.ForeignKey('nodes.id'), nullable=True),
        sa.Column('llm_call_id', sa.String(36), sa.ForeignKey('llm_calls.id'), nullable=True),
        sa.Column('event_type', sa.String(40), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('error_code', sa.String(80), nullable=True),
        sa.Column('payload', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('trace_id', 'seq', name='uq_trace_seq'),
        sa.CheckConstraint(task_constraint, name='ck_trace_task'))
    op.create_index('ix_execution_traces_trace_id', 'execution_traces', ['trace_id'])


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM story_tasks) OR EXISTS(SELECT 1 FROM execution_traces) "
                                 "OR EXISTS(SELECT 1 FROM runs WHERE trace_id IS NOT NULL) "
                                 "OR EXISTS(SELECT 1 FROM nodes WHERE investigation_options IS NOT NULL) "
                                 "OR EXISTS(SELECT 1 FROM llm_calls WHERE attempt_id IS NOT NULL)")):
        raise RuntimeError('cannot downgrade execution records')
    op.drop_table('execution_traces')
    op.drop_constraint('ck_call_task', 'llm_calls', type_='check')
    op.drop_constraint('uq_llm_calls_attempt_id', 'llm_calls', type_='unique')
    for field in ('creation_task_id', 'trace_id', 'span_id', 'attempt_id', 'call_status', 'usage_status'):
        op.drop_column('llm_calls', field)
    for field in ('run_id', 'input_tokens', 'output_tokens', 'estimated_cost_cny'):
        op.alter_column('llm_calls', field, nullable=False)
    op.drop_table('story_task_events')
    op.drop_table('story_tasks')
    op.drop_column('nodes', 'investigation_options')
    op.drop_column('runs', 'trace_seq')
    op.drop_column('runs', 'trace_id')
