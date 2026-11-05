"""The one grounded LLM call in the study-plan feature: given an already-computed deterministic week
plan (studyplan/planner.py) and the profile it was built from, writes a short rationale for each day and
one short weekly motivational note - explanation and encouragement only, never scheduling. Every fact it
may reference (subjects, units, day count, coverage) is handed to it in the prompt; it is never asked to
invent or recompute anything. A deterministic check afterward drops any day-rationale that names a
subject/unit not actually scheduled that day, mirroring exams/store.py's own cross-check philosophy
(solve_question_crosschecked) - trust the LLM for tone, never for facts."""

import json

from llm.client import parse_json_object

COACH_PROMPT = """You are an encouraging study coach for an Ethiopian ESSLCE student. Below is a \
{horizon}-day study schedule already decided for them (you are NOT choosing or changing it), plus a \
short profile of their progress. Write:
1. One short (<=20 words) line per day explaining briefly why that day's tasks matter, using ONLY the \
subjects/units/skills listed for that day - never mention anything not listed.
2. One short (<=40 words) encouraging note for the whole week, grounded only in the facts given below \
(days remaining, subjects, coverage, realistic flag). Never invent a fact, number, or subject not given.

Profile: {profile_json}
Schedule: {schedule_json}

Respond with ONLY a JSON object: {{"day_rationales": ["...", ...], "weekly_note": "..."}} - one \
rationale string per day, in the same order as the schedule."""


def _mentions_only_scheduled(rationale: str, day_tasks: list[dict]) -> bool:
    """Cheap grounding check: a rationale that doesn't mention ANY of that day's own subjects/units/
    skills is dropped rather than shown - likely hallucinated or copied from a different day. This is a
    cheap substring check, not a full fact-check, by design (see
    docs/dev_plans/rigorous_study_planner.md) - the LLM's wording is never trusted blindly, same as
    every other LLM-grounding check in this app."""
    allowed_terms = {
        t for task in day_tasks for t in (task.get("subject"), task.get("unit"), task.get("skill")) if t
    }
    if not allowed_terms:
        return True
    return any(term.lower() in rationale.lower() for term in allowed_terms)


def add_rationale(llm, week_plan: dict, profile: dict) -> dict:
    """Mutates and returns week_plan with `day_rationales`/`weekly_note` added when the LLM call
    succeeds and passes the grounding check, or left as empty defaults on any failure (rate limit,
    parse failure, ungrounded output) - the deterministic schedule is always still usable on its own,
    same degrade-gracefully pattern as notes/store.py's generate_note."""
    days = week_plan["days"]
    week_plan["day_rationales"] = ["" for _ in days]
    week_plan["weekly_note"] = ""

    compact_profile = {
        "days_remaining": profile["days_remaining"],
        "required_subjects": profile["required_subjects"],
        "realistic": week_plan["realistic"],
        "coverage": {s["subject"]: s["coverage_ratio"] for s in profile["subjects"]},
    }
    prompt = COACH_PROMPT.format(
        horizon=week_plan["horizon_days"],
        profile_json=json.dumps(compact_profile),
        schedule_json=json.dumps(days),
    )
    try:
        response = llm.chat([{"role": "user", "content": prompt}])
        data = parse_json_object(response["choices"][0]["message"]["content"])
    except Exception:  # noqa: BLE001 - any provider error degrades to no rationale, never a 500
        return week_plan
    if not data or not isinstance(data.get("day_rationales"), list):
        return week_plan

    rationales = data["day_rationales"]
    week_plan["day_rationales"] = [
        r if isinstance(r, str) and _mentions_only_scheduled(r, days[i]) else ""
        for i, r in enumerate(rationales[: len(days)])
    ] + ["" for _ in range(len(days) - len(rationales))]
    week_plan["weekly_note"] = data.get("weekly_note") if isinstance(data.get("weekly_note"), str) else ""
    return week_plan
