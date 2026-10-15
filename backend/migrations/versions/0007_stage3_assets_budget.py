"""Image preparation and atomic shared reservations, preserving legacy nodes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0007_stage3_assets_budget'
down_revision = '0006_story_presentations'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sessions', sa.Column('requires_assets', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('image_tasks',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('sessions.id'), nullable=False),
        sa.Column('story_version_id', sa.String(36), sa.ForeignKey('story_versions.id'), nullable=False),
        sa.Column('idempotency_key', sa.String(80), nullable=False),
        sa.Column('recovery_keys', sa.JSON().with_variant(JSONB,'postgresql'), nullable=False),
        sa.Column('status', sa.String(30), nullable=False), sa.Column('error_code', sa.String(80)),
        sa.Column('trace_id', sa.String(36)), sa.Column('trace_seq', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('session_id','idempotency_key', name='uq_image_key'),
        sa.UniqueConstraint('session_id','story_version_id', name='uq_image_story'))
    op.create_table('story_assets',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_id', sa.String(36), sa.ForeignKey('image_tasks.id'), nullable=False),
        sa.Column('story_version_id', sa.String(36), sa.ForeignKey('story_versions.id'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False), sa.Column('entity_id', sa.String(64), nullable=False),
        sa.Column('status', sa.String(30), nullable=False), sa.Column('prompt', sa.String(12000), nullable=False),
        sa.Column('prompt_version', sa.String(40), nullable=False), sa.Column('model_id', sa.String(100), nullable=False),
        sa.Column('size', sa.String(20), nullable=False), sa.Column('download_url', sa.String(4000)),
        sa.Column('file_path', sa.String(200)), sa.Column('sha256', sa.String(64)), sa.Column('error_code', sa.String(80)),
        sa.UniqueConstraint('story_version_id','kind','entity_id', name='uq_asset_slot'))
    for table, constraint in [('llm_calls','ck_call_task'), ('execution_traces','ck_trace_task')]:
        op.add_column(table, sa.Column('image_task_id',sa.String(36),sa.ForeignKey('image_tasks.id')))
        op.drop_constraint(constraint,table,type_='check')
        op.create_check_constraint(constraint,table,'num_nonnulls(run_id, creation_task_id, image_task_id) = 1')
    op.add_column('llm_calls',sa.Column('image_count',sa.Integer()))
    op.create_table('budget_accounts',sa.Column('id',sa.Integer(),primary_key=True))
    op.execute('INSERT INTO budget_accounts (id) VALUES (1)')
    op.create_table('cost_reservations',
        sa.Column('attempt_id',sa.String(36),sa.ForeignKey('execution_traces.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('amount_cny',sa.Numeric(12,6),nullable=False),sa.Column('status',sa.String(20),nullable=False),
        sa.Column('provider',sa.String(20),nullable=False),sa.Column('model_id',sa.String(100),nullable=False),
        sa.Column('price_version',sa.String(40),nullable=False),sa.Column('chargeable',sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column('call_id',sa.String(36),sa.ForeignKey('llm_calls.id')))


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT EXISTS(SELECT 1 FROM execution_traces)')):
        raise RuntimeError('cannot downgrade execution records')
    if op.get_bind().scalar(sa.text('SELECT EXISTS(SELECT 1 FROM image_tasks) OR EXISTS(SELECT 1 FROM cost_reservations)')):
        raise RuntimeError('cannot downgrade stage3 runtime records')
    op.drop_table('cost_reservations')
    op.drop_table('budget_accounts')
    op.drop_column('llm_calls','image_count')
    for table,constraint in [('llm_calls','ck_call_task'),('execution_traces','ck_trace_task')]:
        op.drop_constraint(constraint,table,type_='check')
        op.drop_column(table,'image_task_id')
        op.create_check_constraint(constraint,table,'num_nonnulls(run_id, creation_task_id) = 1')
    op.drop_table('story_assets')
    op.drop_table('image_tasks')
    op.drop_column('sessions','requires_assets')
