"""Explicitly published local stories reuse immutable definitions and image files."""
from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy import func, select
from app.config import get_settings
from app.db import SessionLocal
from app.image_tasks import assets_ready
from app.models import Node, StorySession, StoryVersion, TurnEvent
from app.story_schema import StrictModel
from app.story_versions import load_narration_protocol, load_story_version


class Sample(StrictModel):
    id: Literal['ancient','modern','future']
    story_version_id: str


class Catalog(StrictModel):
    version: Literal[1]
    samples: list[Sample] = Field(max_length=3)


class OpenSample(StrictModel):
    sample_id: Literal['ancient','modern','future']
    client_token: str = Field(pattern=r'^[a-zA-Z0-9_-]{32,128}$')


def catalog_path():
    return (get_settings().runtime_dir or Path(__file__).resolve().parents[2] / 'runtime') / 'local-samples.json'


def published(db):
    path = catalog_path()
    if not path.is_file(): return []
    catalog = Catalog.model_validate_json(path.read_text(encoding='utf-8'))
    if len({s.id for s in catalog.samples}) != len(catalog.samples) or len({s.story_version_id for s in catalog.samples}) != len(catalog.samples):
        raise ValueError('invalid_sample_catalog')
    result = []
    for sample in catalog.samples:
        row = db.get(StoryVersion, sample.story_version_id)
        if row is None or row.approval_status != 'approved' or load_narration_protocol(db,row.id) != 'approved-feedback-1': continue
        root = db.scalar(select(Node).where(Node.story_version_id==row.id, Node.parent_id.is_(None)).order_by(Node.created_at))
        if root is None: continue
        source = db.get(StorySession,root.session_id)
        if not assets_ready(db,source): continue
        story = load_story_version(db,row.id)
        if story.era != sample.id: continue
        result.append((sample, story, root, source))
    return result


router = APIRouter()


@router.get('/local-samples')
def list_samples():
    try:
        with SessionLocal() as db:
            return {'samples':[{'id':s.id,'title':story.title,'era':story.era,'intro':story.public_intro} for s,story,_,_ in published(db)]}
    except (ValueError, OSError) as error:
        raise HTTPException(409,detail='local_sample_catalog_unavailable') from error


@router.post('/local-samples/sessions',status_code=201)
def open_sample(request: OpenSample):
    from app.main import public_node
    digest = hashlib.sha256(request.client_token.encode()).hexdigest()
    try:
        with SessionLocal.begin() as db:
            db.execute(select(func.pg_advisory_xact_lock(func.hashtext(digest))))
            old = db.scalar(select(StorySession).where(StorySession.token_hash==digest))
            if old:
                if old.mode != 'sample:'+request.sample_id:
                    raise HTTPException(409,detail='session_creation_conflict')
                root = db.scalar(select(Node).where(Node.session_id==old.id,Node.parent_id.is_(None)))
                return {'root':public_node(root),'session_id':old.id,'provider':old.provider,'model_id':old.model_id}
            item = next((item for item in published(db) if item[0].id==request.sample_id),None)
            if item is None: raise HTTPException(404,detail='local_sample_not_found')
            sample, story, source_root, source = item
            session = StorySession(token_hash=digest,story_version_id=sample.story_version_id,engine_version='investigation-1',
                                   mode='sample:'+sample.id,provider=source.provider,model_id=source.model_id,requires_assets=True)
            db.add(session); db.flush()
            root = Node(session_id=session.id,parent_id=None,depth=0,story_version_id=sample.story_version_id,
                        scene_id=source_root.scene_id,state_snapshot=deepcopy(source_root.state_snapshot),
                        rendered_scene=deepcopy(source_root.rendered_scene),investigation_options=deepcopy(source_root.investigation_options),
                        canon_version=source_root.canon_version,prompt_version=source_root.prompt_version,model_id=source_root.model_id)
            db.add(root); db.flush()
            db.add(TurnEvent(node_id=root.id,event_type='story_started',payload={'scene_id':root.scene_id}))
            return {'root':public_node(root),'session_id':session.id,'provider':session.provider,'model_id':session.model_id}
    except (ValueError, OSError) as error:
        raise HTTPException(409,detail='local_sample_catalog_unavailable') from error
