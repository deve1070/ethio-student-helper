"""A free trial of everything, started the first time a student links the Telegram bot.

Linking is the moment chosen because the bot is what brings a trial student back each day (the
reminders, the evening group, the trial-ending messages in growth/nudges.py); a trial nobody is
reminded of is mostly wasted.

One trial ever per phone number or email and per Telegram account, recorded in FreeTrial, whose
rows outlive the account. A student who has ever had a subscription (paid or granted) gets none.
The trial is an ordinary Subscription row with plan="trial", so every feature, the private group's
join check and its daily sweep of lapsed members treat it like a paid one. Paying during a trial
extends that row and turns it into a paid plan (payments/subscription.py)."""

from datetime import datetime, timedelta, timezone

from config.settings import settings
from db.models import FreeTrial, Subscription, User
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError


def _identifier(user: User) -> str | None:
    return user.phone_number or user.email


def start_trial_if_eligible(db, user: User, telegram_user_id: int) -> datetime | None:
    """Starts the trial and returns when it ends, or None if this student cannot have one.
    Does not commit; the caller commits with its own change."""
    if settings.TRIAL_DAYS <= 0:
        return None
    identifier = _identifier(user)
    if identifier is None:
        return None
    if db.query(Subscription.id).filter(Subscription.user_id == user.id).first() is not None:
        return None
    used = (
        db.query(FreeTrial.id)
        .filter(or_(FreeTrial.identifier == identifier, FreeTrial.telegram_user_id == telegram_user_id))
        .first()
    )
    if used is not None:
        return None
    now = datetime.now(timezone.utc)
    ends = now + timedelta(days=settings.TRIAL_DAYS)
    try:
        with db.begin_nested():  # two links at once for the same number: the second gets no trial
            db.add(FreeTrial(identifier=identifier, telegram_user_id=telegram_user_id, user_id=user.id, started_at=now, ends_at=ends))
            db.add(Subscription(user_id=user.id, plan="trial", status="active", current_period_end=ends))
    except IntegrityError:
        return None
    return ends
