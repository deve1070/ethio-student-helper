"""
A second, independent chat model for cross-checking answers `llm/client.py`'s
Groq-backed LLMClient already produced. The whole point of a cross-check is
that it comes from a genuinely different model family - re-asking Groq again
would mostly repeat whatever blind spot it already has, not catch it.

Implements the exact same `.chat(messages) -> {"choices": [{"message":
{"content": ...}}]}` contract as LLMClient, so every existing caller that
does `parse_json_object(llm.chat(...)["choices"][0]["message"]["content"])`
works unchanged regardless of which client it's given.

timeout bounds one request; retry_attempts and retry_max_wait bound the retrying in
llm/retry.py. A caller whose result a student is waiting on, but which is only a check (the
answer verifier), passes a small budget so an overloaded Gemini costs seconds, not minutes.

Overload is per model (a 503 "high demand" on one model while another answers in two seconds was
measured), so when the main model stays unavailable after its tries, or rejects the request (a
mistyped model name), one more try goes to settings.GEMINI_FALLBACK_MODEL before giving up.
"""

from config.settings import settings
from llm.gemini_rest import GeminiREST
import logging

from llm.gemini_rest import GeminiRequestError
from llm.retry import LLMUnavailableError, invoke_with_retry

logger = logging.getLogger(__name__)


class GeminiLLMClient:
    def __init__(
        self,
        model_id: str | None = None,
        temperature: float = 0,
        max_tokens: int = 1500,
        timeout: float = 60.0,
        retry_attempts: int = 5,
        retry_max_wait: float = 30.0,
    ):
        main = model_id or settings.GEMINI_CHAT_MODEL
        self.models = [
            GeminiREST(m, temperature=temperature, max_output_tokens=max_tokens, timeout=timeout)
            for m in dict.fromkeys([main, settings.GEMINI_FALLBACK_MODEL])  # keeps order, drops a repeat
            if m
        ]
        self.retry_attempts = retry_attempts
        self.retry_max_wait = retry_max_wait

    def chat(self, messages: list[dict]) -> dict:
        main, *fallback = self.models
        try:
            response = invoke_with_retry(main, messages, attempts=self.retry_attempts, max_wait=self.retry_max_wait)
        except (LLMUnavailableError, GeminiRequestError) as e:
            if not fallback:
                raise
            logger.warning("Gemini model %r failed (%s); trying %r", main.model_id, str(e)[:160], fallback[0].model_id)
            response = invoke_with_retry(fallback[0], messages, attempts=1)
        return {"choices": [{"message": {"content": response.content}}]}
