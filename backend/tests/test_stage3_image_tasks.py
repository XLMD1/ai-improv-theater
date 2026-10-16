import asyncio
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_custom_story_creation import client, create_session, prepare, successful_provider


def approved(c, *, illustrated=False):
    headers, session = create_session(c)
    if illustrated:
        from app.db import SessionLocal
        from app.models import StorySession
        with SessionLocal.begin() as db:
            db.get(StorySession,session['session_id']).requires_assets=True
    with patch('app.story_operations.call_operation_provider',side_effect=successful_provider):
        task=prepare(c,headers)
    assert task['status']=='awaiting_confirmation',task['error_code']
    root=c.post(f"/story-tasks/{task['id']}/confirm",headers=headers,json={
        'candidate_version_id':task['candidate_version_id'],'content_hash':task['content_hash']}).json()['root']
    return headers, session, root


def test_illustrated_session_cannot_turn_before_preparation_but_legacy_can():
    with client() as c:
        headers, _, root=approved(c,illustrated=True)
        response=c.post('/turns',headers={**headers,'Idempotency-Key':uuid4().hex},json={
            'parent_node_id':root['id'],'action':{'type':'option','value':root['rendered_scene']['options'][0]['id']}})
        assert response.status_code == 409 and response.json()['detail']=='images_not_ready'


def test_client_generated_session_credential_recovers_a_lost_create_response():
    with client() as c:
        create_session(c)
        body={'provider':'deepseek','flow':'illustrated-3','client_token':'fixture-client-credential-'+uuid4().hex}
        first=c.post('/story-sessions',json=body); second=c.post('/story-sessions',json=body)
        assert first.status_code==201 and first.json()['session_id']==second.json()['session_id']
        assert first.json()['token']==body['client_token']
        assert c.get('/session',headers={'Authorization':'Bearer '+body['client_token']}).json()['requires_assets']


def test_player_can_decline_only_an_unapproved_candidate_before_editing_background():
    with client() as c:
        headers,_=create_session(c)
        with patch('app.story_operations.call_operation_provider',side_effect=successful_provider): task=prepare(c,headers)
        result=c.post('/story-tasks/'+task['id']+'/reject',headers=headers)
        assert result.status_code==200
        assert c.get('/story-tasks/'+task['id'],headers=headers).json()['status']=='declined'
        assert c.get('/tree',headers=headers).json()==[]
        with patch('app.story_operations.call_operation_provider',side_effect=successful_provider): next_task=prepare(c,headers)
        root=c.post('/story-tasks/'+next_task['id']+'/confirm',headers=headers,json={
            'candidate_version_id':next_task['candidate_version_id'],'content_hash':next_task['content_hash']})
        assert root.status_code==200
        assert c.post('/story-tasks/'+next_task['id']+'/reject',headers=headers).status_code==409


@pytest.mark.asyncio
async def test_image_resume_only_downloads_checkpoint_and_keeps_completed_slots(tmp_path):
    from app.image_tasks import create_image_task, process_image_task, resume_image_task
    from app.image_operations import ImageFile
    from app.provider_clients import ProviderOutcome
    from app.db import SessionLocal
    from app.models import ImageTask,StoryAsset
    with client() as c:
        _, session, _=approved(c)
    task,created=create_image_task(session['session_id'],'start-key')
    duplicate,again=create_image_task(session['session_id'],'start-key')
    assert created and not again and duplicate.id==task.id
    generated=[]; downloaded=[]
    async def generate(value,key,timeout):
        generated.append(value.prompt)
        return ProviderOutcome(text='{"url":"https://aigc-files.bigmodel.cn/result.png"}',request_sent=True,image_count=1)
    async def download(value,context):
        downloaded.append(value.asset_id)
        if len(downloaded)==2:
            return ProviderOutcome(error_code='download_rejected',request_sent=True,chargeable=False)
        path=f'{value.story_version_id}/{value.asset_id}.png'
        target=tmp_path/path; target.parent.mkdir(exist_ok=True); target.write_bytes(b'saved-fixture')
        import hashlib
        return ProviderOutcome(text=ImageFile(path=path,sha256=hashlib.sha256(b'saved-fixture').hexdigest(),width=int(value.size.split('x')[0]),height=int(value.size.split('x')[1])).model_dump_json(),request_sent=True,chargeable=False)
    with patch('app.image_operations.call_image_provider',side_effect=generate),patch('app.image_operations.download_image',side_effect=download),patch('app.image_tasks.asset_root',return_value=tmp_path):
        await process_image_task(task.id)
        with SessionLocal() as db:
            assert db.get(ImageTask,task.id).status=='failed'
            slots=list(db.scalars(select(StoryAsset).where(StoryAsset.task_id==task.id)))
            assert sum(a.status=='ready' for a in slots)==1
        resumed,started=resume_image_task(session['session_id'],task.id,'resume-key')
        assert started and resumed.id==task.id
        await process_image_task(task.id)
        with SessionLocal() as db:
            assert db.get(ImageTask,task.id).status=='ready'
        assert len(generated)==8
        assert len(downloaded)==9 and downloaded[0] not in downloaded[1:]


def test_image_tasks_are_authenticated_and_never_leak_private_prompt_or_url():
    from app.image_tasks import create_image_task
    with client() as c:
        headers, session, _=approved(c)
        other,_,_=approved(c)
        task,_=create_image_task(session['session_id'],'owned-key')
        response=c.get('/image-tasks/'+task.id,headers=headers)
        assert response.status_code==200
        data=response.json()
        assert data['total']==8 and 'prompt' not in response.text and 'download_url' not in response.text
        assert c.get('/image-tasks/'+task.id,headers=other).status_code==404
        assert c.get('/image-tasks/'+task.id).status_code==401


@pytest.mark.asyncio
async def test_unknown_image_requires_billing_receipt_and_explicit_missing_output_confirmation():
    from app.image_tasks import create_image_task,process_image_task,resume_image_task,ImageTaskError
    from app.provider_clients import ProviderOutcome
    from app.models import LLMCall
    from app.db import SessionLocal
    from app.execution_traces import TraceRecorder,TaskRef
    with client() as c:
        _,session,_=approved(c)
    task,_=create_image_task(session['session_id'],'uncertain-start')
    async def unknown(*args): return ProviderOutcome(error_code='outcome_unknown',request_sent=True)
    with patch('app.image_operations.call_image_provider',side_effect=unknown):
        await process_image_task(task.id)
    with pytest.raises(ImageTaskError,match='image_outcome_unconfirmed'):
        resume_image_task(session['session_id'],task.id,'retry')
    with SessionLocal() as db:
        call=db.scalar(select(LLMCall).where(LLMCall.image_task_id==task.id))
    TraceRecorder(SessionLocal).reconcile_usage(TaskRef('image',task.id,session['session_id']),{
        'schema_version':'usage-reconciliation-1','call_id':call.id,'source':'user_reported_provider_console',
        'actual_cost_cny':__import__('decimal').Decimal(0),'total_tokens':0})
    with pytest.raises(ImageTaskError,match='image_outcome_unconfirmed'):
        resume_image_task(session['session_id'],task.id,'retry')
    _,started=resume_image_task(session['session_id'],task.id,'confirmed-retry',confirm_missing_output=True)
    assert started


@pytest.mark.asyncio
@pytest.mark.parametrize("saved_status",["uncertain","failed"])
async def test_paid_result_checkpoint_failure_recovers_url_without_generation(saved_status):
    from app.image_tasks import create_image_task,process_image_task,resume_image_task,_asset_update
    from app.provider_clients import ProviderOutcome
    from app.db import SessionLocal
    from app.models import StoryAsset
    with client() as c:
        _,session,_=approved(c)
    task,_=create_image_task(session['session_id'],'checkpoint-start')
    def fail_checkpoint(asset_id,**values):
        if 'download_url' in values: raise RuntimeError('checkpoint unavailable')
        return _asset_update(asset_id,**values)
    async def generate(*args):
        return ProviderOutcome(text='{"url":"https://aigc-files.bigmodel.cn/checkpoint.png"}',request_sent=True,image_count=1)
    with patch('app.image_operations.call_image_provider',side_effect=generate),patch('app.image_tasks._asset_update',side_effect=fail_checkpoint):
        await process_image_task(task.id)
    with SessionLocal.begin() as db:
        for asset in db.scalars(select(StoryAsset).where(StoryAsset.task_id==task.id,StoryAsset.status=='uncertain')):
            asset.status=saved_status
    resumed,started=resume_image_task(session['session_id'],task.id,'recover-checkpoint')
    assert started
    with SessionLocal() as db:
        slot=db.scalar(select(StoryAsset).where(StoryAsset.task_id==task.id,StoryAsset.download_url.is_not(None)))
        assert slot is not None and slot.status=='download_pending'
        assert slot.download_url=='https://aigc-files.bigmodel.cn/checkpoint.png'


def test_each_image_prompt_has_only_its_target_card_and_backgrounds_have_no_cast():
    from app.db import SessionLocal
    from app.models import StoryAsset
    from app.image_tasks import create_image_task
    from app.story_versions import load_story_version
    with client() as c: _,session,_=approved(c)
    task,_=create_image_task(session['session_id'],'isolated-prompt')
    with SessionLocal() as db:
        story=load_story_version(db,task.story_version_id)
        for asset in db.scalars(select(StoryAsset).where(StoryAsset.task_id==task.id)):
            assert asset.prompt_version=='cinematic-public-3'
            assert '人物外貌统一参考' not in asset.prompt
            if asset.kind=='background':
                assert '不画任何人物' in asset.prompt
                for person in story.characters: assert f'{person.name}：{person.appearance}' not in asset.prompt
            else:
                target=next(c for c in story.characters if c.id==asset.entity_id)
                assert target.appearance in asset.prompt
                assert '只画这一位人物' in asset.prompt
                for person in story.characters:
                    if person.id!=target.id: assert f'{person.name}：{person.appearance}' not in asset.prompt
