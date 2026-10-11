import json
import time
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.execution import ExecutionContext, ToolRegistry, ToolSuccess, execute
from app.execution_traces import TaskRef
from app.provider_clients import ProviderOutcome
from app.schemas import Action
from test_execution import Recorder


def final_choice():
    from test_controlled_story import template
    from app.story_validation import check_reachability
    from app.investigation import initial_investigation_state
    from app.state import apply_state_changes
    from app.investigation_generation import build_public_options
    story = template()
    ending = next(e.id for e in story.endings if e.id.endswith('_guard_together'))
    state = initial_investigation_state(story)
    for action in check_reachability(story).ending_paths[ending][:-1]:
        state = apply_state_changes(state, story=story, action=action).state
    options, mapping = build_public_options(story, state)
    index = next(i for i, value in enumerate(mapping.values()) if value == {'type': 'decide', 'ending_id': ending})
    return story, state, mapping, options[index]['label'], index


@pytest.mark.parametrize('result', [
    {'status': 'recognized', 'action_index': -1},
    {'status': 'recognized', 'action_index': True},
    {'status': 'recognized', 'action_index': '0'},
    {'status': 'recognized', 'action': {'type': 'talk', 'character_id': 'zhou_yan', 'topic_id': 'verify_together'}},
    {'status': 'recognized', 'action_index': 0, 'action': {'type': 'move', 'location_id': 'archive'}},
    {'status': 'unrecognized', 'action_index': 0},
])
def test_selection_schema_rejects_coercion_and_model_actions(result):
    from app import operation_schemas
    assert hasattr(operation_schemas, 'SelectedInterpretation')
    with pytest.raises(ValidationError):
        operation_schemas.SelectedInterpretation.model_validate({'result': result})


@pytest.mark.asyncio
async def test_final_public_label_selects_current_ending_without_invented_topic():
    from app import operation_schemas
    import app.investigation_generation as module
    story, state, mapping, label, index = final_choice()
    before = deepcopy(state)
    assert hasattr(operation_schemas, 'SelectedInterpretation')
    output = operation_schemas.SelectedInterpretation.model_validate({'result': {'status': 'recognized', 'action_index': index}})
    with patch.object(module, 'execute', new_callable=AsyncMock, return_value=ToolSuccess(output=output)) as executor:
        chosen = await module.interpret_action(story, state, mapping, Action(type='text', value=label), [],
                                               ToolRegistry(), None, version='v2')
    assert chosen == list(mapping.values())[index] and chosen['type'] == 'decide'
    assert executor.call_args.args[2] == 'v2' and executor.await_count == 1 and state == before


@pytest.mark.asyncio
@pytest.mark.parametrize('recognized', [False, True])
async def test_unrecognized_or_out_of_range_never_maps_to_an_action(recognized):
    from app import operation_schemas
    import app.investigation_generation as module
    story, state, mapping, label, index = final_choice()
    assert hasattr(operation_schemas, 'SelectedInterpretation')
    result = {'status': 'recognized', 'action_index': len(mapping)} if recognized else {'status': 'unrecognized'}
    output = operation_schemas.SelectedInterpretation.model_validate({'result': result})
    with patch.object(module, 'execute', new_callable=AsyncMock, return_value=ToolSuccess(output=output)) as executor:
        if recognized:
            with pytest.raises(module.GenerationError, match='invalid_action_index'):
                await module.interpret_action(story, state, mapping, Action(type='text', value=label), [],
                                              ToolRegistry(), None, version='v2')
        else:
            assert await module.interpret_action(story, state, mapping, Action(type='text', value=label), [],
                                                 ToolRegistry(), None, version='v2') is None
    assert executor.await_count == 1


@pytest.mark.asyncio
async def test_v2_prompt_has_bounded_choices_and_v1_retains_its_contract():
    from app.story_operations import register_investigation_operations
    from app.investigation import public_projection
    from app.investigation_generation import interpret_action
    story, state, mapping, label, index = final_choice()
    registry = ToolRegistry()
    register_investigation_operations(registry)
    assert registry.get('action.interpret', 'v2') is not None
    spec = registry.get('action.interpret', 'v2')
    assert (spec.timeout_seconds, spec.max_attempts, spec.side_effect_policy) == (20, 3, 'non_idempotent_external')
    assert spec.retry_codes == frozenset({'rate_limited', 'connect_failure'})
    labels = ['move', 'sink', 'guard', 'publish']
    assert len(mapping) == len(labels)
    inputs = {'public_world': public_projection(story, state), 'text': 'guard', 'available_actions': list(mapping.values()),
              'action_labels': labels, 'recent_turns': []}
    seen = []
    async def provider(*args):
        prompt = args[3]
        seen.append(prompt)
        if 'action.interpret.v2' in prompt:
            return ProviderOutcome(json.dumps({'result': {'status': 'recognized', 'action_index': index}}), 20, 20, request_sent=True)
        return ProviderOutcome(json.dumps({'result': {'status': 'recognized', 'action': list(mapping.values())[index]}}), 20, 20, request_sent=True)
    context = ExecutionContext(TaskRef('action', 'test', 'session'), time.monotonic() + 60,
                               'deepseek', 'deepseek-flash', Recorder(), budget_check=lambda: None)
    with patch('app.story_operations.call_operation_provider', side_effect=provider):
        result = await execute(registry, 'action.interpret', 'v2', inputs, context)
        assert result.status == 'success' and result.output.result.action_index == index
        old = await interpret_action(story, state, mapping, Action(type='text', value=label), [], registry, context)
    assert old == list(mapping.values())[index] and len(seen) == 2
    schema = json.loads(seen[0].split('\n输出schema：')[1].split('\n输入数据：')[0])
    data = json.loads(seen[0].split('\n输入数据：')[1])
    assert schema['$defs']['Selected']['properties']['action_index']['enum'] == list(range(len(mapping)))
    assert data['action_choices'] == [{'action_index': i, 'label': text} for i, text in enumerate(labels)]
    assert 'action_choices' not in json.loads(seen[1].split('\n输入数据：')[1])


@pytest.mark.parametrize('result,code', [
    ({'status': 'recognized', 'action_index': 999}, 'invalid_action_index'),
    ({'status': 'recognized', 'action': {'type': 'investigate', 'object_id': 'notice_board'}}, 'output_validation'),
])
def test_r1_invalid_selection_keeps_usage_and_parent_without_partial_node(result, code):
    from test_custom_story_creation import client, successful_provider
    from test_investigation_api import approved, turn
    from app.db import SessionLocal
    from app.models import ExecutionTrace, LLMCall
    from sqlalchemy import select
    with client() as c, patch('app.story_operations.call_operation_provider', side_effect=successful_provider):
        headers, root = approved(c)
        try:
            async def provider(*args):
                return ProviderOutcome(json.dumps({'result': result}), 20, 20, request_sent=True)
            with patch('app.story_operations.call_operation_provider', side_effect=provider) as external:
                run = turn(c, headers, root['id'], {'type': 'text', 'value': '调查公开告示载体'})
            assert run['status'] == 'failed' and run['error_code'] == code and run['node_id'] is None
            assert external.call_count == 1 and len(c.get('/tree', headers=headers).json()) == 1
            assert c.get('/nodes/' + root['id'], headers=headers).json() == root
            with SessionLocal() as db:
                attempt = db.scalar(select(ExecutionTrace).where(ExecutionTrace.run_id == run['id'],
                                     ExecutionTrace.event_type == 'attempt_started'))
                assert attempt.payload['version'] == 'v2'
                calls = db.scalars(select(LLMCall).where(LLMCall.run_id == run['id'])).all()
                assert len(calls) == 1 and calls[0].input_tokens == calls[0].output_tokens == 20
        finally:
            c.delete('/local-settings/keys/deepseek')
