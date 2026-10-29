"""DB-querying helpers for a user's QuizQuestion-practice attempt history. Unlike selection.py (pure
functions only), these touch the database - split out so both routes_practice.py and anything else that
needs a student's practice history (e.g. the study-plan generator, which looks across every subject, not
just one) share one query, not two copies of the same join."""

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from db.models_practice import QuizAttempt, QuizQuestion
from practice.selection import unit_progress


def attempt_rows(db: Session, user_id, grade: int, subject: str) -> list[tuple[str, int, int]]:
    """[(unit, attempts, correct)] for one user, grade and subject."""
    correct = func.coalesce(
        func.sum(case((QuizAttempt.is_correct.is_(True), 1), else_=0)), 0
    )
    rows = (
        db.query(QuizQuestion.unit_or_chapter, func.count(QuizAttempt.id), correct)
        .join(QuizAttempt, QuizAttempt.question_id == QuizQuestion.id)
        .filter(
            QuizAttempt.user_id == user_id,
            QuizQuestion.grade == grade,
            QuizQuestion.subject == subject,
        )
        .group_by(QuizQuestion.unit_or_chapter)
        .all()
    )
    return [(u or "(no unit)", int(a), int(c)) for u, a, c in rows]


def attempt_timestamps(db: Session, user_id, grade: int, subject: str):
    """[(created_at, is_correct)] for one user, grade and subject - raw per-attempt rows, for daily_trend."""
    return (
        db.query(QuizAttempt.created_at, QuizAttempt.is_correct)
        .join(QuizQuestion, QuizAttempt.question_id == QuizQuestion.id)
        .filter(
            QuizAttempt.user_id == user_id,
            QuizQuestion.grade == grade,
            QuizQuestion.subject == subject,
        )
        .all()
    )


def weakest_unit_across_subjects(
    db: Session, user_id, grade: int, subjects: list[str]
) -> tuple[str, str, float] | None:
    """The single weakest (subject, unit) this student has enough attempts on to call "weak" with any
    confidence, across every subject given - or None if nothing has reached that bar yet (a brand new
    student, or one who's only ever gotten things right)."""
    best: tuple[str, str, float] | None = None
    for subject in subjects:
        for u in unit_progress(attempt_rows(db, user_id, grade, subject)):
            if u["level"] == "weak" and (best is None or u["accuracy"] < best[2]):
                best = (subject, u["unit"], u["accuracy"])
    return best
