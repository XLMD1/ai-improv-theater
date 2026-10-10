"""Versioned, declarative investigation protocol. No executable story rules."""
import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, field_validator, model_validator

EntityId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", min_length=1, max_length=64)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Trust = Annotated[int, Field(strict=True, ge=-3, le=3)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Investigate(StrictModel):
    type: Literal["investigate"]
    object_id: EntityId


class Talk(StrictModel):
    type: Literal["talk"]
    character_id: EntityId
    topic_id: EntityId


class Present(StrictModel):
    type: Literal["present"]
    character_id: EntityId
    evidence_id: EntityId


class Move(StrictModel):
    type: Literal["move"]
    location_id: EntityId


class Decide(StrictModel):
    type: Literal["decide"]
    ending_id: EntityId


RuleAction = Annotated[Investigate | Talk | Present, Field(discriminator="type")]
Action = Annotated[Investigate | Talk | Present | Move | Decide, Field(discriminator="type")]
_action_adapter = TypeAdapter(Action)


def parse_action(data: dict):
    return _action_adapter.validate_python(data)


class AtLocation(StrictModel):
    op: Literal["at_location"]
    location_id: EntityId


class HasEvidence(StrictModel):
    op: Literal["has_evidence"]
    evidence_id: EntityId
    expected: bool


class HasDisclosure(StrictModel):
    op: Literal["has_disclosure"]
    disclosure_id: EntityId
    expected: bool


class HasCommitment(StrictModel):
    op: Literal["has_commitment"]
    commitment_id: EntityId
    expected: bool


class EventFired(StrictModel):
    op: Literal["event_fired"]
    event_id: EntityId
    expected: bool


class TrustAtLeast(StrictModel):
    op: Literal["trust_at_least"]
    character_id: EntityId
    value: Trust


Atom = Annotated[AtLocation | HasEvidence | HasDisclosure | HasCommitment | EventFired | TrustAtLeast,
                 Field(discriminator="op")]


class Conditions(StrictModel):
    all: list[Atom]


class DiscoverEvidence(StrictModel):
    op: Literal["discover_evidence"]
    evidence_id: EntityId


class Disclose(StrictModel):
    op: Literal["disclose"]
    disclosure_id: EntityId


class RecordCommitment(StrictModel):
    op: Literal["record_commitment"]
    commitment_id: EntityId


class TrustDelta(StrictModel):
    op: Literal["trust_delta"]
    character_id: EntityId
    value: Annotated[int, Field(strict=True, ge=-2, le=2)]


Effect = Annotated[DiscoverEvidence | Disclose | RecordCommitment | TrustDelta, Field(discriminator="op")]


class Character(StrictModel):
    id: EntityId
    name: Text
    goal: Text
    taboos: list[Text]
    appearance: Text
    initial_location_id: EntityId
    known_fact_ids: list[EntityId]
    secret_fact_ids: list[EntityId]


class Exit(StrictModel):
    location_id: EntityId
    conditions: Conditions


class Location(StrictModel):
    id: EntityId
    name: Text
    description: Text
    exits: list[Exit]


class InvestigationObject(StrictModel):
    id: EntityId
    location_id: EntityId
    name: Text
    description: Text


class Evidence(StrictModel):
    id: EntityId
    description: Text
    fact_ids: list[EntityId]


class Truth(StrictModel):
    text: Text
    facts: dict[EntityId, Text]


class Disclosure(StrictModel):
    id: EntityId
    character_id: EntityId
    fact_ids: list[EntityId]
    public_text: Text


class Commitment(StrictModel):
    id: EntityId
    character_id: EntityId
    public_text: Text


class ActionRule(StrictModel):
    id: EntityId
    action: RuleAction
    conditions: Conditions
    effects: list[Effect]
    once: bool
    feedback: Text

    @model_validator(mode="after")
    def finite_trust(self):
        if not self.once and any(e.op == "trust_delta" for e in self.effects):
            raise ValueError("trust changes require a once rule")
        return self


class Event(StrictModel):
    id: EntityId
    conditions: Conditions
    effects: list[Effect]
    feedback: Text


class Ending(StrictModel):
    id: EntityId
    conditions: Conditions
    title: Text
    consequence: Text


class Story(StrictModel):
    schema_version: Literal["investigation-story-1"]
    story_id: str
    story_version: Annotated[str, StringConstraints(min_length=1, max_length=30)]
    title: Text
    setting: Text
    era: Text
    public_intro: Text
    protagonist_id: EntityId
    start_location_id: EntityId
    characters: Annotated[list[Character], Field(min_length=3, max_length=3)]
    locations: Annotated[list[Location], Field(min_length=5, max_length=5)]
    objects: list[InvestigationObject]
    evidence: list[Evidence]
    truth: Truth
    disclosures: list[Disclosure]
    commitments: list[Commitment]
    action_rules: list[ActionRule]
    events: list[Event]
    endings: Annotated[list[Ending], Field(min_length=3, max_length=3)]

    @model_validator(mode="after")
    def references(self):
        if str(UUID(self.story_id)) != self.story_id:
            raise ValueError("story_id must be a canonical UUID")
        groups = {
            "character_id": {x.id for x in self.characters},
            "location_id": {x.id for x in self.locations},
            "object_id": {x.id for x in self.objects},
            "evidence_id": {x.id for x in self.evidence},
            "disclosure_id": {x.id for x in self.disclosures},
            "commitment_id": {x.id for x in self.commitments},
            "event_id": {x.id for x in self.events},
            "ending_id": {x.id for x in self.endings},
            "fact_id": set(self.truth.facts),
        }
        collections = [self.characters, self.locations, self.objects, self.evidence,
                       self.disclosures, self.commitments, self.action_rules, self.events, self.endings]
        ids = [x.id for collection in collections for x in collection] + list(self.truth.facts)
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate entity ID")

        def ref(field, value, npc=False):
            if value not in groups[field] or (npc and value == self.protagonist_id):
                raise ValueError(f"invalid reference: {field}={value}")

        def unique(values):
            if len(values) != len(set(values)):
                raise ValueError("duplicate reference")

        def conditions(value):
            for atom in value.all:
                field = next(key for key in type(atom).model_fields if key in groups)
                ref(field, getattr(atom, field), atom.op == "trust_at_least")

        def effects(values):
            for effect in values:
                field = next(key for key in type(effect).model_fields if key in groups)
                ref(field, getattr(effect, field), effect.op == "trust_delta")

        ref("character_id", self.protagonist_id)
        ref("location_id", self.start_location_id)
        for character in self.characters:
            ref("location_id", character.initial_location_id)
            for values in [character.known_fact_ids, character.secret_fact_ids]:
                unique(values)
                for value in values:
                    ref("fact_id", value)
        if next(c for c in self.characters if c.id == self.protagonist_id).initial_location_id != self.start_location_id:
            raise ValueError("protagonist must start at start_location_id")
        for location in self.locations:
            unique([e.location_id for e in location.exits])
            for exit in location.exits:
                ref("location_id", exit.location_id)
                if exit.location_id == location.id:
                    raise ValueError("self exit is invalid")
                conditions(exit.conditions)
        for obj in self.objects:
            ref("location_id", obj.location_id)
        for item in self.evidence + self.disclosures:
            unique(item.fact_ids)
            for fact in item.fact_ids:
                ref("fact_id", fact)
        for item in self.disclosures + self.commitments:
            ref("character_id", item.character_id, npc=True)
        for rule in self.action_rules:
            action = rule.action
            if action.type == "investigate":
                ref("object_id", action.object_id)
            else:
                ref("character_id", action.character_id, npc=True)
                if action.type == "present":
                    ref("evidence_id", action.evidence_id)
            conditions(rule.conditions)
            effects(rule.effects)
        for event in self.events:
            conditions(event.conditions)
            effects(event.effects)
        for ending in self.endings:
            conditions(ending.conditions)
        return self


class InvestigationState(StrictModel):
    schema_version: Literal[2]
    engine_version: Literal["investigation-1"]
    story_id: str
    story_version: Annotated[str, StringConstraints(min_length=1, max_length=30)]
    location_id: EntityId
    action_turn: Annotated[int, Field(strict=True, ge=0)]
    discovered_evidence: list[EntityId]
    disclosures: list[EntityId]
    commitments: list[EntityId]
    trust: dict[EntityId, Trust]
    applied_once_rules: list[EntityId]
    fired_events: list[EntityId]
    ending_id: EntityId | None

    @field_validator("schema_version", mode="before")
    @classmethod
    def strict_schema_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value

    @model_validator(mode="after")
    def canonical_sets(self):
        for name in ("discovered_evidence", "disclosures", "commitments", "applied_once_rules", "fired_events"):
            values = getattr(self, name)
            if len(values) != len(set(values)) or values != sorted(values):
                raise ValueError(f"{name} must be a sorted unique list")
        return self


def canonical_hash(story: Story) -> str:
    data = Story.model_validate(story.model_dump()).model_dump(mode="json")
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
