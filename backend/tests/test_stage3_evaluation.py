import importlib.util
from pathlib import Path


def runner():
    path=Path(__file__).resolve().parents[2]/'evals/run_stage3.py'
    spec=importlib.util.spec_from_file_location('stage3_runner',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_real_manifest_keeps_failures_and_dependencies_in_denominator(tmp_path,capsys):
    module=runner();manifest=module.load_manifest()
    class FailedClient:
        def post(self,*args,**kwargs): raise RuntimeError('PRIVATE_KEY_SENTINEL')
    def unused_factory(): raise AssertionError('DB used after API failure')
    results=module.execute_cases(FailedClient(),manifest['cases'],tmp_path,unused_factory)
    assert len(results)==15 and module.summarize(results)['succeeded']==0
    assert [c['error_code'] for c in results].count('evaluation_error')==3
    assert [c['error_code'] for c in results].count('creation_dependency_failed')==3
    assert [c['error_code'] for c in results].count('preparation_dependency_failed')==9
    assert 'PRIVATE_KEY_SENTINEL' not in capsys.readouterr().out
    assert 'PRIVATE_KEY_SENTINEL' not in (tmp_path/'progress.json').read_text(encoding='utf-8')


def test_runner_rejects_non_test_database_before_connecting(monkeypatch,capsys):
    module=runner()
    monkeypatch.setenv('UNSAFE_STAGE3_DATABASE','postgresql+psycopg://example@localhost/user_stories')
    monkeypatch.setattr(module.sys,'argv',['stage3','--database-url-env','UNSAFE_STAGE3_DATABASE'])
    assert module.main()==2
    assert capsys.readouterr().out.strip()=='stage3 evaluation: configuration or manifest rejected'


def test_server_database_identity_has_no_credentials_and_must_match_before_calls():
    from sqlalchemy.engine import make_url
    from app.db import testing_database_id
    from unittest.mock import patch
    first=make_url('postgresql+psycopg://user:PRIVATE_PASSWORD@127.0.0.1:25439/acceptance_test')
    other=first.set(database='another_test')
    assert testing_database_id(first)==testing_database_id(first.set(username='other',password='other-secret'))
    assert testing_database_id(first)!=testing_database_id(other)
    assert testing_database_id(first.set(database='user_stories')) is None
    module=runner()
    class WrongServer:
        def get(self,path):
            assert path=='/health'
            import httpx
            return httpx.Response(200,json={'ok':True,'testing_database_id':testing_database_id(other)})
    with __import__('pytest').raises(ValueError,match='server_database_mismatch'):
        module.verify_server_database(WrongServer(),first)


def test_resume_refuses_report_outside_ignored_runtime(tmp_path):
    import pytest
    module=runner()
    with pytest.raises(ValueError,match='resume_report_outside_runtime'):
        module.read_resume_source(tmp_path/'report.json')


def test_resume_restores_exact_approved_root_and_credential_without_new_creation(tmp_path):
    import json
    from sqlalchemy import select,func
    from app.models import StoryTask,StoryVersion,Node
    from app.db import SessionLocal
    from test_stage3_image_tasks import approved
    from test_custom_story_creation import client
    module=runner()
    with client() as c: headers,session,root=approved(c)
    with SessionLocal() as db:
        task=db.scalar(select(StoryTask).where(StoryTask.session_id==session['session_id'],StoryTask.status=='approved'))
        version=db.get(StoryVersion,db.get(Node,root['id']).story_version_id)
        count=db.scalar(select(func.count()).select_from(Node))
    previous={'id':'create_modern','status':'succeeded','task_id':task.id,'root_node_id':root['id'],'session_id':session['session_id'],'story_hash':version.content_hash,'duration_ms':321}
    report=tmp_path/'report.json';report.write_text('original failed report')
    (tmp_path/'modern-credential.json').write_text(json.dumps({'token':headers['Authorization'][7:]}))
    (tmp_path/'modern-frozen.json').write_text('frozen original')
    output=tmp_path/'resume';output.mkdir()
    item,result=module.restore_creation({'era':'modern','id':'create_modern'},({'cases':[previous]},report),output,SessionLocal)
    assert item['root']==root['id'] and item['headers']==headers
    assert result['reused_approved_creation'] and result['original_duration_ms']==321
    assert report.read_text()=='original failed report'
    assert (output/'modern-frozen.json').read_text()=='frozen original'
    with SessionLocal() as db: assert db.scalar(select(func.count()).select_from(Node))==count


def test_successful_path_recovery_reads_nodes_without_repeating_actions(tmp_path):
    from unittest.mock import patch
    from sqlalchemy import select
    from app.models import Node,StoryTask
    from app.db import SessionLocal
    from app.story_versions import load_story_version
    from test_custom_story_creation import client
    from test_stage3_image_tasks import approved
    from test_investigation_api import turn
    module=runner()
    with client() as c:
        headers,session,root=approved(c)
        with SessionLocal() as db:
            task=db.scalar(select(StoryTask).where(StoryTask.session_id==session['session_id'],StoryTask.status=='approved'))
            paths=task.checkpoint['proof']['ending_paths'];story=load_story_version(db,db.get(Node,root['id']).story_version_id)
        ending,path=sorted(paths.items())[1];parent=root['id']
        for action in path:
            with SessionLocal() as db:
                mapping=db.get(Node,parent).investigation_options
                key=next(k for k,v in mapping.items() if v==action)
            run=turn(c,headers,parent,{'type':'option','value':key})
            assert run['status']=='completed'
            parent=run['node_id']
    case={'id':'modern_ending_2','kind':'path','era':'modern','index':1,'free_text':False}
    original={'id':case['id'],'status':'succeeded','error_code':None,'root_node_id':root['id'],'terminal_node_id':parent,'session_id':session['session_id'],'actions':len(path),'ending_id':ending,'duration_ms':456}
    item={'headers':headers,'session_id':session['session_id'],'root':root['id'],'story':story,'paths':paths,'ready':True}
    class NoCalls:
        def post(self,*args,**kwargs): raise AssertionError('replay submitted action')
        def get(self,*args,**kwargs): raise AssertionError('replay called API')
    source=({'cases':[original]},tmp_path/'report.json')
    with patch.object(module,'restore_creation',return_value=(item,{'id':'create_modern','status':'succeeded','error_code':None})):
        results=module.execute_cases(NoCalls(),[{'id':'create_modern','kind':'creation','era':'modern'},case],tmp_path,SessionLocal,source)
    assert results[1]['status']=='succeeded' and results[1]['reused_saved_path']
    assert results[1]['original_duration_ms']==456
