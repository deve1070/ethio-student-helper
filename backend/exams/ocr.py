"""Read a student-submitted photo of an exam question into plain text, for /v1/exam/solve's
image_base64 input. Uses Gemini vision (llm/vision.py's make_gemini_vision_call), the same
provider exams/extract.py already uses to transcribe photographed exam pages and
payments/receipt_verification.py uses to read payment receipts - NOT easyocr (the local
deep-learning OCR library this used before): importing easyocr alone costs ~530MB RSS (it
pulls in torch) and constructing its Reader costs another ~530MB on top of that, measured
directly - about 1GB just for a feature most requests never touch, loaded eagerly at import
time regardless. That ruled out Render's 512MB free tier on its own, independent of (and
larger than) the embedding-model RAM question this project already solved with fastembed.
Gemini vision costs no local RAM at all - the image is sent to Gemini's API, same as every
other vision use in this codebase."""
import base64
import io

from PIL import Image

from llm.vision import make_gemini_vision_call
from utils.logging import logger

# A small/cheap vision model is enough here - this is plain text extraction from a single
# question, not a derivation or judgment call. Matches payments/receipt_verification.py's
# RECEIPT_MODEL_ID choice for the same reason (a similarly simple read-the-photo task).
EXAM_QUESTION_OCR_MODEL_ID = "gemini-3.5-flash-lite"
EXAM_QUESTION_OCR_PROMPT = (
    "This is a student's photo of ONE exam question (and its multiple-choice options, if any). "
    "Transcribe every word exactly as printed - the question stem, then each option on its own "
    "line. Do not answer the question, explain it, or add any commentary. Reply with ONLY the "
    "transcribed text, nothing else. If the photo has no readable exam question in it, reply "
    "with an empty response."
)

_vision_call = None


def _get_vision_call():
    """Built lazily (first real call, not at import time) - make_gemini_vision_call itself is
    cheap (it just constructs a ChatGoogleGenerativeAI client, no local model weights), but
    lazy construction is still the right default for anything built from a request path:
    nothing here should run before the app has even finished starting up."""
    global _vision_call
    if _vision_call is None:
        _vision_call = make_gemini_vision_call(EXAM_QUESTION_OCR_MODEL_ID, EXAM_QUESTION_OCR_PROMPT)
    return _vision_call


def extract_text_from_base64_image(image_base64: str) -> str:
    """Decode a base64-encoded photo of an exam question and read it via Gemini vision."""
    try:
        image_bytes = base64.b64decode(image_base64)
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as e:
        logger.error(f"Failed to decode submitted exam question image: {e}")
        raise ValueError("Could not read the submitted image.") from e

    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=90)
    text = _get_vision_call()(buf.getvalue(), "").strip()
    if not text:
        raise ValueError("No text could be read from the submitted image.")
    return text
