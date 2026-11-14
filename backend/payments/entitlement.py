"""Single pair of guards every AI-gated feature calls: check_entitlement before the expensive
work, record_free_action only after it actually succeeds - mirrors the check-then-charge shape
api/routes_exam.py's old require_credits/_charge_credits pair already used, so a generation that
fails midway (a 422/503) never burns part of a student's free quota.

A student's free allowance is a single shared pool (FREE_ACTION_QUOTA) spent across every gated
feature - not a per-feature allowance - by design: the product goal is to let a student feel real
value across several different features before hitting the paywall, not lock any one feature on
first use. An active subscription bypasses the pool entirely, forever (has_active_subscription).
"""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import FreeActionUsage, Subscription, User

FREE_ACTION_QUOTA = 8


def _as_utc(dt: datetime) -> datetime:
    """Postgres round-trips a DateTime(timezone=True) column as aware; SQLite (used by this
    project's tests) returns it naive regardless - treat a naive value as already UTC rather
    than letting the aware/naive comparison below raise."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def has_active_subscription(db: Session, user_id: UUID) -> bool:
    sub = (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id, Subscription.status == "active")
        .order_by(Subscription.current_period_end.desc())
        .first()
    )
    if sub is None:
        return False
    if sub.current_period_end and _as_utc(sub.current_period_end) < datetime.now(timezone.utc):
        return False
    return True


def check_entitlement(db: Session, user: User, feature: str, resource_key: str | None) -> bool:
    """Raises HTTPException(402) if blocked. Returns True if the caller must call
    record_free_action(...) after the gated work succeeds - i.e. this call will consume a new
    free action; returns False if no recording is needed, either because the user has an active
    subscription or because this exact resource was already unlocked by this user before."""
    if has_active_subscription(db, user.id):
        return False

    if resource_key is not None:
        already_unlocked = db.scalar(
            select(FreeActionUsage.id).where(
                FreeActionUsage.user_id == user.id,
                FreeActionUsage.feature == feature,
                FreeActionUsage.resource_key == resource_key,
            )
        )
        if already_unlocked is not None:
            return False

    used = db.scalar(
        select(func.count(FreeActionUsage.id)).where(FreeActionUsage.user_id == user.id)
    )
    if (used or 0) >= FREE_ACTION_QUOTA:
        raise HTTPException(
            status_code=402,
            detail={
                "message": f"You've used all {FREE_ACTION_QUOTA} free previews. "
                "Subscribe for unlimited access all year.",
                "used": used,
                "quota": FREE_ACTION_QUOTA,
            },
        )
    return True


def record_free_action(db: Session, user: User, feature: str, resource_key: str | None) -> None:
    """Call only after the gated work actually succeeded, and only when check_entitlement
    returned True. A concurrent duplicate insert for the same (user, feature, resource_key) is
    caught by the table's unique constraint and swallowed, not raised - the response the caller
    already produced stands either way."""
    db.add(FreeActionUsage(user_id=user.id, feature=feature, resource_key=resource_key))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
