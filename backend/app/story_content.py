"""Frozen investigation topology and strict model-authored content; no I/O beyond the asset."""
import hashlib
import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import field_validator

from app.story_schema import EntityId, Story, StrictModel, Text, Truth

BLUEPRINT_VERSION = 'controlled-investigation-1'
BLUEPRINT_SHA256 = '516f8804af3bf97df0b964a875a1d818c6ff084fd68ec552e092de016c438c9e'
BLUEPRINT_PATH = Path(__file__).parent/'data/controlled_investigation_v1.json'


class CharacterContent(StrictModel):
    name: Text
    goal: Text
    taboos: list[Text]
    appearance: Text


class NamedContent(StrictModel):
    name: Text
    description: Text


class EvidenceContent(StrictModel):
    description: Text


class EndingContent(StrictModel):
    title: Text
    consequence: Text


class ControlledStoryContent(StrictModel):
    schema_version: Literal['investigation-content-1']
    blueprint_version: Literal['controlled-investigation-1']
    story_id: str
    story_version: Literal['draft-1','draft-2']
    setting: Text
    era: Literal['ancient','modern','future']
    title: Text
    public_intro: Text
    characters: dict[EntityId,CharacterContent]
    locations: dict[EntityId,NamedContent]
    objects: dict[EntityId,NamedContent]
    evidence: dict[EntityId,EvidenceContent]
    truth: Truth
    disclosures: dict[EntityId,Text]
    commitments: dict[EntityId,Text]
    action_feedback: dict[EntityId,Text]
    event_feedback: dict[EntityId,Text]
    endings: dict[EntityId,EndingContent]

    @field_validator('story_id')
    @classmethod
    def identity(cls,value):
        if str(UUID(value)) != value:
            raise ValueError('invalid_identity')
        return value

    @classmethod
    def model_validate_json(cls,json_data,**kwargs):
        json.loads(json_data,object_pairs_hook=reject_duplicate_keys)
        return super().model_validate_json(json_data,**kwargs)


def reject_duplicate_keys(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise ValueError('duplicate_content_key')
        result[key] = value
    return result


def parse_story_content(raw: str) -> ControlledStoryContent:
    return ControlledStoryContent.model_validate_json(raw)


class Blueprint(StrictModel):
    blueprint_version: Literal['controlled-investigation-1']
    source_story_hash: Literal['dbdb37eb57b2eaf90eddfb42246189920147fa94adfeef85cf43598bcbd3ce79']
    template: Story


def load_blueprint_template(story_id: str,story_version: str,setting: str,era: str) -> Story:
    if str(UUID(story_id)) != story_id:
        raise ValueError('invalid_identity')
    raw = BLUEPRINT_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BLUEPRINT_SHA256:
        raise ValueError('blueprint_version_mismatch')
    source = Blueprint.model_validate_json(raw).template.model_dump(mode='json')
    groups = ('characters','locations','objects','evidence','disclosures','commitments','action_rules','events','endings')
    slots = {item['id'] for group in groups for item in source[group]} | set(source['truth']['facts'])
    slots.update(rule['action']['topic_id'] for rule in source['action_rules'] if rule['action']['type']=='talk')
    mapping = {slot:f'i_{UUID(story_id).hex}_{slot}' for slot in slots}

    def remap(value):
        if isinstance(value,list):
            return [remap(item) for item in value]
        if not isinstance(value,dict):
            return value
        result = {}
        for key,item in value.items():
            if key=='id' or key.endswith('_id'):
                result[key] = mapping.get(item,item)
            elif key.endswith('_ids'):
                result[key] = [mapping[i] for i in item]
            elif key=='facts':
                result[key] = {mapping[i]:text for i,text in item.items()}
            else:
                result[key] = remap(item)
        return result

    data = remap(source)
    data.update(story_id=story_id,story_version=story_version,setting=setting,era=era)
    return Story.model_validate(data)
