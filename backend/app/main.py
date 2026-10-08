import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.canon import get_canon
from app.db import SessionLocal
from app.jobs import create_run, create_story_session, dispatch_run, interrupt_unfinished, session_for_token
from app.models import Node, Run, RunEvent, StorySession, TurnEvent
from app.schemas import TurnRequest
from app.state import StoryValidationError


@asynccontextmanager
async def lifespan(_app: FastAPI):
    interrupt_unfinished()
    yield


app = FastAPI(title="AI 即兴剧场 API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID"],
)


def db_session():
    with SessionLocal() as db:
        yield db


def current_session(authorization: str = Header(default=""), db: Session = Depends(db_session)) -> StorySession:
    token = authorization[7:] if authorization.startswith("Bearer ") else ""
    session = session_for_token(db, token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session token")
    return session


def public_node(node: Node) -> dict:
    return {
        "id": node.id, "session_id": node.session_id, "parent_id": node.parent_id,
        "depth": node.depth, "scene_id": node.scene_id,
        "state_snapshot": node.state_snapshot, "rendered_scene": node.rendered_scene,
        "canon_version": node.canon_version, "prompt_version": node.prompt_version,
        "model_id": node.model_id, "created_at": node.created_at.isoformat(),
    }


@app.get("/health")
def health():
    return {"ok": True, "demo_mode": True}


@app.get("/world")
def world():
    canon = get_canon()
    return {"version": canon["version"], "title": canon["title"], "scenes": canon["scenes"], "characters": canon["characters"]}


@app.post("/sessions", status_code=201)
def new_session():
    token, root = create_story_session()
    return {"token": token, "root": public_node(root)}


@app.get("/nodes/{node_id}")
def get_node(node_id: str, session: StorySession = Depends(current_session), db: Session = Depends(db_session)):
    node = db.get(Node, node_id)
    if not node or node.session_id != session.id:
        raise HTTPException(status_code=404, detail="Node not found")
    return public_node(node)


@app.get("/nodes/{node_id}/events")
def get_node_events(node_id: str, session: StorySession = Depends(current_session), db: Session = Depends(db_session)):
    node = db.get(Node, node_id)
    if not node or node.session_id != session.id:
        raise HTTPException(status_code=404, detail="Node not found")
    events = db.scalars(select(TurnEvent).where(TurnEvent.node_id == node_id).order_by(TurnEvent.created_at)).all()
    return [{"event_type": event.event_type, "payload": event.payload} for event in events]


@app.get("/tree")
def get_tree(session: StorySession = Depends(current_session), db: Session = Depends(db_session)):
    nodes = db.scalars(select(Node).where(Node.session_id == session.id).order_by(Node.created_at, Node.depth)).all()
    by_id = {node.id: node for node in nodes}
    events = db.scalars(select(TurnEvent).where(TurnEvent.node_id.in_(by_id), TurnEvent.event_type == "player_action")).all()
    actions = {event.node_id: event.payload for event in events}
    result = []
    for node in nodes:
        action = actions.get(node.id)
        if not action:
            label = "开场"
        elif action["type"] == "text":
            label = f"自由行动：{action['value'][:16]}"
        else:
            parent = by_id[node.parent_id]
            label = next((option["label"] for option in parent.rendered_scene["options"] if option["id"] == action["value"]), action["value"])
        result.append({
            "id": node.id, "parent_id": node.parent_id, "scene_id": node.scene_id,
            "depth": node.depth, "action_label": label, "created_at": node.created_at.isoformat(),
        })
    return result


@app.post("/turns", status_code=202)
async def new_turn(
    request: TurnRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    session: StorySession = Depends(current_session),
):
    try:
        run, created = create_run(session.id, request.parent_node_id, request.action, idempotency_key)
    except StoryValidationError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if created:
        dispatch_run(run.id)
    return {"run_id": run.id, "status": run.status}


@app.get("/runs/{run_id}")
def get_run(run_id: str, session: StorySession = Depends(current_session), db: Session = Depends(db_session)):
    run = db.get(Run, run_id)
    if not run or run.session_id != session.id:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"id": run.id, "status": run.status, "node_id": run.node_id, "error_code": run.error_code}


@app.get("/runs/{run_id}/events")
async def stream_run(
    run_id: str,
    after: int = Query(default=0, ge=0),
    session: StorySession = Depends(current_session),
    db: Session = Depends(db_session),
):
    run = db.get(Run, run_id)
    if not run or run.session_id != session.id:
        raise HTTPException(status_code=404, detail="Run not found")

    async def events():
        cursor = after
        last_heartbeat = asyncio.get_running_loop().time()
        while True:
            with SessionLocal() as event_db:
                rows = event_db.scalars(
                    select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.seq > cursor).order_by(RunEvent.seq).limit(50)
                ).all()
                status = event_db.get(Run, run_id).status
                for row in rows:
                    cursor = row.seq
                    payload = json.dumps(row.payload, ensure_ascii=False)
                    yield f"id: {row.seq}\nevent: {row.event}\ndata: {payload}\n\n"
            if status in ("completed", "failed", "interrupted") and not rows:
                break
            now = asyncio.get_running_loop().time()
            if now - last_heartbeat >= 10:
                yield ": heartbeat\n\n"
                last_heartbeat = now
            await asyncio.sleep(0.4)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
