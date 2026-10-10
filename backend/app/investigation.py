"""Pure deterministic decisions; state.py is the single public update entry."""
from copy import deepcopy
from typing import Literal

from app.state import StoryValidationError
from app.story_schema import Effect, InvestigationState, Story, StrictModel, parse_action


class Adjudication(StrictModel):
    status: Literal["accepted", "invalid", "repeat", "precondition_failed"]
    feedback_code: str
    feedback: str
    effects: list[Effect]
    triggered_events: list[str]
    state: dict


def initial_investigation_state(story: Story) -> dict:
    return InvestigationState(
        schema_version=2, engine_version="investigation-1",
        story_id=story.story_id, story_version=story.story_version,
        location_id=story.start_location_id, action_turn=0,
        discovered_evidence=[], disclosures=[], commitments=[],
        trust={c.id: 0 for c in story.characters if c.id != story.protagonist_id},
        applied_once_rules=[], fired_events=[], ending_id=None,
    ).model_dump()


def validate_snapshot(story: Story, data: dict) -> dict:
    state = InvestigationState.model_validate(data).model_dump()
    if state["story_id"] != story.story_id or state["story_version"] != story.story_version:
        raise StoryValidationError("story_version_mismatch")
    if set(state["trust"]) != {c.id for c in story.characters if c.id != story.protagonist_id}:
        raise StoryValidationError("invalid_trust_characters")
    groups = {
        "discovered_evidence": story.evidence, "disclosures": story.disclosures,
        "commitments": story.commitments,
        "applied_once_rules": [r for r in story.action_rules if r.once],
        "fired_events": story.events,
    }
    for field, entities in groups.items():
        if not set(state[field]).issubset({e.id for e in entities}):
            raise StoryValidationError("invalid_state_reference:" + field)
    if state["location_id"] not in {l.id for l in story.locations}:
        raise StoryValidationError("invalid_state_location")
    if state["ending_id"] is not None and state["ending_id"] not in {e.id for e in story.endings}:
        raise StoryValidationError("invalid_state_ending")
    return state


def matches(conditions, state: dict) -> bool:
    fields = {
        "has_evidence": ("discovered_evidence", "evidence_id"),
        "has_disclosure": ("disclosures", "disclosure_id"),
        "has_commitment": ("commitments", "commitment_id"),
        "event_fired": ("fired_events", "event_id"),
    }
    for atom in conditions.all:
        if atom.op == "at_location":
            valid = state["location_id"] == atom.location_id
        elif atom.op == "trust_at_least":
            valid = state["trust"][atom.character_id] >= atom.value
        else:
            state_key, id_key = fields[atom.op]
            valid = (getattr(atom, id_key) in state[state_key]) == atom.expected
        if not valid:
            return False
    return True


def _add(state: dict, field: str, value: str):
    state[field] = sorted(set(state[field]) | {value})


def _effects(state: dict, effects: list[Effect]):
    for effect in effects:
        if effect.op == "trust_delta":
            value = state["trust"][effect.character_id] + effect.value
            if not -3 <= value <= 3:
                raise StoryValidationError("trust_overflow:" + effect.character_id)
            state["trust"][effect.character_id] = value
        elif effect.op == "discover_evidence":
            _add(state, "discovered_evidence", effect.evidence_id)
        elif effect.op == "disclose":
            _add(state, "disclosures", effect.disclosure_id)
        else:
            _add(state, "commitments", effect.commitment_id)


def _adjudicate(story: Story, parent: dict, raw_action: dict) -> Adjudication:
    state = validate_snapshot(story, parent)
    action = parse_action(raw_action)
    proposal = deepcopy(state)

    def rejected(status: str, code: str, feedback: str):
        return Adjudication(status=status, feedback_code=code, feedback=feedback,
                            effects=[], triggered_events=[], state=deepcopy(state))

    if state["ending_id"]:
        return rejected("invalid", "terminal_state", "本分支已经结束，请回到已有节点查看或选择新的分支。")
    effects = []
    feedback = []
    if action.type == "move":
        if action.location_id == state["location_id"]:
            return rejected("invalid", "same_location", "你已经在这里，可以继续调查。")
        location = next(l for l in story.locations if l.id == state["location_id"])
        exit = next((e for e in location.exits if e.location_id == action.location_id), None)
        if exit is None:
            return rejected("invalid", "no_exit", "这里没有通向该地点的出口。")
        if not matches(exit.conditions, state):
            return rejected("precondition_failed", "exit_locked", "通行条件尚未满足，请继续调查。")
        proposal["location_id"] = action.location_id
        feedback.append("你前往" + next(l.name for l in story.locations if l.id == action.location_id) + "。")
    elif action.type == "decide":
        ending = next((e for e in story.endings if e.id == action.ending_id), None)
        if ending is None:
            return rejected("invalid", "unknown_ending", "无法作出这个抉择。")
        if not matches(ending.conditions, state):
            return rejected("precondition_failed", "ending_locked", "证据或承诺尚不充分，请继续核对。")
        proposal["ending_id"] = ending.id
        feedback.append(ending.consequence)
    else:
        if action.type == "investigate":
            target = next((o for o in story.objects if o.id == action.object_id), None)
            if target is None or target.location_id != state["location_id"]:
                return rejected("invalid", "object_unavailable", "这里没有可以调查的该对象。")
        else:
            target = next((c for c in story.characters if c.id == action.character_id), None)
            if target is None or target.id == story.protagonist_id or target.initial_location_id != state["location_id"]:
                return rejected("invalid", "character_unavailable", "该角色当前不在这里。")
            if action.type == "present" and action.evidence_id not in state["discovered_evidence"]:
                return rejected("invalid", "evidence_unknown", "你尚未发现这项证据。")
        matching = [r for r in story.action_rules if r.action == action]
        if not matching:
            return rejected("invalid", "unknown_action", "该对象或话题没有可执行的调查规则。")
        eligible = [r for r in matching if matches(r.conditions, state)
                    and (not r.once or r.id not in state["applied_once_rules"])]
        if len(eligible) > 1:
            raise StoryValidationError("rule_conflict:" + ",".join(r.id for r in eligible))
        if not eligible:
            if any(r.once and r.id in state["applied_once_rules"] for r in matching):
                return rejected("repeat", "already_applied", "这项行动已经完成，没有新的线索。")
            return rejected("precondition_failed", "rule_locked", "当前证据尚不满足该行动的条件。")
        rule = eligible[0]
        effects.extend(rule.effects)
        _effects(proposal, rule.effects)
        if rule.once:
            _add(proposal, "applied_once_rules", rule.id)
        if proposal == state:
            return rejected("repeat", "no_new_information", "这项行动没有带来新信息。")
        feedback.append(rule.feedback)

    triggered = []
    # A finite event closure: each declared event can be applied only once.
    for _ in range(len(story.events)):
        changed = False
        for event in sorted(story.events, key=lambda e: e.id):
            if event.id not in proposal["fired_events"] and matches(event.conditions, proposal):
                _effects(proposal, event.effects)
                _add(proposal, "fired_events", event.id)
                effects.extend(event.effects)
                triggered.append(event.id)
                feedback.append(event.feedback)
                changed = True
        if not changed:
            break
    proposal["action_turn"] += 1
    result = validate_snapshot(story, proposal)
    return Adjudication(status="accepted", feedback_code="accepted", feedback="\n".join(feedback),
                        effects=effects, triggered_events=triggered, state=result)


def available_actions(story: Story, state: dict) -> list[dict]:
    """Finite candidates; adjudication still validates each candidate."""
    if state["ending_id"]:
        return []
    values = [r.action.model_dump() for r in story.action_rules
              if (r.action.type == "investigate" and any(
                  o.id == r.action.object_id and o.location_id == state["location_id"] for o in story.objects))
              or (r.action.type != "investigate" and any(
                  c.id == r.action.character_id and c.initial_location_id == state["location_id"] for c in story.characters))]
    location = next(l for l in story.locations if l.id == state["location_id"])
    values += [{"type": "move", "location_id": e.location_id} for e in location.exits]
    values += [{"type": "decide", "ending_id": e.id} for e in story.endings]
    seen = set()
    unique = []
    for value in values:
        key = tuple(sorted(value.items()))
        if key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def public_projection(story: Story, snapshot: dict) -> dict:
    state = validate_snapshot(story, snapshot)
    location = next(l for l in story.locations if l.id == state["location_id"])
    ending = next((e for e in story.endings if e.id == state["ending_id"]), None)
    return {
        "story_id": story.story_id, "story_version": story.story_version,
        "title": story.title, "setting": story.setting, "era": story.era, "intro": story.public_intro,
        "location": {"id": location.id, "name": location.name, "description": location.description},
        "action_turn": state["action_turn"],
        "characters": [{"id": c.id, "name": c.name, "appearance": c.appearance}
                       for c in story.characters if c.initial_location_id == state["location_id"]],
        "objects": [{"id": o.id, "name": o.name, "description": o.description}
                    for o in story.objects if o.location_id == state["location_id"]],
        "evidence": [{"id": e.id, "description": e.description} for e in story.evidence
                     if e.id in state["discovered_evidence"]],
        "disclosures": [{"id": d.id, "text": d.public_text} for d in story.disclosures if d.id in state["disclosures"]],
        "commitments": [{"id": c.id, "text": c.public_text} for c in story.commitments if c.id in state["commitments"]],
        "ending": {"id": ending.id, "title": ending.title, "consequence": ending.consequence} if ending else None,
    }
