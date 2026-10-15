"""Independent audit transactions; never commit story state here."""
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import re
from typing import Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.models import CostReservation, ExecutionTrace, ImageTask, LLMCall, Run, StoryTask
from app.usage_reconciliation import UsageReconciliation, ReconciliationReceipt


class TraceStorageFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class TaskRef:
    kind: Literal['action', 'creation', 'image']
    task_id: str
    session_id: str


@dataclass(frozen=True)
class AttemptRef:
    trace_id: str
    span_id: str
    attempt_id: str
    number: int


class TraceRecorder:
    def __init__(self, factory, secrets=(), token_hashes=()):
        self.factory = factory
        self.secrets = tuple(value for value in secrets if value)
        self.token_hashes = tuple(token_hashes)

    def redact(self, value):
        if isinstance(value, dict):
            return {key: '[redacted]' if re.search(r'authorization|api.?key|(?:^|_)token$|session_token|access_token|password|database.?url|reasoning_content|hidden_reasoning', key, re.I)
                    else self.redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, str):
            if len(value)>256_000:
                return '[oversized_payload]'
            for secret in self.secrets:
                value = value.replace(secret, '[redacted]')
            value = re.sub(r'[A-Za-z0-9_-]{16,200}',
                           lambda match:'[redacted]' if hashlib.sha256(match.group().encode()).hexdigest() in self.token_hashes
                           else match.group(),value)
            # Provider candidates are JSON strings at the audit boundary, even
            # when their business schema will subsequently reject them.
            try:
                parsed = json.loads(value)
            except (ValueError,RecursionError):
                if re.search(r'(?:session_token|access_token|api.?key|authorization|password|reasoning_content|hidden_reasoning)["\s\']*[:=]',value,re.I):
                    return '[unstructured_sensitive_payload]'
            else:
                return json.dumps(self.redact(parsed),ensure_ascii=False)
            value = re.sub(r'(?i)Bearer\s+[^\s"\,]+', '[redacted]', value)
            value = re.sub(r'(?i)(?:postgresql|postgres|mysql)(?:\+\w+)?://[^\s"\,]+', '[redacted]', value)
            value = re.sub(r'\bsk-[A-Za-z0-9_-]+', '[redacted]', value)
            return value
        return value

    def _task(self, db, ref):
        if ref.kind not in ('action', 'creation', 'image'):
            raise ValueError('task_not_found')
        cls = {'action': Run, 'creation': StoryTask, 'image': ImageTask}[ref.kind]
        task = db.scalar(select(cls).where(cls.id == ref.task_id, cls.session_id == ref.session_id).with_for_update())
        if task is None:
            raise ValueError('task_not_found')
        if task.trace_id is None:
            task.trace_id = str(uuid4())
        return task

    def _append(self, db, ref, task, event_type, payload, **kwargs):
        task.trace_seq += 1
        row = ExecutionTrace(trace_id=task.trace_id, seq=task.trace_seq, session_id=ref.session_id,
                             run_id=ref.task_id if ref.kind == 'action' else None,
                             creation_task_id=ref.task_id if ref.kind == 'creation' else None,
                             image_task_id=ref.task_id if ref.kind == 'image' else None,
                             event_type=event_type, payload=self.redact(payload), **kwargs)
        db.add(row)
        db.flush()
        return row

    def start(self, task):
        try:
            with self.factory.begin() as db:
                row = self._task(db, task)
                if row.trace_seq == 0:
                    self._append(db, task, row, 'task_started', {})
                return row.trace_id
        except SQLAlchemyError as error:
            raise TraceStorageFailure('trace_storage_failure') from error

    def event(self, task, event_type, payload):
        try:
            with self.factory.begin() as db:
                row = self._task(db, task)
                self._append(db, task, row, event_type, payload)
        except SQLAlchemyError as error:
            raise TraceStorageFailure('trace_storage_failure') from error

    def begin_attempt(self, task, operation, version, number, payload, budget=None):
        self.start(task)
        attempt_id, span_id = str(uuid4()), str(uuid4())
        try:
            with self.factory.begin() as db:
                row = self._task(db, task)
                self._append(db, task, row, 'attempt_started', {'operation': operation, 'version': version, 'input': payload},
                             id=attempt_id, span_id=span_id, attempt=number)
                if budget is not None:
                    from app.budget import reserve
                    reserve(db, attempt_id, budget)
                return AttemptRef(row.trace_id, span_id, attempt_id, number)
        except SQLAlchemyError as error:
            raise TraceStorageFailure('trace_storage_failure') from error

    def reconcile_usage(self, task_ref, raw_input):
        data = UsageReconciliation.model_validate(raw_input)
        payload = data.model_dump(mode='json')
        try:
            with self.factory.begin() as db:
                task = self._task(db,task_ref)
                call = db.get(LLMCall,data.call_id)
                if call is None or {'action':call.run_id,'creation':call.creation_task_id,'image':call.image_task_id}[task_ref.kind] != task_ref.task_id:
                    raise ValueError('call_not_found')
                if call.usage_status != 'uncertain':
                    raise ValueError('call_not_uncertain')
                finished = db.scalar(select(ExecutionTrace).where(ExecutionTrace.llm_call_id==call.id,
                         ExecutionTrace.trace_id==call.trace_id,ExecutionTrace.span_id==call.span_id,
                         ExecutionTrace.event_type=='attempt_finished'))
                if finished is None:
                    raise ValueError('attempt_not_finished')
                old = db.scalar(select(ExecutionTrace).where(ExecutionTrace.llm_call_id==call.id,
                                 ExecutionTrace.event_type=='usage_reconciled'))
                if old:
                    previous = UsageReconciliation.model_validate_json(json.dumps(old.payload))
                    if previous != data:
                        raise ValueError('reconciliation_conflict')
                    return ReconciliationReceipt(event_id=old.id,call_id=call.id,duplicate=True)
                event = self._append(db,task_ref,task,'usage_reconciled',payload,
                                     llm_call_id=call.id,span_id=call.span_id)
                return ReconciliationReceipt(event_id=event.id,call_id=call.id,duplicate=False)
        except SQLAlchemyError as error:
            raise TraceStorageFailure('trace_storage_failure') from error

    def finish_attempt(self, ref, provider_outcome, error_code):
        payload = self.redact({**provider_outcome, 'error_code': error_code})
        try:
            with self.factory.begin() as db:
                begin = db.get(ExecutionTrace, ref.attempt_id)
                if (begin is None or begin.trace_id != ref.trace_id or begin.span_id != ref.span_id
                        or begin.event_type != 'attempt_started'):
                    raise ValueError('attempt_not_found')
                task_ref = TaskRef('action' if begin.run_id else 'creation' if begin.creation_task_id else 'image',
                                   begin.run_id or begin.creation_task_id or begin.image_task_id, begin.session_id)
                task = self._task(db, task_ref)
                old = db.scalar(select(ExecutionTrace).where(ExecutionTrace.trace_id == ref.trace_id,
                                 ExecutionTrace.span_id == ref.span_id, ExecutionTrace.event_type == 'attempt_finished'))
                if old:
                    if old.payload != payload:
                        raise ValueError('attempt_result_conflict')
                    return
                call = None
                if provider_outcome.get('request_sent') and provider_outcome.get('chargeable', True):
                    cost = provider_outcome.get('estimated_cost_cny')
                    call = LLMCall(run_id=begin.run_id, creation_task_id=begin.creation_task_id, image_task_id=begin.image_task_id,
                                   trace_id=ref.trace_id, span_id=ref.span_id, attempt_id=ref.attempt_id,
                                   provider=provider_outcome['provider'], model_id=provider_outcome['model_id'],
                                   input_tokens=provider_outcome.get('input_tokens'), output_tokens=provider_outcome.get('output_tokens'),
                                   image_count=provider_outcome.get('image_count'),
                                   estimated_cost_cny=Decimal(str(cost)) if cost is not None else None,
                                   price_version=provider_outcome['price_version'], call_status=error_code or 'completed',
                                   usage_status='known' if provider_outcome.get('input_tokens') is not None or provider_outcome.get('image_count') is not None else 'uncertain')
                    db.add(call)
                    db.flush()
                from app.budget import settle
                settle(db, ref.attempt_id, call)
                self._append(db, task_ref, task, 'attempt_finished', payload, span_id=ref.span_id,
                             attempt=ref.number, llm_call_id=call.id if call else None, error_code=error_code,
                             duration_ms=provider_outcome.get('duration_ms'))
        except SQLAlchemyError as error:
            raise TraceStorageFailure('trace_storage_failure') from error


def interrupt_reservations(factory):
    """A started request has an unknown result after restart; never resend it."""
    with factory() as db:
        rows = list(db.scalars(select(CostReservation).where(CostReservation.status == 'reserved')))
    recorder = TraceRecorder(factory)
    for row in rows:
        with factory() as db:
            begin = db.get(ExecutionTrace, row.attempt_id)
            ref = AttemptRef(begin.trace_id, begin.span_id, begin.id, begin.attempt)
        recorder.finish_attempt(ref, dict(provider=row.provider, model_id=row.model_id,
            price_version=row.price_version, request_sent=True, chargeable=row.chargeable, estimated_cost_cny=None), 'process_restarted')
