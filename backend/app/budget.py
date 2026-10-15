"""Shared cost reservations; all mutations hold one PostgreSQL account lock."""
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.models import BudgetAccount, CostReservation


def lock_budget(db):
    db.execute(insert(BudgetAccount).values(id=1).on_conflict_do_nothing())
    db.scalar(select(BudgetAccount).where(BudgetAccount.id == 1).with_for_update())


def reserved_cny(db):
    from app.usage_reconciliation import reconciled_usage
    confirmed = reconciled_usage(db)
    return sum((row.amount_cny for row in db.scalars(select(CostReservation).where(
        CostReservation.status.in_(['reserved', 'uncertain']))) if row.call_id not in confirmed), Decimal(0))


def reserve(db, attempt_id, data):
    from app.costs import check_execution_budget
    lock_budget(db)
    amount = Decimal(data['estimate'])
    if not amount.is_finite() or amount < 0:
        raise ValueError('invalid_reservation')
    # The new attempt is not visible to the orphan-audit check yet.
    if data.get('chargeable',True): check_execution_budget(db, amount, exclude_attempt=attempt_id)
    db.add(CostReservation(attempt_id=attempt_id, amount_cny=amount, status='reserved',
           provider=data['provider'], model_id=data['model_id'], price_version=data['price_version'],chargeable=data.get('chargeable',True)))


def settle(db, attempt_id, call):
    lock_budget(db)
    row = db.get(CostReservation, attempt_id)
    if row:
        row.status = 'uncertain' if call and call.usage_status == 'uncertain' else 'settled'
        row.call_id = call.id if call else None
