"""Deterministic (no LLM) multi-day task allocator - the actual scheduling intelligence behind the
study plan. Given one student's profile (studyplan/profile.py's build_profile) and their own daily time
goal, decides which subject/unit gets which day's minutes over a real multi-day horizon tied to the
exam countdown, instead of picking one day's tasks in isolation.

Pure function, no DB access - mirrors the old plan.py's own split (profile.py does the DB reads, this
module only does arithmetic), so the scheduling logic is fully unit-testable without a database."""

from dataclasses import dataclass

MIN_MINUTES_PER_TASK = 15
MAX_TASKS_PER_DAY = 3
DEFAULT_HORIZON_DAYS = 7
MAX_HORIZON_DAYS = 14


@dataclass
class Task:
    kind: str  # "notes" | "practice" | "esslce" | "ask"
    label: str
    subject: str | None = None
    unit: str | None = None
    skill: str | None = None
    minutes: int | None = None
    done: bool = False


def _subject_queue(subject_profile: dict, test_weight: dict[str, int]) -> list[dict]:
    """Every candidate task this subject could offer, highest-need first: a weak ESSLCE spot or weak
    practice spot (the student has already tried this and is getting it wrong) outranks an uncovered
    unit (the student hasn't started it yet) - fixing a known gap is more urgent than opening a new one.
    Among uncovered units, test_weight (exams.store.unit_stats's real past-paper question counts for
    this subject) breaks ties so a heavily-tested unit is queued before a rarely-tested one."""
    subject = subject_profile["subject"]
    queue = []
    for w in subject_profile["weak_esslce"]:
        label = w["unit"] or w["skill"]
        queue.append({
            "score": 20 - w["accuracy"], "kind": "esslce", "subject": subject,
            "unit": w["unit"], "skill": w["skill"], "label": f"ESSLCE review: {label}",
        })
    for w in subject_profile["weak_practice"]:
        queue.append({
            "score": 20 - w["accuracy"], "kind": "practice", "subject": subject,
            "unit": w["unit"], "skill": None, "label": f"Practice: {w['unit']}",
        })
    for u in subject_profile["uncovered_units"]:
        weight = test_weight.get(u["unit"], 0)
        queue.append({
            "score": 1 + weight * 0.05, "kind": "notes", "subject": subject,
            "unit": u["unit"], "skill": None, "label": f"Learn: {u['unit']}",
        })
    queue.sort(key=lambda c: -c["score"])
    return queue


def build_week_plan(profile: dict) -> dict:
    """profile: studyplan/profile.py's build_profile() output (includes daily_goal_minutes,
    days_remaining, required_subjects, per-subject weak/uncovered breakdowns, and test_weight).
    Returns {"horizon_days", "realistic", "shortfall_minutes", "days": [[task_dict, ...], ...]}.

    `realistic` is False, with `shortfall_minutes` set, when the total time needed to touch every weak
    spot and every uncovered unit at least once exceeds what the remaining days at this student's own
    daily pace can actually fit - a deterministic check, not a guess, so the plan never silently looks
    complete when it isn't."""
    daily_minutes = profile["daily_goal_minutes"] or 60
    days_remaining = profile["days_remaining"]
    horizon = min(days_remaining, MAX_HORIZON_DAYS) if days_remaining is not None else DEFAULT_HORIZON_DAYS
    horizon = max(horizon, 1)

    subjects = profile["required_subjects"]
    queues = {
        sp["subject"]: _subject_queue(sp, profile["test_weight"].get(sp["subject"], {}))
        for sp in profile["subjects"]
    }

    total_needed_minutes = sum(MIN_MINUTES_PER_TASK * len(q) for q in queues.values())
    total_available_minutes = horizon * daily_minutes
    realistic = total_needed_minutes <= total_available_minutes

    days: list[list[dict]] = []
    rotation = 0
    for _day in range(horizon):
        day_tasks: list[Task] = []
        required_slots = max(1, min(MAX_TASKS_PER_DAY, daily_minutes // MIN_MINUTES_PER_TASK))
        attempts = 0
        max_attempts = max(1, len(subjects)) * MAX_TASKS_PER_DAY * 2
        while subjects and len(day_tasks) < required_slots and attempts < max_attempts:
            subject = subjects[rotation % len(subjects)]
            rotation += 1
            attempts += 1
            queue = queues.get(subject, [])
            if not queue:
                continue
            c = queue.pop(0)
            day_tasks.append(Task(kind=c["kind"], label=c["label"], subject=c["subject"], unit=c["unit"], skill=c["skill"]))

        if day_tasks:
            per = daily_minutes // len(day_tasks)
            remainder = daily_minutes - per * len(day_tasks)
            for i, t in enumerate(day_tasks):
                t.minutes = per + (remainder if i == len(day_tasks) - 1 else 0)
        day_tasks.append(Task(kind="ask", label="Ask a question about anything you're stuck on"))
        days.append([_task_dict(t) for t in day_tasks])

    return {
        "horizon_days": horizon,
        "realistic": realistic,
        "shortfall_minutes": max(0, total_needed_minutes - total_available_minutes),
        "days": days,
    }


def _task_dict(t: Task) -> dict:
    return {
        "kind": t.kind, "label": t.label, "subject": t.subject,
        "unit": t.unit, "skill": t.skill, "minutes": t.minutes, "done": t.done,
    }
