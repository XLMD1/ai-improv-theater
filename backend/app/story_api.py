"""Authenticated creation progress and publicly known investigation data."""
import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.db import SessionLocal
from app.execution_traces import TraceStorageFailure
from app.investigation import public_projection
from app.local_settings import MODELS
from app.models import Node, StoryTask, StoryTaskEvent, StoryVersion
from app.story_creation import (CreationError, CreationRequest, ConfirmationRequest, confirm_creation,
    create_creation_task, create_custom_session, owned_task, process_creation_task, public_creation_root, resume_creation)
from app.story_schema import StrictModel
from app.story_versions import load_story_version


class CustomSessionRequest(StrictModel):
    provider: Literal['deepseek'] = 'deepseek'
    model_id: str | None = None


def _http(error):
    if isinstance(error,TraceStorageFailure):
        raise HTTPException(status_code=503,detail='storage_failure') from error
    code = str(error)
    raise HTTPException(status_code=404 if code.endswith('_not_found') else 409,detail=code) from error


def dispatch_creation(task_id):
    from app.jobs import active_tasks
    task = asyncio.create_task(process_creation_task(task_id))
    active_tasks.add(task)
    task.add_done_callback(active_tasks.discard)


def create_router(current_session,db_session):
    router = APIRouter()

    @router.post('/story-sessions',status_code=201)
    def new_session(request: CustomSessionRequest):
        try:
            token,session = create_custom_session(request.provider,request.model_id or MODELS['deepseek'])
            return {'token':token,'session_id':session.id,'provider':session.provider,'model_id':session.model_id,
                    'engine_version':session.engine_version,'mode':session.mode}
        except CreationError as error:
            _http(error)

    @router.post('/story-tasks',status_code=202)
    async def new_task(request: CreationRequest,key: str = Header(alias='Idempotency-Key'),session=Depends(current_session)):
        try:
            task,created = create_creation_task(session.id,request,key)
            if created:
                dispatch_creation(task.id)
            return {'task_id':task.id,'status':task.status}
        except CreationError as error:
            _http(error)

    @router.get('/story-tasks/{task_id}')
    def get_task(task_id: str,session=Depends(current_session),db=Depends(db_session)):
        try:
            task = owned_task(db,session.id,task_id)
            result = {'id':task.id,'status':task.status,'stage':task.stage,'error_code':task.error_code,
                      'recoverable':task.status in ('failed','interrupted') and not (task.repair_count and not task.checkpoint.get('repair_done'))}
            if task.status in ('awaiting_confirmation','approved'):
                row = db.get(StoryVersion,task.candidate_version_id)
                story = load_story_version(db,row.id)
                protagonist = next(c for c in story.characters if c.id == story.protagonist_id)
                location = next(l for l in story.locations if l.id == story.start_location_id)
                result.update(candidate_version_id=row.id,content_hash=row.content_hash,
                              title=story.title,setting=story.setting,era=story.era,public_intro=story.public_intro,
                              protagonist={'name':protagonist.name,'appearance':protagonist.appearance},
                              location={'name':location.name,'description':location.description})
            return result
        except CreationError as error:
            _http(error)

    @router.post('/story-tasks/{task_id}/confirm')
    def confirm(task_id: str,request: ConfirmationRequest,session=Depends(current_session)):
        try:
            return {'root':public_creation_root(confirm_creation(session.id,task_id,request))}
        except (CreationError,TraceStorageFailure) as error:
            _http(error)

    @router.post('/story-tasks/{task_id}/resume',status_code=202)
    async def resume(task_id: str,key: str = Header(alias='Idempotency-Key'),session=Depends(current_session)):
        try:
            task,created = resume_creation(session.id,task_id,key)
            if created:
                dispatch_creation(task.id)
            return {'task_id':task.id,'status':task.status,'source_task_id':task.source_task_id}
        except CreationError as error:
            _http(error)

    @router.get('/story-tasks/{task_id}/events')
    async def events(task_id: str,after: int = Query(default=0,ge=0),session=Depends(current_session),db=Depends(db_session)):
        try:
            owned_task(db,session.id,task_id)
        except CreationError as error:
            _http(error)
        async def stream():
            cursor = after
            while True:
                with SessionLocal() as reader:
                    rows = reader.scalars(select(StoryTaskEvent).where(StoryTaskEvent.task_id == task_id,
                                           StoryTaskEvent.seq > cursor).order_by(StoryTaskEvent.seq).limit(50)).all()
                    status = reader.get(StoryTask,task_id).status
                    for row in rows:
                        cursor = row.seq
                        yield f'id: {row.seq}\nevent: {row.event}\ndata: {json.dumps(row.payload,ensure_ascii=False)}\n\n'
                if status not in ('queued','running') and not rows:
                    break
                yield ': heartbeat\n\n'
                await asyncio.sleep(.4)
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache'})

    @router.get('/session/world')
    def world(node_id: str,session=Depends(current_session),db=Depends(db_session)):
        node = db.get(Node,node_id)
        if node is None or node.session_id != session.id or node.story_version_id is None:
            raise HTTPException(status_code=404,detail='node_not_found')
        return public_projection(load_story_version(db,node.story_version_id),node.state_snapshot)

    return router
