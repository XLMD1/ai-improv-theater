import importlib.util
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_investigation_schema import sample_data


def schemas():
    assert importlib.util.find_spec('app.operation_schemas'), 'operation schemas missing'
    import app.operation_schemas as module
    return module


def test_story_input_strict_identity_and_extra_fields():
    module = schemas()
    valid = {'story_id':str(uuid4()),'story_version':'draft-1','setting':'调查故事','era':'modern'}
    assert module.StoryGenerateInput.model_validate(valid).era == 'modern'
    for extra in ({'story_id':'not-uuid'},{'approval_status':'approved'},{'era':'invented'}):
        with pytest.raises(ValidationError):
            module.StoryGenerateInput.model_validate({**valid,**extra})


def test_semantic_report_rejects_contradiction_and_unknown_entity():
    module = schemas()
    with pytest.raises(ValidationError):
        module.SemanticReport.model_validate({'passed':True,'issues':[{'code':'public_leak','entity_ids':[],'description':'leak'}]})
    from app.story_schema import Story
    report = module.SemanticReport.model_validate({'passed':False,'issues':[{'code':'contradiction','entity_ids':['unknown'],'description':'wrong'}]})
    with pytest.raises(ValueError,match='semantic_reference'):
        module.validate_semantic_report(report,Story.model_validate(sample_data()))


def test_story_operations_have_separate_strict_schemas_and_budgets():
    assert importlib.util.find_spec('app.story_operations'), 'story operations missing'
    from app.execution import ToolRegistry
    from app.story_operations import register_story_operations, OUTPUT_BUDGETS
    registry = ToolRegistry()
    register_story_operations(registry)
    assert set(registry.specs) == {('story.generate','v2'),('story.repair','v2'),('story.semantic_check','v1'),('scene.semantic_check','v1')}
    assert registry.get('story.generate','v2').input_schema != registry.get('story.repair','v2').input_schema
    assert registry.get('story.generate','v2').timeout_seconds == 120
    assert registry.get('story.repair','v2').timeout_seconds == 120
    assert registry.get('story.semantic_check','v1').timeout_seconds == 20
    assert OUTPUT_BUDGETS['story.generate'] == 12000 and OUTPUT_BUDGETS['scene.semantic_check'] == 2000


@pytest.mark.asyncio
@pytest.mark.parametrize('remaining', [300, .05])
async def test_generation_http_and_wall_timeout_share_policy_and_remaining_deadline(monkeypatch,remaining):
    import asyncio
    import time
    from app.execution import ExecutionContext,ToolRegistry,execute
    from app.execution_traces import TaskRef
    from app.provider_clients import ProviderOutcome
    import app.story_operations as operations
    from app.story_schema import Story
    from test_execution import Recorder
    limits = []
    original = asyncio.timeout
    def timeout(value):
        limits.append(('wall',value))
        return original(value)
    async def provider(*args):
        limits.append(('http',args[-1]))
        return ProviderOutcome(Story.model_validate(sample_data()).model_dump_json(),20,20,request_sent=True)
    monkeypatch.setattr(asyncio,'timeout',timeout)
    monkeypatch.setattr(operations,'call_operation_provider',provider)
    registry = ToolRegistry()
    operations.register_story_operations(registry)
    context = ExecutionContext(TaskRef('creation','task','session'),time.monotonic()+remaining,
                               'deepseek','deepseek-flash',Recorder(),budget_check=lambda:None)
    result = await execute(registry,'story.generate','v2',
                           {'story_id':str(uuid4()),'story_version':'draft-1','setting':'调查故事','era':'modern'},context)
    assert result.status == 'success'
    assert [kind for kind,_ in limits] == ['wall','http']
    assert 0 < limits[1][1] <= limits[0][1] <= min(120,remaining)+1e-9
    assert abs(limits[1][1]-limits[0][1]) < .01
