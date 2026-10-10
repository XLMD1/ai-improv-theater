import asyncio
import importlib.util
import time

import pytest
from pydantic import BaseModel, ConfigDict


class Input(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    value: int


class Output(Input):
    pass


class Recorder:
    def __init__(self):
        self.results = []
        self.events = []

    def start(self, task):
        return 'trace'

    def event(self, task, kind, payload):
        self.events.append(kind)

    def begin_attempt(self, *args):
        return args[3]

    def finish_attempt(self, ref, outcome, error):
        self.results.append((ref, outcome, error))

    def redact(self, value):
        return value


def setup(handler, **overrides):
    assert importlib.util.find_spec('app.execution'), 'executor is not implemented'
    from app.execution import ToolRegistry, ToolSpec, ExecutionContext
    from app.execution_traces import TaskRef
    registry = ToolRegistry()
    recorder = Recorder()
    registry.register(ToolSpec('test', 'v1', Input, Output, handler, 20, 3, frozenset({'rate_limited','connect_failure'}), 'non_idempotent_external', lambda _: 0))
    context = ExecutionContext(TaskRef('creation', 'test', 'session'), time.monotonic()+60,
                               'deepseek', 'deepseek-flash', recorder, budget_check=lambda: None, **overrides)
    return registry, context


@pytest.mark.asyncio
@pytest.mark.parametrize('name,data,code', [('unknown', {'value':1},'unknown_tool'), ('test',{'value':True},'input_validation')])
async def test_invalid_requests_do_not_execute(name, data, code):
    async def handler(*args):
        pytest.fail('invalid request executed')
    registry, context = setup(handler)
    from app.execution import execute
    result = await execute(registry, name, 'v1', data, context)
    assert result.error_code == code and not context.recorder.results


@pytest.mark.asyncio
@pytest.mark.parametrize('code,expected', [('unauthorized',1),('rate_limited',3),('outcome_unknown',1),('internal_error',1)])
async def test_error_classification_has_bounded_attempts(code, expected):
    from app.provider_clients import ModelResult
    async def handler(*args):
        from app.provider_clients import ProviderOutcome
        return ProviderOutcome(error_code=code, request_sent=code=='outcome_unknown', chargeable=code=='outcome_unknown')
    async def no_wait(delay):
        return None
    registry, context = setup(handler, sleep=no_wait, jitter=lambda:0)
    from app.execution import execute
    result = await execute(registry,'test','v1',{'value':1},context)
    assert result.error_code == code
    assert len(context.recorder.results) == expected


@pytest.mark.asyncio
async def test_output_validation_keeps_incurred_usage():
    async def handler(*args):
        from app.provider_clients import ProviderOutcome
        return ProviderOutcome(text='{"value":true}',input_tokens=12,output_tokens=8,request_sent=True)
    registry, context = setup(handler)
    from app.execution import execute
    result = await execute(registry,'test','v1',{'value':1},context)
    assert result.error_code == 'output_validation'
    assert context.recorder.results[0][1]['input_tokens'] == 12
    assert len(context.recorder.results) == 1


@pytest.mark.asyncio
async def test_deadline_includes_retry_after():
    async def handler(*args):
        from app.provider_clients import ProviderOutcome
        return ProviderOutcome(error_code='rate_limited',retry_after=61,chargeable=False)
    registry, context = setup(handler)
    from app.execution import execute
    result = await execute(registry,'test','v1',{'value':1},context)
    assert result.error_code == 'task_timeout'
    assert len(context.recorder.results) == 1


@pytest.mark.asyncio
async def test_cancellation_propagates():
    async def handler(*args):
        raise asyncio.CancelledError()
    registry, context = setup(handler)
    from app.execution import execute
    with pytest.raises(asyncio.CancelledError):
        await execute(registry,'test','v1',{'value':1},context)
    assert context.stopped and context.recorder.results[0][2] == 'cancelled'


@pytest.mark.asyncio
async def test_storage_failure_stops_later_calls():
    async def handler(*args):
        pytest.fail('must stop before handler')
    registry, context = setup(handler)
    from app.execution import execute
    from app.execution_traces import TraceStorageFailure
    def unavailable(*args):
        raise TraceStorageFailure('unavailable')
    context.recorder.begin_attempt = unavailable
    result = await execute(registry,'test','v1',{'value':1},context)
    assert result.error_code == 'storage_failure' and context.stopped


@pytest.mark.asyncio
async def test_attempt_wall_timeout_does_not_retry():
    from dataclasses import replace
    async def handler(*args):
        await asyncio.Event().wait()
    registry, context = setup(handler)
    registry.specs[('test','v1')] = replace(registry.get('test','v1'),timeout_seconds=.01)
    from app.execution import execute
    result = await execute(registry,'test','v1',{'value':1},context)
    assert result.error_code == 'outcome_unknown' and len(context.recorder.results) == 1


def test_duplicate_registration_rejected():
    async def handler(*args):
        pass
    registry, _ = setup(handler)
    with pytest.raises(ValueError,match='duplicate_tool'):
        registry.register(registry.get('test','v1'))


@pytest.mark.asyncio
async def test_safe_rate_limit_then_success():
    attempts = []
    async def handler(*args):
        from app.provider_clients import ProviderOutcome
        attempts.append(1)
        if len(attempts) == 1:
            return ProviderOutcome(error_code='rate_limited',chargeable=False)
        return ProviderOutcome(text='{"value":2}',input_tokens=12,output_tokens=8,request_sent=True)
    async def no_wait(delay):
        pass
    registry, context = setup(handler,sleep=no_wait,jitter=lambda:0)
    from app.execution import execute
    result = await execute(registry,'test','v1',{'value':1},context)
    assert result.output.value == 2 and len(context.recorder.results) == 2


@pytest.mark.asyncio
async def test_handler_exception_is_structured_and_not_retried():
    async def handler(*args):
        raise RuntimeError('private diagnostic')
    registry, context = setup(handler)
    from app.execution import execute
    result = await execute(registry,'test','v1',{'value':1},context)
    assert result.error_code == 'internal_error' and len(context.recorder.results) == 1
    assert 'private diagnostic' not in str(context.recorder.results)
