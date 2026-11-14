"""Cross-system progress metrics that legitimately span QuizQuestion-practice and ESSLCE (the two systems
stay separate at the data-model level, per the project's own system-boundaries rule - this router only
combines their already-independently-queried attempt DATES at the API layer, never their schemas)."""

from datetime import datetime, timedelta

from api.routes_mass_challenge import weekly_leaderboard
from auth.dependencies import get_current_user, require_bot_internal_token
from db.models import TelegramLink, User
from db.models_practice import QuizAttempt
from db.session import get_db
from exams.models import EsslceAttempt, EsslcePaper
from config.constants import ESSLCE_SKILL_STRAND_SUBJECTS, subject_visible
from exams.store import (
    eligible_skill_strands,
    eligible_units,
    readiness,
    recommend_focus,
    student_progress,
)
from fastapi import APIRouter, Depends
from practice.selection import local_date, study_streak, today_local
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1/progress", tags=["progress"])


@router.get("/streak")
def streak(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Consecutive days with at least one attempt, in EITHER system - a student who practices from the
    textbook bank one day and an ESSLCE past paper the next should see that as one unbroken streak."""
    practice_dates = {
        local_date(row[0])
        for row in db.query(QuizAttempt.created_at).filter(QuizAttempt.user_id == user.id).all()
    }
    esslce_dates = {
        local_date(row[0])
        for row in db.query(EsslceAttempt.created_at).filter(EsslceAttempt.user_id == user.id).all()
    }
    return {"streak_days": study_streak(practice_dates | esslce_dates)}


def weakest_unit(db: Session, user_id) -> dict | None:
    """The single weakest ESSLCE unit across every subject this student has practised, using the
    same per-subject signal the ESSLCE progress screen already recommends from (recommend_focus:
    lowest accuracy among units with enough attempts to mean something). unit_index is that unit's
    position in eligible_units(subject) - the same list the bot's unit picker shows - so a button
    can open practice on exactly that unit. None until some unit has enough attempts."""
    subjects = [
        row[0]
        for row in db.query(EsslcePaper.subject)
        .join(EsslceAttempt, EsslceAttempt.paper_id == EsslcePaper.id)
        .filter(EsslceAttempt.user_id == user_id)
        .distinct()
    ]
    best = None
    for subject in subjects:
        focus = recommend_focus(student_progress(db, user_id, subject))
        if focus is None or focus["kind"] != "unit":
            continue
        if best is None or focus["accuracy"] < best["accuracy"]:
            best = {**focus, "subject": subject}
    if best is None:
        return None
    units = eligible_units(db, best["subject"])
    index = next(
        (i for i, u in enumerate(units) if u["unit"] == best["unit"] and u["grade"] == best["grade"]), None
    )
    return {
        "subject": best["subject"],
        "grade": best["grade"],
        "unit": best["unit"],
        "accuracy": best["accuracy"],
        "unit_index": index,
    }


@router.get("/weekly-reports", dependencies=[Depends(require_bot_internal_token)])
def weekly_reports(db: Session = Depends(get_db)) -> dict:
    """One summary per Telegram-linked student for the last 7 local days (today included): days
    with any practice in either system, questions answered, accuracy, this week's mass-practice
    rank, and the weakest unit. For the bot's Sunday message."""
    first_day = today_local() - timedelta(days=6)
    since = datetime.utcnow() - timedelta(days=8)
    activity: dict = {}
    for model in (QuizAttempt, EsslceAttempt):
        for user_id, ok, ts in db.query(model.user_id, model.is_correct, model.created_at).filter(
            model.created_at >= since
        ):
            day = local_date(ts)
            if day < first_day:
                continue
            row = activity.setdefault(user_id, {"days": set(), "answered": 0, "correct": 0})
            row["days"].add(day)
            row["answered"] += 1
            row["correct"] += bool(ok)

    ranks = {e.user_id: i + 1 for i, e in enumerate(weekly_leaderboard(db).entries)}
    reports = []
    for link in db.query(TelegramLink).all():
        row = activity.get(link.user_id, {"days": set(), "answered": 0, "correct": 0})
        reports.append(
            {
                "telegram_user_id": link.telegram_user_id,
                "days_practised": len(row["days"]),
                "answered": row["answered"],
                "accuracy": row["correct"] / row["answered"] if row["answered"] else None,
                "mass_rank": ranks.get(str(link.user_id)),
                "mass_participants": len(ranks),
                "weakest": weakest_unit(db, link.user_id),
            }
        )
    return {"reports": reports}


@router.get("/readiness")
def exam_readiness(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Projected ESSLCE score per subject (exams/store.py's readiness), for every subject the
    student chose or has practised, plus days left to their exam date."""
    practised = {
        row[0]
        for row in db.query(EsslcePaper.subject)
        .join(EsslceAttempt, EsslceAttempt.paper_id == EsslcePaper.id)
        .filter(EsslceAttempt.user_id == user.id)
        .distinct()
    }
    subjects = sorted(
        s for s in practised | set(user.subjects_selected or []) if subject_visible(s, user.stream)
    )
    out = []
    for subject in subjects:
        skills = subject in ESSLCE_SKILL_STRAND_SUBJECTS
        weights = eligible_skill_strands(db, subject) if skills else eligible_units(db, subject)
        if not weights:
            continue
        r = readiness(student_progress(db, user.id, subject), weights, "skills" if skills else "units")
        out.append({"subject": subject, **r})
    days_left = (user.exam_date - today_local()).days if user.exam_date else None
    return {"exam_date": user.exam_date, "days_left": days_left, "subjects": out}
