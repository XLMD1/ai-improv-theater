import importlib.util
import json
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from test_investigation_schema import sample_data
import pytest
import asyncio


def client():
    assert importlib.util.find_spec('app.story_creation'), 'creation pipeline missing'
    from app.main import app
    return TestClient(app)


def create_session(c):
    c.put('/local-settings/keys/deepseek',json={'api_key':'stage2-fixture-private-key'})
    response = c.post('/story-sessions',json={'provider':'deepseek'})
    assert response.status_code == 201,response.text
    data = response.json()
    return {'Authorization':'Bearer '+data['token']},data


async def successful_provider(provider,model,key,prompt,budget,timeout):
    from app.provider_clients import ProviderOutcome
    inp = json.loads(prompt.split('\n输入数据：',1)[1])
    if 'story_id' in inp:
        result = sample_data()
        result.update(story_id=inp['story_id'],story_version=inp['story_version'],setting=inp['setting'],era=inp['era'])
    elif 'candidate' in inp or 'reachability' in inp:
        result = {'passed':True,'issues':[]}
    elif 'text' in inp:
        result = {'result':{'status':'recognized','action':inp['available_actions'][0]}}
    else:
        result = {'narration':inp['adjudication_feedback'][:1200],'dialogue':[]}
    return ProviderOutcome(json.dumps(result,ensure_ascii=False),100,100,request_sent=True)


def wait_creation(c,headers,task_id):
    for _ in range(200):
        response = c.get('/story-tasks/'+task_id,headers=headers)
        data = response.json()
        if data['status'] not in ('queued','running'):
            return data
        time.sleep(.02)
    raise AssertionError('creation did not finish')


def prepare(c,headers,key=None):
    result = c.post('/story-tasks',headers={**headers,'Idempotency-Key':key or uuid4().hex},
                    json={'setting':'架空雾港调查','era':'modern'})
    assert result.status_code == 202,result.text
    return wait_creation(c,headers,result.json()['task_id'])


def test_create_confirm_is_atomic_idempotent_and_private():
    with client() as c, patch('app.story_operations.call_operation_provider',side_effect=successful_provider):
        headers,session = create_session(c)
        assert c.get('/tree',headers=headers).json() == []
        task = prepare(c,headers)
        assert task['status'] == 'awaiting_confirmation',task
        assert task['stage'] == 'awaiting_confirmation'
        assert 'truth' not in json.dumps(task) and c.get('/tree',headers=headers).json() == []
        body = {'candidate_version_id':task['candidate_version_id'],'content_hash':task['content_hash']}
        first = c.post(f"/story-tasks/{task['id']}/confirm",headers=headers,json=body)
        assert first.status_code == 200,first.text
        second = c.post(f"/story-tasks/{task['id']}/confirm",headers=headers,json=body)
        assert second.json() == first.json()
        assert first.json()['root']['rendered_scene']['options']
        assert len(c.get('/tree',headers=headers).json()) == 1
        c.delete('/local-settings/keys/deepseek')


def test_creation_true_concurrent_idempotency_and_foreign_access():
    with client() as c, patch('app.story_operations.call_operation_provider',side_effect=successful_provider):
        headers,_ = create_session(c)
        other,_ = create_session(c)
        key = uuid4().hex
        def submit(_):
            return c.post('/story-tasks',headers={**headers,'Idempotency-Key':key},json={'setting':'雾港','era':'modern'})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit,range(2)))
        assert all(result.status_code == 202 for result in results)
        task_id = results[0].json()['task_id']
        assert results[1].json()['task_id'] == task_id
        assert c.get('/story-tasks/'+task_id,headers=other).status_code == 404
        changed = c.post('/story-tasks',headers={**headers,'Idempotency-Key':key},json={'setting':'different','era':'future'})
        assert changed.status_code == 409
        assert wait_creation(c,headers,task_id)['status'] == 'awaiting_confirmation'
        c.delete('/local-settings/keys/deepseek')


def test_malformed_story_repairs_once_then_fails_without_root():
    async def invalid(*args):
        from app.provider_clients import ProviderOutcome
        return ProviderOutcome('broken',12,8,request_sent=True)
    with client() as c, patch('app.story_operations.call_operation_provider',side_effect=invalid) as provider:
        headers,_ = create_session(c)
        task = prepare(c,headers)
        assert task['status'] == 'failed' and provider.call_count == 2
        assert c.get('/tree',headers=headers).json() == []
        resumed = c.post(f"/story-tasks/{task['id']}/resume",headers={**headers,'Idempotency-Key':uuid4().hex})
        assert resumed.status_code == 409 and provider.call_count == 2
        c.delete('/local-settings/keys/deepseek')


@pytest.mark.parametrize('fault',['npc_reference','unreachable_ending','missing_protagonist'])
def test_repair_receives_specific_internal_errors_and_can_fix_one_candidate(fault):
    seen = []
    async def provider(*args):
        from app.provider_clients import ProviderOutcome
        inp = json.loads(args[3].split('\n输入数据：',1)[1])
        if 'raw_candidate' in inp:
            seen.extend(inp['issues'])
            return await successful_provider(*args)
        if 'story_id' in inp:
            data = sample_data()
            data.update(story_id=inp['story_id'],story_version=inp['story_version'],setting=inp['setting'],era=inp['era'])
            if fault=='npc_reference':
                data['endings'][0]['conditions']['all'].append({'op':'trust_at_least','character_id':data['protagonist_id'],'value':1})
            elif fault=='missing_protagonist':
                data['protagonist_id'] = 'missing_player'
            else:
                for place in data['locations'][:2]:
                    data['endings'][0]['conditions']['all'].append({'op':'at_location','location_id':place['id']})
            return ProviderOutcome(json.dumps(data,ensure_ascii=False),100,100,request_sent=True)
        return await successful_provider(*args)
    with client() as c,patch('app.story_operations.call_operation_provider',side_effect=provider):
        headers,_ = create_session(c)
        task = prepare(c,headers)
        assert task['status']=='awaiting_confirmation',task
        assert seen and 'errors' not in task and 'missing_endings' not in task
        assert all(issue.startswith('{') for issue in seen),seen
        details = [json.loads(issue) for issue in seen]
        if fault=='npc_reference':
            assert any('invalid reference: character_id=' in e['message'] for issue in details
                       for e in issue.get('errors',[]))
            assert all('input' not in e and 'ctx' not in e for issue in details for e in issue.get('errors',[]))
        elif fault=='missing_protagonist':
            messages = [e['message'] for issue in details for e in issue.get('errors',[])]
            assert any('protagonist_id=missing_player' in message and 'characters' in message
                       and all(c['id'] in message for c in sample_data()['characters']) for message in messages)
        else:
            assert any(sample_data()['endings'][0]['id'] in issue.get('missing_endings',[]) for issue in details)
        assert c.get('/tree',headers=headers).json()==[]
        c.delete('/local-settings/keys/deepseek')


@pytest.mark.parametrize('body',[{'setting':'   ','era':'modern'}, {'setting':'x'*501,'era':'modern'},
                                 {'setting':'港口','era':'past'}, {'setting':'港口','era':'modern','truth':'x'}])
def test_creation_rejects_invalid_request_before_provider(body):
    with client() as c, patch('app.story_operations.call_operation_provider') as provider:
        headers,_ = create_session(c)
        assert c.post('/story-tasks',headers={**headers,'Idempotency-Key':uuid4().hex},json=body).status_code == 422
        assert provider.call_count == 0
        assert c.post('/turns',headers={**headers,'Idempotency-Key':uuid4().hex},
                      json={'parent_node_id':str(uuid4()),'action':{'type':'text','value':'调查'}}).json()['detail'] == 'story_not_ready'
        c.delete('/local-settings/keys/deepseek')


def test_confirmation_rejects_hash_and_foreign_task_and_stream_is_public():
    with client() as c, patch('app.story_operations.call_operation_provider',side_effect=successful_provider) as provider:
        headers,_ = create_session(c)
        other,_ = create_session(c)
        task = prepare(c,headers)
        body = {'candidate_version_id':task['candidate_version_id'],'content_hash':'0'*64}
        assert c.post(f"/story-tasks/{task['id']}/confirm",headers=headers,json=body).status_code == 409
        assert c.post(f"/story-tasks/{task['id']}/confirm",headers=other,json=body).status_code == 404
        stream = c.get(f"/story-tasks/{task['id']}/events",headers=headers).text
        assert 'awaiting_confirmation' in stream and 'truth' not in stream and 'raw' not in stream
        assert c.get('/tree',headers=headers).json() == [] and provider.call_count == 2
        c.delete('/local-settings/keys/deepseek')


def test_restart_resume_reuses_candidate_and_does_not_reset_repair():
    from app.db import SessionLocal
    from app.models import StoryTask,ExecutionTrace
    from app.execution_traces import TaskRef,TraceRecorder
    from app.story_creation import CreationRequest,create_creation_task,interrupt_creation_tasks
    with client() as c, patch('app.story_operations.call_operation_provider',side_effect=successful_provider) as provider:
        headers,session = create_session(c)
        source,_ = create_creation_task(session['session_id'],CreationRequest(setting='雾港',era='modern'),uuid4().hex)
        source_trace = TraceRecorder(SessionLocal).start(TaskRef('creation',source.id,session['session_id']))
        data = sample_data()
        data.update(story_id=source.story_id,story_version='draft-2',setting='雾港',era='modern')
        with SessionLocal.begin() as db:
            row = db.get(StoryTask,source.id)
            row.status = 'running'
            row.repair_count = 1
            row.checkpoint = {'raw':json.dumps(data),'repair_done':True}
        interrupt_creation_tasks()
        key = uuid4().hex
        first = c.post(f'/story-tasks/{source.id}/resume',headers={**headers,'Idempotency-Key':key})
        assert first.status_code == 202
        task_id = first.json()['task_id']
        task = wait_creation(c,headers,task_id)
        assert task['status'] == 'awaiting_confirmation' and provider.call_count == 1
        duplicate = c.post(f'/story-tasks/{source.id}/resume',headers={**headers,'Idempotency-Key':key})
        assert duplicate.json()['task_id'] == task_id and provider.call_count == 1
        with SessionLocal() as db:
            assert db.get(StoryTask,task_id).repair_count == 1
            assert db.get(StoryTask,source.id).status == 'interrupted'
            link = db.scalar(select(ExecutionTrace).where(ExecutionTrace.creation_task_id==task_id,
                              ExecutionTrace.event_type=='creation_resumed'))
            assert link and link.payload['source_trace_id']==source_trace
        c.delete('/local-settings/keys/deepseek')


def test_claimed_task_initialization_storage_failure_is_terminal_and_recoverable():
    from app.db import SessionLocal
    from app.models import StoryTask
    from app.story_creation import CreationRequest,create_creation_task,process_creation_task
    from sqlalchemy.exc import OperationalError
    with client() as c:
        headers,session = create_session(c)
        task,_ = create_creation_task(session['session_id'],CreationRequest(setting='雾港',era='modern'),uuid4().hex)
        with patch('app.story_creation.creation_context',side_effect=OperationalError('context read',{},Exception('transient'))):
            asyncio.run(process_creation_task(task.id))
        queried = c.get('/story-tasks/'+task.id,headers=headers).json()
        assert queried['status']=='failed' and queried['error_code']=='storage_failure' and queried['recoverable']
        with patch('app.story_operations.call_operation_provider',side_effect=successful_provider):
            resumed = c.post('/story-tasks/'+task.id+'/resume',headers={**headers,'Idempotency-Key':uuid4().hex})
            assert resumed.status_code==202
            assert wait_creation(c,headers,resumed.json()['task_id'])['status']=='awaiting_confirmation'
        c.delete('/local-settings/keys/deepseek')
