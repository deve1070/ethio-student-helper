"""Student-facing Today's Study Plan: GET generates it once per calendar day (and serves the same
tasks on every later request that day), POST marks a task done/undone. Spans both QuizQuestion-practice
and ESSLCE the same way routes_progress.py's streak endpoint does - calling each system's OWN existing
progress logic independently and combining only the resulting task candidates, never their data models."""

import datetime

from auth.dependencies import get_current_user
from db.models import User
from db.models_practice import QuizQuestion
from db.models_studyplan import StudyPlanDay
from db.session import get_db
from exams.models import EsslcePaper
from exams.store import recommend_focus, student_progress
from fastapi import APIRouter, Depends, HTTPException
from practice.progress import weakest_unit_across_subjects
from sqlalchemy.orm import Session
from studyplan.plan import TaskCandidate, build_plan

router = APIRouter(prefix="/v1/study-plan", tags=["study-plan"])

DEFAULT_GOAL_MINUTES = 60


def _practice_subjects(db: Session, user: User) -> list[str]:
    if user.subjects_selected:
        return user.subjects_selected
    if not user.grade_level:
        return []
    rows = (
        db.query(QuizQuestion.subject)
        .filter(QuizQuestion.grade == user.grade_level, QuizQuestion.status == "active")
        .distinct()
        .all()
    )
    return [r[0] for r in rows]


def _esslce_subjects(db: Session, user: User) -> list[str]:
    if user.subjects_selected:
        return user.subjects_selected
    return [r[0] for r in db.query(EsslcePaper.subject).distinct().all()]


def _gather_candidates(db: Session, user: User) -> list[TaskCandidate]:
    candidates: list[TaskCandidate] = []

    if user.grade_level:
        practice_subjects = _practice_subjects(db, user)
        weak = weakest_unit_across_subjects(db, user.id, user.grade_level, practice_subjects)
        if weak:
            subject, unit, _accuracy = weak
            candidates.append(TaskCandidate(kind="practice", label=f"Practice {unit}", subject=subject, unit=unit))
        elif practice_subjects:
            s = practice_subjects[0]
            candidates.append(
                TaskCandidate(kind="practice", label=f"Practice {s.replace('_', ' ').title()}", subject=s)
            )

    esslce_subjects = _esslce_subjects(db, user)
    best: tuple[str, dict] | None = None
    for subject in esslce_subjects:
        rec = recommend_focus(student_progress(db, user.id, subject))
        if rec and (best is None or rec["accuracy"] < best[1]["accuracy"]):
            best = (subject, rec)
    if best:
        subject, rec = best
        if rec["kind"] == "unit":
            candidates.append(
                TaskCandidate(kind="esslce", label=f"ESSLCE: {rec['unit']}", subject=subject, unit=rec["unit"])
            )
        else:
            candidates.append(
                TaskCandidate(kind="esslce", label=f"ESSLCE: {rec['skill']}", subject=subject, skill=rec["skill"])
            )
    elif esslce_subjects:
        s = esslce_subjects[0]
        candidates.append(
            TaskCandidate(kind="esslce", label=f"ESSLCE {s.replace('_', ' ').title()} practice", subject=s)
        )

    candidates.append(TaskCandidate(kind="ask", label="Ask a question about anything you're stuck on"))
    return candidates


def _get_or_create_today(db: Session, user: User) -> StudyPlanDay:
    plan_date = datetime.date.today()
    row = (
        db.query(StudyPlanDay)
        .filter(StudyPlanDay.user_id == user.id, StudyPlanDay.plan_date == plan_date)
        .one_or_none()
    )
    if row is None:
        goal = user.daily_goal_minutes or DEFAULT_GOAL_MINUTES
        tasks = build_plan(goal, _gather_candidates(db, user))
        row = StudyPlanDay(user_id=user.id, plan_date=plan_date, tasks=tasks)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@router.get("/today")
def today(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    row = _get_or_create_today(db, user)
    return {"plan_date": row.plan_date.isoformat(), "tasks": row.tasks}


@router.post("/today/tasks/{index}/done")
def mark_done(
    index: int,
    done: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    row = _get_or_create_today(db, user)
    if index < 0 or index >= len(row.tasks):
        raise HTTPException(status_code=404, detail="No such task in today's plan.")
    tasks = list(row.tasks)
    tasks[index] = {**tasks[index], "done": done}
    row.tasks = tasks  # reassign (not mutate in place) so SQLAlchemy marks the JSON column dirty
    db.commit()
    return {"plan_date": row.plan_date.isoformat(), "tasks": row.tasks}
