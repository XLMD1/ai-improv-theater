import hashlib
import json
from unittest.mock import patch
from uuid import uuid4
from sqlalchemy import select, func
from test_stage3_image_tasks import approved
from test_custom_story_creation import client


def publish(c, tmp_path, monkeypatch):
    from app.db import SessionLocal
    from app.image_tasks import create_image_task
    from app.models import StoryAsset, ImageTask
    headers, session, root = approved(c)
    task, _ = create_image_task(session['session_id'], 'fixture-images')
    with SessionLocal.begin() as db:
        for asset in db.scalars(select(StoryAsset).where(StoryAsset.task_id == task.id)):
            path = tmp_path / (asset.id + '.png')
            path.write_bytes(b'fixture')
            asset.file_path = path.name
            asset.sha256 = hashlib.sha256(b'fixture').hexdigest()
            asset.status = 'ready'
        db.get(ImageTask, task.id).status = 'ready'
    catalog = tmp_path / 'local-samples.json'
    catalog.write_text(json.dumps({'version':1, 'samples':[{'id':'modern', 'story_version_id':task.story_version_id}]}))
    monkeypatch.setattr('app.local_samples.catalog_path', lambda:catalog)
    monkeypatch.setattr('app.image_tasks.asset_root', lambda:tmp_path)
    monkeypatch.setattr('app.image_api.asset_root', lambda:tmp_path)
    c.delete('/local-settings/keys/deepseek')
    c.delete('/local-settings/keys/cogview')
    return task, root, headers


def test_sample_opens_without_keys_with_independent_nodes_shared_assets_and_no_calls(tmp_path, monkeypatch):
    from app.db import SessionLocal
    from app.models import LLMCall
    with client() as c:
        task, original_root, original_headers = publish(c, tmp_path, monkeypatch)
        with SessionLocal() as db: calls = db.scalar(select(func.count()).select_from(LLMCall))
        with patch('app.story_operations.call_operation_provider', side_effect=AssertionError('external text call')), patch('app.image_operations.call_image_provider', side_effect=AssertionError('external image call')):
            listed = c.get('/local-samples')
            assert listed.status_code == 200, listed.text
            assert len(listed.json()['samples']) == 1
            assert not any(value in listed.text for value in ('truth','secret','token','story_version_id','prompt','download_url'))
            token = 'local-sample-client-' + uuid4().hex
            body = {'sample_id':'modern','client_token':token}
            opened = c.post('/local-samples/sessions', json=body)
            assert opened.status_code == 201, opened.text
            data = opened.json()
            assert c.post('/local-samples/sessions', json=body).json()['root'] == data['root']
            assert data['root']['id'] != original_root['id']
            auth = {'Authorization':'Bearer '+token}
            assert c.get('/session',headers=auth).json()['root_node_id'] == data['root']['id']
            manifest = c.get('/session/assets',headers=auth).json()
            assert manifest['ready'] and len(manifest['backgrounds']) == 5 and len(manifest['portraits']) == 3
            asset_id = next(iter(manifest['backgrounds'].values()))
            assert c.get('/assets/'+asset_id,headers=auth).status_code == 200
            assert c.get('/nodes/'+original_root['id'],headers=auth).status_code == 404
            from test_investigation_api import turn
            root = data['root']
            run = turn(c,auth,root['id'],{'type':'option','value':root['rendered_scene']['options'][0]['id']})
            assert run['status'] == 'completed', run
            node = c.get('/nodes/'+run['node_id'],headers=auth).json()
            assert c.get('/nodes/'+run['node_id'],headers=auth).json() == node
            assert c.get('/nodes/'+original_root['id'],headers=original_headers).json() == original_root
            assert c.post('/image-tasks',headers={**auth,'Idempotency-Key':'forbidden'}).status_code == 409
            assert c.post('/turns',headers={**auth,'Idempotency-Key':'text'},json={'parent_node_id':node['id'],'action':{'type':'text','value':'调查'}}).json()['detail'] == 'key_not_configured'
        with SessionLocal() as db: assert db.scalar(select(func.count()).select_from(LLMCall)) == calls


def test_missing_assets_cannot_be_opened_and_other_versions_stay_private(tmp_path, monkeypatch):
    with client() as c:
        task, _, _ = publish(c, tmp_path, monkeypatch)
        other_headers, _, _ = approved(c)
        from app.db import SessionLocal
        from app.models import StoryAsset
        with SessionLocal() as db:
            asset = db.scalar(select(StoryAsset).where(StoryAsset.task_id==task.id)); asset_id=asset.id; file_path=asset.file_path
        assert c.get('/assets/'+asset_id,headers=other_headers).status_code == 404
        (tmp_path/file_path).write_bytes(b'corrupt')
        assert c.get('/local-samples').json()['samples'] == []
        for sample_id in ('modern','ancient'):
            assert c.post('/local-samples/sessions',json={'sample_id':sample_id,'client_token':'unpublished-client-'+uuid4().hex}).status_code == 404


def test_sample_client_token_is_strict_and_catalog_absence_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr('app.local_samples.catalog_path',lambda:tmp_path/'absent.json')
    with client() as c:
        assert c.get('/local-samples').json() == {'samples':[]}
        assert c.post('/local-samples/sessions',json={'sample_id':'modern','client_token':'short'}).status_code == 422


def test_all_three_button_endings_are_reachable_without_keys_or_provider_calls(tmp_path, monkeypatch):
    from app.db import SessionLocal
    from app.models import Node, LLMCall
    from app.story_versions import load_story_version
    from app.story_validation import check_reachability
    from test_investigation_api import turn
    with client() as c:
        task, _, _ = publish(c,tmp_path,monkeypatch)
        with SessionLocal() as db:
            paths=check_reachability(load_story_version(db,task.story_version_id)).ending_paths
            count=db.scalar(select(func.count()).select_from(LLMCall))
        with patch('app.story_operations.call_operation_provider',side_effect=AssertionError('external call')):
            token='paths-client-'+uuid4().hex
            data=c.post('/local-samples/sessions',json={'sample_id':'modern','client_token':token}).json()
            headers={'Authorization':'Bearer '+token}
            root=data['root']['id']
            assert len(paths)==3
            for ending,path in paths.items():
                parent=root
                for action in path:
                    with SessionLocal() as db:
                        mapping=db.get(Node,parent).investigation_options
                    option=next(key for key,value in mapping.items() if value==action)
                    run=turn(c,headers,parent,{'type':'option','value':option})
                    assert run['status']=='completed',run
                    parent=run['node_id']
                node=c.get('/nodes/'+parent,headers=headers).json()
                assert node['state_snapshot']['ending_id']==ending
                assert c.get('/nodes/'+parent,headers=headers).json()==node
            with SessionLocal() as db: assert db.scalar(select(func.count()).select_from(LLMCall))==count


def test_existing_sample_recovers_after_catalog_is_withdrawn_and_rejects_other_sample_id(tmp_path,monkeypatch):
    with client() as c:
        publish(c,tmp_path,monkeypatch)
        body={'sample_id':'modern','client_token':'withdrawn-client-'+uuid4().hex}
        first=c.post('/local-samples/sessions',json=body)
        assert first.status_code==201
        (tmp_path/'local-samples.json').write_text('{"version":1,"samples":[]}')
        recovered=c.post('/local-samples/sessions',json=body)
        assert recovered.status_code==201 and recovered.json()==first.json()
        assert c.post('/local-samples/sessions',json={**body,'sample_id':'ancient'}).status_code==409
