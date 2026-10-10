"""One validated boundary for registered external operations."""
import asyncio
from dataclasses import asdict, dataclass, field
import random
import time
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app.costs import PRICE_VERSION, check_execution_budget, estimate_cny
from app.execution_traces import TaskRef, TraceRecorder, TraceStorageFailure
from app.provider_clients import ProviderOutcome


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    handler: Callable
    timeout_seconds: float
    max_attempts: int
    retry_codes: frozenset[str]
    side_effect_policy: Literal['pure','read_only','idempotent_external','non_idempotent_external']
    estimate_cost: Callable

    def __post_init__(self):
        if not 0 < self.timeout_seconds <= 20 or not 1 <= self.max_attempts <= 3:
            raise ValueError('invalid_execution_policy')
        for schema in (self.input_schema, self.output_schema):
            if schema.model_config.get('extra') != 'forbid' or not schema.model_config.get('strict'):
                raise ValueError('strict_schema_required')


class ToolRegistry:
    def __init__(self):
        self.specs = {}

    def register(self, spec):
        key = (spec.name, spec.version)
        if key in self.specs:
            raise ValueError('duplicate_tool')
        self.specs[key] = spec

    def get(self, name, version):
        return self.specs.get((name, version))


@dataclass
class ExecutionContext:
    task: TaskRef
    deadline: float
    provider: str
    model_id: str
    recorder: TraceRecorder
    budget_check: Callable | None = None
    sleep: Callable = asyncio.sleep
    jitter: Callable = field(default=lambda: random.uniform(0, .25))
    stopped: bool = False

    def check_budget(self, estimate):
        if self.budget_check:
            self.budget_check()
        else:
            with self.recorder.factory() as db:
                check_execution_budget(db, estimate)


class ToolSuccess(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    status: Literal['success'] = 'success'
    output: BaseModel


class ToolFailure(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    status: Literal['failure'] = 'failure'
    error_code: str
    raw_candidate: str | None = None


ToolResult = ToolSuccess | ToolFailure


async def execute(registry, name, version, raw_input, context):
    if context.stopped:
        return ToolFailure(error_code='execution_stopped')
    try:
        context.recorder.start(context.task)
        spec = registry.get(name, version)
        if spec is None:
            context.recorder.event(context.task, 'validation_failed', {'error_code':'unknown_tool'})
            return ToolFailure(error_code='unknown_tool')
        try:
            validated = spec.input_schema.model_validate(raw_input)
        except ValidationError:
            context.recorder.event(context.task, 'validation_failed', {'error_code':'input_validation'})
            return ToolFailure(error_code='input_validation')
        for number in range(1, spec.max_attempts + 1):
            remaining = context.deadline - time.monotonic()
            if remaining <= 0:
                return ToolFailure(error_code='task_timeout')
            try:
                context.check_budget(spec.estimate_cost(validated))
            except ValueError as error:
                context.recorder.event(context.task, 'budget_blocked', {'error_code':str(error)})
                return ToolFailure(error_code=str(error))
            ref = context.recorder.begin_attempt(context.task,name,version,number,validated.model_dump(mode='json'))
            started = time.monotonic()
            cancelled = False
            try:
                async with asyncio.timeout(min(spec.timeout_seconds, remaining)):
                    outcome = await spec.handler(validated, context)
                if not isinstance(outcome, ProviderOutcome):
                    raise TypeError('invalid_handler_result')
            except asyncio.CancelledError:
                cancelled = True
                context.stopped = True
                outcome = ProviderOutcome(error_code='cancelled', request_sent=True)
            except TimeoutError:
                outcome = ProviderOutcome(error_code='outcome_unknown', request_sent=True)
            except Exception:
                outcome = ProviderOutcome(error_code='internal_error', request_sent=True)
            data = asdict(outcome)
            data.update(provider=context.provider,model_id=context.model_id,price_version=PRICE_VERSION,
                        duration_ms=round((time.monotonic()-started)*1000),estimated_cost_cny=None)
            if outcome.input_tokens is not None and outcome.output_tokens is not None:
                data['estimated_cost_cny'] = str(estimate_cny(context.provider,outcome.input_tokens,outcome.output_tokens))
            context.recorder.finish_attempt(ref,data,outcome.error_code)
            if cancelled:
                raise asyncio.CancelledError()
            if outcome.error_code:
                safe = outcome.error_code in {'rate_limited','connect_failure'}
                retry = safe and outcome.error_code in spec.retry_codes and number < spec.max_attempts
                if not retry:
                    return ToolFailure(error_code=outcome.error_code)
                delay = max(.5 * 2**(number-1) + context.jitter(),outcome.retry_after or 0)
                if delay >= context.deadline-time.monotonic():
                    return ToolFailure(error_code='task_timeout')
                context.recorder.event(context.task,'retry_wait',{'attempt':number,'seconds':delay})
                await context.sleep(delay)
                continue
            try:
                if outcome.text is None or len(outcome.text.encode('utf-8')) > 256_000:
                    raise ValueError('invalid_output_size')
                output = spec.output_schema.model_validate_json(outcome.text)
            except (ValueError, ValidationError):
                context.recorder.event(context.task,'output_validation_failed',{'operation':name,'attempt':number})
                raw = context.recorder.redact(outcome.text or '')[:256_000]
                return ToolFailure(error_code='output_validation',raw_candidate=raw)
            if time.monotonic() >= context.deadline:
                return ToolFailure(error_code='task_timeout')
            context.recorder.event(context.task,'output_validated',{'operation':name,'output':output.model_dump(mode='json')})
            return ToolSuccess(output=output)
    except TraceStorageFailure:
        context.stopped = True
        return ToolFailure(error_code='storage_failure')
    except asyncio.CancelledError:
        context.stopped = True
        raise
    except ValueError:
        return ToolFailure(error_code='authorization_or_validation_error')
