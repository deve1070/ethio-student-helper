"""Shared by every client built on langchain_google_genai.ChatGoogleGenerativeAI (llm/vision.py's
make_gemini_vision_call, llm/gemini_client.py's GeminiLLMClient) - both wrap the same underlying
`.content` attribute and both hit the same Gemini response shape below."""


def content_to_text(content) -> str:
    """ChatGoogleGenerativeAI's .content is USUALLY a plain string, but for certain multi-part Gemini
    responses it comes back as a list instead - list[str], or list[dict] with a "text" key per part.
    Confirmed live in two independent call paths: transcribing a real batch of exam pages, a bare
    downstream `"\n".join(...)`/`re.sub(..., text)` crashed with "expected str instance, list found" on
    roughly 1 in 6 pages (llm/vision.py's own caller); separately, solve_paper's cross-check call
    crashed with "'list' object has no attribute 'strip'" (exams/store.py, through GeminiLLMClient.chat).
    Neither is tied to vision specifically - it's the Gemini response shape itself, occasionally split
    into multiple parts rather than returned as one block. Normalized once here so every caller gets a
    plain string unconditionally, instead of each one needing to guard against this shape itself."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(part.get("text", ""))
        return "".join(parts)
    return str(content) if content else ""
