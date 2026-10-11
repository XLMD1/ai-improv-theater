import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest


def runner():
    path = Path(__file__).resolve().parents[2]/'evals/run_stage2.py'
    assert path.exists(), 'stage2 evaluation missing'
    spec = importlib.util.spec_from_file_location('stage2_eval',path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stage2_denominator_and_missing_keys_are_not_success():
    module = runner()
    assert module.summarize([{'status':s} for s in ('succeeded','failed','error','skipped')])['task_success_rate']==.25
    with pytest.raises(ValueError,match='empty_suite'):
        module.summarize([])
    manifest = module.load_manifest()
    real = [c for c in manifest['cases'] if c['suite']=='real_model']
    assert len(real)==12 and {c['era'] for c in real}=={'ancient','modern','future'}
    results = module.execute_real_cases(real,Path('.'))
    assert len(results)==12 and all(r['status']=='error' for r in results)


def test_stage2_unsafe_database_rejected_before_any_connection(monkeypatch,tmp_path):
    module = runner()
    monkeypatch.setenv('STAGE2_TEST_DATABASE','postgresql+psycopg://owner:sk-private@localhost/stories')
    with patch.object(module,'execute_case',side_effect=AssertionError('unsafe subprocess')):
        with pytest.raises(ValueError,match='dedicated_postgresql_test_database_required'):
            module.run_suite('runtime_simulated','STAGE2_TEST_DATABASE')


def test_trace_inspection_is_read_only_scoped_and_never_calls_tools():
    from test_execution_records import records,cleanup_records
    from app.db import SessionLocal
    from app.execution_traces import TraceRecorder
    module = runner()
    _,task,_ = records()
    recorder = TraceRecorder(SessionLocal,secrets=['sk-fixture-secret'])
    trace_id = recorder.start(task)
    recorder.event(task,'saved',{'text':'sk-fixture-secret','reasoning_content':'should not be saved'})
    with patch('app.provider_clients.call_operation_provider',side_effect=AssertionError('replayed provider')):
        data = module.inspect_trace(SessionLocal,task.session_id,trace_id)
        assert 'sk-fixture-secret' not in json.dumps(data)
        assert 'should not be saved' not in json.dumps(data)
        with pytest.raises(ValueError,match='trace_not_found'):
            module.inspect_trace(SessionLocal,'foreign',trace_id)
    cleanup_records()


def test_real_runner_harness_freezes_story_then_uses_public_text_and_buttons(tmp_path):
    from pydantic import SecretStr
    from app.local_settings import put_key,clear_key
    from test_custom_story_creation import successful_provider
    module = runner()
    cases = [case for case in module.load_manifest()['cases'] if case['suite']=='real_model' and case['era']=='ancient']
    put_key('deepseek',SecretStr('fixture-private-key'))
    async def interpret_public_label(provider,model,key,prompt,budget,timeout):
        from app.provider_clients import ProviderOutcome
        inp = json.loads(prompt.split('\n输入数据：',1)[1])
        if 'text' in inp:
            index = next(i for i,label in enumerate(inp['action_labels']) if label==inp['text'])
            return ProviderOutcome(json.dumps({'result':{'status':'recognized','action':inp['available_actions'][index]}}),20,20,request_sent=True)
        return await successful_provider(provider,model,key,prompt,budget,timeout)
    try:
        with patch('app.story_operations.call_operation_provider',side_effect=interpret_public_label),patch.object(module,'_text',
                side_effect=lambda story,action,mapping,node:next(o['label'] for o in node.rendered_scene['options'] if mapping[o['id']]==action)),patch(
                'app.story_validation.check_reachability',side_effect=AssertionError('approved proof must not be searched again')):
            results = module.execute_real_cases(cases,tmp_path)
        assert all(r['status']=='succeeded' for r in results),results
        assert results[1]['free_text'] is True and results[2]['free_text'] is False
        assert (tmp_path/'ancient-frozen.json').exists()
        progress = json.loads((tmp_path/'progress.json').read_text(encoding='utf-8'))
        assert progress['complete'] is True and progress['cases']==results
        assert results[0]['root_node_id'] and results[0]['task_id'] and results[0]['session_id']
        assert 'fixture-private-key' not in json.dumps(progress) and 'Authorization' not in json.dumps(progress)
    finally:
        clear_key('deepseek')


def test_report_separates_original_usage_operator_evidence_and_unconfirmed_calls():
    from test_execution_records import unknown_call,reconciliation,cleanup_records
    from app.models import LLMCall
    module = runner()
    recorder,task,factory,call_id = unknown_call()
    try:
        assert hasattr(module,'usage_summary'), 'reconciled report measurements are missing'
        recorder.reconcile_usage(task,reconciliation(call_id))
        with factory() as db:
            summary = module.usage_summary(db,[db.get(LLMCall,call_id)])
        assert summary['input_tokens']==summary['output_tokens']==0
        assert summary['uncertain_calls']==1 and summary['unconfirmed_calls']==0
        assert summary['reconciled_calls']==1 and summary['reconciled_total_tokens']==9598
        assert summary['reconciled_input_tokens']==5088 and summary['reconciled_output_tokens']==4510
        from decimal import Decimal
        assert Decimal(summary['actual_reconciled_cost_cny'])==Decimal('.02')
        assert Decimal(summary['estimated_cost_cny'])==0
    finally:
        cleanup_records()


def test_controlled_default_creation_freezes_protocol_and_approval_replays_without_provider():
    from app.db import SessionLocal
    from app.models import StoryTask,Node,ExecutionTrace
    from app.story_content import BLUEPRINT_SHA256,BLUEPRINT_VERSION
    from app.story_operations import PROMPT_VERSION
    from test_custom_story_creation import client,create_session,prepare,successful_provider
    from sqlalchemy import select
    with client() as c,patch('app.story_operations.call_operation_provider',side_effect=successful_provider) as provider:
        headers,_ = create_session(c)
        try:
            task = prepare(c,headers)
            assert task['status']=='awaiting_confirmation',task
            assert c.get('/tree',headers=headers).json()==[]
            with SessionLocal() as db:
                cp = db.get(StoryTask,task['id']).checkpoint
                assert cp['creation_protocol']=='controlled-content-1'
                assert cp['blueprint_version']==BLUEPRINT_VERSION and cp['blueprint_sha256']==BLUEPRINT_SHA256
                assert cp['prompt_version']==PROMPT_VERSION and cp['content_raw'] and cp['proof']['states_checked']==70
                operations = [t.payload['operation'] for t in db.scalars(select(ExecutionTrace).where(
                    ExecutionTrace.creation_task_id==task['id'],ExecutionTrace.event_type=='attempt_started').order_by(ExecutionTrace.seq))]
                assert operations == ['story.content_generate','story.semantic_check']
            assert not {'raw','proof','content_raw','truth','checkpoint'}.intersection(task)
            body = {'candidate_version_id':task['candidate_version_id'],'content_hash':task['content_hash']}
            first = c.post('/story-tasks/'+task['id']+'/confirm',headers=headers,json=body)
            before = provider.call_count
            second = c.post('/story-tasks/'+task['id']+'/confirm',headers=headers,json=body)
            assert first.status_code==200 and second.json()==first.json() and provider.call_count==before
            assert len(c.get('/tree',headers=headers).json())==1
            with SessionLocal() as db:
                assert db.get(Node,first.json()['root']['id']).prompt_version==cp['prompt_version']
        finally:
            c.delete('/local-settings/keys/deepseek')


@pytest.mark.parametrize('fault',['missing_slot','rules','duplicate_key','semantic','semantic_still_bad','wrong_repair_version','repair_still_bad'])
def test_controlled_content_repairs_once_with_original_protocol_and_incurred_usage(fault):
    from app.db import SessionLocal
    from app.models import StoryTask,LLMCall
    from app.provider_clients import ProviderOutcome
    from test_custom_story_creation import client,create_session,prepare,successful_provider
    from test_controlled_story import content_data
    from test_investigation_schema import sample_data
    from sqlalchemy import select
    seen=[]
    vetoed=False
    async def provider(*args):
        nonlocal vetoed
        inp = json.loads(args[3].split('\n输入数据：',1)[1])
        if 'story_id' in inp:
            seen.append(inp)
            s = inp.get('template',sample_data())
            data = content_data(s)
            data.update(**{key:inp[key] for key in ('story_id','story_version','setting','era')})
            repair = 'raw_candidate' in inp
            if fault=='missing_slot' and not repair or fault=='repair_still_bad':
                data['evidence'].pop(next(iter(data['evidence'])))
            if fault in ('rules','wrong_repair_version') and not repair:
                data['action_rules'] = []
            if fault=='wrong_repair_version' and repair:
                data['story_version']='draft-1'
            raw = json.dumps(data,ensure_ascii=False)
            if fault=='duplicate_key' and not repair:
                raw = raw[:-1]+',"title":"overwritten"}'
            return ProviderOutcome(raw,100,100,request_sent=True)
        if 'reachability' in inp and fault.startswith('semantic') and (not vetoed or fault=='semantic_still_bad'):
            vetoed=True
            return ProviderOutcome(json.dumps({'passed':False,'issues':[{'code':'public_leak','entity_ids':[],
                                  'description':'公开字段提前泄漏，修复内容。'}]},ensure_ascii=False),100,100,request_sent=True)
        return await successful_provider(*args)
    with client() as c,patch('app.story_operations.call_operation_provider',side_effect=provider):
        headers,_ = create_session(c)
        try:
            task = prepare(c,headers)
            failed = fault in ('wrong_repair_version','repair_still_bad','semantic_still_bad')
            assert task['status']==('failed' if failed else 'awaiting_confirmation'),task
            assert c.get('/tree',headers=headers).json()==[]
            assert len(seen)==2 and 'template' in seen[0] and seen[1]['story_version']=='draft-2'
            assert seen[0]['template']['protagonist_id']==seen[1]['template']['protagonist_id']
            assert seen[1]['issues'] and 'raw_candidate' in seen[1]
            with SessionLocal() as db:
                row = db.get(StoryTask,task['id'])
                assert row.repair_count==1 and row.checkpoint['creation_protocol']=='controlled-content-1'
                calls = db.scalars(select(LLMCall).where(LLMCall.creation_task_id==task['id'])).all()
                assert len(calls)==(4 if fault.startswith('semantic') else 2 if failed else 3)
                assert all(call.usage_status=='known' and call.input_tokens==100 for call in calls)
                if not failed:
                    assert row.checkpoint['repair_done'] and row.checkpoint['semantic_passed']
                else:
                    assert row.candidate_version_id is None and task['error_code']=='story_repair_exhausted'
        finally:
            c.delete('/local-settings/keys/deepseek')


@pytest.mark.parametrize('field,value',[('creation_protocol','unknown'),('blueprint_version','unknown'),
                                      ('blueprint_sha256','f'*64),('prompt_version','unknown')])
def test_unknown_creation_provenance_stops_before_external_call(field,value):
    import asyncio
    from uuid import uuid4
    from app.db import SessionLocal
    from app.models import StoryTask
    from app.story_creation import CreationRequest,create_creation_task,process_creation_task
    from test_custom_story_creation import client,create_session,successful_provider
    with client() as c,patch('app.story_operations.call_operation_provider',side_effect=successful_provider) as provider:
        headers,session = create_session(c)
        try:
            task,_ = create_creation_task(session['session_id'],CreationRequest(setting='调查',era='modern'),uuid4().hex)
            with SessionLocal.begin() as db:
                row=db.get(StoryTask,task.id)
                row.checkpoint={**row.checkpoint,field:value}
            asyncio.run(process_creation_task(task.id))
            result=c.get('/story-tasks/'+task.id,headers=headers).json()
            assert result['status']=='failed' and result['error_code']=='creation_protocol_mismatch'
            assert provider.call_count==0 and c.get('/tree',headers=headers).json()==[]
        finally:
            c.delete('/local-settings/keys/deepseek')


def test_controlled_restart_reuses_saved_passed_candidate_and_proof():
    import asyncio
    from uuid import uuid4
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import StoryTask,LLMCall
    from app.story_creation import CreationRequest,create_creation_task,process_creation_task,interrupt_creation_tasks
    from test_custom_story_creation import client,create_session,wait_creation,successful_provider
    with client() as c,patch('app.story_operations.call_operation_provider',side_effect=successful_provider) as provider:
        headers,session=create_session(c)
        try:
            task,_=create_creation_task(session['session_id'],CreationRequest(setting='调查',era='modern'),uuid4().hex)
            asyncio.run(process_creation_task(task.id))
            with SessionLocal.begin() as db:
                row=db.get(StoryTask,task.id)
                cp=dict(row.checkpoint)
                assert cp['creation_protocol']=='controlled-content-1'
                row.status='running'
                row.candidate_version_id=None
            interrupt_creation_tasks()
            before=provider.call_count
            with patch('app.story_creation.validate_reachability',side_effect=AssertionError('saved proof reused')):
                response=c.post('/story-tasks/'+task.id+'/resume',headers={**headers,'Idempotency-Key':uuid4().hex})
                assert response.status_code==202
                result=wait_creation(c,headers,response.json()['task_id'])
            assert result['status']=='awaiting_confirmation' and provider.call_count==before
            with SessionLocal() as db:
                restored=db.get(StoryTask,result['id'])
                assert restored.checkpoint==cp
                assert not db.scalars(select(LLMCall).where(LLMCall.creation_task_id==result['id'])).all()
        finally:
            c.delete('/local-settings/keys/deepseek')


def test_usage_saved_before_failed_checkpoint_cannot_blindly_regenerate_on_resume():
    import asyncio
    from uuid import uuid4
    from sqlalchemy import select
    from sqlalchemy.exc import OperationalError
    from app.db import SessionLocal
    from app.models import StoryTask,LLMCall
    from app.story_creation import CreationRequest,create_creation_task,process_creation_task,_checkpoint
    from test_custom_story_creation import client,create_session,wait_creation,successful_provider
    def fail_after_content(task_id,checkpoint,stage,repair_count=None):
        if checkpoint.get('content_raw'):
            raise OperationalError('checkpoint',{},Exception('synthetic storage failure'))
        return _checkpoint(task_id,checkpoint,stage,repair_count)
    with client() as c,patch('app.story_operations.call_operation_provider',side_effect=successful_provider) as provider:
        headers,session=create_session(c)
        try:
            task,_=create_creation_task(session['session_id'],CreationRequest(setting='调查',era='modern'),uuid4().hex)
            with patch('app.story_creation._checkpoint',side_effect=fail_after_content):
                asyncio.run(process_creation_task(task.id))
            result=c.get('/story-tasks/'+task.id,headers=headers).json()
            assert result['status']=='failed' and result['error_code']=='storage_failure'
            with SessionLocal() as db:
                calls=db.scalars(select(LLMCall).where(LLMCall.creation_task_id==task.id)).all()
                assert len(calls)==1 and calls[0].input_tokens==100 and calls[0].usage_status=='known'
                assert db.get(StoryTask,task.id).checkpoint['content_started']
            before=provider.call_count
            response=c.post('/story-tasks/'+task.id+'/resume',headers={**headers,'Idempotency-Key':uuid4().hex})
            assert response.status_code==202
            restored=wait_creation(c,headers,response.json()['task_id'])
            assert restored['status']=='failed' and restored['error_code']=='creation_checkpoint_incomplete'
            assert provider.call_count==before and c.get('/tree',headers=headers).json()==[]
        finally:
            c.delete('/local-settings/keys/deepseek')


def test_unknown_cost_blocks_new_controlled_generation_before_provider():
    from test_execution_records import unknown_call,cleanup_records
    from test_custom_story_creation import client,create_session,prepare
    recorder,task,factory,call_id=unknown_call()
    try:
        with client() as c,patch('app.story_operations.call_operation_provider') as provider:
            headers,_=create_session(c)
            try:
                result=prepare(c,headers)
                assert result['status']=='failed' and result['error_code']=='cost_unconfirmed'
                assert provider.call_count==0 and c.get('/tree',headers=headers).json()==[]
            finally:
                c.delete('/local-settings/keys/deepseek')
    finally:
        cleanup_records()


def test_cancelled_controlled_generation_preserves_intent_usage_and_empty_world():
    import asyncio
    from uuid import uuid4
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import StoryTask,LLMCall
    from app.story_creation import CreationRequest,create_creation_task,process_creation_task
    from test_custom_story_creation import client,create_session
    from test_execution_records import _test_sessions,cleanup_records
    async def cancel_in_provider(task_id):
        entered=asyncio.Event()
        async def pending(*args):
            entered.set()
            await asyncio.Event().wait()
        with patch('app.story_operations.call_operation_provider',side_effect=pending):
            worker=asyncio.create_task(process_creation_task(task_id))
            await asyncio.wait_for(entered.wait(),2)
            worker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await worker
    try:
        with client() as c:
            headers,session=create_session(c)
            _test_sessions.append(session['session_id'])
            try:
                task,_=create_creation_task(session['session_id'],CreationRequest(setting='调查',era='modern'),uuid4().hex)
                asyncio.run(cancel_in_provider(task.id))
                result=c.get('/story-tasks/'+task.id,headers=headers).json()
                assert result['status']=='interrupted' and result['error_code']=='cancelled'
                assert c.get('/tree',headers=headers).json()==[]
                with SessionLocal() as db:
                    row=db.get(StoryTask,task.id)
                    calls=db.scalars(select(LLMCall).where(LLMCall.creation_task_id==task.id)).all()
                    assert row.checkpoint['creation_protocol']=='controlled-content-1' and row.checkpoint['content_started']
                    assert not row.candidate_version_id and len(calls)==1 and calls[0].usage_status=='uncertain'
            finally:
                c.delete('/local-settings/keys/deepseek')
    finally:
        cleanup_records()


def test_local_reconciliation_cli_uses_strict_evidence_and_refuses_unsafe_database():
    import os
    import subprocess
    import sys
    from test_execution_records import unknown_call,cleanup_records
    root = Path(__file__).resolve().parents[2]
    script = root/'scripts/reconcile-execution-usage.py'
    assert script.exists(), 'local reconciliation CLI is missing'
    recorder,task,factory,call_id = unknown_call()
    args = [sys.executable,str(script),'--session-id',task.session_id,'--call-id',call_id,
            '--source','user_reported_provider_console','--actual-cost-cny','.02','--total-tokens','9598',
            '--input-tokens','5088','--output-tokens','4510']
    environment = dict(os.environ,MIGRATION_DATABASE_URL=os.environ['DATABASE_URL'])
    try:
        result = subprocess.run(args,cwd=root,env=environment,capture_output=True,text=True,timeout=20)
        assert result.returncode==0,result.stdout
        assert json.loads(result.stdout)['duplicate'] is False
        repeated = subprocess.run(args,cwd=root,env=environment,capture_output=True,text=True,timeout=20)
        assert repeated.returncode==0 and json.loads(repeated.stdout)['duplicate'] is True
        environment['MIGRATION_DATABASE_URL']='postgresql+psycopg://owner:sk-private@localhost/stories'
        rejected = subprocess.run(args,cwd=root,env=environment,capture_output=True,text=True,timeout=20)
        assert rejected.returncode==2 and 'sk-private' not in rejected.stdout+rejected.stderr
    finally:
        cleanup_records()
