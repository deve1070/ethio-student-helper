"""Grants or extends the one-year subscription a completed payment buys. Called from both places
a Payment is ever marked 'completed' (api/routes_payments.py's submit_receipt auto-approve branch
and approve_payment's manual-admin branch) - same shared-helper pattern payments/referral.py's
credit_referral_if_first_payment already uses for the same two call sites."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from db.models import Subscription

SUBSCRIPTION_DURATION = timedelta(days=365)


def _as_utc(dt: datetime) -> datetime:
    """Postgres round-trips a DateTime(timezone=True) column as aware; SQLite (used by this
    project's tests) returns it naive regardless - treat a naive value as already UTC rather
    than letting the aware/naive comparison below raise."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def grant_or_extend_subscription(db: Session, user_id: UUID, duration: timedelta = SUBSCRIPTION_DURATION) -> Subscription:
    """`duration` is a year for a payment, or what an admin chose for a free grant (/v1/payments/grant).
    If the user already has an active, not-yet-expired subscription, extend it by `duration`
    from its current expiry (so renewing early stacks on top of remaining time rather than
    wasting it). Otherwise create a new one starting now. Does not commit - the caller commits
    once, alongside its own payment-status change."""
    now = datetime.now(timezone.utc)
    sub = (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id, Subscription.status == "active")
        .order_by(Subscription.current_period_end.desc())
        .first()
    )
    if sub is not None and sub.current_period_end and _as_utc(sub.current_period_end) > now:
        sub.current_period_end = _as_utc(sub.current_period_end) + duration
        if sub.plan == "trial":
            sub.plan = "yearly"  # paid or granted during the free trial: no longer a trial (growth/trial.py)
        return sub

    sub = Subscription(
        user_id=user_id,
        plan="yearly",
        status="active",
        current_period_end=now + duration,
    )
    db.add(sub)
    return sub
