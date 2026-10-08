import asyncio
import hashlib
import secrets

from sqlalchemy import func, select

from app.canon import get_canon, initial_state
from app.costs import LIMIT_CNY, PRICE_VERSION, estimate_cny, total_spend_cny
from app.db import SessionLocal
from app.demo import build_demo_scene
from app.generation import build_ai_scene
from app.local_settings import configured
from app.models import LLMCall, Node, Run, RunEvent, StorySession, TurnEvent
from app.schemas import Action, RunStatus
from app.state import StoryValidationError, apply_state_changes


active_tasks: set[asyncio.Task] = set()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_story_session(provider: str = "demo", model_id: str = "demo") -> tuple[str, Node]:
    token = secrets.token_urlsafe(32)
    canon = get_canon()
    with SessionLocal.begin() as db:
        session = StorySession(token_hash=token_hash(token), provider=provider, model_id=model_id)
        db.add(session)
        db.flush()
        root = Node(
            session_id=session.id, parent_id=None, depth=0, scene_id="s1",
            state_snapshot=initial_state(),
            rendered_scene={
                "scene_id": "s1",
                "narration": "暴风雨封锁了雾港。林岚、周砚和沈知夏在候船厅碰面，失踪船长的航海日志成为争执的中心。",
                "dialogue": [{"character_id": "c1", "text": "如果日志真的在这里，我们必须在天亮前找到它。", "emotion": "neutral"}],
                "options": [{"id": "search", "label": "前往档案室寻找日志"}, {"id": "ask", "label": "先问周砚隐瞒了什么"}],
                "fallback": False,
            },
            canon_version=canon["version"], prompt_version="demo-1", model_id="demo",
        )
        db.add(root)
        db.flush()
        db.add(TurnEvent(node_id=root.id, event_type="story_started", payload={"scene_id": "s1"}))
        db.expunge(root)
    return token, root


def session_for_token(db, token: str) -> StorySession | None:
    if not token:
        return None
    return db.scalar(select(StorySession).where(StorySession.token_hash == token_hash(token)))


def _append_event(db, run_id: str, event: str, payload: dict) -> None:
    seq = (db.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == run_id)) or 0) + 1
    db.add(RunEvent(run_id=run_id, seq=seq, event=event, payload=payload))
    db.flush()


def _recent_turns(db, parent_node_id: str) -> list[dict]:
    turns = []
    node = db.get(Node, parent_node_id)
    while node and len(turns) < 3:
        action = db.scalar(select(TurnEvent.payload).where(
            TurnEvent.node_id == node.id, TurnEvent.event_type == "player_action",
        ))
        turns.append({
            "scene_id": node.scene_id,
            "player_action": {**action, "value": action["value"][:120]} if action else None,
            "narration": node.rendered_scene["narration"][:240],
            "dialogue": [
                {"character_id": line["character_id"], "text": line["text"][:100]}
                for line in node.rendered_scene["dialogue"]
            ],
        })
        node = db.get(Node, node.parent_id) if node.parent_id else None
    return list(reversed(turns))


def create_run(session_id: str, parent_node_id: str, action: Action, key: str) -> tuple[Run, bool]:
    if not 1 <= len(key) <= 80:
        raise StoryValidationError("invalid Idempotency-Key")
    with SessionLocal.begin() as db:
        db.execute(select(StorySession).where(StorySession.id == session_id).with_for_update()).scalar_one()
        existing = db.scalar(select(Run).where(Run.session_id == session_id, Run.idempotency_key == key))
        if existing:
            if existing.parent_node_id != parent_node_id or existing.action != action.model_dump():
                raise StoryValidationError("Idempotency-Key reused for a different turn")
            db.expunge(existing)
            return existing, False
        parent = db.get(Node, parent_node_id)
        if not parent or parent.session_id != session_id:
            raise StoryValidationError("parent node not found")
        if not get_canon()["transitions"][parent.scene_id]:
            raise StoryValidationError("ending cannot continue")
        if action.type == "option" and action.value not in {option["id"] for option in parent.rendered_scene["options"]}:
            raise StoryValidationError("option does not belong to parent node")
        session = db.get(StorySession, session_id)
        if session.provider != "demo" and not configured(session.provider):
            raise StoryValidationError("API key is not configured")
        if session.provider != "demo" and total_spend_cny(db) >= LIMIT_CNY:
            raise StoryValidationError("estimated model budget reached")
        active = db.scalar(select(Run.id).where(Run.session_id == session_id, Run.status.in_(["queued", "running"])))
        if active:
            raise StoryValidationError("a turn is already running")
        run = Run(session_id=session_id, parent_node_id=parent_node_id, idempotency_key=key, action=action.model_dump())
        db.add(run)
        db.flush()
        _append_event(db, run.id, "queued", {})
        db.expunge(run)
        return run, True


async def process_run(run_id: str) -> None:
    with SessionLocal.begin() as db:
        run = db.get(Run, run_id)
        if not run or run.status != RunStatus.QUEUED:
            return
        run.status = RunStatus.RUNNING
        _append_event(db, run_id, "running", {})
    try:
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            parent = db.get(Node, run.parent_node_id)
            session = db.get(StorySession, run.session_id)
            action = Action.model_validate(run.action)
            parent_state = parent.state_snapshot
            parent_id = parent.id
            parent_depth = parent.depth
            session_id = run.session_id
            provider = session.provider
            model_id = session.model_id
            recent_turns = _recent_turns(db, parent_id) if provider != "demo" else []
        if provider == "demo":
            scene, changes = build_demo_scene(parent_state, action)
            usage = None
        else:
            with SessionLocal.begin() as db:
                _append_event(db, run_id, "writing", {})
            scene, changes, usage = await build_ai_scene(parent_state, action, provider, model_id, recent_turns)
        with SessionLocal.begin() as db:
            run = db.get(Run, run_id)
            state = apply_state_changes(parent_state, scene["scene_id"], changes)
            node = Node(
                session_id=session_id, parent_id=parent_id, depth=parent_depth + 1,
                scene_id=scene["scene_id"], state_snapshot=state, rendered_scene=scene,
                canon_version=get_canon()["version"],
                prompt_version="demo-1" if provider == "demo" else "single-2",
                model_id="demo" if provider == "demo" else f"{provider}:{model_id}",
            )
            db.add(node)
            db.flush()
            if usage is not None:
                db.add(LLMCall(
                    run_id=run_id, provider=provider, model_id=model_id,
                    input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                    estimated_cost_cny=estimate_cny(provider, usage.input_tokens, usage.output_tokens),
                    price_version=PRICE_VERSION,
                ))
            for event_type, payload in (
                ("player_action", action.model_dump()),
                ("approved_scene", scene),
                ("state_changes", {"changes": [change.model_dump() for change in changes]}),
            ):
                db.add(TurnEvent(node_id=node.id, event_type=event_type, payload=payload))
            run.status = RunStatus.COMPLETED
            run.node_id = node.id
            text = scene["narration"] + "\n" + "\n".join(line["text"] for line in scene["dialogue"])
            for index in range(0, len(text), 60):
                _append_event(db, run_id, "scene_chunk", {"text": text[index:index + 60]})
            _append_event(db, run_id, "options", {"options": scene["options"]})
            _append_event(db, run_id, "done", {"node_id": node.id})
    except Exception as error:
        with SessionLocal.begin() as db:
            run = db.get(Run, run_id)
            if run and run.status == RunStatus.RUNNING:
                run.status = RunStatus.FAILED
                run.error_code = type(error).__name__
                _append_event(db, run_id, "failed", {"error": "本幕未提交，请重新选择。"})


def dispatch_run(run_id: str) -> None:
    task = asyncio.create_task(process_run(run_id))
    active_tasks.add(task)
    task.add_done_callback(active_tasks.discard)


def interrupt_unfinished() -> None:
    with SessionLocal.begin() as db:
        for run in db.scalars(select(Run).where(Run.status.in_(["queued", "running"]))):
            run.status = RunStatus.INTERRUPTED
            run.error_code = "process_restarted"
            _append_event(db, run.id, "interrupted", {"error": "服务重启，本幕未提交。"})
