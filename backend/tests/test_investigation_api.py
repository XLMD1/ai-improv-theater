import json
import time
from unittest.mock import patch
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import asyncio
import pytest

from sqlalchemy import select,func

from test_custom_story_creation import client,create_session,prepare,successful_provider


def approved(c):
    headers,session = create_session(c)
    task = prepare(c,headers)
    assert task['status'] == 'awaiting_confirmation',task
    body = {'candidate_version_id':task['candidate_version_id'],'content_hash':task['content_hash']}
    root = c.post(f"/story-tasks/{task['id']}/confirm",headers=headers,json=body).json()['root']
    return headers,root


def turn(c,headers,parent,action,key=None):
    response = c.post('/turns',headers={**headers,'Idempotency-Key':key or uuid4().hex},
                      json={'parent_node_id':parent,'action':action})
    assert response.status_code == 202,response.text
    run_id = response.json()['run_id']
    for _ in range(200):
        run = c.get('/runs/'+run_id,headers=headers).json()
        if run['status'] not in ('queued','running'):
            return run
        time.sleep(.01)
    raise AssertionError('turn unfinished')


def test_investigation_option_public_replay_and_no_cross_session():
    with client() as c,patch('app.story_operations.call_operation_provider',side_effect=successful_provider) as provider:
        headers,root = approved(c)
        action = {'type':'option','value':root['rendered_scene']['options'][0]['id']}
        key = uuid4().hex
        run = turn(c,headers,root['id'],action,key)
        assert run['status'] == 'completed',run
        node = c.get('/nodes/'+run['node_id'],headers=headers).json()
        assert node['state_snapshot']['action_turn'] == 1
        assert 'applied_once_rules' not in node['state_snapshot'] and 'fired_events' not in node['state_snapshot']
        count = provider.call_count
        with patch('app.state.apply_state_changes',side_effect=AssertionError('replay adjudicated')):
            assert c.get('/nodes/'+node['id'],headers=headers).json() == node
            assert turn(c,headers,root['id'],action,key)['node_id'] == node['id']
            assert c.get('/session/world',headers=headers,params={'node_id':node['id']}).status_code == 200
        assert provider.call_count == count == 4
        other,_ = create_session(c)
        assert c.get('/nodes/'+node['id'],headers=other).status_code == 404
        events = c.get('/nodes/'+node['id']+'/events',headers=headers).text
        assert 'topic_id' not in events and 'triggered_events' not in events and 'truth' not in events
        stream = c.get('/runs/'+run['id']+'/events',headers=headers).text
        assert 'scene_chunk' in stream and 'done' in stream
        c.delete('/local-settings/keys/deepseek')


def test_repeated_free_text_feedback_does_not_render_or_change_state():
    async def repeated(provider,model,key,prompt,budget,timeout):
        from app.provider_clients import ProviderOutcome
        inp = json.loads(prompt.split('\n输入数据：',1)[1])
        if 'text' in inp:
            return ProviderOutcome(json.dumps({'result':{'status':'recognized','action':{'type':'investigate','object_id':'notice_board'}}}),20,20,request_sent=True)
        return await successful_provider(provider,model,key,prompt,budget,timeout)
    with client() as c,patch('app.story_operations.call_operation_provider',side_effect=repeated) as provider:
        headers,root = approved(c)
        first = turn(c,headers,root['id'],{'type':'option','value':root['rendered_scene']['options'][0]['id']})
        assert first['status'] == 'completed',first
        parent = c.get('/nodes/'+first['node_id'],headers=headers).json()
        count = provider.call_count
        second = turn(c,headers,parent['id'],{'type':'text','value':'再次调查告示牌'})
        assert second['status'] == 'completed',second
        child = c.get('/nodes/'+second['node_id'],headers=headers).json()
        assert child['state_snapshot'] == parent['state_snapshot'] and provider.call_count == count+1
        c.delete('/local-settings/keys/deepseek')


def test_scene_veto_keeps_usage_and_parent_without_partial_node():
    from app.db import SessionLocal
    from app.models import LLMCall,ExecutionTrace
    with client() as c,patch('app.story_operations.call_operation_provider',side_effect=successful_provider):
        headers,root = approved(c)
        async def veto(provider,model,key,prompt,budget,timeout):
            from app.provider_clients import ProviderOutcome
            inp = json.loads(prompt.split('\n输入数据：',1)[1])
            if 'candidate' in inp:
                return ProviderOutcome(json.dumps({'passed':False,'issues':[{'code':'public_leak','entity_ids':[],'description':'SECRET_SENTINEL'}]}),21,13,request_sent=True)
            return await successful_provider(provider,model,key,prompt,budget,timeout)
        with patch('app.story_operations.call_operation_provider',side_effect=veto):
            run = turn(c,headers,root['id'],{'type':'option','value':root['rendered_scene']['options'][0]['id']})
        assert run['status'] == 'failed' and run['error_code'] == 'scene_semantic_rejected',run
        assert len(c.get('/tree',headers=headers).json()) == 1
        stream = c.get('/runs/'+run['id']+'/events',headers=headers).text
        assert 'SECRET_SENTINEL' not in stream and 'scene_chunk' not in stream
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(LLMCall).where(LLMCall.run_id==run['id'])) == 2
            assert db.scalar(select(func.count()).select_from(ExecutionTrace).where(ExecutionTrace.run_id==run['id'])) > 0
        c.delete('/local-settings/keys/deepseek')


def test_all_five_actions_and_three_endings_follow_frozen_witnesses():
    from app.db import SessionLocal
    from app.models import Node,TurnEvent
    from app.story_versions import load_story_version
    from app.story_validation import check_reachability
    with client() as c,patch('app.story_operations.call_operation_provider',side_effect=successful_provider):
        headers,root = approved(c)
        with SessionLocal() as db:
            story = load_story_version(db,db.get(Node,root['id']).story_version_id)
        proof = check_reachability(story)
        seen = set()
        for ending,path in proof.ending_paths.items():
            parent = root
            for normalized in path:
                with SessionLocal() as db:
                    mapping = db.get(Node,parent['id']).investigation_options
                option_id = next(key for key,value in mapping.items() if value == normalized)
                run = turn(c,headers,parent['id'],{'type':'option','value':option_id})
                assert run['status']=='completed',run
                parent = c.get('/nodes/'+run['node_id'],headers=headers).json()
                seen.add(normalized['type'])
            assert parent['state_snapshot']['ending_id']==ending
        assert seen == {'investigate','talk','present','move','decide'}
        with SessionLocal() as db:
            types = set(db.scalars(select(TurnEvent.event_type).join(Node).where(Node.session_id==root['session_id'])))
            assert 'triggered_event' in types and 'disclose' in types and 'record_commitment' in types
        c.delete('/local-settings/keys/deepseek')


@pytest.mark.parametrize('fault',['cancel','expired','rollback','old_worker'])
def test_failed_commit_cancel_and_old_worker_never_leave_a_node(fault):
    from app.db import SessionLocal
    from app.models import Run,Node,LLMCall
    import app.investigation_jobs as jobs
    from app.execution_traces import TraceRecorder
    from sqlalchemy.exc import SQLAlchemyError
    original_render = jobs.render_investigation_scene
    original_append = TraceRecorder._append
    async def failing_render(*args):
        if fault=='cancel':
            raise asyncio.CancelledError()
        draft = await original_render(*args)
        if fault=='expired':
            args[-1].deadline = 0
        elif fault=='old_worker':
            with SessionLocal.begin() as db:
                db.get(Run,args[-1].task.task_id).status = 'interrupted'
        return draft
    def append(recorder,db,task,row,event_type,payload,**kwargs):
        if fault=='rollback' and event_type=='node_committed':
            raise SQLAlchemyError('simulated narrative commit failure')
        return original_append(recorder,db,task,row,event_type,payload,**kwargs)
    with client() as c,patch('app.story_operations.call_operation_provider',side_effect=successful_provider):
        headers,root = approved(c)
        with patch('app.investigation_jobs.render_investigation_scene',side_effect=failing_render),patch.object(TraceRecorder,'_append',append):
            run = turn(c,headers,root['id'],{'type':'option','value':root['rendered_scene']['options'][0]['id']})
        assert run['status'] in ('failed','interrupted') and run['node_id'] is None
        assert len(c.get('/tree',headers=headers).json())==1
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(LLMCall).where(LLMCall.run_id==run['id'])) == (0 if fault=='cancel' else 2)
        c.delete('/local-settings/keys/deepseek')


def test_concurrent_same_key_one_run_and_sibling_context_is_excluded():
    from app.db import SessionLocal
    from app.models import Node
    from app.investigation_jobs import recent_investigation_turns
    with client() as c,patch('app.story_operations.call_operation_provider',side_effect=successful_provider) as provider:
        headers,root = approved(c)
        key = uuid4().hex
        action = {'type':'option','value':root['rendered_scene']['options'][0]['id']}
        with ThreadPoolExecutor(max_workers=2) as pool:
            runs = list(pool.map(lambda _:turn(c,headers,root['id'],action,key),range(2)))
        assert runs[0]['id']==runs[1]['id'] and len(c.get('/tree',headers=headers).json())==2
        sibling = turn(c,headers,root['id'],action)
        with SessionLocal() as db:
            turns = recent_investigation_turns(db,sibling['node_id'])
            first = db.get(Node,runs[0]['node_id'])
            # Only root + selected sibling, even when another child exists.
            assert len(turns)==2
            assert turns[-1]['player_action']['value']==action['value']
            assert c.get('/tree',headers=headers).json()[1]['id']==first.id
        assert provider.call_count==6
        c.delete('/local-settings/keys/deepseek')
