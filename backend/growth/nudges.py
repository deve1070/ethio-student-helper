"""Bot messages at chosen moments, for Telegram-linked students who have not turned them off.

Each day the bot asks for the messages due today (POST /v1/growth/nudges). A student gets at most
one a day; when several are due, the first in this order wins and the others wait for a later day
(each moment is "on or after" a date, so a waiting one is still due tomorrow, until it is a week
stale):

  trial_ended     the free trial ended (within the last week) and they have not subscribed
  trial_ending    the free trial ends within 2 days
  countdown       their exam is 90, 60, 30, 14, 7, 3 or 1 day(s) away (exactly that day only)
  previews_used   they used up the free previews at least 2 days ago and have not subscribed
  inactive        they practised before, but not in the last 3 days

Each moment has a key, recorded in NudgeSent when it is handed to the bot, so it is sent once:
"trial:ended", "countdown:30", "inactive:<date of last practice>" (a new stretch of inactivity is a
new moment)."""

from datetime import date

from config.settings import settings
from db.models import FreeActionUsage, FreeTrial, NudgeSent, Subscription, TelegramLink, User
from db.models_practice import QuizAttempt
from exams.models import EsslceAttempt
from payments.entitlement import FREE_ACTION_QUOTA, has_active_subscription
from practice.selection import local_date, study_streak

COUNTDOWN_DAYS = (90, 60, 30, 14, 7, 3, 1)
TRIAL_ENDING_DAYS = 2
PREVIEWS_WAIT_DAYS = 2
INACTIVE_DAYS = 3
STALE_DAYS = 7  # a moment not sent within a week of it is dropped, not sent late


def _activity(db, user_ids) -> dict:
    """user_id -> set of local dates with any answer, in either question system."""
    days: dict = {}
    for model in (QuizAttempt, EsslceAttempt):
        for uid, ts in db.query(model.user_id, model.created_at).filter(model.user_id.in_(user_ids)):
            days.setdefault(uid, set()).add(local_date(ts))
    return days


def _answered(db, user_id, since=None) -> int:
    total = 0
    for model in (QuizAttempt, EsslceAttempt):
        q = db.query(model.id).filter(model.user_id == user_id)
        if since is not None:
            q = q.filter(model.created_at >= since)
        total += q.count()
    return total


def _is_trial(db, user_id) -> bool:
    sub = (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id, Subscription.status == "active")
        .order_by(Subscription.current_period_end.desc())
        .first()
    )
    return sub is not None and sub.plan == "trial"


def _previews_used_on(db, user_id) -> date | None:
    """The local date the last free preview was used, or None while some are left."""
    rows = (
        db.query(FreeActionUsage.created_at)
        .filter(FreeActionUsage.user_id == user_id)
        .order_by(FreeActionUsage.created_at)
        .limit(FREE_ACTION_QUOTA)
        .all()
    )
    return local_date(rows[-1][0]) if len(rows) >= FREE_ACTION_QUOTA else None


def _moment(db, user: User, today: date, days: set) -> list[tuple[str, str, dict]]:
    """Every (kind, key, extra data) due for this student today, in priority order, before
    checking what was already sent."""
    candidates = []
    trial = db.query(FreeTrial).filter(FreeTrial.user_id == user.id).one_or_none()
    subscribed = has_active_subscription(db, user.id)
    if trial is not None:
        ends = local_date(trial.ends_at)
        stats = {"answered": _answered(db, user.id, since=trial.started_at), "streak": study_streak(days)}
        if not subscribed and 0 < (today - ends).days <= STALE_DAYS:
            candidates.append(("trial_ended", "trial:ended", stats))
        elif subscribed and _is_trial(db, user.id) and 0 <= (ends - today).days <= TRIAL_ENDING_DAYS:
            candidates.append(("trial_ending", "trial:ending", {**stats, "days_left": (ends - today).days}))
    if user.exam_date is not None and (user.exam_date - today).days in COUNTDOWN_DAYS:
        n = (user.exam_date - today).days
        candidates.append(("countdown", f"countdown:{n}", {"days_left": n}))
    if not subscribed:
        used_on = _previews_used_on(db, user.id)
        if used_on is not None and PREVIEWS_WAIT_DAYS <= (today - used_on).days <= STALE_DAYS:
            candidates.append(("previews_used", "previews:used", {"answered": _answered(db, user.id)}))
    if days:
        last = max(days)
        if INACTIVE_DAYS <= (today - last).days <= INACTIVE_DAYS + STALE_DAYS:
            candidates.append(("inactive", f"inactive:{last.isoformat()}", {"days_away": (today - last).days}))
    return candidates


def due_nudges(db, today: date) -> list[dict]:
    """The messages due today, at most one per student, recorded as sent. Commits."""
    from api.routes_progress import weakest_unit  # the same weakest unit the Sunday report names

    links = (
        db.query(TelegramLink, User)
        .join(User, TelegramLink.user_id == User.id)
        .filter(User.nudges_off.is_(False))
        .all()
    )
    if not links:
        return []
    user_ids = [u.id for _, u in links]
    activity = _activity(db, user_ids)
    sent = {}
    for uid, key, sent_on in db.query(NudgeSent.user_id, NudgeSent.key, NudgeSent.sent_on).filter(
        NudgeSent.user_id.in_(user_ids)
    ):
        sent.setdefault(uid, {})[key] = sent_on

    out = []
    for link, user in links:
        already = sent.get(user.id, {})
        if today in already.values():
            continue  # one message a day at most
        due = next(((k, key, extra) for k, key, extra in _moment(db, user, today, activity.get(user.id, set())) if key not in already), None)
        if due is None:
            continue
        kind, key, extra = due
        if kind in ("inactive", "previews_used", "countdown"):
            extra = {**extra, "weakest": weakest_unit(db, user.id)}
        db.add(NudgeSent(user_id=user.id, key=key, sent_on=today))
        out.append({
            "telegram_user_id": link.telegram_user_id,
            "kind": kind,
            "first_name": (user.full_name or "").split(" ")[0] or None,
            "price_etb": settings.SUBSCRIPTION_PRICE_ETB,
            **extra,
        })
    db.commit()
    return out
