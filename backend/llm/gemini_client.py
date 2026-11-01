"""
A second, independent chat model for cross-checking answers `llm/client.py`'s
Groq-backed LLMClient already produced. The whole point of a cross-check is
that it comes from a genuinely different model family - re-asking Groq again
would mostly repeat whatever blind spot it already has, not catch it. Gemini
is already a live dependency of this project (GoogleGenerativeAIEmbeddings,
retriever/builder.py), so this adds no new provider relationship, only a
chat-capable sibling of the embeddings client already in use.

Implements the exact same `.chat(messages) -> {"choices": [{"message":
{"content": ...}}]}` contract as LLMClient, so every existing caller that
does `parse_json_object(llm.chat(...)["choices"][0]["message"]["content"])`
works unchanged regardless of which client it's given.
"""

from config.settings import settings
from langchain_google_genai import ChatGoogleGenerativeAI
from llm.retry import invoke_with_retry


class GeminiLLMClient:
    def __init__(
        self,
        model_id: str | None = None,
        temperature: float = 0,
        max_tokens: int = 1500,
    ):
        self.model = ChatGoogleGenerativeAI(
            model=model_id or settings.GEMINI_CHAT_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

    def chat(self, messages: list[dict]) -> dict:
        response = invoke_with_retry(self.model, messages)
        return {"choices": [{"message": {"content": response.content}}]}
