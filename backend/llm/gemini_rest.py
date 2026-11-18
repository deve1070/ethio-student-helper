"""
Gemini over plain HTTPS (the generateContent REST endpoint), with a hard per-request timeout.

Why not langchain_google_genai: version 2.0.9 runs on the deprecated google-generativeai SDK, which
retries a 503 "model is experiencing high demand" by itself, silently, for minutes, ignoring both
`timeout` and `max_retries` (measured: a call that the REST endpoint answers with 503 in 6s did not
return within 150s through the library, over gRPC or REST transport). A student waiting on an answer
check or a receipt check then waited that long. Here one request takes at most `timeout` seconds, and
retrying is left to llm/retry.py's invoke_with_retry, whose attempts each caller chooses.

  GeminiREST(model_id, ...).invoke(messages)  -> GeminiResponse(content, response_metadata)
  GeminiRateLimitError    HTTP 429; llm/retry.py waits and retries it like Groq's RateLimitError
  GeminiUnavailableError  HTTP 500/502/503/504, a timeout or a network failure; retried as a
                          connection error
  GeminiRequestError      any other 4xx (wrong model name, bad key); not retried

Messages use the same shape the LangChain clients took: {"role": "user"|"assistant"|"system",
"content": str | [{"type": "text", "text": ...}, {"type": "image_url", "image_url": {"url":
"data:<mime>;base64,<data>"}}]}.
"""

from dataclasses import dataclass, field

import httpx

from config.settings import settings

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiRateLimitError(RuntimeError):
    """HTTP 429: the per-minute or daily quota is used up."""


class GeminiUnavailableError(RuntimeError):
    """The model is overloaded or down (5xx), or the request timed out or could not connect."""


class GeminiRequestError(RuntimeError):
    """Any other 4xx: a wrong model name, a bad key, a malformed request. Retrying the same request
    cannot help, so llm/retry.py does not."""


@dataclass
class GeminiResponse:
    content: str
    response_metadata: dict = field(default_factory=dict)


def _parts(content) -> list[dict]:
    if isinstance(content, str):
        return [{"text": content}]
    parts = []
    for item in content:
        if item.get("type") == "text":
            parts.append({"text": item["text"]})
        elif item.get("type") == "image_url":
            url = item["image_url"]["url"]
            header, data = url.split(",", 1)  # "data:image/jpeg;base64", "<base64>"
            mime = header.removeprefix("data:").split(";")[0]
            parts.append({"inline_data": {"mime_type": mime, "data": data}})
    return parts


class GeminiREST:
    def __init__(
        self,
        model_id: str,
        temperature: float = 0,
        max_output_tokens: int = 1500,
        timeout: float = 60.0,
    ):
        self.model_id = model_id
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout

    def invoke(self, messages: list[dict]) -> GeminiResponse:
        system = [m for m in messages if m["role"] == "system"]
        body = {
            "contents": [
                {"role": "model" if m["role"] == "assistant" else "user", "parts": _parts(m["content"])}
                for m in messages
                if m["role"] != "system"
            ],
            "generationConfig": {"temperature": self.temperature, "maxOutputTokens": self.max_output_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [p for m in system for p in _parts(m["content"])]}

        try:
            r = httpx.post(
                API_URL.format(model=self.model_id),
                headers={"x-goog-api-key": settings.GEMINI_API_KEY},
                json=body,
                timeout=self.timeout,
            )
        except httpx.HTTPError as e:  # timeouts and network failures alike
            raise GeminiUnavailableError(f"{type(e).__name__}: {e}") from e

        if r.status_code == 429:
            raise GeminiRateLimitError(r.text[:500])
        if r.status_code >= 500:
            raise GeminiUnavailableError(f"HTTP {r.status_code}: {r.text[:300]}")
        if r.status_code >= 400:
            raise GeminiRequestError(f"Gemini rejected the request for model {self.model_id!r} (HTTP {r.status_code}): {r.text[:300]}")

        data = r.json()
        candidates = data.get("candidates") or []
        if not candidates:
            # the prompt itself was blocked; report it the way a finished-but-empty answer is reported
            reason = (data.get("promptFeedback") or {}).get("blockReason", "")
            return GeminiResponse("", {"finish_reason": reason})
        first = candidates[0]
        # parts marked "thought" are the model's hidden reasoning, not the answer
        text = "".join(
            p.get("text", "") for p in (first.get("content") or {}).get("parts", []) if not p.get("thought")
        )
        return GeminiResponse(text, {"finish_reason": first.get("finishReason", "")})
