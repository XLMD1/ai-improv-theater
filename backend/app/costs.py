"""Conservative local cost estimates, not a guarantee of provider billing."""

from decimal import Decimal

from sqlalchemy import func, select

from app.models import LLMCall


PRICE_VERSION = "2026-10-08-peak-usd-cny7.5"
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
    return db.scalar(select(func.coalesce(func.sum(LLMCall.estimated_cost_cny), 0))) or Decimal(0)


def budget_status(db) -> dict:
    spent = total_spend_cny(db)
    return {
        "estimated_spend_cny": float(spent),
        "warning_cny": int(WARNING_CNY), "limit_cny": int(LIMIT_CNY),
        "status": "blocked" if spent >= LIMIT_CNY else "warning" if spent >= WARNING_CNY else "ok",
    }
