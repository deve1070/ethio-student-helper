"""Schools, ambassadors, and the weekly top-schools ranking the bot posts to the public channel.

A student's school comes from one of two places: signing up with an ambassador's referral code
(they join the ambassador's school), or choosing it on their Profile. Schools are added by an
admin from the bot (/add_school), so the list stays clean instead of every student typing a
different spelling."""

from datetime import datetime, timedelta, timezone

from db.models import School, User
from db.models_practice import QuizAttempt
from exams.models import EsslceAttempt
from sqlalchemy import func

LEADERBOARD_SIZE = 10


def find_school(db, text: str) -> School | None:
    """By id, or by name ignoring case."""
    text = text.strip()
    if text.isdigit():
        return db.get(School, int(text))
    return db.query(School).filter(func.lower(School.name) == text.lower()).one_or_none()


def weekly_ranking(db) -> list[dict]:
    """Schools ranked by questions their students answered in the last 7 days (either system).
    Only schools with at least one answer appear."""
    since = datetime.now(timezone.utc) - timedelta(days=7)
    answered: dict = {}
    students: dict = {}
    for model in (QuizAttempt, EsslceAttempt):
        rows = (
            db.query(User.school_id, model.user_id, func.count(model.id))
            .join(User, User.id == model.user_id)
            .filter(model.created_at >= since, User.school_id.isnot(None))
            .group_by(User.school_id, model.user_id)
            .all()
        )
        for school_id, user_id, n in rows:
            answered[school_id] = answered.get(school_id, 0) + n
            students.setdefault(school_id, set()).add(user_id)
    if not answered:
        return []
    names = {s.id: s.name for s in db.query(School).filter(School.id.in_(answered.keys()))}
    ranked = sorted(answered, key=lambda sid: (-answered[sid], names.get(sid, "")))
    return [
        {"school": names[sid], "answered": answered[sid], "active_students": len(students[sid])}
        for sid in ranked[:LEADERBOARD_SIZE]
        if sid in names
    ]
