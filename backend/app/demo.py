"""Fixed, deterministic scenes for the storage/replay milestone; no model calls."""

from app.canon import get_canon
from app.schemas import Action, StateChange
from app.state import StoryValidationError, validate_transition


def _destination(scene_id: str, action: Action) -> str:
    choice = action.value
    if scene_id == "s1":
        return "s2"
    if scene_id == "s2":
        return "s4" if choice == "tower" or "钟楼" in choice else "s3"
    if scene_id in ("s3", "s4"):
        return "s5"
    if scene_id == "s5":
        if choice == "guard" or "保管" in choice or "守护" in choice:
            return "e2"
        if choice == "sink" or "沉海" in choice or "销毁" in choice:
            return "e3"
        return "e1"
    raise StoryValidationError("ending cannot continue")


def build_demo_scene(parent_state: dict, action: Action) -> tuple[dict, list[StateChange]]:
    parent = parent_state["scene_id"]
    target = _destination(parent, action)
    validate_transition(parent, target)
    canon = get_canon()
    options = {
        "s2": [("dock", "去码头追查脚印"), ("tower", "去钟楼查旧记录")],
        "s3": [("continue", "带着线索前往灯塔"), ("reflect", "先核对码头的证词")],
        "s4": [("continue", "带着记录前往灯塔"), ("reflect", "先核对钟楼的记录")],
        "s5": [("reveal", "公开日志"), ("guard", "共同保管"), ("sink", "让秘密沉海")],
    }.get(target, [])
    participants = ["c1", "c2"] if target in ("s2", "s5") else ["c1", "c3"]
    changes: list[StateChange] = []
    if parent == "s1":
        changes.append(StateChange(kind="relation_delta", key="c1:c2", value=-1 if action.value == "ask" else 1))
    if target == "s2":
        changes.append(StateChange(kind="flag_set", key="clue_found", value=1))
    if target == "s4":
        changes.append(StateChange(kind="flag_set", key="secret_shared", value=1))
    if target == "e3":
        changes.append(StateChange(kind="flag_set", key="trust_broken", value=1))
    scene = {
        "scene_id": target,
        "narration": canon["scenes"][target]["fallback"],
        "dialogue": [
            {"character_id": character_id, "text": line, "emotion": "neutral"}
            for character_id, line in zip(participants, (
                "线索已经摆在眼前，我们得决定下一步。",
                "这一次，我希望我们能一起承担选择的后果。",
            ))
        ],
        "options": [{"id": option_id, "label": label} for option_id, label in options],
        "fallback": False,
    }
    return scene, changes
