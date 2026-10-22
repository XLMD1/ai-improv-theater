"""Reproducible R1 baseline: read saved real evidence, replay metrics, or run stage 2.

Raw bundles stay local in runtime/evals. Recorded collection uses a read-only
PostgreSQL *_test transaction and never starts the app or calls a provider.
"""
import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))
from evals.run_stage1 import summarize, validate_database_url
from evals import run_stage2


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical_digest(value):
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def seal_bundle(bundle):
    bundle['bundle_sha256'] = canonical_digest({k:v for k,v in bundle.items() if k != 'bundle_sha256'})
    return bundle


def snapshot_usage(calls, reconciliations):
    from app.usage_reconciliation import UsageReconciliation
    rows = [SimpleNamespace(**{**c, 'estimated_cost_cny':None if c['estimated_cost_cny'] is None
                              else Decimal(c['estimated_cost_cny'])}) for c in calls]
    evidence = {}
    for raw in reconciliations:
        item = UsageReconciliation.model_validate_json(json.dumps(raw))
        if item.call_id in evidence:
            raise ValueError('duplicate_reconciliation')
        evidence[item.call_id] = item
    if not set(evidence).issubset(c.id for c in rows):
        raise ValueError('foreign_reconciliation')
    return dict(ledger_calls=len(rows), **run_stage2.usage_summary(None, rows, evidence=evidence))


def verify_snapshot(bundle):
    if bundle.get('bundle_sha256') != canonical_digest({k:v for k,v in bundle.items() if k != 'bundle_sha256'}):
        raise ValueError('bundle_hash_mismatch')
    attempts, turns, calls = bundle['attempts'], bundle['turns'], bundle['calls']
    if (len({a['id'] for a in attempts}) != len(attempts) or len({t['id'] for t in turns}) != len(turns)
            or len({c['id'] for c in calls}) != len(calls) or len({c['attempt_id'] for c in calls}) != len(calls)
            or bundle['coverage']['saved_turns'] != len(turns)
            or bundle['coverage']['attempts'] != len(attempts) or bundle['coverage']['ledger_calls'] != len(calls)):
        raise ValueError('snapshot_count_mismatch')
    by_attempt = {c['attempt_id']:c for c in calls}
    previous = {}
    sequences = set()
    for item in sorted(attempts, key=lambda a:(a['task'], a['sequence'])):
        if (item['task'], item['sequence']) in sequences:
            raise ValueError('duplicate_attempt_sequence')
        sequences.add((item['task'], item['sequence']))
        key = (item['task'], item['operation'])
        old = previous.get(key)
        if (type(item['number']) is not int or not 1 <= item['number'] <= 3
                or old is None and item['number'] != 1
                or item['number'] > 1 and (old is None or old['number']+1 != item['number']
                                          or old['error_code'] not in ('rate_limited','connect_failure'))):
            raise ValueError('attempt_sequence_incomplete')
        previous[key] = item
        call = by_attempt.get(item['id'])
        if item['request_sent'] and item['chargeable']:
            if (call is None or call['id'] != item['call_id']
                    or call['input_tokens'] != item['input_tokens'] or call['output_tokens'] != item['output_tokens']):
                raise ValueError('chargeable_ledger_missing')
        elif call is not None or item['call_id'] is not None:
            raise ValueError('unexpected_ledger')
    if not set(by_attempt).issubset(a['id'] for a in attempts):
        raise ValueError('foreign_ledger')
    computed = dict(attempts=len(attempts), **snapshot_usage(calls, bundle['reconciliations']))
    if computed != bundle['usage']:
        raise ValueError('usage_evidence_mismatch')
    human = bundle.get('human_review')
    if human is not None and bundle.get('human_review_sha256') != canonical_digest(human):
        raise ValueError('human_review_hash_mismatch')


def source_report(bundle):
    if bundle.get('bundle_version') != 'stage5-baseline-1':
        raise ValueError('unsupported_bundle')
    raw = bundle['source_report_json']
    if digest(raw.encode('utf-8')) != bundle['source_report_sha256']:
        raise ValueError('source_hash_mismatch')
    source = json.loads(raw)
    if (source.get('suite') != 'real_model' or source.get('measurement') != 'real_model_with_approved_feedback'
            or source.get('model_version') != 'deepseek-flash'
            or source.get('creation_protocol') != 'controlled-content-2'
            or source.get('narration_protocol') != 'approved-feedback-1'):
        raise ValueError('unsupported_source')
    expected = [c['id'] for c in run_stage2.load_manifest()['cases'] if c['suite'] == 'real_model']
    manifest = run_stage2.MANIFEST.read_bytes()
    if source.get('manifest_sha256') not in {digest(manifest), digest(manifest.replace(b'\r\n', b'\n'))}:
        raise ValueError('source_manifest_mismatch')
    if ([c['id'] for c in source['cases']] != expected
            or any(c['status'] not in ('succeeded', 'failed', 'error', 'skipped') for c in source['cases'])):
        raise ValueError('source_case_set_mismatch')
    if source['summary'] != summarize(source['cases']):
        raise ValueError('source_summary_mismatch')
    return source


def latency(values):
    measured = [v for v in values if v is not None]
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in measured):
        raise ValueError('invalid_latency')
    measured.sort()
    return dict(samples=len(measured), missing=len(values)-len(measured),
                p50_ms=measured[math.ceil(len(measured)*.5)-1] if measured else None,
                p95_ms=measured[math.ceil(len(measured)*.95)-1] if measured else None)


def summarize_baseline(bundle):
    verify_snapshot(bundle)
    source = source_report(bundle)
    from app.execution import ToolRegistry
    from app.story_operations import register_story_operations, register_investigation_operations
    registry, investigation_registry = ToolRegistry(), ToolRegistry()
    register_story_operations(registry, prompt_version=source['prompt_version'])
    register_investigation_operations(investigation_registry)
    def operation(name, version):
        return registry.get(name, version) or investigation_registry.get(name, version)
    first, semantic, repair_tasks = {}, [], set()
    for attempt in sorted(bundle['attempts'], key=lambda a:(a['task'], a['sequence'])):
        key = (attempt['task'], attempt['operation'])
        first.setdefault(key, attempt)
        if attempt['operation'] == 'story.content_repair':
            repair_tasks.add(attempt['task'])
        if attempt['operation'].endswith('semantic_check') and attempt.get('output'):
            try:
                report = operation(attempt['operation'], attempt['version']).output_schema.model_validate_json(attempt['output'])
                semantic.append(report.passed)
            except (ValueError, AttributeError):
                pass
    valid = 0
    for attempt in first.values():
        spec = operation(attempt['operation'], attempt['version'])
        if spec is None:
            raise ValueError('unsupported_operation_version')
        try:
            if attempt.get('error_code') or not attempt.get('output'):
                continue
            spec.output_schema.model_validate_json(attempt['output'])
            valid += 1
        except ValueError:
            pass
    human = bundle.get('human_review')
    facts = dict(status='not_reviewed', reviewers=0, stories_without_reported_conflict=None)
    if human is not None:
        if (human.get('run_id') != source['run_id'] or type(human.get('reviewers')) is not int
                or human['reviewers'] < 1 or set(human.get('results', {})) != {'ancient', 'modern', 'future'}
                or not isinstance(human.get('reported_issues'), list) or not human.get('review_date')
                or human.get('scope') != 'three_stories_nine_saved_paths'):
            raise ValueError('invalid_human_review')
        facts = dict(status='historical_human_review', reviewers=human['reviewers'], review_date=human['review_date'],
                     scope=human.get('scope'), reviewed_stories=3,
                     stories_without_reported_conflict=sum(r.get('无事实冲突') == 'passed' for r in human['results'].values()),
                     reported_issues=len(human['reported_issues']))
    turns = bundle['turns']
    creations = [c for c in source['cases'] if c['id'].startswith('create_')]
    count = len(first)
    return dict(metric_version='stage5-baseline-1', measurement='recorded_real_model_with_approved_feedback',
                source={k:source.get(k) for k in ('run_id', 'timestamp', 'git_commit', 'model_version', 'prompt_version',
                    'price_version', 'manifest_sha256', 'blueprint_version', 'blueprint_sha256', 'creation_protocol', 'narration_protocol')},
                source_report_sha256=bundle['source_report_sha256'], tasks=summarize(source['cases']),
                bundle_sha256=bundle['bundle_sha256'],
                stories=[dict(era=c['id'].removeprefix('create_'), content_hash=c.get('story_hash'),
                              frozen_paths_sha256=c.get('paths_sha256')) for c in creations],
                first_output_structure=dict(total=count, valid=valid,
                    rate=valid/count if count and bundle['coverage']['accounting_complete'] else None),
                semantic_checks=dict(total=len(semantic), rejected=semantic.count(False)),
                creation_repair=dict(total=len(creations), count=len(repair_tasks), rate=len(repair_tasks)/len(creations)),
                fallback=dict(total=len(turns), count=sum(t['fallback'] for t in turns),
                              rate=sum(t['fallback'] for t in turns)/len(turns) if turns else None),
                latency=dict(button=latency([t['duration_ms'] for t in turns if t['input_type'] == 'option']),
                             free_text=latency([t['duration_ms'] for t in turns if t['input_type'] == 'text']),
                             creation_case=latency([c.get('duration_ms') for c in creations])),
                fact_consistency=facts, usage={**bundle['usage'],
                    'coverage_complete':bundle['coverage']['accounting_complete'],
                    'full_run_estimated_cost_cny':bundle['usage']['estimated_cost_cny']
                        if bundle['coverage']['accounting_complete'] and not bundle['usage']['unconfirmed_calls'] else None},
                coverage=bundle.get('coverage'), environment=bundle.get('environment'),
                limitations=['Historical evidence, not a new model or current-prompt quality evaluation.',
                             'R1 saved feedback is server presentation, not live model narration.',
                             'Turn latency excludes queueing, browser rendering and network delivery.',
                             'CNY estimates are not provider invoice verification.'])


def collect_baseline(source_path, database_url, human_review=None):
    url = validate_database_url(database_url)
    path = Path(source_path)
    raw = path.read_bytes()
    bundle = dict(bundle_version='stage5-baseline-1', source_report_json=raw.decode('utf-8'),
                  source_report_sha256=digest(raw), attempts=[], turns=[], calls=[], reconciliations=[], human_review=None)
    source = source_report(bundle)
    if human_review is not None:
        human_raw = Path(human_review).read_bytes()
        human = json.loads(human_raw)
        bundle.update(human_review=human, human_review_sha256=canonical_digest(human), human_file_sha256=digest(human_raw))
    from sqlalchemy import create_engine, or_, select
    from sqlalchemy.orm import Session, load_only
    from app.models import ExecutionTrace, LLMCall, Node, Run, StoryPresentation, StorySession, StoryTask, StoryVersion, TurnEvent
    from app.story_schema import Story, canonical_hash
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql('SET TRANSACTION READ ONLY')
            if connection.exec_driver_sql('SHOW transaction_read_only').scalar_one() != 'on':
                raise ValueError('read_only_required')
            with Session(bind=connection) as db:
                nodes, tasks, eras, unmeasured, runs = {}, {}, {}, [], {}
                manifests = {c['id']:c for c in run_stage2.load_manifest()['cases'] if c['suite'] == 'real_model'}
                provenance_keys = ('creation_protocol','narration_protocol','blueprint_version','blueprint_sha256','prompt_version')
                for case in source['cases']:
                    spec = manifests[case['id']]
                    if case['id'].startswith('create_'):
                        task = db.get(StoryTask, case.get('task_id')) if case.get('task_id') else None
                        if task:
                            if task.session_id != case.get('session_id'):
                                raise ValueError('creation_session_mismatch')
                            tasks[task.id] = task
                        if case['status'] != 'succeeded':
                            unmeasured.append(case['id'])
                            continue
                        if task is None or task.root_node_id != case['root_node_id']:
                            raise ValueError('creation_evidence_missing')
                        era = case['id'].removeprefix('create_')
                        frozen_raw = (path.parent / (era+'-frozen.json')).read_bytes()
                        frozen = json.loads(frozen_raw)
                        root = db.get(Node, case['root_node_id'])
                        version = db.get(StoryVersion, root.story_version_id) if root else None
                        presentation = db.get(StoryPresentation, version.id) if version else None
                        session = db.execute(select(StorySession.provider, StorySession.model_id).where(
                            StorySession.id == task.session_id)).one()
                        if (digest(frozen_raw) != case['paths_sha256'] or version is None
                                or root.session_id != task.session_id or root.parent_id is not None
                                or version.content_hash != case['story_hash'] or frozen['content_hash'] != version.content_hash
                                or canonical_hash(Story.model_validate(frozen['story'])) != version.content_hash
                                or canonical_hash(Story.model_validate(version.definition)) != version.content_hash
                                or version.approval_status != 'approved'
                                or session.provider != 'deepseek' or session.model_id != source['model_version']):
                            raise ValueError('frozen_story_mismatch')
                        if (any(item.get(key) != source.get(key) or source.get(key) is None
                                for item in (case, frozen, task.checkpoint) for key in provenance_keys)
                                or root.prompt_version != source['prompt_version'] or presentation is None
                                or presentation.narration_protocol != source['narration_protocol']):
                            raise ValueError('provenance_mismatch')
                        if frozen['paths'] != task.checkpoint['proof']['ending_paths']:
                            raise ValueError('frozen_path_mismatch')
                        eras[era] = (root, frozen['paths'])
                        continue
                    if spec['era'] not in eras:
                        unmeasured.append(case['id'])
                        continue
                    root, frozen_paths = eras[spec['era']]
                    if case.get('root_node_id') != root.id or case.get('session_id') != root.session_id:
                        raise ValueError('path_evidence_mismatch')
                    if any(case.get(key) != source.get(key) for key in provenance_keys):
                        raise ValueError('provenance_mismatch')
                    ending, expected = sorted(frozen_paths.items())[spec['index']]
                    if case['status'] == 'succeeded':
                        if (case.get('ending_id') != ending or case.get('free_text') is not spec['free_text']
                                or case.get('actions') != len(expected)):
                            raise ValueError('frozen_path_mismatch')
                        chain, node = [], db.get(Node, case.get('terminal_node_id'))
                        if node is None or node.state_snapshot.get('ending_id') != ending:
                            raise ValueError('path_evidence_mismatch')
                        while node.id != root.id:
                            if (node.id in {n.id for n in chain} or node.session_id != root.session_id
                                    or node.story_version_id != root.story_version_id or not node.parent_id):
                                raise ValueError('foreign_or_broken_parent_chain')
                            chain.append(node)
                            node = db.get(Node, node.parent_id)
                            if node is None: raise ValueError('missing_parent')
                        chain.reverse()
                        if len(chain) != len(expected): raise ValueError('frozen_path_mismatch')
                        path_runs = []
                        for node in chain:
                            linked = list(db.scalars(select(Run).where(Run.node_id == node.id)))
                            if len(linked) != 1: raise ValueError('run_evidence_missing')
                            path_runs.append(linked[0])
                        if 'run_ids' in case and case['run_ids'] != [r.id for r in path_runs]:
                            raise ValueError('frozen_path_mismatch')
                    elif 'run_ids' in case:
                        path_runs = [db.get(Run, identity) for identity in case['run_ids']]
                        if any(r is None for r in path_runs): raise ValueError('run_evidence_missing')
                    else:
                        # Older failed reports lack IDs for the failed attempt and paid prefix.
                        unmeasured.append(case['id'])
                        continue
                    if len(path_runs) > len(expected): raise ValueError('frozen_path_mismatch')
                    parent = root
                    for index, run in enumerate(path_runs):
                        if (run.id in runs or run.session_id != root.session_id or run.parent_node_id != parent.id
                                or run.action['type'] != ('text' if spec['free_text'] else 'option')):
                            raise ValueError('frozen_path_mismatch')
                        runs[run.id] = run
                        if run.node_id is None:
                            if case['status'] == 'succeeded' or index != len(path_runs)-1:
                                raise ValueError('run_evidence_missing')
                            continue
                        node = db.get(Node, run.node_id)
                        actions = list(db.scalars(select(TurnEvent).where(TurnEvent.node_id == node.id,
                                                                         TurnEvent.event_type == 'action_interpretation')))
                        if (node.parent_id != parent.id or node.session_id != root.session_id
                                or node.story_version_id != root.story_version_id or len(actions) != 1
                                or actions[0].payload.get('action') != expected[index]):
                            raise ValueError('frozen_path_mismatch')
                        nodes[node.id], parent = node, node
                runs = list(runs.values())
                # Read the phase-2 columns only; recorded source databases need no image migration.
                trace_fields = [ExecutionTrace.id, ExecutionTrace.trace_id, ExecutionTrace.seq, ExecutionTrace.span_id,
                    ExecutionTrace.run_id, ExecutionTrace.creation_task_id, ExecutionTrace.session_id,
                    ExecutionTrace.node_id, ExecutionTrace.event_type, ExecutionTrace.attempt,
                    ExecutionTrace.payload, ExecutionTrace.error_code, ExecutionTrace.created_at, ExecutionTrace.llm_call_id]
                traces = list(db.scalars(select(ExecutionTrace).options(load_only(*trace_fields)).where(or_(
                    ExecutionTrace.creation_task_id.in_(list(tasks)), ExecutionTrace.run_id.in_([r.id for r in runs])))
                    .order_by(ExecutionTrace.trace_id, ExecutionTrace.seq)))
                owners = {('creation',t.id):t.session_id for t in tasks.values()}
                owners.update({('action',r.id):r.session_id for r in runs})
                if any(e.session_id != owners.get(('creation',e.creation_task_id) if e.creation_task_id
                                                  else ('action',e.run_id)) for e in traces):
                    raise ValueError('foreign_trace')
                for run in runs:
                    node = nodes.get(run.node_id)
                    events = [e for e in traces if e.run_id == run.id]
                    starts = [e for e in events if e.event_type == 'task_started']
                    ends = [e for e in events if (e.event_type == 'node_committed' and node and e.node_id == node.id)
                            or e.event_type == 'task_failed' and node is None]
                    if len(starts) != 1 or len(ends) != 1:
                        raise ValueError('turn_trace_missing_or_foreign')
                    if node is None:
                        continue  # Failed attempts still contribute traces and usage, never a saved scene.
                    bundle['turns'].append(dict(id=run.id, node_id=run.node_id, input_type=run.action['type'],
                        duration_ms=round((ends[-1].created_at-starts[0].created_at).total_seconds()*1000, 3),
                        fallback=node.rendered_scene['fallback'], status=run.status))
                begins = [e for e in traces if e.event_type == 'attempt_started']
                finishes = [e for e in traces if e.event_type == 'attempt_finished']
                if len(begins) != len(finishes) or {e.span_id for e in begins} != {e.span_id for e in finishes}:
                    raise ValueError('attempt_evidence_incomplete')
                for task in tasks.values():
                    if task.status != 'approved': continue
                    operations = [e.payload['operation'] for e in begins if e.creation_task_id == task.id and e.attempt == 1]
                    if (operations.count('story.content_generate') != 1
                            or operations.count('story.content_repair') != task.repair_count
                            or operations.count('story.semantic_check') != task.repair_count+1):
                        raise ValueError('required_operation_missing')
                for run in runs:
                    operations = [e.payload['operation'] for e in begins if e.run_id == run.id]
                    if (run.node_id and run.action['type'] == 'text' and 'action.interpret' not in operations
                            or run.action['type'] == 'option' and operations):
                        raise ValueError('required_operation_missing')
                for begin in begins:
                    ends = [e for e in traces if e.span_id == begin.span_id and e.event_type == 'attempt_finished']
                    if len(ends) != 1:
                        raise ValueError('attempt_evidence_incomplete')
                    end = ends[0]
                    if ((begin.trace_id,begin.run_id,begin.creation_task_id,begin.attempt) !=
                            (end.trace_id,end.run_id,end.creation_task_id,end.attempt) or end.seq <= begin.seq
                            or source['operation_versions'].get(begin.payload['operation']) != begin.payload['version']):
                        raise ValueError('attempt_evidence_incomplete')
                    bundle['attempts'].append(dict(id=begin.id, sequence=begin.seq,
                        task=('creation:'+begin.creation_task_id if begin.creation_task_id else 'action:'+begin.run_id),
                        operation=begin.payload['operation'], version=begin.payload['version'], number=begin.attempt,
                        output=end.payload.get('text'), error_code=end.error_code, request_sent=end.payload['request_sent'],
                        chargeable=end.payload['chargeable'], call_id=end.llm_call_id,
                        input_tokens=end.payload.get('input_tokens'), output_tokens=end.payload.get('output_tokens')))
                call_fields = [LLMCall.id, LLMCall.attempt_id, LLMCall.input_tokens, LLMCall.output_tokens,
                    LLMCall.usage_status, LLMCall.estimated_cost_cny, LLMCall.trace_id, LLMCall.span_id,
                    LLMCall.run_id, LLMCall.creation_task_id, LLMCall.provider, LLMCall.model_id, LLMCall.price_version]
                calls = list(db.scalars(select(LLMCall).options(load_only(*call_fields)).where(
                    LLMCall.attempt_id.in_([e.id for e in begins]))))
                for call in calls:
                    begin = next(e for e in begins if e.id == call.attempt_id)
                    if ((call.trace_id,call.span_id,call.run_id,call.creation_task_id) !=
                            (begin.trace_id,begin.span_id,begin.run_id,begin.creation_task_id)
                            or call.provider != 'deepseek' or call.model_id != source['model_version']
                            or call.price_version != source['price_version']):
                        raise ValueError('ledger_identity_mismatch')
                    bundle['calls'].append(dict(id=call.id, attempt_id=call.attempt_id, input_tokens=call.input_tokens,
                        output_tokens=call.output_tokens, usage_status=call.usage_status,
                        estimated_cost_cny=None if call.estimated_cost_cny is None else str(call.estimated_cost_cny)))
                from app.usage_reconciliation import UsageReconciliation
                evidence, by_id = {}, {c.id:c for c in calls}
                for row in traces:
                    call = by_id.get(row.llm_call_id)
                    if row.event_type != 'usage_reconciled' or call is None:
                        continue
                    item = UsageReconciliation.model_validate_json(json.dumps(row.payload))
                    if (call.usage_status != 'uncertain' or item.call_id != call.id
                            or (row.trace_id, row.span_id, row.run_id, row.creation_task_id) !=
                               (call.trace_id, call.span_id, call.run_id, call.creation_task_id)
                            or call.id in evidence and evidence[call.id] != item):
                        raise ValueError('invalid_scoped_reconciliation')
                    evidence[call.id] = item
                bundle['reconciliations'] = [item.model_dump(mode='json') for item in evidence.values()]
                bundle['usage'] = dict(attempts=len(begins), **snapshot_usage(bundle['calls'], bundle['reconciliations']))
                bundle['coverage'] = dict(saved_turns=len(bundle['turns']), observed_runs=len(runs), creation_tasks=len(tasks), attempts=len(begins),
                    ledger_calls=len(calls), unmeasured_cases=unmeasured, accounting_complete=not unmeasured,
                    scope='declared_creation_tasks_and_frozen_paths_including_failed_run_ids', read_only=True)
                verify_snapshot(seal_bundle(bundle))
                if not unmeasured:
                    for key in ('attempts','ledger_calls','input_tokens','output_tokens','estimated_cost_cny'):
                        if Decimal(str(bundle['usage'][key])) != Decimal(str(source['usage'][key])):
                            raise ValueError('source_usage_coverage_mismatch')
    finally:
        engine.dispose()
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=False)
    bundle['environment'] = dict(collector_commit=commit.stdout.strip(), python=platform.python_version(),
        collector_script_sha256=digest(Path(__file__).read_bytes()),
        platform=platform.system(), packages={name:importlib.metadata.version(name) for name in ('sqlalchemy', 'pydantic', 'psycopg')})
    summarize_baseline(seal_bundle(bundle))
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, choices=('recorded', 'replay', 'real_model', 'runtime_simulated'))
    parser.add_argument('--source-report', type=Path)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--human-review', type=Path)
    parser.add_argument('--database-url-env', default='MIGRATION_DATABASE_URL')
    parser.add_argument('--prompt-key', action='store_true')
    args = parser.parse_args()
    from sqlalchemy.exc import SQLAlchemyError
    try:
        if args.prompt_key and args.suite != 'real_model':
            raise ValueError('key_not_needed')
        if args.suite == 'replay':
            if args.bundle is None: raise ValueError('bundle_required')
            bundle = json.loads(args.bundle.read_bytes())
        else:
            url = validate_database_url(os.environ.get(args.database_url_env, ''))
            if args.suite in ('real_model', 'runtime_simulated'):
                if args.prompt_key:
                    from pydantic import SecretStr
                    from app.local_settings import put_key
                    put_key('deepseek', SecretStr(getpass.getpass('DeepSeek API key (memory only): ')))
                original, source = run_stage2.run_suite(args.suite, args.database_url_env)
                if args.suite == 'runtime_simulated':
                    print(json.dumps(dict(measurement='simulated_faults', **original['summary'], report=str(source))))
                    return 0 if original['summary']['succeeded'] == original['summary']['total'] else 1
            else:
                if args.source_report is None: raise ValueError('source_report_required')
                source = args.source_report
            bundle = collect_baseline(source, url.render_as_string(hide_password=False), args.human_review)
        report = summarize_baseline(bundle)
        output = ROOT / 'runtime/evals' / ('stage5_'+uuid4().hex)
        output.mkdir(parents=True)
        for name, value in [('bundle.json', bundle), ('report.json', report)]:
            with (output/name).open('x', encoding='utf-8') as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
        print(json.dumps(dict(**report['tasks'], report=str(output/'report.json')), ensure_ascii=False))
        return 0 if (report['tasks']['succeeded'] == report['tasks']['total']
                     and report['coverage']['accounting_complete'] and not report['usage']['unconfirmed_calls']) else 1
    except (ValueError, OSError, KeyError, TypeError, SQLAlchemyError):
        print('stage5 evaluation: source, configuration or evidence rejected')
        return 2
    finally:
        if args.prompt_key:
            from app.local_settings import clear_key
            clear_key('deepseek')


if __name__ == '__main__':
    raise SystemExit(main())
