import base64
import io

import easyocr
import numpy as np
from PIL import Image

from utils.logging import logger


_reader = easyocr.Reader(["en"], gpu=False)


def extract_text_from_base64_image(image_base64: str) -> str:
    """Decode a base64-encoded photo of an exam question and OCR it."""
    try:
        image_bytes = base64.b64decode(image_base64)
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as e:
        logger.error(f"Failed to decode submitted exam question image: {e}")
        raise ValueError("Could not read the submitted image.") from e

    results = _reader.readtext(np.array(image), detail=0, paragraph=True)
    text = "\n".join(results).strip()
    if not text:
        raise ValueError("No text could be read from the submitted image.")
    return text
