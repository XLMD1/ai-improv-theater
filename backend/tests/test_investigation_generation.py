import json
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch

import pytest

from app.execution import ToolRegistry,ToolSuccess
from app.investigation import initial_investigation_state
from app.operation_schemas import Interpretation,SceneTextDraft,SemanticReport
from app.schemas import Action
from app.story_schema import Story
from pydantic import ValidationError
from test_investigation_schema import sample_data


def setup():
    import app.investigation_generation as module
    assert hasattr(module,'interpret_action'), 'action interpretation missing'
    story = Story.model_validate(sample_data())
    state = initial_investigation_state(story)
    options,mapping = module.build_public_options(story,state)
    return module,story,state,mapping


def test_render_schema_cannot_set_state_or_location_and_operations_have_budgets():
    for extra in ({'state_changes':[]},{'scene_id':'elsewhere'},{'options':[]}):
        with pytest.raises(ValidationError):
            SceneTextDraft.model_validate({'narration':'说明','dialogue':[],**extra})
    from app.story_operations import register_investigation_operations,OUTPUT_BUDGETS
    registry = ToolRegistry()
    register_investigation_operations(registry)
    assert set(registry.specs) == {(name,'v1') for name in ('action.interpret','scene.render','scene.semantic_check')}
    assert OUTPUT_BUDGETS['action.interpret'] == 300 and OUTPUT_BUDGETS['scene.render'] == 900


@pytest.mark.asyncio
async def test_option_skips_interpretation_and_foreign_option_is_rejected():
    module,story,state,mapping = setup()
    with patch('app.investigation_generation.execute',new_callable=AsyncMock) as executor:
        key = next(iter(mapping))
        assert await module.interpret_action(story,state,mapping,Action(type='option',value=key),[],ToolRegistry(),None) == mapping[key]
        with pytest.raises(module.GenerationError,match='invalid_option'):
            await module.interpret_action(story,state,mapping,Action(type='option',value='foreign'),[],ToolRegistry(),None)
        assert executor.await_count == 0


@pytest.mark.asyncio
async def test_text_receives_public_context_and_unrecognized_is_none():
    module,story,state,mapping = setup()
    output = Interpretation.model_validate({'result':{'status':'unrecognized'}})
    with patch('app.investigation_generation.execute',new_callable=AsyncMock,return_value=ToolSuccess(output=output)) as executor:
        assert await module.interpret_action(story,state,mapping,Action(type='text',value='无效指令'),[],ToolRegistry(),None) is None
        inp = executor.call_args.args[3]
        assert 'truth' not in json.dumps(inp) and 'secret' not in json.dumps(inp)
        assert inp['available_actions'] == list(mapping.values())


@pytest.mark.asyncio
async def test_render_rejects_wrong_speaker_and_semantic_leak_without_repair():
    module,story,state,_ = setup()
    from app.state import apply_state_changes
    decision = apply_state_changes(state,story=story,action={'type':'investigate','object_id':'notice_board'})
    draft = SceneTextDraft(narration='秘密哨兵',dialogue=[])
    rejected = SemanticReport.model_validate({'passed':False,'issues':[{'code':'public_leak','entity_ids':[],'description':'leak'}]})
    ctx = SimpleNamespace(recorder=SimpleNamespace(event=lambda *args:None),task=None)
    with patch('app.investigation_generation.execute',new_callable=AsyncMock,side_effect=[ToolSuccess(output=draft),ToolSuccess(output=rejected)]) as executor:
        with pytest.raises(module.GenerationError,match='scene_semantic_rejected'):
            await module.render_investigation_scene(story,decision.state,{'type':'investigate','object_id':'notice_board'},decision.feedback,[],ToolRegistry(),ctx)
        assert executor.await_count == 2
    wrong = SceneTextDraft(narration='说明',dialogue=[{'character_id':story.protagonist_id,'text':'错误角色','emotion':'neutral'}])
    with patch('app.investigation_generation.execute',new_callable=AsyncMock,return_value=ToolSuccess(output=wrong)) as executor:
        with pytest.raises(module.GenerationError,match='invalid_scene_speaker'):
            await module.render_investigation_scene(story,state,{'type':'investigate','object_id':'notice_board'},'调查',[],ToolRegistry(),ctx)
        assert executor.await_count == 1
