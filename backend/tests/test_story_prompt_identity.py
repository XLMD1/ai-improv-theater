import json
from unittest.mock import patch

import pytest


@pytest.mark.parametrize('operation', ['story.generate','story.repair'])
def test_story_prompt_binds_identity_to_request_instead_of_old_draft(operation):
    from app.execution import ToolRegistry
    from app.story_operations import register_story_operations
    from app.operation_schemas import StoryGenerateInput, StoryRepairInput
    from app.provider_clients import ProviderOutcome
    from types import SimpleNamespace
    import asyncio,time
    request = {'story_id':'00000000-0000-0000-0000-000000000001',
               'story_version':'draft-2' if operation=='story.repair' else 'draft-1',
               'setting':'固定背景','era':'ancient'}
    value = (StoryRepairInput(**request,raw_candidate=json.dumps({**request,'story_version':'draft-1'}),issues=['fix'])
             if operation=='story.repair' else StoryGenerateInput(**request))
    captured = []
    async def provider(*args):
        captured.append(args[3])
        return ProviderOutcome('{}',1,1,request_sent=True)
    registry = ToolRegistry()
    register_story_operations(registry)
    from app.story_operations import OPERATION_VERSIONS
    spec = registry.get(operation,OPERATION_VERSIONS[operation])
    with patch('app.story_operations.call_operation_provider',side_effect=provider),patch('app.story_operations.get_key',return_value='fixture-key'):
        asyncio.run(spec.handler(value,SimpleNamespace(provider='deepseek',model_id='deepseek-flash',deadline=time.monotonic()+120)))
    schema = json.loads(captured[0].split('\n输出schema：',1)[1].split('\n输入数据：',1)[0])
    assert {field:schema['properties'][field].get('const') for field in request}==request


@pytest.mark.parametrize('count',[0,1,2])
def test_scene_prompt_limits_dialogue_to_current_speaker_ids(count):
    from app.execution import ToolRegistry
    from app.story_operations import register_investigation_operations
    from app.operation_schemas import SceneRenderInput
    from app.provider_clients import ProviderOutcome
    from app.investigation import public_projection,initial_investigation_state
    from app.story_schema import Story
    from test_investigation_schema import sample_data
    from types import SimpleNamespace
    import asyncio,time
    story = Story.model_validate(sample_data())
    world = public_projection(story,initial_investigation_state(story))
    world['characters'] = [{'id':f'npc_{i}','name':f'NPC {i}','appearance':'普通外貌'} for i in range(count)]
    value = SceneRenderInput(public_world=world,action={'type':'investigate','object_id':'notice_board'},
                             adjudication_feedback='调查反馈',recent_turns=[])
    captured=[]
    async def provider(*args):
        captured.append(args[3])
        return ProviderOutcome('{}',1,1,request_sent=True)
    registry=ToolRegistry()
    register_investigation_operations(registry)
    with patch('app.story_operations.call_operation_provider',side_effect=provider),patch('app.story_operations.get_key',return_value='fixture-key'):
        asyncio.run(registry.get('scene.render','v1').handler(value,
            SimpleNamespace(provider='deepseek',model_id='deepseek-flash',deadline=time.monotonic()+20)))
    schema=json.loads(captured[0].split('\n输出schema：',1)[1].split('\n输入数据：',1)[0])
    if count:
        assert schema['$defs']['SceneDialogue']['properties']['character_id'].get('enum')==[f'npc_{i}' for i in range(count)]
    else:
        assert schema['properties']['dialogue']['maxItems']==0
