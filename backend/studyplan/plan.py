"""Generates today's study plan: a short, deterministic task list sized to the student's own daily
time goal (User.daily_goal_minutes), drawing on whichever weak-area signal already exists in either
system - practice.progress.weakest_unit_across_subjects for QuizQuestion practice,
exams.store.student_progress/recommend_focus for ESSLCE, both reused as-is, never reimplemented.

Pure function, no DB access - the caller (api/routes_studyplan.py) gathers the candidates; this module
only decides how many of them fit the student's time budget and how to split the minutes."""

from dataclasses import dataclass

MIN_MINUTES_PER_TASK = 15


@dataclass
class TaskCandidate:
    kind: str  # "practice" | "esslce" | "mistakes" | "ask"
    label: str
    subject: str | None = None
    unit: str | None = None
    skill: str | None = None


def build_plan(daily_goal_minutes: int, candidates: list[TaskCandidate]) -> list[dict]:
    """candidates: ordered by priority, highest first. A "kind='ask'" candidate (if present) is always
    optional/flexible (no fixed minutes, never competes for the time budget) and always sorts last. The
    remaining ("required") candidates split daily_goal_minutes evenly, each getting at least
    MIN_MINUTES_PER_TASK - lower-priority ones are dropped first if the goal is too small to give
    everyone that much."""
    required = [c for c in candidates if c.kind != "ask"]
    optional = [c for c in candidates if c.kind == "ask"]

    max_tasks = max(0, daily_goal_minutes // MIN_MINUTES_PER_TASK)
    required = required[: max(1, max_tasks)] if required else []

    tasks = []
    if required:
        per_task = daily_goal_minutes // len(required)
        remainder = daily_goal_minutes - per_task * len(required)
        for i, c in enumerate(required):
            minutes = per_task + (remainder if i == len(required) - 1 else 0)
            tasks.append(_task_dict(c, minutes))
    for c in optional:
        tasks.append(_task_dict(c, None))
    return tasks


def _task_dict(c: TaskCandidate, minutes: int | None) -> dict:
    return {
        "kind": c.kind,
        "label": c.label,
        "subject": c.subject,
        "unit": c.unit,
        "skill": c.skill,
        "minutes": minutes,
        "done": False,
    }
