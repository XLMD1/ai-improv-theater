import asyncio
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from app.image_operations import asset_root
from app.image_tasks import (ImageTaskError,asset_available,create_image_task,owned_image_task,
                             process_image_task,resume_image_task,saved_generation_url,uncertainty_reconciled)
from app.models import ImageTask, StoryAsset
from app.story_schema import StrictModel
from app.story_versions import load_story_version


class ImageResumeRequest(StrictModel):
    confirm_missing_output: bool = False


def dispatch_images(task_id):
    from app.jobs import active_tasks
    task=asyncio.create_task(process_image_task(task_id))
    active_tasks.add(task); task.add_done_callback(active_tasks.discard)


def _error(error):
    code=str(error)
    raise HTTPException(status_code=404 if code.endswith('_not_found') else 409,detail=code) from error


def create_image_router(current_session,db_session):
    router=APIRouter()
    @router.post('/image-tasks',status_code=202)
    async def create(key: str=Header(alias='Idempotency-Key'),session=Depends(current_session)):
        try:
            task,new=create_image_task(session.id,key)
            if new: dispatch_images(task.id)
            return {'task_id':task.id,'status':task.status}
        except ImageTaskError as error: _error(error)

    @router.get('/image-tasks/{task_id}')
    def progress(task_id: str,session=Depends(current_session),db=Depends(db_session)):
        try: task=owned_image_task(db,session.id,task_id)
        except ImageTaskError as error: _error(error)
        slots=list(db.scalars(select(StoryAsset).where(StoryAsset.task_id==task_id)))
        story=load_story_version(db,task.story_version_id)
        names={item.id:item.name for item in [*story.locations,*story.characters]}
        items=[{'id':a.id,'kind':a.kind,'entity_id':a.entity_id,'name':names[a.entity_id],'status':a.status,'error_code':a.error_code,
                'available':asset_available(a)} for a in slots]
        return {'id':task.id,'status':task.status,'error_code':task.error_code,'total':len(items),
            'completed':sum(a['available'] for a in items),'assets':items,
            'needs_generation':any(not asset_available(a) and not a.download_url and not saved_generation_url(db,a) for a in slots),
            'requires_missing_output_confirmation':any(a.status=='uncertain' and not saved_generation_url(db,a) for a in slots),
            'recoverable':task.status in ('failed','interrupted','ready') and all(
                a.status!='uncertain' or saved_generation_url(db,a) or uncertainty_reconciled(db,a) for a in slots)}

    @router.post('/image-tasks/{task_id}/resume',status_code=202)
    async def resume(task_id: str,request: ImageResumeRequest | None=None,key: str=Header(alias='Idempotency-Key'),session=Depends(current_session)):
        try:
            task,new=resume_image_task(session.id,task_id,key,confirm_missing_output=bool(request and request.confirm_missing_output))
            if new: dispatch_images(task.id)
            return {'task_id':task.id,'status':task.status}
        except ImageTaskError as error: _error(error)

    @router.get('/session/assets')
    def manifest(session=Depends(current_session),db=Depends(db_session)):
        if (session.mode or '').startswith('sample:'):
            slots=list(db.scalars(select(StoryAsset).where(StoryAsset.story_version_id==session.story_version_id)))
            return {'task_id':None,'ready':len(slots)==8 and all(asset_available(a) for a in slots),
                'backgrounds':{a.entity_id:a.id for a in slots if a.kind=='background' and asset_available(a)},
                'portraits':{a.entity_id:a.id for a in slots if a.kind=='portrait' and asset_available(a)}}
        task=db.scalar(select(ImageTask).where(ImageTask.session_id==session.id,ImageTask.story_version_id==session.story_version_id))
        if task is None: return {'task_id':None,'ready':False,'backgrounds':{},'portraits':{}}
        slots=list(db.scalars(select(StoryAsset).where(StoryAsset.task_id==task.id)))
        return {'task_id':task.id,'ready':len(slots)==8 and all(asset_available(a) for a in slots),
            'backgrounds':{a.entity_id:a.id for a in slots if a.kind=='background' and asset_available(a)},
            'portraits':{a.entity_id:a.id for a in slots if a.kind=='portrait' and asset_available(a)}}

    @router.get('/assets/{asset_id}')
    def image(asset_id: str,session=Depends(current_session),db=Depends(db_session)):
        query=select(StoryAsset).where(StoryAsset.id==asset_id)
        if (session.mode or '').startswith('sample:'):
            query=query.where(StoryAsset.story_version_id==session.story_version_id)
        else:
            query=query.join(ImageTask,StoryAsset.task_id==ImageTask.id).where(ImageTask.session_id==session.id)
        asset=db.scalar(query)
        if asset is None or not asset_available(asset): raise HTTPException(404,detail='asset_not_found')
        return FileResponse(asset_root()/asset.file_path,media_type='image/png',headers={'Cache-Control':'private, max-age=86400','Vary':'Authorization'})
    return router
