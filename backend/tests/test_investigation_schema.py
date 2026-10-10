import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.story_schema import Story, canonical_hash, parse_action

FIXTURE = Path(__file__).parent / "fixtures" / "mist_harbor_investigation.json"


def sample_data():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_full_sample_and_canonical_hash():
    data = sample_data()
    story = Story.model_validate(data)
    assert len(story.characters) == 3
    assert len(story.locations) == 5
    assert len(story.endings) == 3
    assert canonical_hash(story) == canonical_hash(Story.model_validate(deepcopy(data)))


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(schema_version="unknown"),
    lambda d: d.update(extra="forbidden"),
    lambda d: d["characters"].append(deepcopy(d["characters"][0])),
    lambda d: d["locations"][0].update(id="../path"),
    lambda d: d["characters"][0].update(initial_location_id="missing"),
    lambda d: d["evidence"][0].update(fact_ids=["missing"]),
    lambda d: d["endings"][0]["conditions"]["all"].append(
        {"op": "has_evidence", "evidence_id": "missing", "expected": True}),
    lambda d: d["action_rules"][0].update(once=1),
    lambda d: d["action_rules"][0]["effects"].append({"op": "run_code", "code": "x"}),
    lambda d: d["action_rules"][0]["effects"].append(
        {"op": "trust_delta", "character_id": "zhou_yan", "value": True}),
    lambda d: d["action_rules"][0].update(once=False, effects=[
        {"op": "trust_delta", "character_id": "zhou_yan", "value": 1}]),
    lambda d: d["action_rules"][0]["effects"].append(
        {"op": "trust_delta", "character_id": "lin_lan", "value": 1}),
])
def test_invalid_story_is_rejected(mutate):
    data = sample_data()
    mutate(data)
    with pytest.raises(ValidationError):
        Story.model_validate(data)


@pytest.mark.parametrize("action", [
    {"type": "investigate", "object_id": "notice", "effects": []},
    {"type": "move", "location_id": 1},
    {"type": "execute", "code": "print('no')"},
    {"type": "talk", "character_id": "zhou_yan"},
])
def test_action_schema_rejects_untrusted_fields(action):
    with pytest.raises(ValidationError):
        parse_action(action)
