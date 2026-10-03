"""
Thin adapter so agents/research_agent.py, agents/verification_agent.py,
and agents/relevance_checker.py can keep calling
`.chat(messages=[{"role": "user", "content": ...}])` and reading
`response["choices"][0]["message"]["content"]` exactly as they did
against IBM WatsonX's ModelInference — only the provider underneath
changes. Backed by Groq (fast inference, generous free tier) via
LangChain's ChatGroq.

Get a free API key at console.groq.com and set GROQ_API_KEY.
"""

from config.settings import settings
from langchain_groq import ChatGroq
from llm.retry import invoke_with_retry


class LLMClient:
    def __init__(
        self,
        model_id: str | None = None,
        temperature: float = 0,
        max_tokens: int = 1500,
        reasoning_effort: str = "low",
    ):
        self.model = ChatGroq(
            model=model_id or settings.GROQ_MODEL,
            api_key=settings.GROQ_API_KEY,
            temperature=temperature,
            max_tokens=max_tokens,
            # openai/gpt-oss-120b (the current GROQ_MODEL default) is a
            # reasoning model: part of max_tokens gets spent on hidden
            # reasoning before the visible answer, and at Groq's default
            # ("medium") effort a small max_tokens can be consumed
            # entirely by that, returning empty content with
            # finish_reason="length". "low" leaves more of the budget for
            # the actual answer on these simple classification/extraction
            # tasks. Only openai/gpt-oss-20b, openai/gpt-oss-120b, and the
            # qwen3.x reasoning models on Groq accept this param — if
            # GROQ_MODEL is later pointed at a non-reasoning model, check
            # whether it still accepts reasoning_effort before assuming
            # this line is harmless.
            reasoning_effort=reasoning_effort,
        )

    def chat(self, messages: list[dict]) -> dict:
        """Same request/response shape the agents already use — a list
        of {"role", "content"} messages in, a WatsonX-style
        {"choices": [{"message": {"content": ...}}]} dict out — so the
        three call sites needed zero changes beyond how this object is
        constructed.
        """
        response = invoke_with_retry(self.model, messages)
        return {"choices": [{"message": {"content": response.content}}]}
