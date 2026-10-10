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
    assert set(registry.specs) == {(name,'v1') for name in ['story.generate','story.repair','story.semantic_check','scene.semantic_check']}
    assert registry.get('story.generate','v1').input_schema != registry.get('story.repair','v1').input_schema
    assert OUTPUT_BUDGETS['story.generate'] == 12000 and OUTPUT_BUDGETS['scene.semantic_check'] == 2000
