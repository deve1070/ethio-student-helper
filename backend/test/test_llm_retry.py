"""Test of llm/retry.py's invoke_with_retry: a per-minute rate limit is retried (clears within our own
backoff window), a daily rate limit is NOT - no amount of waiting inside one call frees up a quota that
resets once every 24 hours, so retrying it is pure wasted time (confirmed live: it cost ~7.5 minutes on
a single question before this fix). Run from backend/:   python test/test_llm_retry.py"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm.retry as retry
from llm.retry import LLMUnavailableError, invoke_with_retry


class FakeRateLimitError(Exception):
    pass


retry.RATE_LIMIT_ERRORS = (FakeRateLimitError,)


class FlakyModel:
    """Raises the given error every call until call number `succeeds_on` (1-indexed), then succeeds."""

    def __init__(self, error_factory, succeeds_on=None):
        self.error_factory = error_factory
        self.succeeds_on = succeeds_on
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.succeeds_on is not None and self.calls >= self.succeeds_on:
            return "ok"
        raise self.error_factory()


# ---- 1. a per-minute rate limit retries and eventually succeeds -------------------------------------
per_minute = FlakyModel(lambda: FakeRateLimitError("Rate limit reached ... requests per minute (RPM)"), succeeds_on=3)
result = invoke_with_retry(per_minute, [], attempts=5, max_wait=0.01)
assert result == "ok" and per_minute.calls == 3, per_minute.calls

# ---- 2. a per-minute rate limit that never clears raises after exhausting every attempt --------------
always_limited = FlakyModel(lambda: FakeRateLimitError("Rate limit reached ... tokens per minute (TPM)"))
try:
    invoke_with_retry(always_limited, [], attempts=3, max_wait=0.01)
    assert False, "should have raised"
except LLMUnavailableError:
    pass
assert always_limited.calls == 3, always_limited.calls  # used every attempt - a per-minute limit IS worth retrying

# ---- 3. a daily rate limit fails on the FIRST attempt - never retried, even once ----------------------
daily = FlakyModel(lambda: FakeRateLimitError(
    "Rate limit reached for model `x` ... on tokens per day (TPD): Limit 200000, Used 198690, Requested 1659. "
    "Please try again in 2m30.768s."
))
t0 = time.monotonic()
try:
    invoke_with_retry(daily, [], attempts=5, max_wait=30.0)
    assert False, "should have raised"
except LLMUnavailableError as e:
    assert "daily" in str(e).lower(), e
assert daily.calls == 1, daily.calls          # never retried
assert time.monotonic() - t0 < 1.0             # and never slept waiting for a daily quota to clear

print("LLM RETRY TESTS PASSED")
