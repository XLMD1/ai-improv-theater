"""Recoverable creation checkpoints and explicit immutable story approval."""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import time
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field, StringConstraints, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.db import SessionLocal
from app.execution import ExecutionContext, ToolFailure, ToolRegistry, execute
from app.execution_traces import TaskRef, TraceRecorder, TraceStorageFailure
from app.investigation import initial_investigation_state
from app.investigation_generation import build_public_options
from app.local_settings import MODELS, configured, get_key
from app.models import Node, StorySession, StoryTask, StoryTaskEvent, StoryVersion, TurnEvent
from app.operation_schemas import validate_semantic_report
from app.reachability_worker import validate_reachability
from app.story_operations import PROMPT_VERSION, OPERATION_VERSIONS, register_story_operations
from app.story_schema import Story, StrictModel
from app.story_versions import load_story_version, save_story_version


class CreationError(ValueError):
    pass


class CreationRequest(StrictModel):
    setting: Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=500)]
    era: Literal['ancient','modern','future']


class ConfirmationRequest(StrictModel):
    candidate_version_id: str
    content_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


def create_custom_session(provider,model_id):
    if provider != 'deepseek' or model_id != MODELS['deepseek']:
        raise CreationError('unverified_model')
    if not configured(provider):
        raise CreationError('key_not_configured')
    token = secrets.token_urlsafe(32)
    with SessionLocal.begin() as db:
        session = StorySession(token_hash=hashlib.sha256(token.encode()).hexdigest(),provider=provider,
                               model_id=model_id,engine_version='investigation-1',mode='single')
        db.add(session)
        db.flush()
        db.expunge(session)
    return token,session


def _session(db,session_id):
    session = db.scalar(select(StorySession).where(StorySession.id == session_id).with_for_update())
    if session is None or session.engine_version != 'investigation-1':
        raise CreationError('session_not_found')
    return session


def owned_task(db,session_id,task_id,lock=False):
    query = select(StoryTask).where(StoryTask.id == task_id,StoryTask.session_id == session_id)
    task = db.scalar(query.with_for_update() if lock else query)
    if task is None:
        raise CreationError('task_not_found')
    return task


def append_creation_event(db,task,event,payload):
    # Caller holds the corresponding StoryTask row lock.
    seq = (db.scalar(select(func.max(StoryTaskEvent.seq)).where(StoryTaskEvent.task_id == task.id)) or 0)+1
    db.add(StoryTaskEvent(task_id=task.id,seq=seq,event=event,payload=payload))


def _key(key):
    if not 1 <= len(key) <= 80:
        raise CreationError('invalid_idempotency_key')


def create_creation_task(session_id,request,key):
    _key(key)
    with SessionLocal.begin() as db:
        session = _session(db,session_id)
        existing = db.scalar(select(StoryTask).where(StoryTask.session_id == session_id,StoryTask.idempotency_key == key))
        if existing:
            if existing.request != request.model_dump() or existing.source_task_id:
                raise CreationError('idempotency_conflict')
            db.expunge(existing)
            return existing,False
        if session.story_version_id:
            raise CreationError('story_already_approved')
        if db.scalar(select(StoryTask.id).where(StoryTask.session_id == session_id,
                         StoryTask.status.in_(['queued','running','awaiting_confirmation']))):
            raise CreationError('creation_already_pending')
        task = StoryTask(session_id=session_id,story_id=str(uuid4()),idempotency_key=key,request=request.model_dump())
        db.add(task)
        db.flush()
        append_creation_event(db,task,'queued',{})
        db.expunge(task)
        return task,True


def _checkpoint(task_id,checkpoint,stage,repair_count=None):
    with SessionLocal.begin() as db:
        task = db.scalar(select(StoryTask).where(StoryTask.id == task_id).with_for_update())
        if task.status != 'running':
            raise CreationError('task_no_longer_running')
        task.checkpoint = checkpoint
        task.stage = stage
        if repair_count is not None:
            task.repair_count = repair_count
        append_creation_event(db,task,'progress',{'stage':stage})


def creation_context(task,seconds):
    with SessionLocal() as db:
        session = db.get(StorySession,task.session_id)
        recorder = TraceRecorder(SessionLocal,secrets=[get_key(session.provider)],token_hashes=[session.token_hash])
        return ExecutionContext(TaskRef('creation',task.id,session.id),time.monotonic()+seconds,
                                 session.provider,session.model_id,recorder)


async def process_creation_task(task_id):
    deadline = time.monotonic()+300
    with SessionLocal.begin() as db:
        task = db.scalar(select(StoryTask).where(StoryTask.id == task_id).with_for_update())
        if task is None or task.status != 'queued':
            return
        task.status = 'running'
        task.deadline_at = datetime.now(timezone.utc)+timedelta(seconds=300)
        checkpoint = dict(task.checkpoint)
        repair_count = task.repair_count
        request = dict(task.request)
        story_id = task.story_id
        db.flush()
        db.expunge(task)
    context = None
    try:
        async with asyncio.timeout_at(deadline):
            context = creation_context(task,max(0,deadline-time.monotonic()))
            context.deadline = deadline
            registry = ToolRegistry()
            register_story_operations(registry)
            if task.source_task_id:
                with SessionLocal() as db:
                    source = db.get(StoryTask,task.source_task_id)
                    source_trace_id = source.trace_id
                context.recorder.event(context.task,'creation_resumed',{'source_task_id':task.source_task_id,
                                                                       'source_trace_id':source_trace_id})
            while True:
                version = 'draft-2' if repair_count else 'draft-1'
                if 'raw' not in checkpoint:
                    result = await execute(registry,'story.generate',OPERATION_VERSIONS['story.generate'],
                              {'story_id':story_id,'story_version':version,**request},context)
                    if isinstance(result,ToolFailure):
                        if result.error_code != 'output_validation':
                            raise CreationError(result.error_code)
                        raw = result.raw_candidate
                    else:
                        raw = result.output.model_dump_json()
                    checkpoint = {**checkpoint,'raw':context.recorder.redact(raw)}
                    _checkpoint(task_id,checkpoint,'validate')
                issues = []
                try:
                    story = Story.model_validate_json(checkpoint['raw'])
                    if story.story_id != story_id or story.story_version != version or story.era != request['era'] or story.setting != request['setting']:
                        raise ValueError('candidate_identity_or_setting')
                    proof = await validate_reachability(story,context.deadline)
                    if proof.status != 'passed':
                        issues = [json.dumps({'kind':'reachability',**proof.model_dump(mode='json',
                                   exclude={'ending_paths','locations','evidence'})},ensure_ascii=False)]
                    elif not checkpoint.get('semantic_passed'):
                        _checkpoint(task_id,checkpoint,'semantic_check')
                        check = await execute(registry,'story.semantic_check','v1',
                                              {'story':story.model_dump(),'reachability':proof.model_dump()},context)
                        if isinstance(check,ToolFailure):
                            raise CreationError(check.error_code)
                        report = validate_semantic_report(check.output,story)
                        issues = [issue.model_dump_json() for issue in report.issues]
                        if report.passed:
                            checkpoint = {**checkpoint,'semantic_passed':True,'proof':proof.model_dump()}
                            _checkpoint(task_id,checkpoint,'validate')
                except CreationError:
                    raise
                except ValidationError as error:
                    errors = [{'path':list(e['loc']),'type':e['type'],'message':e['msg'][:1000]}
                              for e in error.errors(include_input=False,include_context=False,include_url=False)[:20]]
                    issues = [json.dumps({'kind':'schema','errors':errors},ensure_ascii=False)]
                except (ValueError,TypeError) as error:
                    issues = [json.dumps({'kind':'validation','message':str(error)[:1000]},ensure_ascii=False)]
                issues = [context.recorder.redact(issue) for issue in issues]
                if not issues:
                    break
                context.recorder.event(context.task,'story_validation_failed',{'issues':issues})
                if repair_count:
                    raise CreationError('story_repair_exhausted')
                repair_count = 1
                checkpoint = {**checkpoint,'repair_started':True,'semantic_passed':False}
                _checkpoint(task_id,checkpoint,'repair',repair_count=1)
                repaired = await execute(registry,'story.repair',OPERATION_VERSIONS['story.repair'],
                              {'story_id':story_id,'story_version':'draft-2',**request,
                               'raw_candidate':checkpoint['raw'],'issues':issues[:20]},context)
                if isinstance(repaired,ToolFailure):
                    raise CreationError('story_repair_exhausted' if repaired.error_code=='output_validation' else repaired.error_code)
                checkpoint = {'raw':repaired.output.model_dump_json(),'repair_done':True}
                _checkpoint(task_id,checkpoint,'validate')
            context.recorder.event(context.task,'story_validated',{'story_id':story_id,'story_version':version})
            if time.monotonic() >= context.deadline:
                raise TimeoutError()
            with SessionLocal.begin() as db:
                current = owned_task(db,task.session_id,task_id,lock=True)
                if current.status != 'running':
                    raise CreationError('task_no_longer_running')
                row = save_story_version(db,story)
                current.candidate_version_id = row.id
                current.status = 'awaiting_confirmation'
                current.stage = 'awaiting_confirmation'
                append_creation_event(db,current,'awaiting_confirmation',{'intro':story.public_intro,'title':story.title})
    except asyncio.CancelledError:
        _fail_creation(task,context,'cancelled',interrupted=True)
        raise
    except Exception as error:
        code = 'task_timeout' if isinstance(error,TimeoutError) else str(error) if isinstance(error,CreationError) else 'storage_failure' if isinstance(error,(TraceStorageFailure,SQLAlchemyError)) else 'internal_error'
        _fail_creation(task,context,code,interrupted=code=='task_timeout')


def _fail_creation(task,context,code,interrupted=False):
    recorder = context.recorder if context else TraceRecorder(SessionLocal)
    task_ref = context.task if context else TaskRef('creation',task.id,task.session_id)
    try:
        recorder.event(task_ref,'task_failed',{'error_code':code})
    except TraceStorageFailure:
        code = 'storage_failure'
    with SessionLocal.begin() as db:
        current = owned_task(db,task.session_id,task.id,lock=True)
        if current.status == 'running':
            current.status = 'interrupted' if interrupted else 'failed'
            current.error_code = code
            append_creation_event(db,current,current.status,{'error_code':code})


def public_creation_root(node):
    from app.main import public_node
    result = public_node(node)
    result['created_at'] = node.created_at.astimezone(timezone.utc).isoformat()
    result['state_snapshot'] = {key:value for key,value in node.state_snapshot.items()
                               if key not in ('applied_once_rules','fired_events')}
    return result


def confirm_creation(session_id,task_id,request):
    with SessionLocal() as db:
        task = owned_task(db,session_id,task_id)
        db.expunge(task)
    context = creation_context(task,60)
    context.recorder.event(context.task,'approval_requested',{'candidate_version_id':request.candidate_version_id})
    with SessionLocal.begin() as db:
        session = _session(db,session_id)
        task = owned_task(db,session_id,task_id,lock=True)
        row = db.get(StoryVersion,task.candidate_version_id)
        if (row is None or row.id != request.candidate_version_id or row.content_hash != request.content_hash
                or not task.checkpoint.get('semantic_passed')):
            raise CreationError('candidate_conflict')
        if task.status == 'approved':
            root = db.get(Node,task.root_node_id)
            db.expunge(root)
            return root
        if task.status != 'awaiting_confirmation' or session.story_version_id:
            raise CreationError('confirmation_not_available')
        story = load_story_version(db,row.id)
        state = initial_investigation_state(story)
        options,mapping = build_public_options(story,state)
        root = Node(session_id=session_id,parent_id=None,depth=0,scene_id=story.start_location_id,
                    state_snapshot=state,rendered_scene={'scene_id':story.start_location_id,'narration':story.public_intro,
                                                        'dialogue':[],'options':options,'fallback':False},
                    investigation_options=mapping,story_version_id=row.id,canon_version=story.story_version,
                    prompt_version=PROMPT_VERSION,model_id=f'{session.provider}:{session.model_id}')
        db.add(root)
        db.flush()
        row.approval_status = 'approved'
        session.story_version_id = row.id
        task.status = 'approved'
        task.stage = 'approved'
        task.root_node_id = root.id
        db.add(TurnEvent(node_id=root.id,event_type='story_started',payload={'scene_id':root.scene_id}))
        append_creation_event(db,task,'approved',{'node_id':root.id})
        context.recorder._append(db,context.task,task,'story_approved',{'node_id':root.id},node_id=root.id)
        db.expunge(root)
        return root


def resume_creation(session_id,task_id,key):
    _key(key)
    with SessionLocal.begin() as db:
        session = _session(db,session_id)
        source = owned_task(db,session_id,task_id,lock=True)
        existing = db.scalar(select(StoryTask).where(StoryTask.session_id == session_id,StoryTask.idempotency_key == key))
        if existing:
            if existing.source_task_id != source.id:
                raise CreationError('idempotency_conflict')
            db.expunge(existing)
            return existing,False
        if source.status not in ('failed','interrupted') or session.story_version_id:
            raise CreationError('recovery_not_available')
        if source.repair_count and not source.checkpoint.get('repair_done'):
            raise CreationError('story_repair_exhausted')
        if db.scalar(select(StoryTask.id).where(StoryTask.session_id == session_id,
                         StoryTask.status.in_(['queued','running','awaiting_confirmation']))):
            raise CreationError('creation_already_pending')
        task = StoryTask(session_id=session_id,story_id=source.story_id,idempotency_key=key,request=source.request,
                         source_task_id=source.id,checkpoint=source.checkpoint,repair_count=source.repair_count)
        db.add(task)
        db.flush()
        append_creation_event(db,task,'queued',{'source_task_id':source.id})
        db.expunge(task)
        return task,True


def interrupt_creation_tasks():
    with SessionLocal.begin() as db:
        tasks = db.scalars(select(StoryTask).where(StoryTask.status.in_(['queued','running'])).with_for_update()).all()
        for task in tasks:
            task.status = 'interrupted'
            task.error_code = 'process_restarted'
            append_creation_event(db,task,'interrupted',{'error_code':'process_restarted'})
