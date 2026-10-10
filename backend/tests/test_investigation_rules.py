import json
from pathlib import Path
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.investigation import initial_investigation_state, public_projection
from app.state import StoryValidationError, apply_state_changes
from app.story_schema import Story
from app.story_validation import check_reachability
from test_investigation_schema import sample_data


def story():
    return Story.model_validate(sample_data())


def step(definition, state, **action):
    return apply_state_changes(state, story=definition, action=action)


def walk(definition, actions):
    state = initial_investigation_state(definition)
    for action in actions:
        result = apply_state_changes(state, story=definition, action=action)
        assert result.status == "accepted", result
        state = result.state
    return state


def test_same_location_repeated_and_invalid_actions_preserve_parent():
    definition = story()
    root = initial_investigation_state(definition)
    original = deepcopy(root)
    first = step(definition, root, type="investigate", object_id="notice")
    second = step(definition, first.state, type="investigate", object_id="satchel")
    assert root == original
    assert second.state["location_id"] == "waiting_hall"
    assert second.state["action_turn"] == 2
    assert second.state["discovered_evidence"] == ["ferry_record", "press_note"]
    for action, status in [
        ({"type": "investigate", "object_id": "notice"}, "repeat"),
        ({"type": "move", "location_id": "waiting_hall"}, "invalid"),
        ({"type": "investigate", "object_id": "lens"}, "invalid"),
        ({"type": "investigate", "object_id": "missing"}, "invalid"),
        ({"type": "present", "character_id": "zhou_yan", "evidence_id": "radio_tape"}, "invalid"),
    ]:
        result = apply_state_changes(first.state, story=definition, action=action)
        assert result.status == status
        assert result.state == first.state
    blocked = step(definition, root, type="move", location_id="archive")
    assert blocked.status == "precondition_failed"
    assert blocked.state == root


def test_three_endings_have_witnesses_and_events_fire_once():
    definition = story()
    proof = check_reachability(definition)
    assert proof.status == "passed"
    assert set(proof.ending_paths) == {e.id for e in definition.endings}
    assert len(proof.locations) == 5
    assert len(proof.evidence) == len(definition.evidence)
    for ending, actions in proof.ending_paths.items():
        assert 15 <= len(actions) <= 25
        state = walk(definition, actions)
        assert state["ending_id"] == ending
        assert state["fired_events"] == ["keeper_intervenes"]
        rejected = step(definition, state, type="move", location_id="bell_tower")
        assert rejected.status == "invalid"
        assert rejected.feedback_code == "terminal_state"
        assert rejected.state == state


def test_siblings_and_public_projection_are_isolated():
    definition = story()
    root = initial_investigation_state(definition)
    first = step(definition, root, type="investigate", object_id="notice")
    sibling = step(definition, root, type="investigate", object_id="satchel")
    assert sibling.status == "precondition_failed"
    assert sibling.state == root
    public = public_projection(definition, root)
    serialized = str(public)
    for private in ["truth", "fact_ids", "known_fact_ids", "secret_fact_ids", "conditions", "effects", "rescue_list", "fact_cover"]:
        assert private not in serialized
    assert public["evidence"] == []
    found = public_projection(definition, first.state)
    assert [e["id"] for e in found["evidence"]] == ["ferry_record"]


@pytest.mark.parametrize("field,value", [
    ("engine_version", "future"),
    ("schema_version", 3),
    ("story_id", "00000000-0000-0000-0000-000000000000"),
    ("story_version", "other"),
    ("location_id", "missing"),
    ("discovered_evidence", ["missing"]),
    ("trust", {"zhou_yan": True, "shen_zhixia": 0}),
    ("trust", {"zhou_yan": 0}),
    ("applied_once_rules", ["missing"]),
    ("applied_once_rules", ["inspect_notice", "inspect_notice"]),
    ("ending_id", "missing"),
    ("action_turn", True),
])
def test_forged_state_is_rejected(field, value):
    definition = story()
    state = initial_investigation_state(definition)
    state[field] = value
    saved = deepcopy(state)
    with pytest.raises((StoryValidationError, ValidationError)):
        step(definition, state, type="investigate", object_id="notice")
    assert state == saved


def test_trust_overflow_in_event_is_atomic():
    data = sample_data()
    data["events"][0]["conditions"] = {"all": []}
    data["events"][0]["effects"] = [
        {"op": "discover_evidence", "evidence_id": "rescue_list"},
        {"op": "trust_delta", "character_id": "zhou_yan", "value": 2},
        {"op": "trust_delta", "character_id": "zhou_yan", "value": 2},
    ]
    definition = Story.model_validate(data)
    state = initial_investigation_state(definition)
    saved = deepcopy(state)
    with pytest.raises(StoryValidationError, match="trust_overflow"):
        step(definition, state, type="investigate", object_id="notice")
    assert state == saved
    assert check_reachability(definition).status == "invalid_rules"


def test_matching_rule_conflict_is_not_guessed():
    data = sample_data()
    other = deepcopy(data["action_rules"][0])
    other["id"] = "ambiguous_notice"
    data["action_rules"].append(other)
    definition = Story.model_validate(data)
    root = initial_investigation_state(definition)
    with pytest.raises(StoryValidationError, match="rule_conflict"):
        step(definition, root, type="investigate", object_id="notice")
    assert check_reachability(definition).status == "invalid_rules"


def test_evidence_mutual_lock_and_unreachable_location_are_rejected():
    data = sample_data()
    data["action_rules"][0]["conditions"] = {"all": [
        {"op": "has_evidence", "evidence_id": "press_note", "expected": True}]}
    proof = check_reachability(Story.model_validate(data))
    assert proof.status == "unreachable"
    assert "press_note" in proof.missing_evidence
    assert "archive" in proof.missing_locations
    assert len(proof.missing_endings) == 3


def test_unreachable_ending_and_search_cap_are_not_success():
    data = sample_data()
    data["endings"][0]["conditions"]["all"].append(
        {"op": "trust_at_least", "character_id": "zhou_yan", "value": 3})
    proof = check_reachability(Story.model_validate(data))
    assert proof.status == "unreachable"
    assert proof.missing_endings == ["publish_truth"]
    assert check_reachability(story(), max_states=1).status == "reachability_inconclusive"


def test_event_closure_reevaluates_sorted_ids_and_no_retrigger():
    data = sample_data()
    data["events"] = [
        {"id": "a_after", "conditions": {"all": [{"op": "event_fired", "event_id": "z_first", "expected": True}]},
         "effects": [{"op": "disclose", "disclosure_id": "last_warning"}], "feedback": "后续事件"},
        {"id": "z_first", "conditions": {"all": []},
         "effects": [{"op": "disclose", "disclosure_id": "warning"}], "feedback": "初始事件"},
    ]
    definition = Story.model_validate(data)
    root = initial_investigation_state(definition)
    first = step(definition, root, type="investigate", object_id="notice")
    assert first.triggered_events == ["z_first", "a_after"]
    second = step(definition, first.state, type="investigate", object_id="satchel")
    assert second.triggered_events == []
    assert second.state["fired_events"] == ["a_after", "z_first"]


@pytest.mark.parametrize("ending", ["publish_truth", "guard_together", "sink_secret"])
def test_sample_ending(ending):
    paths = json.loads((Path(__file__).parent / "fixtures" / "mist_harbor_paths.json").read_text(encoding="utf-8"))
    actions = paths[ending]
    manifest = json.loads((Path(__file__).resolve().parents[2] / "evals" / "cases" / "stage1.json").read_text(encoding="utf-8"))
    declared = next(case["actions"] for case in manifest["cases"] if case["test"].endswith("test_sample_ending[" + ending + "]"))
    assert actions == declared
    assert 15 <= len(actions) <= 25
    state = walk(story(), actions)
    assert state["ending_id"] == ending


def test_unknown_legacy_version_and_mixed_inputs_are_rejected():
    from app.canon import initial_state
    legacy = initial_state()
    legacy["engine_version"] = "future"
    with pytest.raises(StoryValidationError, match="unsupported_state_version"):
        apply_state_changes(legacy, "s2", [])
    definition = story()
    parent = initial_investigation_state(definition)
    with pytest.raises(StoryValidationError, match="investigation_requires_story_and_action"):
        apply_state_changes(parent, "s2", [], story=definition, action={"type": "investigate", "object_id": "notice"})


def test_known_character_unknown_evidence_and_topic_do_not_mutate():
    definition = story()
    parent = initial_investigation_state(definition)
    # Use a validated state at the character's fixed location, without granting evidence.
    parent["location_id"] = "dock"
    saved = deepcopy(parent)
    for action, code in [
        ({"type": "present", "character_id": "shen_zhixia", "evidence_id": "empty_crate"}, "evidence_unknown"),
        ({"type": "talk", "character_id": "shen_zhixia", "topic_id": "missing"}, "unknown_action"),
    ]:
        result = apply_state_changes(parent, story=definition, action=action)
        assert result.status == "invalid"
        assert result.feedback_code == code
        assert result.state == saved


def test_rule_overflow_and_schema_error_preserve_parent():
    data = sample_data()
    data["action_rules"][0]["effects"] += [
        {"op": "trust_delta", "character_id": "zhou_yan", "value": 2},
        {"op": "trust_delta", "character_id": "zhou_yan", "value": 2}]
    definition = Story.model_validate(data)
    parent = initial_investigation_state(definition)
    original = deepcopy(parent)
    with pytest.raises(StoryValidationError, match="trust_overflow"):
        step(definition, parent, type="investigate", object_id="notice")
    assert parent == original
    with pytest.raises(ValidationError):
        step(definition, parent, type="investigate", object_id="notice", effects=[])
    assert parent == original


def test_event_trust_once_and_public_disclosure_visibility():
    data = sample_data()
    data["events"][0]["conditions"] = {"all": []}
    data["events"][0]["effects"].append({"op": "trust_delta", "character_id": "zhou_yan", "value": 1})
    definition = Story.model_validate(data)
    root = initial_investigation_state(definition)
    first = step(definition, root, type="investigate", object_id="notice")
    second = step(definition, first.state, type="investigate", object_id="satchel")
    assert first.state["trust"]["zhou_yan"] == second.state["trust"]["zhou_yan"] == 1
    public = public_projection(definition, second.state)
    assert [item["id"] for item in public["disclosures"]] == ["last_warning"]
    assert "confession" not in str(public)

def test_story_ids_are_data_driven():
    data = sample_data()
    groups = ["characters", "locations", "objects", "evidence", "disclosures", "commitments", "action_rules", "events", "endings"]
    ids = {item["id"] for group in groups for item in data[group]} | set(data["truth"]["facts"])
    ids |= {rule["action"]["topic_id"] for rule in data["action_rules"] if rule["action"]["type"] == "talk"}
    mapping = {value: "custom_" + value for value in ids}
    def rename(value):
        if isinstance(value, dict):
            return {mapping.get(key, key): rename(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rename(item) for item in value]
        return mapping.get(value, value) if isinstance(value, str) else value
    definition = Story.model_validate(rename(data))
    proof = check_reachability(definition)
    assert proof.status == "passed"
    assert set(proof.ending_paths) == {"custom_publish_truth", "custom_guard_together", "custom_sink_secret"}
