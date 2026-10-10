import importlib.util
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
import json
import secrets
import hashlib
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


def test_raw_json_and_bare_session_token_are_redacted_before_invalid_output_is_saved():
    recorder,task,factory = records()
    token = secrets.token_urlsafe(32)
    # Server stores a token hash, never its plaintext, and checks text against it.
    recorder.token_hashes = (hashlib.sha256(token.encode()).hexdigest(),)
    raw = json.dumps({'nested':json.dumps({'session_token':token,'reasoning_content':'PRIVATE_REASONING_SENTINEL'})})
    attempt = recorder.begin_attempt(task,'story.generate','v1',1,{'player_text':'请处理 '+token})
    recorder.finish_attempt(attempt,{**outcome(),'text':raw},None)
    recorder.event(task,'output_validation_failed',{'raw':'{"session_token":"'+token+'","reasoning_content":"PRIVATE_REASONING_SENTINEL'})
    from app.models import ExecutionTrace,LLMCall
    with factory() as db:
        saved = json.dumps([row.payload for row in db.scalars(select(ExecutionTrace).where(ExecutionTrace.trace_id==attempt.trace_id))])
        assert token not in saved and 'PRIVATE_REASONING_SENTINEL' not in saved
        call = db.scalar(select(LLMCall).where(LLMCall.attempt_id==attempt.attempt_id))
        assert call.input_tokens==120 and call.output_tokens==80


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


def unknown_call():
    recorder,task,factory = records()
    from app.models import LLMCall
    attempt = recorder.begin_attempt(task,'story.generate','v1',1,{})
    data = outcome()
    data.update(input_tokens=None,output_tokens=None,estimated_cost_cny=None)
    recorder.finish_attempt(attempt,data,'outcome_unknown')
    with factory() as db:
        call = db.scalar(select(LLMCall).where(LLMCall.attempt_id==attempt.attempt_id))
        return recorder,task,factory,call.id


def reconciliation(call_id,**changes):
    return {'schema_version':'usage-reconciliation-1','call_id':call_id,
            'source':'user_reported_provider_console','actual_cost_cny':Decimal('.02'),
            'total_tokens':9598,'input_tokens':5088,'output_tokens':4510,**changes}


def test_reconciliation_unblocks_only_reported_call_and_preserves_original_ledger():
    recorder,task,factory,call_id = unknown_call()
    from app.costs import check_execution_budget,total_spend_cny
    from app.models import ExecutionTrace,LLMCall,Node
    assert hasattr(recorder,'reconcile_usage'), 'local audited reconciliation is missing'
    with factory() as db:
        before = total_spend_cny(db)
        nodes = len(db.scalars(select(Node)).all())
        with pytest.raises(ValueError,match='cost_unconfirmed'):
            check_execution_budget(db)
    receipt = recorder.reconcile_usage(task,reconciliation(call_id))
    assert receipt.duplicate is False
    with factory() as db:
        check_execution_budget(db)
        assert total_spend_cny(db)==before+Decimal('.02')
        call = db.get(LLMCall,call_id)
        assert (call.call_status,call.usage_status)==('outcome_unknown','uncertain')
        assert call.input_tokens is None and call.output_tokens is None and call.estimated_cost_cny is None
        event = db.get(ExecutionTrace,receipt.event_id)
        assert event.llm_call_id==call_id and event.payload['total_tokens']==9598
        assert event.payload['input_tokens']==5088 and event.payload['output_tokens']==4510
        assert len(db.scalars(select(Node)).all())==nodes
        with pytest.raises(ValueError,match='budget_exhausted'):
            check_execution_budget(db,Decimal('100')-before-Decimal('.02'))
    recorder.begin_attempt(task,'test','v1',2,{})
    with factory() as db:
        with pytest.raises(ValueError,match='audit_incomplete'):
            check_execution_budget(db)


def test_concurrent_reconciliation_is_idempotent_and_conflict_is_rejected():
    recorder,task,factory,call_id = unknown_call()
    assert hasattr(recorder,'reconcile_usage'), 'local audited reconciliation is missing'
    from app.models import ExecutionTrace
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda _:recorder.reconcile_usage(task,reconciliation(call_id)),range(4)))
    assert sum(not r.duplicate for r in receipts)==1
    assert len({r.event_id for r in receipts})==1
    with pytest.raises(ValueError,match='reconciliation_conflict'):
        recorder.reconcile_usage(task,reconciliation(call_id,actual_cost_cny=Decimal('.03')))
    with factory() as db:
        assert len(db.scalars(select(ExecutionTrace).where(ExecutionTrace.llm_call_id==call_id,
                         ExecutionTrace.event_type=='usage_reconciled')).all())==1


@pytest.mark.parametrize('changes',[{'actual_cost_cny':Decimal('-1')},{'actual_cost_cny':Decimal('NaN')},
    {'total_tokens':True},{'source':'model_claim'},{'input_tokens':None},{'output_tokens':4509},{'extra':'ignored'}])
def test_reconciliation_rejects_invalid_evidence(changes):
    assert importlib.util.find_spec('app.usage_reconciliation'), 'reconciliation schema is missing'
    from app.usage_reconciliation import UsageReconciliation
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        UsageReconciliation.model_validate(reconciliation(str(uuid4()),**changes))


def test_reconciliation_rejects_foreign_known_and_unfinished_calls_and_keeps_other_uncertain_blocked():
    recorder,task,factory,call_id = unknown_call()
    _,foreign,_,other_id = unknown_call()
    assert hasattr(recorder,'reconcile_usage'), 'local audited reconciliation is missing'
    from app.costs import check_execution_budget
    with pytest.raises(ValueError,match='call_not_found'):
        recorder.reconcile_usage(foreign,reconciliation(call_id))
    recorder.reconcile_usage(task,reconciliation(call_id))
    with factory() as db:
        with pytest.raises(ValueError,match='cost_unconfirmed'):
            check_execution_budget(db)
    known = recorder.begin_attempt(task,'test','v1',2,{})
    recorder.finish_attempt(known,outcome(),None)
    from app.models import LLMCall,ExecutionTrace
    with factory() as db:
        known_id = db.scalar(select(LLMCall.id).where(LLMCall.attempt_id==known.attempt_id))
    with pytest.raises(ValueError,match='call_not_uncertain'):
        recorder.reconcile_usage(task,reconciliation(known_id))
    # A ledger row alone cannot make an unfinished audit eligible for recovery.
    with factory.begin() as db:
        db.execute(delete(ExecutionTrace).where(ExecutionTrace.llm_call_id==other_id,
                                               ExecutionTrace.event_type=='attempt_finished'))
    with pytest.raises(ValueError,match='attempt_not_finished'):
        recorder.reconcile_usage(foreign,reconciliation(other_id))


@pytest.mark.parametrize('cost,status',[('80','warning'),('100','blocked')])
def test_reconciled_cost_preserves_shared_warning_and_stop_threshold(cost,status):
    recorder,task,factory,call_id = unknown_call()
    from app.costs import budget_status,check_execution_budget
    recorder.reconcile_usage(task,reconciliation(call_id,actual_cost_cny=Decimal(cost)))
    with factory() as db:
        assert budget_status(db)['status']==status
        if status=='blocked':
            with pytest.raises(ValueError,match='budget_exhausted'):
                check_execution_budget(db)


def test_budget_cannot_clear_uncertainty_with_a_newer_unaccounted_reconciliation(monkeypatch):
    recorder,task,factory,call_id = unknown_call()
    import app.costs as costs
    from app.usage_reconciliation import UsageReconciliation
    confirmed = UsageReconciliation.model_validate(reconciliation(call_id,actual_cost_cny=Decimal('100')))
    # Reproduce a local operator committing between the amount and uncertainty reads.
    reads = iter([{}, {call_id:confirmed}])
    monkeypatch.setattr(costs,'reconciled_usage',lambda db:next(reads))
    with factory() as db:
        with pytest.raises(ValueError,match='cost_unconfirmed|budget_exhausted'):
            costs.check_execution_budget(db)
