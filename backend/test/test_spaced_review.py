"""Spaced review schedule (exams/store.py's review_due) - a pure function of one question's
attempt history, so no database. Run from backend/:   python test/test_spaced_review.py"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exams.store import review_due  # noqa: E402

passed = failed = 0


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL: {label}")


now = datetime(2026, 11, 20, 12, 0)
d = lambda days: now - timedelta(days=days)  # noqa: E731

check("never answered wrong: not in review", review_due([(True, d(10))], now) is False)
check("wrong today: not due yet", review_due([(False, d(0.5))], now) is False)
check("wrong over a day ago: due", review_due([(False, d(1.1))], now) is True)
check("wrong, then right once 2 days ago: not due (3-day gap)", review_due([(False, d(5)), (True, d(2))], now) is False)
check("wrong, then right once 4 days ago: due", review_due([(False, d(6)), (True, d(4))], now) is True)
check("right twice since the wrong, 5 days ago: not due (7-day gap)",
      review_due([(False, d(12)), (True, d(10)), (True, d(5))], now) is False)
check("right twice since the wrong, 8 days ago: due",
      review_due([(False, d(15)), (True, d(12)), (True, d(8))], now) is True)
check("right three times in a row: leaves review",
      review_due([(False, d(30)), (True, d(25)), (True, d(20)), (True, d(10))], now) is False)
check("wrong again after graduating: back in at 1 day",
      review_due([(False, d(30)), (True, d(25)), (True, d(20)), (True, d(10)), (False, d(2))], now) is True)


# ---- readiness: projected score weighted by how much of the exam each unit makes up ------------
from exams.store import readiness  # noqa: E402

weights = [{"grade": 11, "unit": "A", "questions": 30}, {"grade": 12, "unit": "B", "questions": 10}]
few = {"attempted": 5, "correct": 5, "units": [], "skills": []}
check("too few answers: no projection", readiness(few, weights, "units")["projected"] is None)

strong_a = {"attempted": 20, "correct": 18, "skills": [],
            "units": [{"grade": 11, "unit": "A", "attempted": 20, "correct": 18}]}
r = readiness(strong_a, weights, "units")
check("strong on the big unit projects high", r["projected"] > 0.75)
check("coverage is the big unit's share of the exam", abs(r["coverage"] - 0.75) < 1e-9)

strong_b = {"attempted": 20, "correct": 18, "skills": [],
            "units": [{"grade": 12, "unit": "B", "attempted": 20, "correct": 18}]}
check("strong only on the small unit covers less of the exam",
      readiness(strong_b, weights, "units")["coverage"] < r["coverage"])

weak = {"attempted": 20, "correct": 4, "skills": [],
        "units": [{"grade": 11, "unit": "A", "attempted": 20, "correct": 4}]}
check("weak answers project low", readiness(weak, weights, "units")["projected"] < 0.35)
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
