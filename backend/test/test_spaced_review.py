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

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
