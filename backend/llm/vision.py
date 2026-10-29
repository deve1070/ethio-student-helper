"""
A single-image vision call through Gemini, shared by anything that needs to read a photo with an
LLM (exam page transcription in exams/extract.py, payment receipt verification in
payments/receipt_verification.py). Not through llm.client.LLMClient - that adapter is Groq-only
(llm/retry.py's retry logic is typed to Groq's SDK exceptions, and Groq has no vision model on this
account as of 2026-10-21, see the esh-extraction-gemini-vision memory).
"""
import base64

from config.settings import settings


def make_gemini_vision_call(model_id: str, system_prompt: str, max_output_tokens: int = 12000):
    """Returns call(jpeg_bytes, note) -> response text.

    max_output_tokens defaults to 12000, not a smaller number: Gemini 3.x models spend part of the
    budget on hidden reasoning before the visible answer, and a smaller ceiling was seen in real
    data to come back as an empty, non-error response ("the model returned nothing usable") on
    dense images - see the esh-extraction-gemini-vision memory for the full story.

    A SECOND empty-response cause, found transcribing the 2005-2010 EC web-archive batch: Gemini's
    recitation filter (response_metadata.finish_reason == "RECITATION") refuses to answer at all when
    a page's content matches training text widely duplicated elsewhere - these exam questions are
    mirrored verbatim across many sites, so an ordinary content page triggers it, not just boilerplate.
    Confirmed this is NOT a sampling effect (temperature 0 -> 0.4 still blocked on the same page) but IS
    a function of how much matching text is in view at once: cropping the blocked page to its bottom
    half transcribed cleanly, while the top half alone still blocked (the matched span was concentrated
    there). The fix is a recursive crop-and-retry: a block gets retried on the top and bottom halves
    separately (each recursing the same way if IT still blocks), and their text is concatenated - every
    caller (exam page/answer-key transcription, payment receipt verification) gets this for free, and a
    page that resolves cleanly on the first try never pays for any of it.

    The split point is a blank row found near the vertical midpoint, not a blind 50% cut: a first version
    that split at exactly h // 2 worked, but on a real blocked page it happened to cut straight through a
    cluster of questions, costing several of them a dropped or duplicated option at the seam (confirmed by
    the arithmetic-practice paper's own review.txt). An MCQ page reliably has blank space between one
    question's options and the next question's stem, so searching outward from the midpoint for a mostly-
    white row and cutting there almost always lands between questions instead of inside one."""
    from io import BytesIO

    import numpy as np
    from langchain_google_genai import ChatGoogleGenerativeAI
    from PIL import Image

    llm = ChatGoogleGenerativeAI(
        model=model_id, google_api_key=settings.GEMINI_API_KEY, temperature=0,
        max_output_tokens=max_output_tokens,
    )

    def _invoke(jpg: bytes, note: str) -> tuple[str, bool]:
        content = [
            {"type": "text", "text": system_prompt + "\n\n" + note},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpg).decode()}},
        ]
        r = llm.invoke([{"role": "user", "content": content}])
        blocked = not r.content and r.response_metadata.get("finish_reason") == "RECITATION"
        return r.content or "", blocked

    def _split_row(img) -> int:
        """A y-coordinate near the vertical midpoint that falls on a near-blank row, so cropping there is
        unlikely to cut through a question's own text. Falls back to the exact midpoint if no sufficiently
        blank row exists within the search band (rare, but better than searching the whole page)."""
        gray = np.array(img.convert("L"))
        h = gray.shape[0]
        row_means = gray.mean(axis=1)
        mid = h // 2
        band = h // 4   # search within the middle half of the page, not the whole thing
        for d in range(band):
            for y in (mid - d, mid + d):
                if 0 <= y < h and row_means[y] > 250:
                    return y
        return mid

    def call(jpg: bytes, note: str, _depth: int = 0) -> str:
        text, blocked = _invoke(jpg, note)
        if not blocked:
            return text
        if _depth >= 3:   # already down to a 1/8-page crop - give up rather than recurse indefinitely
            return ""
        img = Image.open(BytesIO(jpg))
        w, h = img.size
        if h < 150:       # too small a sliver to contain readable text at all
            return ""
        split_y = _split_row(img)
        overlap = 10      # a small margin, now that the cut itself targets blank space between questions
        half_note = note + " (this image shows only part of the page - transcribe only what's visible)"
        pieces = []
        for box in ((0, 0, w, min(split_y + overlap, h)), (0, max(split_y - overlap, 0), w, h)):
            buf = BytesIO()
            img.crop(box).convert("RGB").save(buf, "JPEG", quality=85)
            pieces.append(call(buf.getvalue(), half_note, _depth + 1))
        return "\n".join(p for p in pieces if p)

    return call
