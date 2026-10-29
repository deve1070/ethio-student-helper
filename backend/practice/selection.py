"""Which questions to serve next, and how to summarise progress. Pure functions."""
import random
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LEVEL_MIN_ATTEMPTS = 5

# Every student is in Ethiopia, so "today" always means the Ethiopian calendar day - a fixed zone, not
# whatever timezone the server process happens to run in (EAT has no DST, so this never needs updating).
# Attempt timestamps are stored in UTC (Postgres DateTime(timezone=True) via func.now()); bucketing them
# by raw ts.date() silently uses UTC's day boundary instead, which is 3 hours behind Ethiopia's - any
# attempt made in the first 3 hours of a new Ethiopian day would be bucketed as "yesterday" and could
# make a same-day streak look broken even though the student really did study today.
_LOCAL_TZ = ZoneInfo("Africa/Addis_Ababa")


def local_date(ts: datetime) -> date:
    """The calendar date `ts` falls on in Ethiopia, regardless of what timezone `ts` carries (UTC, in
    production) or lacks (naive - assumed already UTC, matching what func.now() actually produces, so a
    test fixture that constructs a naive "UTC-ish" timestamp buckets the same way production does)."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(_LOCAL_TZ).date()


def today_local() -> date:
    return datetime.now(_LOCAL_TZ).date()


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


def classify_level(accuracy: float, attempts: int, min_attempts: int = LEVEL_MIN_ATTEMPTS) -> str:
    """weak < 60% accuracy, strong >= 80%, otherwise learning - but only once `attempts` has reached
    `min_attempts`; below that there isn't enough signal to call it anything. Shared by every system
    that shows a per-unit/skill mastery badge (QuizQuestion practice and ESSLCE both), so "weak" means
    the same thing everywhere even though each system tunes its own min_attempts and accuracy formula."""
    if attempts < min_attempts:
        return "not enough data"
    if accuracy < 0.6:
        return "weak"
    if accuracy >= 0.8:
        return "strong"
    return "learning"


def unit_progress(rows: list[tuple]) -> list[dict]:
    """rows: [(unit, attempts, correct)] -> per-unit summary, weakest first.

    accuracy is smoothed ((correct+1)/(attempts+2)) so 1 lucky answer is not "100%".
    """
    out = []
    for unit, attempts, correct in rows:
        accuracy = (correct + 1) / (attempts + 2)
        level = classify_level(accuracy, attempts)
        out.append({"unit": unit, "attempts": attempts, "correct": correct,
                    "accuracy": round(accuracy, 2), "level": level})
    out.sort(key=lambda r: (r["level"] != "weak", r["accuracy"]))
    return out


def daily_trend(rows: list[tuple[datetime, bool]], days: int = 7) -> list[dict]:
    """rows: [(timestamp, is_correct)] for one user (and usually one subject) -> the last `days`
    calendar days, oldest first, ending today. A day with zero attempts gets accuracy=None rather than 0,
    so a quiet day draws as a gap on a trend chart instead of a false crash to the bottom."""
    buckets: dict[date, list[int]] = {}
    for ts, ok in rows:
        b = buckets.setdefault(local_date(ts), [0, 0])
        b[0] += 1
        b[1] += int(ok)
    today = today_local()
    out = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        attempts, correct = buckets.get(d, [0, 0])
        out.append({
            "date": d.isoformat(),
            "attempts": attempts,
            "accuracy": round(correct / attempts, 2) if attempts else None,
        })
    return out


def study_streak(study_dates: set[date]) -> int:
    """Consecutive-day streak ending today or yesterday - today not having an attempt YET doesn't break
    yesterday's streak until the day is actually over. 0 if neither today nor yesterday has activity."""
    today = today_local()
    cursor = today if today in study_dates else today - timedelta(days=1)
    if cursor not in study_dates:
        return 0
    streak = 0
    while cursor in study_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak
