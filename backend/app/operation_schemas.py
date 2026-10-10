"""Independent strict schemas for each registered model operation."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.story_schema import Action, EntityId, Story, StrictModel
from app.story_validation import ReachabilityReport


class StoryGenerateInput(StrictModel):
    story_id: str
    story_version: Literal['draft-1','draft-2']
    setting: Annotated[str, StringConstraints(strip_whitespace=True,min_length=1,max_length=500)]
    era: Literal['ancient','modern','future']

    @field_validator('story_id')
    @classmethod
    def identity(cls,value):
        if str(UUID(value)) != value:
            raise ValueError('invalid_identity')
        return value


class StoryRepairInput(StoryGenerateInput):
    raw_candidate: str = Field(max_length=256_000)
    issues: list[str] = Field(max_length=20)


class SemanticIssue(StrictModel):
    code: Literal['evidence_support','contradiction','public_leak','ending_consequence']
    entity_ids: list[EntityId]
    description: str = Field(min_length=1,max_length=1000)


class SemanticReport(StrictModel):
    passed: bool
    issues: list[SemanticIssue] = Field(max_length=20)

    @model_validator(mode='after')
    def consistent(self):
        if self.passed != (not self.issues):
            raise ValueError('inconsistent_semantic_report')
        return self


def validate_semantic_report(report,story):
    ids = set(story.truth.facts)
    for group in (story.characters,story.locations,story.objects,story.evidence,story.disclosures,
                  story.commitments,story.action_rules,story.events,story.endings):
        ids.update(entity.id for entity in group)
    if any(not set(issue.entity_ids).issubset(ids) for issue in report.issues):
        raise ValueError('semantic_reference')
    return report


class StorySemanticInput(StrictModel):
    story: Story
    reachability: ReachabilityReport


class PublicLocation(StrictModel):
    id: EntityId
    name: str
    description: str


class PublicCharacter(StrictModel):
    id: EntityId
    name: str
    appearance: str


class PublicObject(PublicLocation):
    pass


class PublicEvidence(StrictModel):
    id: EntityId
    description: str


class PublicStatement(StrictModel):
    id: EntityId
    text: str


class PublicEnding(StrictModel):
    id: EntityId
    title: str
    consequence: str


class PublicWorld(StrictModel):
    story_id: str
    story_version: str
    title: str
    setting: str
    era: str
    intro: str
    location: PublicLocation
    action_turn: int = Field(ge=0)
    characters: list[PublicCharacter]
    objects: list[PublicObject]
    evidence: list[PublicEvidence]
    disclosures: list[PublicStatement]
    commitments: list[PublicStatement]
    ending: PublicEnding | None


class RecentDialogue(StrictModel):
    character_id: EntityId
    text: str


class RecentTurn(StrictModel):
    scene_id: EntityId
    player_action: dict[str,str] | None
    narration: str
    dialogue: list[RecentDialogue]


class ActionInterpretInput(StrictModel):
    public_world: PublicWorld
    text: str = Field(min_length=1,max_length=500)
    available_actions: list[Action]
    action_labels: list[str]
    recent_turns: list[RecentTurn] = Field(max_length=3)

    @model_validator(mode='after')
    def labels_match(self):
        if len(self.action_labels)!=len(self.available_actions):
            raise ValueError('action_labels_mismatch')
        return self


class Recognized(StrictModel):
    status: Literal['recognized']
    action: Action


class Unrecognized(StrictModel):
    status: Literal['unrecognized']


class Interpretation(StrictModel):
    result: Annotated[Recognized | Unrecognized,Field(discriminator='status')]


class SceneDialogue(StrictModel):
    character_id: EntityId
    text: str = Field(min_length=1,max_length=280)
    emotion: Literal['neutral','joy','fear','anger','sadness']


class SceneTextDraft(StrictModel):
    narration: str = Field(min_length=1,max_length=1200)
    dialogue: list[SceneDialogue] = Field(max_length=2)


class SceneRenderInput(StrictModel):
    public_world: PublicWorld
    action: Action
    adjudication_feedback: str
    recent_turns: list[RecentTurn] = Field(max_length=3)


class SceneSemanticInput(StrictModel):
    story: Story
    public_world: PublicWorld
    adjudication_feedback: str
    candidate: SceneTextDraft
