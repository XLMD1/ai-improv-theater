"""Strict local operator evidence, separate from original provider usage."""
from decimal import Decimal
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select

from app.models import ExecutionTrace, LLMCall


class UsageReconciliation(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)
    schema_version: Literal['usage-reconciliation-1']
    call_id: str = Field(pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    source: Literal['user_reported_provider_console']
    actual_cost_cny: Decimal = Field(ge=0, decimal_places=6)
    total_tokens: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def token_sum(self):
        if (self.input_tokens is None) != (self.output_tokens is None):
            raise ValueError('token_split_requires_pair')
        if self.input_tokens is not None and self.input_tokens+self.output_tokens != self.total_tokens:
            raise ValueError('token_total_mismatch')
        return self


class ReconciliationReceipt(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    event_id: str
    call_id: str
    duplicate: bool


def reconciled_usage(db):
    rows = db.execute(select(ExecutionTrace, LLMCall).join(LLMCall,ExecutionTrace.llm_call_id==LLMCall.id).where(
        ExecutionTrace.event_type=='usage_reconciled',LLMCall.usage_status=='uncertain',
        ExecutionTrace.trace_id==LLMCall.trace_id,ExecutionTrace.span_id==LLMCall.span_id,
        or_(ExecutionTrace.run_id==LLMCall.run_id,ExecutionTrace.creation_task_id==LLMCall.creation_task_id))).all()
    evidence = {}
    for row,call in rows:
        item = UsageReconciliation.model_validate_json(json.dumps(row.payload))
        if item.call_id != call.id:
            raise ValueError('invalid_reconciliation')
        if call.id in evidence and evidence[call.id] != item:
            raise ValueError('reconciliation_conflict')
        evidence[call.id] = item
    return evidence
