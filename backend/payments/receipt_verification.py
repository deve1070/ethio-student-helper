"""
Automatic verification of a submitted payment-receipt photo: reads the receipt with a vision
model and checks it against what the student claims (transaction id + the bundle's price),
auto-approving ONLY when both match with real confidence - the same "verify before trust" gate
used throughout exams/store.py (quote_in_passage), not "the model says it looks fine". Anything
the model can't read clearly, or that doesn't match, falls through to a human admin instead of
being guessed.
"""
import json
import re

RECEIPT_MODEL_ID = "gemini-3.5-flash-lite"

RECEIPT_PROMPT = """You are reading a mobile-money or bank transfer receipt screenshot (Telebirr, \
CBE, or similar) submitted as proof of payment. Extract exactly what is printed - never guess or \
fill in a plausible-looking value you cannot actually read.

Reply with ONLY a JSON object, no other text:
{"amount_etb": <number or null>, "transaction_id": "<string or null>", "readable": true/false}

amount_etb: the transferred amount in Ethiopian Birr, as a plain number (no currency symbol, no \
thousands separator).
transaction_id: the transaction/reference number printed on the receipt, copied exactly.
readable: false if the image is too blurry, cropped, or dark to confidently read BOTH fields above
- in that case leave amount_etb and transaction_id null rather than guessing."""


def _parse_json_object(raw: str) -> dict | None:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def extract_receipt_data(vision_call, photo_bytes: bytes) -> dict:
    """vision_call: the call(jpg, note) -> str contract from llm.vision.make_gemini_vision_call.
    Never raises on a bad response - any parse failure is treated the same as an unreadable receipt."""
    unreadable = {"readable": False, "amount_etb": None, "transaction_id": None}
    try:
        raw = vision_call(photo_bytes, "Read this payment receipt.")
    except Exception:  # noqa: BLE001 - a failed vision call is exactly as inconclusive as a bad read
        return unreadable
    data = _parse_json_object(raw)
    if not data or not isinstance(data.get("readable"), bool):
        return unreadable
    return data


def _normalize_id(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", s).upper()


def verify_receipt(
    extracted: dict, claimed_transaction_id: str, expected_amount_etb: float, amount_tolerance: float = 0.5
) -> tuple[bool, str]:
    """(auto_approved, note). Never auto-approves on an unreadable receipt, a transaction id that
    doesn't match what the student typed, or an amount that doesn't match the bundle price - any of
    those goes to a human admin instead."""
    if not extracted.get("readable"):
        return False, "receipt image was not clearly readable"

    extracted_id = (extracted.get("transaction_id") or "").strip()
    if not extracted_id:
        return False, "no transaction id found on the receipt"
    if _normalize_id(extracted_id) != _normalize_id(claimed_transaction_id):
        return False, f"submitted transaction id does not match the receipt (receipt shows {extracted_id!r})"

    amount = extracted.get("amount_etb")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool):
        return False, "no amount found on the receipt"
    if abs(amount - expected_amount_etb) > amount_tolerance:
        return False, f"amount mismatch: receipt shows {amount} ETB, expected {expected_amount_etb} ETB"

    return True, "transaction id and amount matched the receipt"
