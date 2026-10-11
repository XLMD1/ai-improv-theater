"""Investigation task service: proposals are validated before atomic commit."""
import asyncio
from copy import deepcopy
from datetime import timezone
import time

from sqlalchemy import select

from app.db import SessionLocal
from app.execution import ExecutionContext,ToolRegistry
from app.execution_traces import TaskRef,TraceRecorder,TraceStorageFailure
from app.investigation import Adjudication,public_projection
from app.investigation_generation import GenerationError,build_public_options,interpret_action,render_investigation_scene
from app.local_settings import configured,get_key
from app.models import Node,Run,StorySession,StoryVersion,TurnEvent
from app.schemas import Action
from app.state import StoryValidationError,apply_state_changes
from app.story_operations import PROMPT_VERSION,register_investigation_operations
from app.story_versions import load_narration_protocol,load_story_version


def create_investigation_run(session_id,parent_node_id,action,key):
    from app.jobs import _append_event
    if not 1 <= len(key) <= 80:
        raise StoryValidationError('invalid_idempotency_key')
    with SessionLocal.begin() as db:
        session = db.scalar(select(StorySession).where(StorySession.id==session_id).with_for_update())
        existing = db.scalar(select(Run).where(Run.session_id==session_id,Run.idempotency_key==key))
        if existing:
            if existing.parent_node_id != parent_node_id or existing.action != action.model_dump():
                raise StoryValidationError('idempotency_conflict')
            db.expunge(existing)
            return existing,False
        if not session.story_version_id:
            raise StoryValidationError('story_not_ready')
        row = db.get(StoryVersion,session.story_version_id)
        if row.approval_status != 'approved':
            raise StoryValidationError('story_not_ready')
        parent = db.get(Node,parent_node_id)
        if parent is None or parent.session_id != session_id or parent.story_version_id != row.id:
            raise StoryValidationError('parent_node_not_found')
        if parent.state_snapshot['ending_id']:
            raise StoryValidationError('ending_cannot_continue')
        if action.type=='option' and action.value not in (parent.investigation_options or {}):
            raise StoryValidationError('invalid_option')
        narration_protocol = load_narration_protocol(db,row.id)
        if not (narration_protocol=='approved-feedback-1' and action.type=='option') and not configured(session.provider):
            raise StoryValidationError('key_not_configured')
        if db.scalar(select(Run.id).where(Run.session_id==session_id,Run.status.in_(['queued','running']))):
            raise StoryValidationError('turn_already_pending')
        run = Run(session_id=session_id,parent_node_id=parent_node_id,idempotency_key=key,action=action.model_dump())
        db.add(run)
        db.flush()
        _append_event(db,run.id,'queued',{})
        db.expunge(run)
        return run,True


def recent_investigation_turns(db,parent_node_id):
    result = []
    node = db.get(Node,parent_node_id)
    while node and len(result)<3:
        action = db.scalar(select(TurnEvent.payload).where(TurnEvent.node_id==node.id,TurnEvent.event_type=='player_action'))
        result.append({'scene_id':node.scene_id,'player_action':action,
                       'narration':node.rendered_scene['narration'][:240],
                       'dialogue':[{'character_id':line['character_id'],'text':line['text'][:100]}
                                   for line in node.rendered_scene['dialogue']]})
        node = db.get(Node,node.parent_id) if node.parent_id else None
    return list(reversed(result))


def public_investigation_node(node):
    return {'id':node.id,'session_id':node.session_id,'parent_id':node.parent_id,'depth':node.depth,
            'scene_id':node.scene_id,
            'state_snapshot':{key:deepcopy(value) for key,value in node.state_snapshot.items()
                              if key in ('schema_version','engine_version','story_id','story_version','location_id',
                                         'action_turn','discovered_evidence','disclosures','commitments','trust','ending_id')},
            'rendered_scene':deepcopy(node.rendered_scene),'canon_version':node.canon_version,
            'prompt_version':node.prompt_version,'model_id':node.model_id,
            'created_at':node.created_at.astimezone(timezone.utc).isoformat()}


def public_investigation_events(db,node):
    events = db.scalars(select(TurnEvent).where(TurnEvent.node_id==node.id).order_by(TurnEvent.created_at)).all()
    result = []
    for event in events:
        if event.event_type in ('story_started','player_action','approved_scene'):
            result.append({'event_type':event.event_type,'payload':event.payload})
        elif event.event_type=='adjudication':
            result.append({'event_type':event.event_type,'payload':{key:event.payload[key]
                                      for key in ('status','feedback_code','feedback')}})
    return result


def decide(story,state,normalized):
    if normalized is None:
        return Adjudication(status='invalid',feedback_code='uninterpretable',
                            feedback='无法理解这项行动，请选择公开选项或说明调查对象。',
                            effects=[],triggered_events=[],state=deepcopy(state))
    return apply_state_changes(state,story=story,action=normalized)


async def process_investigation_run(run_id):
    from app.jobs import _append_event
    with SessionLocal.begin() as db:
        run = db.scalar(select(Run).where(Run.id==run_id).with_for_update())
        if run is None or run.status!='queued':
            return
        run.status = 'running'
        _append_event(db,run.id,'running',{})
        session = db.get(StorySession,run.session_id)
        parent = db.get(Node,run.parent_node_id)
        story = load_story_version(db,parent.story_version_id)
        narration_protocol = load_narration_protocol(db,parent.story_version_id)
        parent_state = deepcopy(parent.state_snapshot)
        parent_version = parent.story_version_id
        parent_depth = parent.depth
        mapping = deepcopy(parent.investigation_options or {})
        recent = recent_investigation_turns(db,parent.id)
        provider,model_id = session.provider,session.model_id
        session_token_hash = session.token_hash
        action = Action.model_validate(run.action)
        db.expunge(run)
    context = ExecutionContext(TaskRef('action',run.id,run.session_id),time.monotonic()+60,
                               provider,model_id,TraceRecorder(SessionLocal,secrets=[get_key(provider)],token_hashes=[session_token_hash]))
    registry = ToolRegistry()
    register_investigation_operations(registry)
    try:
        async with asyncio.timeout(60):
            context.recorder.start(context.task)
            context.recorder.event(context.task,'presentation_selected',{'narration_protocol':narration_protocol})
            normalized = await interpret_action(story,parent_state,mapping,action,recent,registry,context,
                                                version='v2' if narration_protocol=='approved-feedback-1' else 'v1')
            decision = decide(story,parent_state,normalized)
            context.recorder.event(context.task,'adjudicated',decision.model_dump())
            if decision.status=='accepted' and narration_protocol=='model-scene-1':
                with SessionLocal.begin() as db:
                    current = db.scalar(select(Run).where(Run.id==run.id).with_for_update())
                    if current.status!='running':
                        raise GenerationError('task_no_longer_running')
                    _append_event(db,run.id,'writing',{})
                draft = await render_investigation_scene(story,decision.state,normalized,decision.feedback,recent,registry,context)
            else:
                draft = {'narration':decision.feedback,'dialogue':[]}
            options,option_mapping = build_public_options(story,decision.state)
            scene = {'scene_id':decision.state['location_id'],**draft,'options':options,'fallback':False}
            context.recorder.event(context.task,'scene_validated',{'scene':scene})
            with SessionLocal.begin() as db:
                session = db.scalar(select(StorySession).where(StorySession.id==run.session_id).with_for_update())
                current = db.scalar(select(Run).where(Run.id==run.id).with_for_update())
                saved_parent = db.get(Node,run.parent_node_id)
                if current.status!='running' or time.monotonic()>=context.deadline or context.stopped:
                    raise GenerationError('task_no_longer_running')
                if (saved_parent.session_id != session.id or saved_parent.story_version_id != parent_version
                        or session.story_version_id != parent_version or saved_parent.state_snapshot != parent_state
                        or decide(story,parent_state,normalized) != decision):
                    raise GenerationError('parent_or_decision_conflict')
                node = Node(session_id=session.id,parent_id=saved_parent.id,depth=parent_depth+1,
                             scene_id=scene['scene_id'],state_snapshot=decision.state,rendered_scene=scene,
                             investigation_options=option_mapping,story_version_id=parent_version,
                             canon_version=story.story_version,
                             prompt_version='approved-feedback-1' if narration_protocol=='approved-feedback-1' else PROMPT_VERSION,
                             model_id='server:approved-feedback-1' if narration_protocol=='approved-feedback-1' else f'{provider}:{model_id}')
                db.add(node)
                db.flush()
                events = [('player_action',context.recorder.redact(action.model_dump())),
                          ('action_interpretation',{'action':normalized}),('adjudication',decision.model_dump()),
                          ('approved_scene',scene)]
                for effect in decision.effects:
                    if effect.op in ('disclose','record_commitment'):
                        events.append((effect.op,effect.model_dump()))
                for event_id in decision.triggered_events:
                    events.append(('triggered_event',{'event_id':event_id}))
                for event_type,payload in events:
                    db.add(TurnEvent(node_id=node.id,event_type=event_type,payload=payload))
                context.recorder._append(db,context.task,current,'node_committed',{'node_id':node.id},node_id=node.id)
                current.status = 'completed'
                current.node_id = node.id
                text = scene['narration']+'\n'+'\n'.join(line['text'] for line in scene['dialogue'])
                for index in range(0,len(text),60):
                    _append_event(db,run.id,'scene_chunk',{'text':text[index:index+60]})
                _append_event(db,run.id,'options',{'options':options})
                _append_event(db,run.id,'done',{'node_id':node.id})
    except asyncio.CancelledError:
        _fail_run(context,'cancelled',interrupted=True)
        raise
    except Exception as error:
        code = ('task_timeout' if isinstance(error,TimeoutError) else str(error) if isinstance(error,GenerationError)
                else 'storage_failure' if isinstance(error,TraceStorageFailure) else 'internal_error')
        _fail_run(context,code,interrupted=code=='task_timeout')


def _fail_run(context,code,interrupted=False):
    from app.jobs import _append_event
    try:
        context.recorder.event(context.task,'task_failed',{'error_code':code})
    except TraceStorageFailure:
        code = 'storage_failure'
    with SessionLocal.begin() as db:
        run = db.scalar(select(Run).where(Run.id==context.task.task_id).with_for_update())
        if run.status=='running':
            run.status = 'interrupted' if interrupted else 'failed'
            run.error_code = code
            _append_event(db,run.id,'error',{'error_code':code})
