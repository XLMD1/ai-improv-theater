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
    assert set(registry.specs) == {('story.generate','v2'),('story.repair','v2'),('story.content_generate','v1'),
                                 ('story.content_repair','v1'),('story.semantic_check','v1'),('scene.semantic_check','v1')}
    assert registry.get('story.generate','v2').input_schema != registry.get('story.repair','v2').input_schema
    assert registry.get('story.generate','v2').timeout_seconds == 120
    assert registry.get('story.repair','v2').timeout_seconds == 120
    assert registry.get('story.semantic_check','v1').timeout_seconds == 20
    assert OUTPUT_BUDGETS['story.generate'] == 12000 and OUTPUT_BUDGETS['scene.semantic_check'] == 2000
    for name in ('story.content_generate','story.content_repair'):
        assert registry.get(name,'v1').timeout_seconds == 120 and OUTPUT_BUDGETS[name] == 12000
    assert registry.get('story.content_generate','v1').input_schema != registry.get('story.content_repair','v1').input_schema


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


@pytest.mark.asyncio
@pytest.mark.parametrize('name,version',[('story.content_generate','draft-1'),('story.content_repair','draft-2')])
@pytest.mark.parametrize('prompt_version',['investigation-single-6','investigation-single-7'])
async def test_controlled_provider_receives_complete_output_slot_names_before_authoring(monkeypatch,name,version,prompt_version):
    import json,time
    from app.execution import ExecutionContext,ToolRegistry,execute
    from app.execution_traces import TaskRef
    from app.story_content import load_blueprint_template,assemble_story_content,BLUEPRINT_SHA256
    import app.story_operations as operations
    from test_execution import Recorder
    from test_custom_story_creation import successful_provider
    template=load_blueprint_template(str(uuid4()),version,'未来货运记录调查','future')
    received=[]
    async def provider(*args):
        received.append(json.loads(args[3].split('\n输入数据：',1)[1]))
        return await successful_provider(*args)
    monkeypatch.setattr(operations,'call_operation_provider',provider)
    monkeypatch.setattr(operations,'get_key',lambda provider:'fixture-key')
    registry=ToolRegistry();operations.register_story_operations(registry,prompt_version=prompt_version)
    context=ExecutionContext(TaskRef('creation','task','session'),time.monotonic()+120,
                             'deepseek','deepseek-flash',Recorder(),budget_check=lambda:None)
    data={'story_id':template.story_id,'story_version':version,'setting':template.setting,'era':'future',
          'blueprint_version':'controlled-investigation-1','blueprint_sha256':BLUEPRINT_SHA256,'template':template.model_dump()}
    if name.endswith('repair'):data.update(raw_candidate='{}',issues=['missing action_feedback'])
    result=await execute(registry,name,'v1',data,context)
    assert result.status=='success'
    assert assemble_story_content(template,result.output).story_version==version
    if prompt_version=='investigation-single-6':
        assert 'content_slots' not in received[0]
        return
    slots=received[0]['content_slots']
    assert set(slots)=={'characters','locations','objects','evidence','disclosures','commitments','action_feedback','event_feedback','endings','truth_facts'}
    assert slots['action_feedback']==[rule.id for rule in template.action_rules]
    assert slots['event_feedback']==[event.id for event in template.events]
    assert len(slots['characters'])==3 and len(slots['locations'])==5 and len(slots['endings'])==3
    assert assemble_story_content(template,result.output).story_version==version
