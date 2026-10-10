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


def apply_state_changes(parent_state: dict, scene_id: str | None = None,
                        changes: list[StateChange] | None = None, *, story=None, action: dict | None = None):
    engine = parent_state.get("engine_version")
    if engine == "investigation-1":
        if story is None or action is None or scene_id is not None or changes is not None:
            raise StoryValidationError("investigation_requires_story_and_action")
        from app.investigation import _adjudicate
        from app.story_schema import Story
        return _adjudicate(Story.model_validate(story.model_dump()), parent_state, action)
    legacy_version = parent_state.get("schema_version", 1)
    if engine is not None or type(legacy_version) is not int or legacy_version != 1:
        raise StoryValidationError("unsupported_state_version")
    if story is not None or action is not None or scene_id is None or changes is None:
        raise StoryValidationError("legacy_requires_scene_and_changes")
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
