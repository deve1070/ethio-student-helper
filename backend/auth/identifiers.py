"""One stored format for the two things a student logs in with.

A phone number is stored as the 10-digit local form 09XXXXXXXX (Ethio Telecom) or 07XXXXXXXX
(Safaricom), and an email in lower case. Signup stores that form, and every lookup (login, Telegram
link, password reset) converts what was typed the same way first, so "+251 912 345 678",
"0912-345-678" and "0912345678" all reach the same account.
"""

import re

_SEPARATORS = re.compile(r"[\s\-().]")
_LOCAL = re.compile(r"0[79]\d{8}")
_INTERNATIONAL = re.compile(r"251[79]\d{8}")
_NO_PREFIX = re.compile(r"[79]\d{8}")

PHONE_FORMAT_ERROR = "Enter an Ethiopian mobile number like 0912345678."


def normalize_phone(raw: str) -> str:
    """The 09/07 local form of an Ethiopian mobile number, or ValueError if `raw` isn't one."""
    digits = _SEPARATORS.sub("", raw.strip()).removeprefix("+")
    if _LOCAL.fullmatch(digits):
        return digits
    if _INTERNATIONAL.fullmatch(digits):
        return "0" + digits[3:]
    if _NO_PREFIX.fullmatch(digits):
        return "0" + digits
    raise ValueError(PHONE_FORMAT_ERROR)


def normalize_email(raw: str) -> str:
    return raw.strip().lower()


def normalize_identifier(raw: str) -> str:
    """The stored form of a login identifier. Text that is neither an email nor a valid phone number
    is returned stripped but otherwise unchanged; it matches no account, which the caller reports as
    invalid credentials."""
    text = raw.strip()
    if "@" in text:
        return normalize_email(text)
    try:
        return normalize_phone(text)
    except ValueError:
        return text
