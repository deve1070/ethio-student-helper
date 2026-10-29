"""
Single guard every paid feature calls before doing expensive work.
Balance is derived by summing credit_ledger, never stored as a running
counter, so entitlement is always computed from the ledger itself —
never trust a client's locally cached credit count.
"""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import CreditLedgerEntry, Subscription


def get_credit_balance(db: Session, user_id: UUID) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(CreditLedgerEntry.delta), 0)).where(
            CreditLedgerEntry.user_id == user_id
        )
    )
    return int(total or 0)


def has_active_subscription(db: Session, user_id: UUID) -> bool:
    sub = (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id, Subscription.status == "active")
        .order_by(Subscription.current_period_end.desc())
        .first()
    )
    if sub is None:
        return False
    if sub.current_period_end and sub.current_period_end < datetime.now(timezone.utc):
        return False
    return True


def require_credits(db: Session, user_id: UUID, cost: int) -> None:
    """Raise 402 Payment Required if the user can't cover `cost`.

    An active subscription bypasses the credit check entirely; otherwise
    the ledger balance must cover the cost. Call this right before the
    expensive step (an LLM call), not at the top of the request — a
    request that turns out to be a cache hit should never be blocked by
    an empty credit balance.
    """
    if cost <= 0:
        return
    if has_active_subscription(db, user_id):
        return
    balance = get_credit_balance(db, user_id)
    if balance < cost:
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Not enough credits for this action.",
                "balance": balance,
                "required": cost,
            },
        )
