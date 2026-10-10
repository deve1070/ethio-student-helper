"""Which questions to serve next, and how to summarise progress. Pure functions."""
import random

LEVEL_MIN_ATTEMPTS = 5


def pick_questions(candidates: list[dict], last_attempt: dict, n: int, rng: random.Random | None = None) -> list[dict]:
    """Order: never seen -> last answer wrong -> last answer right (oldest first).

    candidates:   [{"id": ..., ...}]
    last_attempt: {question_id: (is_correct, timestamp)} for this user
    """
    rng = rng or random.Random()
    unseen, wrong, right = [], [], []
    for q in candidates:
        last = last_attempt.get(q["id"])
        if last is None:
            unseen.append(q)
        elif not last[0]:
            wrong.append(q)
        else:
            right.append(q)
    rng.shuffle(unseen)
    rng.shuffle(wrong)
    right.sort(key=lambda q: last_attempt[q["id"]][1])  # least recently answered first
    return (unseen + wrong + right)[:n]


def unit_progress(rows: list[tuple]) -> list[dict]:
    """rows: [(unit, attempts, correct)] -> per-unit summary, weakest first.

    accuracy is smoothed ((correct+1)/(attempts+2)) so 1 lucky answer is not "100%".
    level needs at least LEVEL_MIN_ATTEMPTS answers before calling a unit weak/strong.
    """
    out = []
    for unit, attempts, correct in rows:
        accuracy = (correct + 1) / (attempts + 2)
        if attempts < LEVEL_MIN_ATTEMPTS:
            level = "not enough data"
        elif accuracy < 0.6:
            level = "weak"
        elif accuracy >= 0.8:
            level = "strong"
        else:
            level = "learning"
        out.append({"unit": unit, "attempts": attempts, "correct": correct,
                    "accuracy": round(accuracy, 2), "level": level})
    out.sort(key=lambda r: (r["level"] != "weak", r["accuracy"]))
    return out
