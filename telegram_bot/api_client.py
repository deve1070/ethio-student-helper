"""
Thin HTTP client the bot uses to call the backend API. Every function
here maps to one endpoint from docs/data-model-api.md; the bot never
touches the database, vector store, or payment gateway directly — the
same backend that serves the web app and mobile app serves this too.
"""

import httpx

from telegram_bot.config import BACKEND_BASE_URL

# In-memory session store: telegram_user_id -> bearer token. Fine for a
# single-process bot during development; replace with something
# persistent (Redis, a small table) before running more than one worker,
# or before a restart should keep students logged in.
_sessions: dict[int, str] = {}


class BackendError(Exception):
    def __init__(self, status_code: int, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{status_code}: {detail}")


def _headers(telegram_user_id: int) -> dict:
    token = _sessions.get(telegram_user_id)
    if not token:
        raise BackendError(401, "Not logged in")
    return {"Authorization": f"Bearer {token}"}


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = response.text
        raise BackendError(response.status_code, detail)


def is_logged_in(telegram_user_id: int) -> bool:
    return telegram_user_id in _sessions


def link_account(telegram_user_id: int, identifier: str, password: str) -> None:
    response = httpx.post(
        f"{BACKEND_BASE_URL}/v1/auth/telegram-link",
        json={
            "telegram_user_id": telegram_user_id,
            "identifier": identifier,
            "password": password,
        },
        timeout=15,
    )
    _raise_for_status(response)
    _sessions[telegram_user_id] = response.json()["access_token"]


def explain(telegram_user_id: int, grade: int, subject: str, question: str) -> dict:
    response = httpx.post(
        f"{BACKEND_BASE_URL}/v1/explain",
        json={"grade": grade, "subject": subject, "question": question},
        headers=_headers(telegram_user_id),
        timeout=60,
    )
    _raise_for_status(response)
    return response.json()


def exam_solve(
    telegram_user_id: int,
    grade: int,
    subject: str,
    question_text: str | None = None,
    image_base64: str | None = None,
    exam_year: int | None = None,
) -> dict:
    response = httpx.post(
        f"{BACKEND_BASE_URL}/v1/exam/solve",
        json={
            "grade": grade,
            "subject": subject,
            "exam_year": exam_year,
            "question_text": question_text,
            "image_base64": image_base64,
        },
        headers=_headers(telegram_user_id),
        timeout=90,  # OCR + a possible LLM call can be slow
    )
    _raise_for_status(response)
    return response.json()


def get_credits(telegram_user_id: int) -> dict:
    response = httpx.get(
        f"{BACKEND_BASE_URL}/v1/me/credits",
        headers=_headers(telegram_user_id),
        timeout=15,
    )
    _raise_for_status(response)
    return response.json()


def checkout(telegram_user_id: int, bundle: str) -> dict:
    response = httpx.post(
        f"{BACKEND_BASE_URL}/v1/payments/checkout",
        json={"bundle": bundle},
        headers=_headers(telegram_user_id),
        timeout=15,
    )
    _raise_for_status(response)
    return response.json()


# ---- practice mode (questions served from the approved question bank; no AI call, no credits) ----------------
def _get(telegram_user_id: int, path: str, params: dict, timeout: int = 20) -> dict:
    response = httpx.get(
        f"{BACKEND_BASE_URL}{path}",
        params=params,
        headers=_headers(telegram_user_id),
        timeout=timeout,
    )
    _raise_for_status(response)
    return response.json()


def _post(telegram_user_id: int, path: str, body: dict, timeout: int = 20) -> dict:
    response = httpx.post(
        f"{BACKEND_BASE_URL}{path}",
        json=body,
        headers=_headers(telegram_user_id),
        timeout=timeout,
    )
    _raise_for_status(response)
    return response.json()


def practice_subjects(telegram_user_id: int, grade: int) -> dict:
    return _get(telegram_user_id, "/v1/practice/subjects", {"grade": grade})


def practice_units(telegram_user_id: int, grade: int, subject: str) -> dict:
    return _get(
        telegram_user_id, "/v1/practice/units", {"grade": grade, "subject": subject}
    )


def practice_next(
    telegram_user_id: int,
    grade: int,
    subject: str,
    units: list[str] | None = None,
    count: int = 5,
) -> dict:
    body = {"grade": grade, "subject": subject, "count": count}
    if units:
        body["units"] = units
    return _post(telegram_user_id, "/v1/practice/next", body)


def practice_answer(telegram_user_id: int, question_id: str, chosen_index: int) -> dict:
    return _post(
        telegram_user_id,
        "/v1/practice/answer",
        {"question_id": question_id, "chosen_index": chosen_index},
    )


def practice_progress(telegram_user_id: int, grade: int, subject: str) -> dict:
    return _get(
        telegram_user_id, "/v1/practice/progress", {"grade": grade, "subject": subject}
    )


def practice_report(
    telegram_user_id: int, question_id: str, reason: str | None = None
) -> dict:
    return _post(
        telegram_user_id,
        "/v1/practice/report",
        {"question_id": question_id, "reason": reason},
    )
