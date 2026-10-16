"""Preparation is independent of immutable story state and approved scenes."""
import asyncio
import hashlib
import time
from sqlalchemy import select
from app.db import SessionLocal
from app.execution import ExecutionContext, ToolFailure, ToolRegistry, execute
from app.execution_traces import TaskRef, TraceRecorder
from app.image_operations import IMAGE_PROMPT_VERSION, asset_root, register_image_operations
from app.local_settings import get_key
from app.models import ExecutionTrace, ImageTask, LLMCall, StoryAsset, StorySession, StoryVersion
from app.story_versions import load_story_version


class ImageTaskError(ValueError):
    pass


def owned_image_task(db,session_id,task_id,*,lock=False):
    query=select(ImageTask).where(ImageTask.id==task_id,ImageTask.session_id==session_id)
    task=db.scalar(query.with_for_update() if lock else query)
    if task is None:
        raise ImageTaskError('image_task_not_found')
    return task


def asset_available(asset):
    if asset.status!='ready' or not asset.file_path or not asset.sha256:
        return False
    path=(asset_root()/asset.file_path).resolve()
    return path.is_relative_to(asset_root().resolve()) and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==asset.sha256


def assets_ready(db,session):
    query=select(StoryAsset).where(StoryAsset.story_version_id==session.story_version_id)
    if not (session.mode or '').startswith('sample:'):
        query=query.join(ImageTask,StoryAsset.task_id==ImageTask.id).where(ImageTask.session_id==session.id)
    slots=list(db.scalars(query))
    return len(slots)==8 and all(asset_available(asset) for asset in slots)


def create_image_task(session_id,key):
    if not 1<=len(key)<=80:
        raise ImageTaskError('invalid_idempotency_key')
    with SessionLocal.begin() as db:
        session=db.scalar(select(StorySession).where(StorySession.id==session_id).with_for_update())
        if session is not None and (session.mode or '').startswith('sample:'):
            raise ImageTaskError('local_sample_assets_fixed')
        if session is None or not session.story_version_id:
            raise ImageTaskError('story_not_ready')
        version=db.get(StoryVersion,session.story_version_id)
        if version.approval_status!='approved':
            raise ImageTaskError('story_not_ready')
        old=db.scalar(select(ImageTask).where(ImageTask.session_id==session_id,ImageTask.story_version_id==version.id))
        if old:
            if old.idempotency_key!=key:
                raise ImageTaskError('image_task_exists')
            db.expunge(old)
            return old,False
        story=load_story_version(db,version.id)
        task=ImageTask(session_id=session_id,story_version_id=version.id,idempotency_key=key)
        db.add(task); db.flush()
        era={'ancient':'中国古代','modern':'近现代工业文明','future':'未来科技文明'}[story.era]
        style=f'电影叙事概念美术，写实绘画，细腻光影，冷青与暖金统一色调。年代：{era}。无边框电影画面，真实人体比例与皮肤质感。不要生成文字、书法、题字、印章、卷轴、画框、界面、字幕或调查线索，不揭示秘密。'
        for kind,entities,size in [('background',story.locations,'1344x768'),('portrait',story.characters,'768x1344')]:
            for entity in entities:
                if kind=='background':
                    subject=f'空的环境全景，只绘制建筑、自然环境与陈设，不画任何人物、身体、脸、剪影或人像。故事背景：{story.setting}。地点：{entity.name}。以下只取环境信息，提到的人物不得画出：{entity.description}。依据描述准确区分室内与室外，不擅自改成建筑外观；只绘制这一处地点，不拼接多个场景。再次强调空场景，没有人物、路人或远处人影。'
                else:
                    subject=f'单人竖版全身肖像，只画这一位人物：{entity.name}。唯一目标外貌卡：{entity.appearance}。严格符合外貌卡的年龄、性别、肤色、发型与服饰，不额外衰老或幼化。人物站立，头顶至鞋底完整入画并留少量空间，不截断头脚，不使用半身或特写。服饰与配件逐项符合指定年代及外貌卡。干净的单色氛围背景，禁止第二个人、重复身体、合影、拼图、分屏或镜中人像；禁止题字和印章。'
                db.add(StoryAsset(task_id=task.id,story_version_id=version.id,kind=kind,entity_id=entity.id,
                    prompt=style+subject,prompt_version=IMAGE_PROMPT_VERSION,model_id='cogview-4',size=size))
        db.expunge(task)
        return task,True


def uncertain_call(db,asset):
    return db.scalar(select(LLMCall).join(ExecutionTrace,LLMCall.attempt_id==ExecutionTrace.id).where(
        LLMCall.image_task_id==asset.task_id,ExecutionTrace.payload['input']['asset_id'].as_string()==asset.id)
        .order_by(LLMCall.created_at.desc()).limit(1))


def uncertainty_reconciled(db,asset):
    from app.usage_reconciliation import reconciled_usage
    call=uncertain_call(db,asset)
    return bool(call and call.id in reconciled_usage(db))


def saved_generation_url(db,asset):
    from app.image_operations import ImageProposal
    call=uncertain_call(db,asset)
    if call is None or call.usage_status!='known' or call.call_status!='completed': return None
    attempt=db.get(ExecutionTrace,call.attempt_id)
    finished=db.scalar(select(ExecutionTrace).where(ExecutionTrace.trace_id==attempt.trace_id,
        ExecutionTrace.span_id==attempt.span_id,ExecutionTrace.event_type=='attempt_finished'))
    if finished is None or finished.error_code: return None
    try: return ImageProposal.model_validate_json(finished.payload['text']).url
    except (ValueError,KeyError,TypeError): return None


def resume_image_task(session_id,task_id,key,*,confirm_missing_output=False):
    if not 1<=len(key)<=80:
        raise ImageTaskError('invalid_idempotency_key')
    with SessionLocal.begin() as db:
        task=owned_image_task(db,session_id,task_id,lock=True)
        if key in task.recovery_keys or task.status in ('queued','running'):
            db.expunge(task); return task,False
        slots=list(db.scalars(select(StoryAsset).where(StoryAsset.task_id==task_id)))
        for asset in slots:
            if asset.status in ('failed','uncertain') and not asset.download_url:
                saved_url=saved_generation_url(db,asset)
                if saved_url:
                    asset.download_url=saved_url
                    asset.status='download_pending'
                    asset.error_code=None
                    continue
            if asset.status=='uncertain':
                if not confirm_missing_output or not uncertainty_reconciled(db,asset):
                    raise ImageTaskError('image_outcome_unconfirmed')
                asset.status='pending'
                asset.error_code=None
        if all(asset_available(a) for a in slots):
            task.status='ready'; db.flush(); db.expunge(task); return task,False
        for asset in slots:
            if not asset_available(asset):
                asset.status='download_pending' if asset.download_url else 'pending'
                asset.error_code=None
        task.status='queued'; task.error_code=None
        task.recovery_keys=[*task.recovery_keys,key]
        db.flush()
        db.expunge(task)
        return task,True


def _asset_update(asset_id,**values):
    with SessionLocal.begin() as db:
        row=db.get(StoryAsset,asset_id)
        for key,value in values.items(): setattr(row,key,value)


async def process_image_task(task_id):
    with SessionLocal.begin() as db:
        task=db.scalar(select(ImageTask).where(ImageTask.id==task_id).with_for_update())
        if task is None or task.status!='queued': return
        task.status='running'
        session=db.get(StorySession,task.session_id)
        context=ExecutionContext(TaskRef('image',task.id,task.session_id),time.monotonic()+1200,'cogview','cogview-4',
            TraceRecorder(SessionLocal,secrets=[get_key('cogview')],token_hashes=[session.token_hash]))
        slots=list(db.scalars(select(StoryAsset).where(StoryAsset.task_id==task_id).order_by(StoryAsset.kind,StoryAsset.entity_id)))
    registry=ToolRegistry(); register_image_operations(registry)
    active=None
    try:
        for asset in slots:
            active=asset
            if asset_available(asset): continue
            context.recorder.event(context.task,'asset_started',{'asset_id':asset.id,'kind':asset.kind,'entity_id':asset.entity_id})
            if not asset.download_url:
                _asset_update(asset.id,status='generating')
                result=await execute(registry,'image.generate','v1',{'prompt':asset.prompt,'size':asset.size,'asset_id':asset.id},context)
                if isinstance(result,ToolFailure):
                    unknown=result.error_code in ('outcome_unknown','internal_error','storage_failure','cancelled')
                    _asset_update(asset.id,status='uncertain' if unknown else 'failed',error_code=result.error_code)
                    raise ImageTaskError(result.error_code)
                asset.download_url=result.output.url
                _asset_update(asset.id,download_url=asset.download_url,status='download_pending')
            result=await execute(registry,'image.download','v1',{'url':asset.download_url,'asset_id':asset.id,
                'story_version_id':asset.story_version_id,'size':asset.size,'expected_sha256':asset.sha256},context)
            if isinstance(result,ToolFailure):
                _asset_update(asset.id,status='download_pending',error_code=result.error_code)
                raise ImageTaskError(result.error_code)
            _asset_update(asset.id,status='ready',file_path=result.output.path,sha256=result.output.sha256,error_code=None)
            context.recorder.event(context.task,'asset_ready',{'asset_id':asset.id,'sha256':result.output.sha256})
        with SessionLocal.begin() as db:
            task=db.get(ImageTask,task_id)
            if task.status!='running': raise ImageTaskError('task_no_longer_running')
            task.status='ready'; task.error_code=None
    except (Exception,asyncio.CancelledError) as error:
        if active:
            with SessionLocal.begin() as db:
                asset=db.get(StoryAsset,active.id)
                if asset.status=='generating':
                    asset.status='uncertain'; asset.error_code='outcome_unknown'
        with SessionLocal.begin() as db:
            task=db.get(ImageTask,task_id)
            task.status='interrupted' if isinstance(error,asyncio.CancelledError) else 'failed'
            task.error_code=str(error) if isinstance(error,ImageTaskError) else 'image_task_failed'
        if isinstance(error,asyncio.CancelledError): raise


def interrupt_image_tasks():
    with SessionLocal.begin() as db:
        for task in db.scalars(select(ImageTask).where(ImageTask.status.in_(['queued','running']))):
            task.status='interrupted'; task.error_code='process_restarted'
            for asset in db.scalars(select(StoryAsset).where(StoryAsset.task_id==task.id,StoryAsset.status=='generating')):
                asset.status='uncertain'; asset.error_code='outcome_unknown'
