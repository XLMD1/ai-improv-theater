import asyncio
import json
from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ExecutionTrace, LLMCall, Node, StorySession, StoryTask, TurnEvent
from app.story_versions import load_narration_protocol
from test_custom_story_creation import client, create_session, prepare, successful_provider, wait_creation
from test_investigation_api import approved, turn


def assert_feedback(c, headers, run):
    assert run['status'] == 'completed', run
    node = c.get('/nodes/' + run['node_id'], headers=headers).json()
    with SessionLocal() as db:
        feedback = db.scalar(select(TurnEvent.payload).where(
            TurnEvent.node_id == node['id'], TurnEvent.event_type == 'adjudication'))['feedback']
    assert node['rendered_scene']['narration'] == feedback
    assert node['rendered_scene']['dialogue'] == []
    assert node['rendered_scene']['fallback'] is False
    assert node['prompt_version'] == 'approved-feedback-1'
    assert node['model_id'] == 'server:approved-feedback-1'
    return node


def test_r1_button_without_key_commits_feedback_and_replay_has_no_calls():
    with client() as c, patch('app.story_operations.call_operation_provider', side_effect=successful_provider) as provider:
        headers, root = approved(c)
        c.delete('/local-settings/keys/deepseek')
        before = provider.call_count
        action = {'type': 'option', 'value': root['rendered_scene']['options'][0]['id']}
        key = uuid4().hex
        run = turn(c, headers, root['id'], action, key)
        node = assert_feedback(c, headers, run)
        with SessionLocal() as db:
            assert not db.scalars(select(LLMCall).where(LLMCall.run_id == run['id'])).all()
            trace = db.scalar(select(ExecutionTrace).where(
                ExecutionTrace.run_id == run['id'], ExecutionTrace.event_type == 'presentation_selected'))
            assert trace.payload == {'narration_protocol': 'approved-feedback-1'}
        with patch('app.investigation_jobs.decide', side_effect=AssertionError('replay adjudicated')):
            assert turn(c, headers, root['id'], action, key)['node_id'] == node['id']
            assert c.get('/nodes/' + node['id'], headers=headers).json() == node
            stream = c.get('/runs/' + run['id'] + '/events', headers=headers).text
            assert 'scene_chunk' in stream and 'done' in stream
        assert provider.call_count == before == 2


def test_r1_free_text_uses_only_registered_interpret_and_requires_key():
    with client() as c, patch('app.story_operations.call_operation_provider', side_effect=successful_provider) as provider:
        headers, root = approved(c)
        try:
            before = provider.call_count
            run = turn(c, headers, root['id'], {'type': 'text', 'value': '调查告示牌'})
            assert_feedback(c, headers, run)
            with SessionLocal() as db:
                ops = [row.payload['operation'] for row in db.scalars(select(ExecutionTrace).where(
                    ExecutionTrace.run_id == run['id'], ExecutionTrace.event_type == 'attempt_started'))]
                assert ops == ['action.interpret']
                assert db.scalar(select(ExecutionTrace).where(ExecutionTrace.run_id == run['id'],
                    ExecutionTrace.event_type == 'attempt_started')).payload['version'] == 'v2'
                assert len(db.scalars(select(LLMCall).where(LLMCall.run_id == run['id'])).all()) == 1
            assert provider.call_count == before + 1
            c.delete('/local-settings/keys/deepseek')
            response = c.post('/turns', headers={**headers, 'Idempotency-Key': uuid4().hex},
                              json={'parent_node_id': root['id'], 'action': {'type': 'text', 'value': '调查'}})
            assert response.status_code == 409 and response.json()['detail'] == 'key_not_configured'
        finally:
            c.delete('/local-settings/keys/deepseek')


@pytest.mark.parametrize('protocol,narration', [
    ('controlled-content-2', None), ('controlled-content-2', 'model-scene-1'),
    ('controlled-content-1', 'approved-feedback-1'), (None, 'approved-feedback-1'),
])
def test_mismatched_creation_presentation_stops_before_provider(protocol, narration):
    from app.story_creation import CreationRequest, create_creation_task, process_creation_task
    with client() as c, patch('app.story_operations.call_operation_provider', side_effect=successful_provider) as provider:
        headers, session = create_session(c)
        try:
            task, _ = create_creation_task(session['session_id'], CreationRequest(setting='调查', era='modern'), uuid4().hex)
            with SessionLocal.begin() as db:
                cp = dict(db.get(StoryTask, task.id).checkpoint) if protocol else {}
                if protocol:
                    cp['creation_protocol'] = protocol
                if narration is None:
                    cp.pop('narration_protocol', None)
                else:
                    cp['narration_protocol'] = narration
                db.get(StoryTask, task.id).checkpoint = cp
            asyncio.run(process_creation_task(task.id))
            result = c.get('/story-tasks/' + task.id, headers=headers).json()
            assert result['status'] == 'failed' and result['error_code'] == 'creation_protocol_mismatch'
            assert provider.call_count == 0
        finally:
            c.delete('/local-settings/keys/deepseek')


def test_controlled_v1_resume_and_repeated_confirmation_keep_model_scene():
    from app.story_creation import CreationRequest, create_creation_task, process_creation_task
    with client() as c, patch('app.story_operations.call_operation_provider', side_effect=successful_provider) as provider:
        headers, session = create_session(c)
        try:
            task, _ = create_creation_task(session['session_id'], CreationRequest(setting='调查', era='modern'), uuid4().hex)
            with SessionLocal.begin() as db:
                row = db.get(StoryTask, task.id)
                cp = {**row.checkpoint, 'creation_protocol': 'controlled-content-1'}
                cp.pop('narration_protocol', None)
                row.checkpoint = cp
            asyncio.run(process_creation_task(task.id))
            with SessionLocal.begin() as db:
                row = db.get(StoryTask, task.id)
                cp = deepcopy(row.checkpoint)
                row.status = 'interrupted'
                row.candidate_version_id = None
            before = provider.call_count
            response = c.post('/story-tasks/' + task.id + '/resume', headers={**headers, 'Idempotency-Key': uuid4().hex})
            restored = wait_creation(c, headers, response.json()['task_id'])
            assert restored['status'] == 'awaiting_confirmation' and provider.call_count == before
            with SessionLocal() as db:
                assert db.get(StoryTask, restored['id']).checkpoint == cp
                assert load_narration_protocol(db, restored['candidate_version_id']) == 'model-scene-1'
            body = {'candidate_version_id': restored['candidate_version_id'], 'content_hash': restored['content_hash']}
            first = c.post('/story-tasks/' + restored['id'] + '/confirm', headers=headers, json=body)
            assert first.status_code == 200
            assert c.post('/story-tasks/' + restored['id'] + '/confirm', headers=headers, json=body).json() == first.json()
            c.delete('/local-settings/keys/deepseek')
            root = first.json()['root']
            response = c.post('/turns', headers={**headers, 'Idempotency-Key': uuid4().hex}, json={
                'parent_node_id': root['id'], 'action': {'type': 'option', 'value': root['rendered_scene']['options'][0]['id']}})
            assert response.status_code == 409 and response.json()['detail'] == 'key_not_configured'
        finally:
            c.delete('/local-settings/keys/deepseek')


def test_confirmation_checks_saved_policy_and_candidate_ownership():
    with client() as c, patch('app.story_operations.call_operation_provider', side_effect=successful_provider):
        headers, _ = create_session(c)
        other, _ = create_session(c)
        try:
            task, foreign = prepare(c, headers), prepare(c, other)
            response = c.post('/story-tasks/' + task['id'] + '/confirm', headers=headers, json={
                'candidate_version_id': foreign['candidate_version_id'], 'content_hash': foreign['content_hash']})
            assert response.status_code == 409
            with SessionLocal.begin() as db:
                row = db.get(StoryTask, task['id'])
                row.checkpoint = {**row.checkpoint, 'narration_protocol': 'model-scene-1'}
            response = c.post('/story-tasks/' + task['id'] + '/confirm', headers=headers, json={
                'candidate_version_id': task['candidate_version_id'], 'content_hash': task['content_hash']})
            assert response.status_code == 409 and c.get('/tree', headers=headers).json() == []
        finally:
            c.delete('/local-settings/keys/deepseek')


def saved_sample(c):
    from app.investigation import initial_investigation_state
    from app.investigation_generation import build_public_options
    from app.story_schema import Story
    from app.story_versions import save_story_version
    from test_investigation_schema import sample_data
    headers, session = create_session(c)
    data = sample_data()
    data['story_id'] = str(uuid4())
    next(r for r in data['action_rules'] if r['id'] == 'inspect_register')['feedback'] = '已审核长反馈。' * 220 + 'SECRET_SENTINEL'
    definition = Story.model_validate(data)
    with SessionLocal.begin() as db:
        row = save_story_version(db, definition, narration_protocol='approved-feedback-1')
        row.approval_status = 'approved'
        db.get(StorySession, session['session_id']).story_version_id = row.id
        state = initial_investigation_state(definition)
        options, mapping = build_public_options(definition, state)
        root = Node(session_id=session['session_id'], depth=0, scene_id=state['location_id'], story_version_id=row.id,
                    state_snapshot=state, rendered_scene={'scene_id': state['location_id'], 'narration': definition.public_intro,
                    'dialogue': [], 'options': options, 'fallback': False}, investigation_options=mapping,
                    canon_version=definition.story_version, prompt_version='sample', model_id='sample')
        db.add(root)
        db.flush()
        root_id = root.id
    return headers, c.get('/nodes/' + root_id, headers=headers).json(), definition


def button(c, headers, parent, action):
    with SessionLocal() as db:
        mapping = db.get(Node, parent['id']).investigation_options
        key = next(k for k, value in mapping.items() if value == action)
    return assert_feedback(c, headers, turn(c, headers, parent['id'], {'type': 'option', 'value': key}))


def test_long_feedback_discovery_events_and_siblings_are_preserved_exactly():
    from app.story_validation import check_reachability
    with client() as c, patch('app.story_operations.call_operation_provider', side_effect=successful_provider) as provider:
        headers, root, definition = saved_sample(c)
        c.delete('/local-settings/keys/deepseek')
        first = button(c, headers, root, {'type': 'investigate', 'object_id': 'notice'})
        unlocked = button(c, headers, first, {'type': 'investigate', 'object_id': 'satchel'})
        sibling = button(c, headers, unlocked, {'type': 'move', 'location_id': 'archive'})
        assert 'SECRET_SENTINEL' not in json.dumps(sibling)
        branch = button(c, headers, unlocked, {'type': 'move', 'location_id': 'archive'})
        child = button(c, headers, branch, {'type': 'investigate', 'object_id': 'register'})
        assert child['rendered_scene']['narration'] == '已审核长反馈。' * 220 + 'SECRET_SENTINEL'
        assert 'cargo_manifest' in child['state_snapshot']['discovered_evidence']
        proof = check_reachability(definition)
        parent = root
        event_feedback = definition.events[0].feedback
        seen = 0
        for action in proof.ending_paths['publish_truth']:
            parent = button(c, headers, parent, action)
            seen += parent['rendered_scene']['narration'].count(event_feedback)
        assert seen == 1
        with patch('app.investigation_jobs.decide', side_effect=AssertionError('replay adjudicated')):
            assert c.get('/nodes/' + root['id'], headers=headers).json() == root
            assert c.get('/nodes/' + sibling['id'], headers=headers).json() == sibling
            assert c.get('/nodes/' + child['id'], headers=headers).json() == child
        assert provider.call_count == 0


def test_unknown_cost_allows_pure_button_but_blocks_text_without_partial_node():
    from test_execution_records import unknown_call, cleanup_records
    with client() as c, patch('app.story_operations.call_operation_provider', side_effect=successful_provider) as provider:
        headers, root = approved(c)
        unknown_call()
        try:
            before = provider.call_count
            action = {'type': 'option', 'value': root['rendered_scene']['options'][0]['id']}
            assert_feedback(c, headers, turn(c, headers, root['id'], action))
            run = turn(c, headers, root['id'], {'type': 'text', 'value': '调查告示牌'})
            assert run['status'] == 'failed' and run['error_code'] == 'cost_unconfirmed' and run['node_id'] is None
            assert provider.call_count == before
            assert len(c.get('/tree', headers=headers).json()) == 2
        finally:
            cleanup_records()
            c.delete('/local-settings/keys/deepseek')


@pytest.mark.parametrize('fault', ['unauthorized', 'task_timeout'])
def test_text_failure_keeps_parent_and_has_no_partial_node(fault):
    from app.provider_clients import ProviderOutcome
    from app.execution_traces import TraceRecorder
    original = TraceRecorder.finish_attempt
    def finish(recorder, ref, outcome, error_code):
        result = original(recorder, ref, outcome, error_code)
        if fault == 'task_timeout':
            raise TimeoutError()
        return result
    async def fail(*args):
        if fault == 'unauthorized':
            return ProviderOutcome(error_code='unauthorized', request_sent=True, chargeable=False)
        return await successful_provider(*args)
    with client() as c, patch('app.story_operations.call_operation_provider', side_effect=successful_provider):
        headers, root = approved(c)
        try:
            with patch('app.story_operations.call_operation_provider', side_effect=fail) as provider, patch.object(TraceRecorder, 'finish_attempt', finish):
                run = turn(c, headers, root['id'], {'type': 'text', 'value': '调查告示牌'})
            assert run['status'] in ('failed', 'interrupted') and run['error_code'] == fault and run['node_id'] is None
            assert provider.call_count == 1
            assert c.get('/nodes/' + root['id'], headers=headers).json() == root
            assert len(c.get('/tree', headers=headers).json()) == 1
        finally:
            c.delete('/local-settings/keys/deepseek')


@pytest.mark.parametrize('fault', ['cancel', 'expired', 'rollback', 'old_worker'])
def test_r1_commit_failures_never_publish_partial_node(fault):
    from app.execution_traces import TraceRecorder
    from app.models import Run
    from sqlalchemy.exc import SQLAlchemyError
    original_event, original_append = TraceRecorder.event, TraceRecorder._append
    def event(recorder, task, event_type, payload, **kwargs):
        if event_type == 'scene_validated':
            if fault == 'cancel':
                raise asyncio.CancelledError()
            if fault == 'expired':
                raise TimeoutError()
            if fault == 'old_worker':
                with SessionLocal.begin() as db:
                    db.get(Run, task.task_id).status = 'interrupted'
        return original_event(recorder, task, event_type, payload, **kwargs)
    def append(recorder, db, task, row, event_type, payload, **kwargs):
        if fault == 'rollback' and event_type == 'node_committed':
            raise SQLAlchemyError('synthetic commit failure')
        return original_append(recorder, db, task, row, event_type, payload, **kwargs)
    with client() as c, patch('app.story_operations.call_operation_provider', side_effect=successful_provider) as provider:
        headers, root = approved(c)
        c.delete('/local-settings/keys/deepseek')
        before = provider.call_count
        with patch.object(TraceRecorder, 'event', event), patch.object(TraceRecorder, '_append', append):
            run = turn(c, headers, root['id'], {'type': 'option', 'value': root['rendered_scene']['options'][0]['id']})
        assert run['status'] in ('failed', 'interrupted') and run['node_id'] is None
        assert len(c.get('/tree', headers=headers).json()) == 1
        assert c.get('/nodes/' + root['id'], headers=headers).json() == root
        assert provider.call_count == before
