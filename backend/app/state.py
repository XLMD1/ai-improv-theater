from copy import deepcopy

from app.canon import get_canon
from app.schemas import StateChange


class StoryValidationError(ValueError):
    pass


def validate_transition(parent_scene_id: str, next_scene_id: str) -> None:
    allowed = get_canon()["transitions"].get(parent_scene_id, [])
    if next_scene_id not in allowed:
        raise StoryValidationError(f"illegal scene transition: {parent_scene_id} -> {next_scene_id}")


def validate_change(change: StateChange) -> None:
    if change.kind == "flag_set":
        if change.key not in get_canon()["flags"] or change.value not in (0, 1):
            raise StoryValidationError("invalid flag change")
    elif change.key not in ("c1:c2", "c1:c3", "c2:c3"):
        raise StoryValidationError("invalid relation key")


def apply_state_changes(parent_state: dict, scene_id: str, changes: list[StateChange]) -> dict:
    validate_transition(parent_state["scene_id"], scene_id)
    state = deepcopy(parent_state)
    for change in changes:
        validate_change(change)
        if change.kind == "flag_set":
            state["flags"][change.key] = bool(change.value)
        else:
            value = state["relations"][change.key] + change.value
            if not -3 <= value <= 3:
                raise StoryValidationError("relation outside -3..3")
            state["relations"][change.key] = value
    state["scene_id"] = scene_id
    state["turn"] += 1
    state["ending_id"] = scene_id if scene_id.startswith("e") else None
    return state
