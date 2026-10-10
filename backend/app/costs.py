"""Conservative local cost estimates, not a guarantee of provider billing."""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.models import ExecutionTrace, LLMCall
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
    spent = total_spend_cny(db)
    return {
        "estimated_spend_cny": float(spent),
        "warning_cny": int(WARNING_CNY), "limit_cny": int(LIMIT_CNY),
        "status": "blocked" if spent >= LIMIT_CNY else "warning" if spent >= WARNING_CNY else "ok",
    }


def check_execution_budget(db, estimated_cost=Decimal(0)):
    """Unknown incurred usage or an unfinished audit blocks another external call."""
    confirmed = reconciled_usage(db)
    if _accounted_spend_cny(db,confirmed) + Decimal(str(estimated_cost)) >= LIMIT_CNY:
        raise ValueError('budget_exhausted')
    if db.scalar(select(LLMCall.id).where(LLMCall.usage_status == 'uncertain',LLMCall.id.not_in(list(confirmed))).limit(1)):
        raise ValueError('cost_unconfirmed')
    finished = aliased(ExecutionTrace)
    complete = select(finished.id).where(finished.trace_id == ExecutionTrace.trace_id,
                                         finished.span_id == ExecutionTrace.span_id,
                                         finished.event_type == 'attempt_finished').exists()
    if db.scalar(select(ExecutionTrace.id).where(ExecutionTrace.event_type == 'attempt_started', ~complete).limit(1)):
        raise ValueError('audit_incomplete')
