import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest


def runner():
    path = Path(__file__).resolve().parents[2] / 'evals/run_stage5.py'
    assert path.exists(), 'stage5 evaluation missing'
    spec = importlib.util.spec_from_file_location('stage5_eval', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bundle():
    root = Path(__file__).resolve().parents[2]
    manifest = root / 'evals/cases/stage2.json'
    cases = [dict(id=c['id'], status='succeeded', duration_ms=10)
             for c in json.loads(manifest.read_text(encoding='utf-8'))['cases'] if c['suite'] == 'real_model']
    source = dict(run_id='historical-run', suite='real_model', measurement='real_model_with_approved_feedback',
                  model_version='deepseek-flash', prompt_version='investigation-single-6', git_commit='old-commit',
                  price_version='historical-price', manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                  creation_protocol='controlled-content-2', narration_protocol='approved-feedback-1',
                  cases=cases, summary=dict(total=12, succeeded=12, failed=0, error=0, skipped=0, task_success_rate=1))
    raw = json.dumps(source)
    return seal(dict(bundle_version='stage5-baseline-1', source_report_json=raw,
                source_report_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                attempts=[], turns=[], calls=[], reconciliations=[], human_review=None,
                coverage=dict(accounting_complete=True)))


def seal(value):
    module = runner()
    for i, attempt in enumerate(value['attempts']):
        for key, default in dict(id=str(i), sequence=i, request_sent=False, chargeable=False,
                                 call_id=None, input_tokens=None, output_tokens=None).items():
            attempt.setdefault(key, default)
    value['coverage'].update(saved_turns=len(value['turns']), attempts=len(value['attempts']), ledger_calls=len(value['calls']))
    value['usage'] = dict(attempts=len(value['attempts']), **module.snapshot_usage(value['calls'], value['reconciliations']))
    if value.get('human_review') is not None:
        value['human_review_sha256'] = module.canonical_digest(value['human_review'])
    return module.seal_bundle(value)


def change_source(value, change):
    source = json.loads(value['source_report_json'])
    change(source)
    value['source_report_json'] = json.dumps(source)
    value['source_report_sha256'] = hashlib.sha256(value['source_report_json'].encode()).hexdigest()
    seal(value)


def test_stage5_keeps_failures_and_skips_in_fixed_denominator():
    module, value = runner(), bundle()
    def change(source):
        source['cases'][0]['status'] = 'error'
        source['cases'][1]['status'] = 'skipped'
        source['summary'] = dict(total=12, succeeded=10, failed=0, error=1, skipped=1, task_success_rate=10/12)
    change_source(value, change)
    result = module.summarize_baseline(value)
    assert result['tasks']['total'] == 12 and result['tasks']['task_success_rate'] == 10/12
    assert result['fact_consistency']['status'] == 'not_reviewed'
    assert result['fact_consistency']['stories_without_reported_conflict'] is None
    assert result['first_output_structure']['rate'] is None
    assert result['latency']['button']['samples'] == 0


@pytest.mark.parametrize('fault', ['hash', 'duplicate', 'manifest', 'demo', 'summary'])
def test_stage5_rejects_corrupt_or_mislabelled_sources(fault):
    module, value = runner(), bundle()
    if fault == 'hash':
        value['source_report_json'] += ' '
    else:
        def change(source):
            if fault == 'duplicate': source['cases'][1]['id'] = source['cases'][0]['id']
            if fault == 'manifest': source['manifest_sha256'] = 'wrong'
            if fault == 'demo': source['measurement'] = 'deterministic_demo'
            if fault == 'summary': source['summary']['succeeded'] = 11
        change_source(value, change)
    with pytest.raises(ValueError):
        module.summarize_baseline(value)


def test_stage5_first_attempt_validation_does_not_hide_retry_or_confuse_semantics():
    module, value = runner(), bundle()
    value['attempts'] = [
        dict(task='action:a', operation='action.interpret', version='v2', number=1, output=None, error_code='rate_limited'),
        dict(task='action:a', operation='action.interpret', version='v2', number=2,
             output='{"result":{"status":"recognized","action_index":0}}', error_code=None),
        dict(task='creation:b', operation='story.semantic_check', version='v1', number=1,
             output='{"passed":false,"issues":[{"code":"contradiction","entity_ids":[],"description":"conflict"}]}', error_code=None),
    ]
    result = module.summarize_baseline(seal(value))
    assert result['first_output_structure']['total'] == 2
    # A semantic rejection is structurally valid; it is never evidence of factual correctness.
    assert result['first_output_structure']['valid'] == 1
    assert result['semantic_checks']['rejected'] == 1
    assert result['fact_consistency']['status'] == 'not_reviewed'


def test_stage5_latency_separates_buttons_text_and_missing_samples():
    module, value = runner(), bundle()
    value['turns'] = [dict(id='a', input_type='option', duration_ms=20, fallback=False),
                      dict(id='b', input_type='text', duration_ms=1000, fallback=False),
                      dict(id='c', input_type='text', duration_ms=2000, fallback=True),
                      dict(id='d', input_type='text', duration_ms=None, fallback=False)]
    result = module.summarize_baseline(seal(value))
    assert result['fallback'] == dict(total=4, count=1, rate=.25)
    assert result['latency']['button']['p95_ms'] == 20
    assert result['latency']['free_text']['p95_ms'] == 2000
    assert result['latency']['free_text']['missing'] == 1


def test_stage5_human_evidence_is_scoped_to_the_original_run():
    module, value = runner(), bundle()
    value['human_review'] = dict(run_id='foreign', reviewers=1, review_date='2026-10-11',
                                results={era:{'无事实冲突':'passed'} for era in ('ancient','modern','future')},
                                reported_issues=[], scope='three_stories_nine_saved_paths')
    with pytest.raises(ValueError, match='human_review'):
        module.summarize_baseline(seal(value))
    value['human_review']['run_id'] = 'historical-run'
    result = module.summarize_baseline(seal(value))
    assert result['fact_consistency']['reviewers'] == 1
    assert result['fact_consistency']['stories_without_reported_conflict'] == 3
    assert result['source']['prompt_version'] == 'investigation-single-6'


def test_stage5_unsafe_database_rejected_before_connection_or_provider(tmp_path):
    module = runner()
    with patch('sqlalchemy.create_engine', side_effect=AssertionError('unsafe connection')):
        with pytest.raises(ValueError, match='dedicated_postgresql_test_database_required'):
            module.collect_baseline(tmp_path/'missing.json', 'postgresql://owner@localhost/stories')


def test_stage5_manifest_hash_accepts_lf_equivalent_windows_checkout():
    module, value = runner(), bundle()
    manifest = module.run_stage2.MANIFEST.read_bytes().replace(b'\r\n', b'\n')
    change_source(value, lambda source:source.update(manifest_sha256=hashlib.sha256(manifest).hexdigest()))
    assert module.summarize_baseline(value)['tasks']['total'] == 12


def test_scoped_usage_does_not_query_unrelated_or_newer_schema_records():
    module = runner()
    with patch('app.usage_reconciliation.reconciled_usage', side_effect=AssertionError('unscoped query')):
        result = module.run_stage2.usage_summary(None, [], evidence={})
    assert result['unconfirmed_calls'] == 0 and result['input_tokens'] == 0


@pytest.mark.parametrize('field', ['attempts', 'turns', 'usage', 'human_review'])
def test_stage5_replay_rejects_changed_evidence(field):
    module, value = runner(), bundle()
    value[field] = {'tampered':True}
    with pytest.raises(ValueError, match='bundle_hash_mismatch'):
        module.summarize_baseline(value)


@pytest.mark.parametrize('fault', ['missing_first', 'missing_ledger', 'duplicate', 'usage'])
def test_stage5_replay_rejects_incomplete_accounting_even_after_resealing(fault):
    module, value = runner(), bundle()
    value['attempts'] = [dict(task='action:a', operation='action.interpret', version='v2', number=1,
                              output=None, error_code='rate_limited')]
    seal(value)
    if fault == 'missing_first': value['attempts'][0]['number'] = 2
    if fault == 'missing_ledger': value['attempts'][0].update(request_sent=True, chargeable=True, call_id='missing')
    if fault == 'duplicate':
        value['attempts'].append(dict(value['attempts'][0]))
        value['coverage']['attempts'] = 2
    if fault == 'usage': value['usage']['input_tokens'] = 999
    module.seal_bundle(value)
    with pytest.raises(ValueError):
        module.summarize_baseline(value)


def test_stage5_unknown_usage_does_not_claim_a_full_zero_cost():
    module, value = runner(), bundle()
    value['attempts'] = [dict(id='a', task='action:a', operation='action.interpret', version='v2', number=1,
        output=None, error_code='outcome_unknown', request_sent=True, chargeable=True, call_id='call')]
    value['calls'] = [dict(id='call', attempt_id='a', input_tokens=None, output_tokens=None,
                           usage_status='uncertain', estimated_cost_cny=None)]
    result = module.summarize_baseline(seal(value))
    assert result['usage']['unconfirmed_calls'] == 1
    assert result['usage']['full_run_estimated_cost_cny'] is None


def test_stage5_readonly_collection_excludes_unlinked_usage_and_rejects_foreign_or_missing_traces(monkeypatch, tmp_path):
    from decimal import Decimal
    from uuid import uuid4
    from sqlalchemy import delete, select
    from app.db import SessionLocal
    from app.local_settings import clear_key, put_key
    from app.models import ExecutionTrace, LLMCall, Run
    from app.provider_clients import ProviderOutcome
    from pydantic import SecretStr
    from test_custom_story_creation import successful_provider
    module = runner()
    monkeypatch.setattr(module.run_stage2, 'ROOT', tmp_path)
    unlinked_id = str(uuid4())
    async def provider(provider, model, key, prompt, budget, timeout):
        data = json.loads(prompt.split('\n输入数据：', 1)[1])
        if 'text' in data:
            index = data['action_labels'].index(data['text'])
            return ProviderOutcome(json.dumps({'result':{'status':'recognized','action_index':index}}),20,20,request_sent=True)
        return await successful_provider(provider, model, key, prompt, budget, timeout)
    put_key('deepseek', SecretStr('stage5-fixture-private-key'))
    try:
        with patch('app.story_operations.call_operation_provider', side_effect=provider), patch.object(module.run_stage2, '_text',
                side_effect=lambda story, action, mapping, node:next(o['label'] for o in node.rendered_scene['options'] if mapping[o['id']] == action)):
            source, path = module.run_stage2.run_suite('real_model', 'MIGRATION_DATABASE_URL')
        assert source['summary']['succeeded'] == 12
        with SessionLocal.begin() as db:
            run = db.scalar(select(Run).where(Run.node_id == source['cases'][1]['terminal_node_id']))
            db.add(LLMCall(id=unlinked_id, run_id=run.id, attempt_id=str(uuid4()), provider='deepseek', model_id='deepseek-flash',
                input_tokens=999999, output_tokens=999999, estimated_cost_cny=Decimal('999'), price_version='test'))
        with patch('app.provider_clients.call_operation_provider', side_effect=AssertionError('read-only replay called provider')):
            collected = module.collect_baseline(path, __import__('os').environ['DATABASE_URL'])
            result = module.summarize_baseline(collected)
        assert result['coverage']['read_only'] is True and result['coverage']['saved_turns'] == 189
        assert result['usage']['input_tokens'] == source['usage']['input_tokens']
        assert result['usage']['ledger_calls'] == source['usage']['ledger_calls']
        assert 'stage5-fixture-private-key' not in json.dumps(collected)
        tampered = json.loads(path.read_text(encoding='utf-8'))
        for key in ('ending_id','actions','terminal_node_id','run_ids'):
            tampered['cases'][2][key] = tampered['cases'][1][key]
        wrong = path.with_name('wrong-path.json')
        wrong.write_text(json.dumps(tampered), encoding='utf-8')
        with pytest.raises(ValueError, match='frozen_path_mismatch'):
            module.collect_baseline(wrong, __import__('os').environ['DATABASE_URL'])
        tampered = json.loads(path.read_text(encoding='utf-8'))
        tampered['prompt_version'] = 'investigation-single-6'
        wrong.write_text(json.dumps(tampered), encoding='utf-8')
        with pytest.raises(ValueError, match='provenance_mismatch'):
            module.collect_baseline(wrong, __import__('os').environ['DATABASE_URL'])
        tampered = json.loads(path.read_text(encoding='utf-8'))
        tampered['cases'][1]['status'] = 'error'
        tampered['summary'] = module.summarize(tampered['cases'])
        failed = path.with_name('failed-report.json')
        failed.write_text(json.dumps(tampered), encoding='utf-8')
        failed_bundle = module.collect_baseline(failed, __import__('os').environ['DATABASE_URL'])
        failed_result = module.summarize_baseline(failed_bundle)
        assert failed_result['tasks']['succeeded'] == 11
        assert failed_result['usage']['ledger_calls'] == result['usage']['ledger_calls']
        with SessionLocal.begin() as db:
            saved_run = db.get(Run, run.id)
            saved_node = saved_run.node_id
            saved_run.node_id, saved_run.status = None, 'failed'
            end = db.scalar(select(ExecutionTrace).where(ExecutionTrace.run_id == run.id,
                                                       ExecutionTrace.event_type == 'node_committed'))
            end_id = end.id
            end.node_id, end.event_type = None, 'task_failed'
        try:
            failed_turn = module.summarize_baseline(module.collect_baseline(failed, __import__('os').environ['DATABASE_URL']))
            assert failed_turn['fallback']['total'] == 188
            assert failed_turn['usage']['ledger_calls'] == result['usage']['ledger_calls']
        finally:
            with SessionLocal.begin() as db:
                saved_run = db.get(Run, run.id)
                saved_run.node_id, saved_run.status = saved_node, 'completed'
                end = db.get(ExecutionTrace, end_id)
                end.node_id, end.event_type = saved_node, 'node_committed'
        del tampered['cases'][1]['run_ids']
        del tampered['cases'][1]['terminal_node_id']
        failed.write_text(json.dumps(tampered), encoding='utf-8')
        partial = module.summarize_baseline(module.collect_baseline(failed, __import__('os').environ['DATABASE_URL']))
        assert partial['usage']['coverage_complete'] is False
        assert partial['usage']['full_run_estimated_cost_cny'] is None
        assert partial['first_output_structure']['rate'] is None
        with SessionLocal.begin() as db:
            call = db.scalar(select(LLMCall).where(LLMCall.creation_task_id == source['cases'][0]['task_id']))
            call_id, old_attempt = call.id, call.attempt_id
            call.attempt_id = str(uuid4())
        try:
            with pytest.raises(ValueError, match='chargeable_ledger_missing'):
                module.collect_baseline(path, __import__('os').environ['DATABASE_URL'])
        finally:
            with SessionLocal.begin() as db: db.get(LLMCall, call_id).attempt_id = old_attempt
        with SessionLocal.begin() as db:
            begin = db.get(ExecutionTrace, old_attempt)
            begin.event_type = 'removed_begin'
        try:
            with pytest.raises(ValueError, match='attempt_evidence_incomplete'):
                module.collect_baseline(path, __import__('os').environ['DATABASE_URL'])
        finally:
            with SessionLocal.begin() as db: db.get(ExecutionTrace, old_attempt).event_type = 'attempt_started'
        tampered = json.loads(path.read_text(encoding='utf-8'))
        tampered['cases'][1]['session_id'] = 'foreign'
        foreign = path.with_name('foreign-report.json')
        foreign.write_text(json.dumps(tampered), encoding='utf-8')
        with pytest.raises(ValueError, match='path_evidence_mismatch'):
            module.collect_baseline(foreign, __import__('os').environ['DATABASE_URL'])
        with SessionLocal.begin() as db:
            db.execute(delete(ExecutionTrace).where(ExecutionTrace.run_id == run.id, ExecutionTrace.event_type == 'task_started'))
        with pytest.raises(ValueError, match='turn_trace_missing_or_foreign'):
            module.collect_baseline(path, __import__('os').environ['DATABASE_URL'])
    finally:
        clear_key('deepseek')
        with SessionLocal.begin() as db:
            db.execute(delete(LLMCall).where(LLMCall.id == unlinked_id))
