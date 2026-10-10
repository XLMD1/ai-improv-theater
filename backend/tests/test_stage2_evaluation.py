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
                side_effect=lambda story,action,mapping,node:next(o['label'] for o in node.rendered_scene['options'] if mapping[o['id']]==action)):
            results = module.execute_real_cases(cases,tmp_path)
        assert all(r['status']=='succeeded' for r in results),results
        assert results[1]['free_text'] is True and results[2]['free_text'] is False
        assert (tmp_path/'ancient-frozen.json').exists()
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
