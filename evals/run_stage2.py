"""Fixed phase 2 simulated/real tasks. Only dedicated PostgreSQL *_test databases."""
import argparse
from decimal import Decimal
from datetime import datetime,timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'backend'))
from evals.run_stage1 import execute_case,summarize,validate_database_url

MANIFEST = ROOT/'evals/cases/stage2.json'


def load_manifest():
    value = json.loads(MANIFEST.read_text(encoding='utf-8'))
    cases = value.get('cases')
    if value.get('manifest_version')!='stage2-1' or not cases:
        raise ValueError('invalid_manifest')
    ids = set()
    for case in cases:
        if case['id'] in ids or case['suite'] not in ('runtime_simulated','real_model') or not case.get('expected'):
            raise ValueError('invalid_manifest_case')
        if case['suite']=='runtime_simulated':
            import re
            if not re.fullmatch(r'tests/test_[a-z0-9_]+\.py',case['test']) or not 1<=case['timeout_seconds']<=120:
                raise ValueError('invalid_manifest_case')
        elif case.get('era') not in ('ancient','modern','future') or case.get('kind') not in ('creation','path'):
            raise ValueError('invalid_manifest_case')
        ids.add(case['id'])
    return value


def inspect_trace(factory,session_id,trace_id):
    from sqlalchemy import select
    from app.execution_traces import TraceRecorder
    from app.models import ExecutionTrace,StorySession
    with factory() as db:
        rows = db.scalars(select(ExecutionTrace).where(ExecutionTrace.session_id==session_id,
                          ExecutionTrace.trace_id==trace_id).order_by(ExecutionTrace.seq)).all()
        if not rows:
            raise ValueError('trace_not_found')
        session = db.get(StorySession,session_id)
        recorder = TraceRecorder(factory,token_hashes=[session.token_hash])
        return [{'seq':row.seq,'event_type':row.event_type,'span_id':row.span_id,'parent_span_id':row.parent_span_id,
                 'attempt':row.attempt,'duration_ms':row.duration_ms,'error_code':row.error_code,
                 'payload':recorder.redact(row.payload)} for row in rows]


def _poll(client,url,headers,seconds):
    deadline = time.monotonic()+seconds
    while time.monotonic()<deadline:
        response = client.get(url,headers=headers)
        if response.status_code!=200:
            raise ValueError('task_read_failed')
        data = response.json()
        if data['status'] not in ('queued','running'):
            return data
        time.sleep(.1)
    raise ValueError('evaluation_timeout')


def _text(story,action,mapping,node):
    kind = action['type']
    if kind=='move':
        return '前往'+next(l.name for l in story.locations if l.id==action['location_id'])
    if kind=='investigate':
        return '调查'+next(o.name for o in story.objects if o.id==action['object_id'])
    if kind=='present':
        character = next(c.name for c in story.characters if c.id==action['character_id'])
        evidence = next(e.description for e in story.evidence if e.id==action['evidence_id'])
        return f'向{character}出示已发现的证据：{evidence[:200]}'
    key = next(key for key,value in mapping.items() if value==action)
    return next(o['label'] for o in node.rendered_scene['options'] if o['id']==key)


def execute_real_cases(cases,output):
    from app.local_settings import configured
    if not configured('deepseek'):
        return [{'id':case['id'],'status':'error','error_code':'key_not_configured','duration_ms':0} for case in cases]
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import SessionLocal
    from app.models import Node,StoryTask
    from app.story_versions import load_narration_protocol,load_story_version
    saved = {}
    results = []
    with TestClient(app) as client:
        for case in cases:
            started = time.monotonic()
            result = {'id':case['id'],'status':'error','error_code':None}
            try:
                if case['kind']=='creation':
                    session = client.post('/story-sessions',json={'provider':'deepseek'})
                    if session.status_code!=201:
                        raise ValueError('session_creation_failed')
                    headers = {'Authorization':'Bearer '+session.json()['token']}
                    result['session_id'] = session.json()['session_id']
                    task = client.post('/story-tasks',headers={**headers,'Idempotency-Key':uuid4().hex},
                                       json={'setting':case['setting'],'era':case['era']})
                    if task.status_code!=202:
                        raise ValueError('task_creation_failed')
                    result['task_id'] = task.json()['task_id']
                    task = _poll(client,'/story-tasks/'+task.json()['task_id'],headers,310)
                    with SessionLocal() as db:
                        checkpoint = db.get(StoryTask,task['id']).checkpoint
                        provenance = {key:checkpoint[key] for key in ('creation_protocol','narration_protocol','blueprint_version','blueprint_sha256','prompt_version')
                                      if key in checkpoint}
                    result.update(provenance)
                    if task['status']!='awaiting_confirmation':
                        raise ValueError(task['error_code'] or 'creation_not_ready')
                    confirmed = client.post('/story-tasks/'+task['id']+'/confirm',headers=headers,
                                             json={'candidate_version_id':task['candidate_version_id'],'content_hash':task['content_hash']})
                    if confirmed.status_code!=200:
                        raise ValueError('confirmation_failed')
                    root_id = confirmed.json()['root']['id']
                    result['root_node_id'] = root_id
                    with SessionLocal() as db:
                        version_id = db.get(Node,root_id).story_version_id
                        story = load_story_version(db,version_id)
                        narration = load_narration_protocol(db,version_id)
                        if narration != provenance.get('narration_protocol'):
                            raise ValueError('presentation_protocol_mismatch')
                        provenance['narration_protocol'] = narration
                        proof = db.get(StoryTask,task['id']).checkpoint['proof']
                        if proof['status']!='passed':
                            raise ValueError('approved_proof_missing')
                        paths = proof['ending_paths']
                    frozen = {'story':story.model_dump(),'paths':paths,'content_hash':task['content_hash'],**provenance}
                    blob = json.dumps(frozen,ensure_ascii=False,sort_keys=True).encode('utf-8')
                    (output/(case['era']+'-frozen.json')).write_bytes(blob)
                    saved[case['era']] = (headers,root_id,story,paths,provenance)
                    result.update(story_hash=task['content_hash'],paths_sha256=hashlib.sha256(blob).hexdigest())
                else:
                    if case['era'] not in saved:
                        raise ValueError('creation_dependency_failed')
                    headers,parent,story,paths,provenance = saved[case['era']]
                    result.update(root_node_id=parent,**provenance)
                    with SessionLocal() as db:
                        result['session_id'] = db.get(Node,parent).session_id
                    ending,path = sorted(paths.items())[case['index']]
                    for normalized in path:
                        with SessionLocal() as db:
                            node = db.get(Node,parent)
                            mapping = node.investigation_options
                            key = next(key for key,value in mapping.items() if value==normalized)
                            action = ({'type':'text','value':_text(story,normalized,mapping,node)} if case['free_text']
                                      else {'type':'option','value':key})
                        response = client.post('/turns',headers={**headers,'Idempotency-Key':uuid4().hex},
                                               json={'parent_node_id':parent,'action':action})
                        if response.status_code!=202:
                            raise ValueError('turn_creation_failed')
                        run = _poll(client,'/runs/'+response.json()['run_id'],headers,65)
                        if run['status']!='completed':
                            raise ValueError(run['error_code'] or 'turn_failed')
                        with SessionLocal() as db:
                            child = db.get(Node,run['node_id'])
                            if child.state_snapshot['action_turn']!=node.state_snapshot['action_turn']+1:
                                raise ValueError('text_or_button_not_accepted')
                        parent = run['node_id']
                    with SessionLocal() as db:
                        if db.get(Node,parent).state_snapshot['ending_id']!=ending:
                            raise ValueError('wrong_ending')
                    result.update(ending_id=ending,actions=len(path),free_text=case['free_text'],terminal_node_id=parent)
                result['status'] = 'succeeded'
            except (ValueError,KeyError,StopIteration) as error:
                # Stable codes only; never persist exception/provider diagnostics.
                code = str(error)
                result['error_code'] = code if code and code.replace('_','').isalnum() and len(code)<=80 else 'evaluation_error'
            except Exception:
                result['error_code'] = 'evaluation_error'
            result['duration_ms'] = round((time.monotonic()-started)*1000,3)
            results.append(result)
            progress = {'complete':len(results)==len(cases),'cases':results}
            temporary = output/'progress.tmp'
            temporary.write_text(json.dumps(progress,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            temporary.replace(output/'progress.json')
    return results


def usage_summary(db,calls):
    from app.usage_reconciliation import reconciled_usage
    evidence = reconciled_usage(db)
    confirmed = [evidence[c.id] for c in calls if c.id in evidence]
    actual = sum((item.actual_cost_cny for item in confirmed),Decimal(0))
    original_estimate = sum((c.estimated_cost_cny or Decimal(0) for c in calls),Decimal(0))
    accounted = sum((c.estimated_cost_cny or Decimal(0) for c in calls if c.id not in evidence),Decimal(0))+actual
    return {'usage_measurement_version':'execution-usage-2',
            'input_tokens':sum(c.input_tokens or 0 for c in calls),
            'output_tokens':sum(c.output_tokens or 0 for c in calls),
            'uncertain_calls':sum(c.usage_status!='known' for c in calls),
            'unconfirmed_calls':sum(c.usage_status!='known' and c.id not in evidence for c in calls),
            'estimated_cost_cny':str(original_estimate),
            'reconciled_calls':len(confirmed),
            'reconciliation_source':'user_reported_provider_console' if confirmed else None,
            'reconciled_total_tokens':sum(item.total_tokens for item in confirmed),
            'reconciled_input_tokens':sum(item.input_tokens or 0 for item in confirmed),
            'reconciled_output_tokens':sum(item.output_tokens or 0 for item in confirmed),
            'reconciled_missing_split_calls':sum(item.input_tokens is None for item in confirmed),
            'actual_reconciled_cost_cny':str(actual),'budget_accounted_cost_cny':str(accounted)}


def operation_usage_summary(db,calls,attempts):
    groups = {}
    for attempt in attempts:
        operation = attempt.payload['operation']
        groups.setdefault(operation,[]).append(attempt.id)
    result = {}
    attributed = set()
    for operation,ids in groups.items():
        linked = [call for call in calls if call.attempt_id in ids]
        attributed.update(call.id for call in linked)
        result[operation] = {'attempts':len(ids),'ledger_calls':len(linked),**usage_summary(db,linked)}
    unlinked = [call for call in calls if call.id not in attributed]
    if unlinked:
        result['unattributed'] = {'attempts':0,'ledger_calls':len(unlinked),**usage_summary(db,unlinked)}
    return result


def run_suite(suite,database_url_env):
    manifest = load_manifest()
    cases = [case for case in manifest['cases'] if case['suite']==suite]
    if not cases:
        raise ValueError('empty_suite')
    url = validate_database_url(os.environ.get(database_url_env,''))
    environment = dict(os.environ)
    environment['DATABASE_URL'] = url.render_as_string(hide_password=False)
    environment['MIGRATION_DATABASE_URL'] = environment['DATABASE_URL']
    run_id = uuid4().hex
    output = ROOT/'runtime/evals'/run_id
    output.mkdir(parents=True)
    started = time.monotonic()
    started_at = datetime.now(timezone.utc)
    if suite=='real_model':
        # Must set before the backend imports create its engine.
        os.environ.update(DATABASE_URL=environment['DATABASE_URL'],MIGRATION_DATABASE_URL=environment['DATABASE_URL'])
        from app.db import engine
        if engine.url != url:
            raise ValueError('loaded_database_mismatch')
        results = execute_real_cases(cases,output)
    else:
        results = [execute_case(case,output,environment) for case in cases]
    from sqlalchemy import create_engine,select
    from sqlalchemy.orm import Session
    from app.models import ExecutionTrace,LLMCall
    from app.costs import EXECUTION_PRICE_VERSION,budget_status
    from app.story_operations import PROMPT_VERSION,OPERATION_VERSIONS,OPERATION_TIMEOUTS
    from app.story_content import BLUEPRINT_VERSION,BLUEPRINT_SHA256
    with create_engine(url).connect() as connection,Session(bind=connection) as db:
        query = select(LLMCall).where(LLMCall.created_at>=started_at)
        calls = db.scalars(query).all()
        attempts = db.scalars(select(ExecutionTrace).where(
            ExecutionTrace.event_type=='attempt_started',ExecutionTrace.created_at>=started_at))
        attempts = list(attempts)
        usage = {'measurement':'retained_ledger_rows','attempts':len(attempts),'ledger_calls':len(calls),
                 'operations':operation_usage_summary(db,calls,attempts),**usage_summary(db,calls)}
        budget = budget_status(db)
    commit = subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=False)
    report = {'metric_version':manifest['metric_version'],'run_id':run_id,'suite':suite,
              'measurement':'simulated_faults' if suite=='runtime_simulated' else 'real_model_with_approved_feedback',
              'git_commit':commit.stdout.strip(),'manifest_sha256':hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
              'model_version':'deepseek-flash','prompt_version':PROMPT_VERSION,'price_version':EXECUTION_PRICE_VERSION,
              'operation_versions':OPERATION_VERSIONS,'operation_timeout_seconds':OPERATION_TIMEOUTS,
              'creation_protocol':'controlled-content-2','narration_protocol':'approved-feedback-1',
              'blueprint_version':BLUEPRINT_VERSION,'blueprint_sha256':BLUEPRINT_SHA256,
              'timestamp':datetime.now(timezone.utc).isoformat(),'duration_ms':round((time.monotonic()-started)*1000,3),
              'manual_reviewers':0,'summary':summarize(results),'cases':results,'usage':usage,'database_budget':budget}
    path = output/'report.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report,path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',choices=('runtime_simulated','real_model'),required=True)
    parser.add_argument('--database-url-env',default='MIGRATION_DATABASE_URL')
    parser.add_argument('--prompt-key',action='store_true',help='Ask locally without echo; store in backend memory only')
    args = parser.parse_args()
    # Refuse an unsafe DB before loading configuration or accepting a key.
    try:
        validate_database_url(os.environ.get(args.database_url_env,''))
        if args.prompt_key:
            if args.suite!='real_model':
                raise ValueError('key_not_needed')
            from app.local_settings import put_key
            from pydantic import SecretStr
            put_key('deepseek',SecretStr(getpass.getpass('DeepSeek API key (memory only): ')))
        report,path = run_suite(args.suite,args.database_url_env)
    except (ValueError,OSError,KeyError):
        print('stage2 evaluation: configuration or manifest rejected')
        return 2
    finally:
        if args.prompt_key:
            from app.local_settings import clear_key
            clear_key('deepseek')
    print(json.dumps({**report['summary'],'report':str(path)},ensure_ascii=False))
    return 0 if report['summary']['succeeded']==report['summary']['total'] else 1


if __name__=='__main__':
    raise SystemExit(main())
