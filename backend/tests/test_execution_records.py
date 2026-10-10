import importlib.util
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, select


_test_sessions = []


def cleanup_records():
    from app.db import SessionLocal
    from app.models import ExecutionTrace, LLMCall, StorySession, StoryTask, StoryTaskEvent
    with SessionLocal.begin() as db:
        tasks = select(StoryTask.id).where(StoryTask.session_id.in_(_test_sessions))
        db.execute(delete(ExecutionTrace).where(ExecutionTrace.session_id.in_(_test_sessions)))
        db.execute(delete(LLMCall).where(LLMCall.creation_task_id.in_(tasks)))
        db.execute(delete(StoryTaskEvent).where(StoryTaskEvent.task_id.in_(tasks)))
        db.execute(delete(StoryTask).where(StoryTask.session_id.in_(_test_sessions)))
        db.execute(delete(StorySession).where(StorySession.id.in_(_test_sessions)))
    _test_sessions.clear()


@pytest.fixture(autouse=True)
def clean_records():
    yield
    cleanup_records()


def records():
    assert importlib.util.find_spec('app.execution_traces'), 'execution records are not implemented'
    from app.db import SessionLocal
    from app.execution_traces import TaskRef, TraceRecorder
    from app.models import StorySession, StoryTask
    with SessionLocal.begin() as db:
        session = StorySession(token_hash=uuid4().hex, provider='deepseek', model_id='deepseek-flash')
        db.add(session)
        db.flush()
        _test_sessions.append(session.id)
        task = StoryTask(session_id=session.id, story_id=str(uuid4()), idempotency_key=uuid4().hex,
                         request={'setting': 'test', 'era': 'modern'})
        db.add(task)
        db.flush()
        ref = TaskRef('creation', task.id, session.id)
    return TraceRecorder(SessionLocal, secrets=['fixture-private-key']), ref, SessionLocal


def outcome(**overrides):
    return dict(provider='deepseek', model_id='deepseek-flash', text='{}', input_tokens=120,
                output_tokens=80, request_sent=True, estimated_cost_cny='0.001',
                price_version='test-price', **overrides)


def test_trace_survives_story_rollback():
    recorder, task, factory = records()
    from app.models import ExecutionTrace, LLMCall, Node
    recorder.start(task)
    attempt = recorder.begin_attempt(task, 'story.generate', 'v1', 1, {'input': 'safe'})
    recorder.finish_attempt(attempt, outcome(), None)
    with factory() as db:
        db.add(Node(session_id=task.session_id, depth=0, scene_id='test'))
        db.rollback()
    with factory() as db:
        assert len(db.scalars(select(ExecutionTrace).where(ExecutionTrace.trace_id == attempt.trace_id)).all()) == 3
        call = db.scalar(select(LLMCall).where(LLMCall.attempt_id == attempt.attempt_id))
        assert call.input_tokens == 120
        assert call.estimated_cost_cny == Decimal('0.001')


def test_attempt_finalization_is_idempotent():
    recorder, task, factory = records()
    from app.models import LLMCall
    attempt = recorder.begin_attempt(task, 'story.generate', 'v1', 1, {})
    recorder.finish_attempt(attempt, outcome(), None)
    recorder.finish_attempt(attempt, outcome(), None)
    with factory() as db:
        assert len(db.scalars(select(LLMCall).where(LLMCall.attempt_id == attempt.attempt_id)).all()) == 1
    with pytest.raises(ValueError, match='attempt_result_conflict'):
        changed = outcome()
        changed['output_tokens'] = 81
        recorder.finish_attempt(attempt, changed, None)


def test_unknown_usage_is_not_zero():
    recorder, task, factory = records()
    from app.models import LLMCall
    attempt = recorder.begin_attempt(task, 'story.generate', 'v1', 1, {})
    data = outcome()
    data.update(input_tokens=None, output_tokens=None, estimated_cost_cny=None)
    recorder.finish_attempt(attempt, data, 'outcome_unknown')
    with factory() as db:
        call = db.scalar(select(LLMCall).where(LLMCall.attempt_id == attempt.attempt_id))
        assert call.input_tokens is None and call.output_tokens is None
        assert call.usage_status == 'uncertain'
        assert call.estimated_cost_cny is None


def test_foreign_task_rejected():
    recorder, task, _ = records()
    from app.execution_traces import TaskRef
    with pytest.raises(ValueError, match='task_not_found'):
        recorder.start(TaskRef('creation', task.task_id, str(uuid4())))


def test_redacts_known_credentials_and_headers():
    recorder, task, factory = records()
    from app.models import ExecutionTrace
    recorder.event(task, 'validation', {'Authorization': 'Bearer bad', 'nested': {'text': 'fixture-private-key'},
                                      'url': 'postgresql://name:pass@localhost/db', 'text': 'Bearer fixture-token'})
    with factory() as db:
        payload = str(db.scalar(select(ExecutionTrace.payload).where(ExecutionTrace.session_id == task.session_id)))
        assert 'fixture-private-key' not in payload and 'fixture-token' not in payload
        assert 'name:pass' not in payload and 'Bearer bad' not in payload


def test_concurrent_sequences_are_unique():
    recorder, task, factory = records()
    from app.models import ExecutionTrace
    recorder.start(task)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: recorder.event(task, 'test', {'index': i}), range(12)))
    with factory() as db:
        seqs = db.scalars(select(ExecutionTrace.seq).where(ExecutionTrace.session_id == task.session_id).order_by(ExecutionTrace.seq)).all()
        assert seqs == list(range(1, 14))


def test_migration_refuses_to_remove_execution_records():
    records()
    from alembic import command
    from alembic.config import Config
    with pytest.raises(RuntimeError, match='cannot downgrade execution records'):
        command.downgrade(Config('alembic.ini'), '0004_story_versions')
