"""Frozen real phase-3 cases via an existing local service; keys stay in server memory."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'backend'))
from evals.run_stage1 import summarize,validate_database_url
from evals.run_stage2 import _text,operation_usage_summary
MANIFEST=ROOT/'evals/cases/stage3.json'


def load_manifest():
    data=json.loads(MANIFEST.read_text(encoding='utf-8'))
    if data.get('manifest_version')!='stage3-1' or len(data.get('cases',[]))!=15:
        raise ValueError('invalid_manifest')
    if len({c['id'] for c in data['cases']})!=15: raise ValueError('invalid_manifest')
    for era in ('ancient','modern','future'):
        group=[c for c in data['cases'] if c['era']==era]
        if [c['kind'] for c in group]!=['creation','images','path','path','path']:
            raise ValueError('invalid_manifest')
        if [c['index'] for c in group if c['kind']=='path']!=[0,1,2]: raise ValueError('invalid_manifest')
    return data


def checked(response,status):
    if response.status_code!=status:
        try: code=response.json().get('detail','http_failure')
        except ValueError: code='http_failure'
        if not isinstance(code,str) or len(code)>80 or not code.replace('_','').isalnum(): code='http_failure'
        raise ValueError(code)
    return response.json()


def poll(client,path,headers,seconds):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        data=checked(client.get(path,headers=headers),200)
        if data['status'] not in ('queued','running'): return data
        time.sleep(.5)
    raise ValueError('evaluation_timeout')


def read_resume_source(path):
    path=Path(path).resolve()
    if path.name!='report.json' or not path.is_relative_to((ROOT/'runtime/evals').resolve()):
        raise ValueError('resume_report_outside_runtime')
    source=json.loads(path.read_text(encoding='utf-8'))
    if source.get('manifest_sha256')!=hashlib.sha256(MANIFEST.read_bytes()).hexdigest():
        raise ValueError('resume_manifest_mismatch')
    if source.get('measurement')!='real_model_and_local_images' or {c['id'] for c in source['cases']}!={c['id'] for c in load_manifest()['cases']}:
        raise ValueError('invalid_resume_report')
    return source,path


def restore_creation(case,source,output,factory):
    from app.models import Node,StoryTask,StorySession,StoryVersion
    from app.story_versions import load_story_version
    report,path=source
    previous=next(c for c in report['cases'] if c['id']==case['id'])
    if previous['status']!='succeeded': raise ValueError('approved_creation_missing')
    credential=json.loads((path.parent/(case['era']+'-credential.json')).read_text(encoding='utf-8'))
    token=credential['token']
    if not re.fullmatch(r'[a-zA-Z0-9_-]{32,128}',token): raise ValueError('invalid_resume_credential')
    root=previous['root_node_id'];session_id=previous['session_id']
    with factory() as db:
        node=db.get(Node,root);session=db.get(StorySession,session_id);task=db.get(StoryTask,previous['task_id'])
        if not node or not session or not task or node.session_id!=session_id or node.parent_id is not None or task.status!='approved' or task.session_id!=session_id:
            raise ValueError('resume_creation_mismatch')
        if session.token_hash!=hashlib.sha256(token.encode()).hexdigest() or db.get(StoryVersion,node.story_version_id).content_hash!=previous['story_hash']:
            raise ValueError('resume_creation_mismatch')
        story=load_story_version(db,node.story_version_id);proof=task.checkpoint['proof']
        if proof['status']!='passed' or len(proof['ending_paths'])!=3: raise ValueError('proof_missing')
    for suffix in ('-credential.json','-frozen.json'):
        (output/(case['era']+suffix)).write_bytes((path.parent/(case['era']+suffix)).read_bytes())
    item={'headers':{'Authorization':'Bearer '+token},'session_id':session_id,'root':root,'story':story,'paths':proof['ending_paths'],'ready':False}
    return item,{**previous,'reused_approved_creation':True,'original_duration_ms':previous.get('original_duration_ms',previous['duration_ms'])}


def execute_cases(client,cases,output,factory,source=None):
    from app.models import Node,StoryTask,StoryAsset,LLMCall
    from app.story_versions import load_story_version
    from app.image_operations import asset_root
    from sqlalchemy import select,func
    from PIL import Image
    saved={}; results=[]
    for case in cases:
        started=time.monotonic()
        result={'id':case['id'],'status':'error','error_code':None}
        try:
            era=case['era']
            if case['kind']=='creation' and source:
                saved[era],result=restore_creation(case,source,output,factory)
            elif case['kind']=='creation':
                token=uuid4().hex+uuid4().hex
                session=checked(client.post('/story-sessions',json={'provider':'deepseek','flow':'illustrated-3','client_token':token}),201)
                headers={'Authorization':'Bearer '+token}
                result['session_id']=session['session_id']
                task=checked(client.post('/story-tasks',headers={**headers,'Idempotency-Key':uuid4().hex},json={'setting':case['setting'],'era':era}),202)
                task=poll(client,'/story-tasks/'+task['task_id'],headers,310)
                result['task_id']=task['id']
                if task['status']!='awaiting_confirmation': raise ValueError(task.get('error_code') or 'creation_not_ready')
                confirmed=checked(client.post('/story-tasks/'+task['id']+'/confirm',headers=headers,json={'candidate_version_id':task['candidate_version_id'],'content_hash':task['content_hash']}),200)
                root=confirmed['root']['id']
                with factory() as db:
                    story=load_story_version(db,db.get(Node,root).story_version_id)
                    proof=db.get(StoryTask,task['id']).checkpoint['proof']
                    if proof['status']!='passed' or len(proof['ending_paths'])!=3: raise ValueError('proof_missing')
                frozen={'story':story.model_dump(),'paths':proof['ending_paths'],'content_hash':task['content_hash']}
                blob=json.dumps(frozen,ensure_ascii=False,sort_keys=True).encode('utf-8')
                (output/(era+'-frozen.json')).write_bytes(blob)
                saved[era]={'headers':headers,'session_id':session['session_id'],'root':root,'story':story,'paths':proof['ending_paths'],'ready':False}
                (output/(era+'-credential.json')).write_text(json.dumps({'session_id':session['session_id'],'token':token,'root_node_id':root}),encoding='utf-8')
                result.update(root_node_id=root,story_hash=task['content_hash'],paths_sha256=hashlib.sha256(blob).hexdigest())
            elif case['kind']=='images':
                if era not in saved: raise ValueError('creation_dependency_failed')
                item=saved[era];headers=item['headers']; result['session_id']=item['session_id']
                key=uuid4().hex
                manifest=checked(client.get('/session/assets',headers=headers),200)
                if manifest['task_id']:
                    response=checked(client.post('/image-tasks/'+manifest['task_id']+'/resume',headers={**headers,'Idempotency-Key':key},json={'confirm_missing_output':False}),202)
                else:
                    response=checked(client.post('/image-tasks',headers={**headers,'Idempotency-Key':key}),202)
                task=poll(client,'/image-tasks/'+response['task_id'],headers,1250)
                result['task_id']=task['id'];result['completed']=task['completed']
                if task['status']!='ready' or task['completed']!=8: raise ValueError(task.get('error_code') or 'images_not_ready')
                checks=[]
                with factory() as db:
                    slots=list(db.scalars(select(StoryAsset).where(StoryAsset.task_id==task['id'])))
                    before=db.scalar(select(func.count()).select_from(LLMCall).where(LLMCall.image_task_id==task['id']))
                    for asset in slots:
                        local=(asset_root()/asset.file_path).read_bytes()
                        if hashlib.sha256(local).hexdigest()!=asset.sha256: raise ValueError('image_checksum_failed')
                        with Image.open(asset_root()/asset.file_path) as image:
                            if image.format!='PNG' or image.size!=tuple(map(int,asset.size.split('x'))): raise ValueError('image_size_failed')
                        fetched=client.get('/assets/'+asset.id,headers=headers)
                        if fetched.status_code!=200 or hashlib.sha256(fetched.content).hexdigest()!=asset.sha256: raise ValueError('asset_read_failed')
                        checks.append({'entity_id':asset.entity_id,'kind':asset.kind,'size':asset.size,'sha256':asset.sha256})
                if not source: checked(client.post('/image-tasks',headers={**headers,'Idempotency-Key':key}),202)
                manifest=checked(client.get('/session/assets',headers=headers),200)
                if not manifest['ready']: raise ValueError('manifest_not_ready')
                with factory() as db:
                    after=db.scalar(select(func.count()).select_from(LLMCall).where(LLMCall.image_task_id==task['id']))
                if before!=after: raise ValueError('replay_regenerated')
                result.update(assets=checks,model_calls=after);item['ready']=True
            else:
                if era not in saved or not saved[era]['ready']: raise ValueError('preparation_dependency_failed')
                item=saved[era];headers=item['headers'];parent=item['root'];story=item['story']
                result.update(session_id=item['session_id'],root_node_id=parent)
                ending,path=sorted(item['paths'].items())[case['index']]
                previous=next((c for c in source[0]['cases'] if c['id']==case['id'] and c['status']=='succeeded'),None) if source else None
                if previous:
                    with factory() as db:
                        terminal=db.get(Node,previous['terminal_node_id']);node=terminal;visited=set()
                        if previous['root_node_id']!=parent or previous['ending_id']!=ending or previous['actions']!=len(path):
                            raise ValueError('saved_path_mismatch')
                        while node and node.id!=parent:
                            if node.id in visited or node.session_id!=item['session_id']: raise ValueError('saved_path_mismatch')
                            visited.add(node.id);node=db.get(Node,node.parent_id)
                        if node is None or len(visited)!=len(path) or terminal.state_snapshot['ending_id']!=ending:
                            raise ValueError('saved_path_mismatch')
                    result={**previous,'reused_saved_path':True,'original_duration_ms':previous.get('original_duration_ms',previous['duration_ms'])}
                else:
                    for normalized in path:
                        with factory() as db:
                            node=db.get(Node,parent);mapping=node.investigation_options;previous=node.state_snapshot['action_turn']
                            key=next(k for k,v in mapping.items() if v==normalized)
                            action={'type':'text','value':_text(story,normalized,mapping,node)} if case['free_text'] else {'type':'option','value':key}
                        submitted=checked(client.post('/turns',headers={**headers,'Idempotency-Key':uuid4().hex},json={'parent_node_id':parent,'action':action}),202)
                        run=poll(client,'/runs/'+submitted['run_id'],headers,65)
                        if run['status']!='completed': raise ValueError(run.get('error_code') or 'turn_failed')
                        parent=run['node_id']
                        with factory() as db:
                            if db.get(Node,parent).state_snapshot['action_turn']!=previous+1: raise ValueError('action_not_accepted')
                    with factory() as db:
                        if db.get(Node,parent).state_snapshot['ending_id']!=ending: raise ValueError('wrong_ending')
                    result.update(ending_id=ending,actions=len(path),free_text=case['free_text'],terminal_node_id=parent)
            result['status']='succeeded'
        except (ValueError,KeyError,StopIteration) as error:
            code=str(error)
            result['error_code']=code if code and len(code)<=80 and code.replace('_','').isalnum() else 'evaluation_error'
        except Exception:
            result['error_code']='evaluation_error'
        result['duration_ms']=round((time.monotonic()-started)*1000,3)
        results.append(result)
        temporary=output/'progress.tmp'
        temporary.write_text(json.dumps({'cases':results},ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(output/'progress.json')
        print(json.dumps({k:result[k] for k in ('id','status','error_code','duration_ms')},ensure_ascii=False),flush=True)
    return results


def verify_server_database(client,url):
    from app.db import testing_database_id
    health=checked(client.get('/health'),200)
    identity=testing_database_id(url)
    if not identity or health.get('testing_database_id')!=identity:
        raise ValueError('server_database_mismatch')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url-env',default='MIGRATION_DATABASE_URL')
    parser.add_argument('--resume-report',help='Reuse approved stories from this runner runtime report; never regenerate them')
    args=parser.parse_args()
    try:
        url=validate_database_url(os.environ.get(args.database_url_env,''))
        manifest=load_manifest()
        os.environ['DATABASE_URL']=url.render_as_string(hide_password=False)
        import httpx
        from app.db import SessionLocal,engine
        from app.models import ExecutionTrace,LLMCall
        from sqlalchemy import select
        from app.costs import budget_status
        if engine.url!=url: raise ValueError('database_mismatch')
        with httpx.Client(base_url='http://127.0.0.1:8000',timeout=30,trust_env=False) as client:
            verify_server_database(client,url)
            settings=checked(client.get('/local-settings'),200)
            if not all(settings['providers'][p]['configured'] for p in ('deepseek','cogview')):
                raise ValueError('keys_not_configured')
            output=ROOT/'runtime/evals'/('stage3-'+uuid4().hex);output.mkdir(parents=True)
            started=datetime.now(timezone.utc);clock=time.monotonic()
            source=read_resume_source(args.resume_report) if args.resume_report else None
            ledger_start=datetime.fromisoformat(source[0].get('ledger_started_at',source[0]['timestamp'])) if source else started
            results=execute_cases(client,manifest['cases'],output,SessionLocal,source)
        with SessionLocal() as db:
            sessions={case['session_id'] for case in results if 'session_id' in case}
            attempts=list(db.scalars(select(ExecutionTrace).where(ExecutionTrace.event_type=='attempt_started',ExecutionTrace.created_at>=ledger_start,ExecutionTrace.session_id.in_(sessions))))
            calls=list(db.scalars(select(LLMCall).where(LLMCall.attempt_id.in_([a.id for a in attempts]))))
            usage=operation_usage_summary(db,calls,attempts)
            for name,value in usage.items():
                ids={a.id for a in attempts if a.payload['operation']==name}
                value['image_count']=sum(c.image_count or 0 for c in calls if c.attempt_id in ids)
                value['models']=sorted({c.model_id for c in calls if c.attempt_id in ids})
                value['price_versions']=sorted({c.price_version for c in calls if c.attempt_id in ids and c.price_version})
            budget=budget_status(db)
        commit=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
        report={'git_commit':commit,'working_tree_dirty':bool(subprocess.run(['git','status','--porcelain'],cwd=ROOT,capture_output=True,text=True,check=True).stdout),'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'metric_version':manifest['metric_version'],'manifest_sha256':hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
            'measurement':'real_model_and_local_images','timestamp':started.isoformat(),'duration_ms':round((time.monotonic()-clock)*1000,3),
            'source_report_sha256':hashlib.sha256(source[1].read_bytes()).hexdigest() if source else None,
            'ledger_started_at':ledger_start.isoformat(),'manual_reviewers':0,'visual_reviewers':0,'summary':summarize(results),'cases':results,'usage':usage,'database_budget':budget}
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({**report['summary'],'report':str(output/'report.json')},ensure_ascii=False))
        return 0 if report['summary']['succeeded']==15 else 1
    except (ValueError,OSError,KeyError):
        print('stage3 evaluation: configuration or manifest rejected')
        return 2


if __name__=='__main__': raise SystemExit(main())
