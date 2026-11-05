"""Student-facing multi-day Study Plan: GET generates this week's plan once per (user, week-start-date)
and serves the same tasks on every later request within that window, so a checked-off task doesn't lose
its identity if the student's weak-area signal shifts mid-week from further practice - same reasoning
the old single-day plan used, now over a real horizon tied to the exam countdown. Regenerated early if
the student's exam_date/stream/subjects_selected actually changed (see _stable_keys/_is_stale below),
not just because time has passed.

All the actual data-gathering and scheduling math live in studyplan/profile.py (deterministic profile:
exam countdown, curriculum coverage, weak areas - all reused from existing queries) and
studyplan/planner.py (deterministic day-by-day allocation); studyplan/coach.py makes the one LLM call in
this feature, to explain/motivate an already-decided schedule, never to choose it. See
docs/dev_plans/rigorous_study_planner.md for the full design and the alternatives considered."""

import datetime

from auth.dependencies import get_current_user
from db.models import User
from db.models_studyplan import StudyPlanWeek
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException
from llm.client import LLMClient
from sqlalchemy.orm import Session
from studyplan.coach import add_rationale
from studyplan.planner import build_week_plan
from studyplan.profile import build_profile

router = APIRouter(prefix="/v1/study-plan", tags=["study-plan"])


def _stable_keys(user: User) -> dict:
    """The only parts of a student's profile that justify throwing away a week's plan early - a new
    weak-area signal from further practice does NOT (see this module's own docstring); an actual
    change to the exam date, stream, or subject list does, since the existing plan may no longer even
    cover the right subjects."""
    return {
        "exam_date": user.exam_date.isoformat() if user.exam_date else None,
        "stream": user.stream,
        "subjects_selected": sorted(user.subjects_selected or []),
    }


def _get_or_create_week(db: Session, user: User) -> StudyPlanWeek:
    today = datetime.date.today()
    current_keys = _stable_keys(user)
    row = (
        db.query(StudyPlanWeek)
        .filter(StudyPlanWeek.user_id == user.id)
        .order_by(StudyPlanWeek.week_start_date.desc())
        .first()
    )
    if row is not None:
        window_end = row.week_start_date + datetime.timedelta(days=len(row.days) - 1)
        stale = row.profile_snapshot.get("_stable_keys") != current_keys
        if row.week_start_date <= today <= window_end and not stale:
            return row

    profile = build_profile(db, user)
    profile["_stable_keys"] = current_keys
    week_plan = build_week_plan(profile)
    week_plan = add_rationale(LLMClient(temperature=0.3, max_tokens=900), week_plan, profile)

    row = StudyPlanWeek(
        user_id=user.id,
        week_start_date=today,
        days=week_plan["days"],
        day_rationales=week_plan["day_rationales"],
        weekly_note=week_plan["weekly_note"],
        realistic=week_plan["realistic"],
        shortfall_minutes=week_plan["shortfall_minutes"],
        profile_snapshot=profile,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _serialize(row: StudyPlanWeek) -> dict:
    snapshot = row.profile_snapshot
    return {
        "week_start_date": row.week_start_date.isoformat(),
        "days_remaining": snapshot.get("days_remaining"),
        "realistic": row.realistic,
        "shortfall_minutes": row.shortfall_minutes,
        "missing_subjects": snapshot.get("missing_subjects", []),
        "coverage": {s["subject"]: s["coverage_ratio"] for s in snapshot.get("subjects", [])},
        "weekly_note": row.weekly_note,
        "days": [
            {
                "date": (row.week_start_date + datetime.timedelta(days=i)).isoformat(),
                "rationale": row.day_rationales[i] if i < len(row.day_rationales) else "",
                "tasks": tasks,
            }
            for i, tasks in enumerate(row.days)
        ],
    }


@router.get("/week")
def week(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return _serialize(_get_or_create_week(db, user))


@router.post("/week/days/{day_index}/tasks/{task_index}/done")
def mark_done(
    day_index: int,
    task_index: int,
    done: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    row = _get_or_create_week(db, user)
    if day_index < 0 or day_index >= len(row.days):
        raise HTTPException(status_code=404, detail="No such day in this week's plan.")
    day_tasks = row.days[day_index]
    if task_index < 0 or task_index >= len(day_tasks):
        raise HTTPException(status_code=404, detail="No such task in that day's plan.")

    days = [list(d) for d in row.days]
    days[day_index][task_index] = {**days[day_index][task_index], "done": done}
    row.days = days  # reassign (not mutate in place) so SQLAlchemy marks the JSON column dirty
    db.commit()
    db.refresh(row)
    return _serialize(row)
