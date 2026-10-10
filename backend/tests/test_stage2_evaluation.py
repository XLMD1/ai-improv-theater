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
