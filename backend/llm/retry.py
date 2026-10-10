"""
Retry + error type for calls to the LLM provider (Groq).

Why: the free tier allows 8,000 tokens per minute. A broad question makes
several calls (planner, relevance check, answer, verification), so a 429
"rate limit" error is normal, and the provider says exactly how long to wait
("Please try again in 757.5ms"). Without a retry, a 429 on the verifier made
the server return an UNVERIFIED answer, and a dropped connection made the
relevance check tell the student their question was "not related".

  invoke_with_retry(model, messages)  waits and retries rate-limit and
                                      connection errors, then raises
                                      LLMUnavailableError if still failing.
  LLMUnavailableError                 "the AI service could not be reached";
                                      the API turns it into HTTP 503.
"""
import logging
import re
import time

logger = logging.getLogger(__name__)

try:  # the groq SDK's own exception types
    from groq import APIConnectionError, RateLimitError
except ImportError:  # keep this module importable without the SDK
    class RateLimitError(Exception): ...
    class APIConnectionError(Exception): ...


class LLMUnavailableError(RuntimeError):
    """The language model could not be reached (rate limit, network, outage)."""


_RETRY_IN = re.compile(
    r"try again in\s+(?:(\d+)m)?\s*(?:([\d.]+)s)?\s*(?:([\d.]+)ms)?", re.I
)


def retry_after_seconds(message: str) -> float | None:
    """Parse "Please try again in 757.5ms" / "in 2.5s" / "in 1m26.4s"."""
    m = _RETRY_IN.search(message)
    if not m:
        return None
    minutes, seconds, millis = m.groups()
    total = (int(minutes) * 60 if minutes else 0) + (float(seconds) if seconds else 0) \
        + (float(millis) / 1000 if millis else 0)
    return total or None


def invoke_with_retry(model, messages, attempts: int = 5, max_wait: float = 30.0):
    for attempt in range(1, attempts + 1):
        try:
            return model.invoke(messages)
        except RateLimitError as e:
            if attempt == attempts:
                raise LLMUnavailableError(f"rate limit still reached after {attempts} tries: {e}") from e
            wait = min((retry_after_seconds(str(e)) or 2.0 * attempt) + 0.5, max_wait)
            logger.warning("LLM rate limit; waiting %.1fs (try %d/%d)", wait, attempt, attempts)
            time.sleep(wait)
        except APIConnectionError as e:
            if attempt == attempts:
                raise LLMUnavailableError(f"cannot reach the LLM service: {e}") from e
            wait = min(1.5 * attempt, max_wait)
            logger.warning("LLM connection error; waiting %.1fs (try %d/%d)", wait, attempt, attempts)
            time.sleep(wait)
