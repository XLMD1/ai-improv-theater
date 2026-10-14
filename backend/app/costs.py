"""Conservative local cost estimates, not a guarantee of provider billing."""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.models import CostReservation, ExecutionTrace, LLMCall
from app.usage_reconciliation import reconciled_usage


PRICE_VERSION = "2026-10-08-peak-usd-cny7.5"
EXECUTION_PRICE_VERSION = "2026-10-10-flash-peak-usd-cny7.5"
USD_TO_CNY = Decimal("7.5")
USD_PER_MILLION = {
    "deepseek": (Decimal("0.30"), Decimal("1.20")),
}
WARNING_CNY = Decimal("80")
LIMIT_CNY = Decimal("100")


def estimate_cny(provider: str, input_tokens: int, output_tokens: int) -> Decimal:
    input_rate, output_rate = USD_PER_MILLION[provider]
    usd = (Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate) / Decimal(1_000_000)
    return (usd * USD_TO_CNY).quantize(Decimal("0.000001"))


def total_spend_cny(db) -> Decimal:
    return _accounted_spend_cny(db,reconciled_usage(db))


def _accounted_spend_cny(db,evidence) -> Decimal:
    estimated = db.scalar(select(func.coalesce(func.sum(LLMCall.estimated_cost_cny), 0)).where(
                          LLMCall.id.not_in(list(evidence)))) or Decimal(0)
    return estimated + sum((item.actual_cost_cny for item in evidence.values()),Decimal(0))


def budget_status(db) -> dict:
    from app.budget import reserved_cny
    spent = total_spend_cny(db)
    reserved = reserved_cny(db)
    unknown = db.scalar(select(CostReservation.attempt_id).where(CostReservation.status == 'uncertain',
                       CostReservation.call_id.not_in(list(reconciled_usage(db)))).limit(1))
    unknown = unknown or db.scalar(select(LLMCall.id).where(LLMCall.usage_status=='uncertain',
                                  LLMCall.id.not_in(list(reconciled_usage(db)))).limit(1))
    return {
        "estimated_spend_cny": float(spent),
        "reserved_cny": float(reserved), "cost_unconfirmed": bool(unknown),
        "warning_cny": int(WARNING_CNY), "limit_cny": int(LIMIT_CNY),
        "status": "blocked" if spent + reserved >= LIMIT_CNY or unknown else "warning" if spent + reserved >= WARNING_CNY else "ok",
    }


def check_execution_budget(db, estimated_cost=Decimal(0), *, exclude_attempt=None):
    """Unknown incurred usage or an unfinished audit blocks another external call."""
    confirmed = reconciled_usage(db)
    from app.budget import reserved_cny
    if _accounted_spend_cny(db,confirmed) + reserved_cny(db) + Decimal(str(estimated_cost)) >= LIMIT_CNY:
        raise ValueError('budget_exhausted')
    if db.scalar(select(LLMCall.id).where(LLMCall.usage_status == 'uncertain',LLMCall.id.not_in(list(confirmed))).limit(1)):
        raise ValueError('cost_unconfirmed')
    finished = aliased(ExecutionTrace)
    complete = select(finished.id).where(finished.trace_id == ExecutionTrace.trace_id,
                                         finished.span_id == ExecutionTrace.span_id,
                                         finished.event_type == 'attempt_finished').exists()
    reserved = select(CostReservation.attempt_id).where(CostReservation.attempt_id == ExecutionTrace.id).exists()
    orphan = select(ExecutionTrace.id).where(ExecutionTrace.event_type == 'attempt_started', ~complete, ~reserved)
    if exclude_attempt:
        orphan = orphan.where(ExecutionTrace.id != exclude_attempt)
    if db.scalar(orphan.limit(1)):
        raise ValueError('audit_incomplete')
