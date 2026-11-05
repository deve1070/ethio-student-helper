"""Deterministic (no LLM) aggregation of everything studyplan/planner.py needs to build a realistic,
multi-day plan: the exam countdown, which subjects this student's stream actually requires, how much of
each required subject's curriculum they've touched, and every weak spot across both practice systems -
all read from data that already exists in Postgres, never guessed. The only LLM call anywhere in this
feature lives in studyplan/coach.py, which explains a plan this module's numbers already fully
determined; nothing here calls an LLM or the network."""

import datetime

from config.constants import COMMON_SUBJECTS, NATURAL_ONLY_SUBJECTS, SOCIAL_ONLY_SUBJECTS, SUPPORTED_GRADES
from db.models import User
from exams.store import MIN_ATTEMPTS_FOR_SIGNAL, student_progress, unit_stats
from notes.store import available_units, viewed_units
from practice.progress import attempt_rows, weak_units_across_subjects
from utils.units import unit_sort_key

# Same "weak" cutoff practice.selection.classify_level uses for QuizQuestion practice, applied here to
# ESSLCE's own per-unit/skill accuracy too, so "weak" means the same thing on both sides of a plan -
# unlike recommend_focus() (exams/store.py), which picks the single lowest-accuracy row unconditionally
# (fine for "give me one thing to work on"), this needs a real threshold to decide which rows even count.
ESSLCE_WEAK_ACCURACY = 0.6


def required_subjects(user: User) -> tuple[list[str], list[str]]:
    """(required, missing). `required` is exactly what the student picked at onboarding
    (subjects_selected) - their own choice is never silently overridden or expanded. `missing` is any
    subject their own stream (natural vs social science) actually needs on the real ESSLCE that they
    have NOT picked - a real, previously unsurfaced gap (e.g. a natural-science student who never added
    Chemistry); always empty for grades 9-10, which have no stream yet."""
    picked = sorted(user.subjects_selected or [])
    if not user.stream:
        return picked, []
    stream_required = COMMON_SUBJECTS | (
        NATURAL_ONLY_SUBJECTS if user.stream == "natural_science" else SOCIAL_ONLY_SUBJECTS
    )
    return picked, sorted(stream_required - set(picked))


def days_remaining(user: User) -> int | None:
    """None if the student hasn't set an exam date yet (onboarding only asks Grade 12 students, and even
    then it's optional) - never guessed. Clamped at 0 so an exam date that's already passed doesn't hand
    the allocator a negative horizon."""
    if not user.exam_date:
        return None
    return max(0, (user.exam_date - datetime.date.today()).days)


def _curriculum_units(db, user: User, subject: str) -> set[tuple[int, str]]:
    """Every (grade, unit) in this subject's textbook corpus, across every grade up to the student's own
    - ESSLCE is cumulative across grades 9-12, so a grade-12 student's curriculum includes grade 9-11
    content too, not just this year's."""
    top_grade = user.grade_level or max(SUPPORTED_GRADES)
    out: set[tuple[int, str]] = set()
    for g in SUPPORTED_GRADES:
        if g > top_grade:
            continue
        for u in available_units(db, g, subject):
            out.add((g, u))
    return out


def _touched_units(db, user: User, subject: str) -> set[tuple[int, str]]:
    """Every (grade, unit) this student has engaged with in this subject, from every signal that
    actually exists: a Study Note they opened (any grade - notes.store.StudyNoteView), an ESSLCE
    past-paper attempt (any grade, via the question's own topic link), or a QuizQuestion-practice
    attempt (only ever at the student's current grade - that bank has no older-grade content to
    practice from, so it can't signal coverage of earlier grades on its own)."""
    touched = viewed_units(db, user.id, subject)
    touched |= {(row["grade"], row["unit"]) for row in student_progress(db, user.id, subject)["units"]}
    if user.grade_level:
        touched |= {
            (user.grade_level, unit)
            for unit, attempts, _correct in attempt_rows(db, user.id, user.grade_level, subject)
            if attempts > 0
        }
    return touched


def subject_profile(db, user: User, subject: str, weak_practice_rows: list[tuple[str, str, float]]) -> dict:
    """One required subject's full picture: curriculum coverage + every weak spot, from both practice
    systems independently (see esh_system_boundaries memory - QuizQuestion practice and the ESSLCE bank
    are never merged into one dataset, only their resulting signals are combined here).
    weak_practice_rows is weak_units_across_subjects' full result, computed once by build_profile for
    every required subject together rather than re-querying per subject."""
    full = _curriculum_units(db, user, subject)
    touched = (_touched_units(db, user, subject) & full) if full else set()
    uncovered = sorted(full - touched, key=lambda gu: (gu[0], unit_sort_key(gu[1])))

    progress = student_progress(db, user.id, subject)
    weak_esslce = [
        {"unit": r["unit"], "skill": None, "accuracy": r["accuracy"]}
        for r in progress["units"]
        if r["attempted"] >= MIN_ATTEMPTS_FOR_SIGNAL and r["accuracy"] < ESSLCE_WEAK_ACCURACY
    ] + [
        {"unit": None, "skill": r["skill"], "accuracy": r["accuracy"]}
        for r in progress["skills"]
        if r["attempted"] >= MIN_ATTEMPTS_FOR_SIGNAL and r["accuracy"] < ESSLCE_WEAK_ACCURACY
    ]
    weak_practice = [
        {"unit": unit, "accuracy": accuracy}
        for (s, unit, accuracy) in weak_practice_rows
        if s == subject
    ]

    return {
        "subject": subject,
        "coverage_ratio": round(len(touched) / len(full), 2) if full else None,
        "uncovered_units": [{"grade": g, "unit": u} for g, u in uncovered],
        "weak_esslce": weak_esslce,
        "weak_practice": weak_practice,
    }


def _test_weight(db, subjects: list[str]) -> dict[str, dict[str, int]]:
    """{subject: {unit: real past-paper question count}} - how often each unit has actually been
    tested, from exams.store.unit_stats (now a cheap SQL-aggregate query, not a full-ORM scan). Used
    only to break ties among uncovered units when studyplan/planner.py can't fit everything before the
    exam - the units that actually show up on the real ESSLCE get priority over ones that rarely do.
    Nested by subject (rather than a (subject, unit) tuple key) because this whole profile gets stored
    as JSON in StudyPlanWeek.profile_snapshot, and JSON object keys must be strings."""
    weight: dict[str, dict[str, int]] = {}
    for subject in subjects:
        for row in unit_stats(db, subject):
            weight.setdefault(row["subject"], {})[row["unit"]] = row["all_count"]
    return weight


def build_profile(db, user: User) -> dict:
    """The complete, deterministic input studyplan/planner.py needs - no LLM, no network call, just
    Postgres reads. Safe to call on every plan-generation request; every piece reuses an existing query
    rather than re-deriving it (see docs/dev_plans/rigorous_study_planner.md)."""
    required, missing = required_subjects(user)
    weak_practice_rows = (
        weak_units_across_subjects(db, user.id, user.grade_level, required) if user.grade_level else []
    )
    return {
        "required_subjects": required,
        "missing_subjects": missing,
        "days_remaining": days_remaining(user),
        "daily_goal_minutes": user.daily_goal_minutes,
        "subjects": [subject_profile(db, user, s, weak_practice_rows) for s in required],
        "test_weight": _test_weight(db, required),
    }
