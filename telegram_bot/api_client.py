import httpx

from telegram_bot import store as _store
from telegram_bot.config import BACKEND_BASE_URL

# Login tokens are kept by telegram_bot/store.py (a file), so a bot restart does not log students out.
# A token that the backend rejects (401) is forgotten at once, so the next command asks for /login.
# Run ONE bot process: the file is not safe to share between several.


class BackendError(Exception):
    def __init__(self, status_code: int, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{status_code}: {detail}")


def _headers(telegram_user_id: int) -> dict:
    token = _store.get_store().get_token(telegram_user_id)
    if not token:
        raise BackendError(401, "Not logged in")
    return {"Authorization": f"Bearer {token}"}


def _raise_for_status(
    response: httpx.Response, telegram_user_id: int | None = None
) -> None:
    if response.status_code == 401 and telegram_user_id is not None:
        _store.get_store().drop_token(telegram_user_id)
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = response.text
        raise BackendError(response.status_code, detail)


def is_logged_in(telegram_user_id: int) -> bool:
    return _store.get_store().get_token(telegram_user_id) is not None


def logout(telegram_user_id: int) -> None:
    _store.get_store().drop_token(telegram_user_id)


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
    _store.get_store().set_token(telegram_user_id, response.json()["access_token"])


def explain(telegram_user_id: int, grade: int, subject: str, question: str) -> dict:
    response = httpx.post(
        f"{BACKEND_BASE_URL}/v1/explain",
        json={"grade": grade, "subject": subject, "question": question},
        headers=_headers(telegram_user_id),
        timeout=60,
    )
    _raise_for_status(response, telegram_user_id)
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
    _raise_for_status(response, telegram_user_id)
    return response.json()


def get_credits(telegram_user_id: int) -> dict:
    response = httpx.get(
        f"{BACKEND_BASE_URL}/v1/me/credits",
        headers=_headers(telegram_user_id),
        timeout=15,
    )
    _raise_for_status(response, telegram_user_id)
    return response.json()


def submit_receipt(
    telegram_user_id: int, bundle: str, transaction_id: str, photo_bytes: bytes
) -> dict:
    response = httpx.post(
        f"{BACKEND_BASE_URL}/v1/payments/submit-receipt",
        data={"bundle": bundle, "transaction_id": transaction_id},
        files={"receipt": ("receipt.jpg", photo_bytes, "image/jpeg")},
        headers=_headers(telegram_user_id),
        timeout=30,  # the backend runs a vision call before replying
    )
    _raise_for_status(response, telegram_user_id)
    return response.json()


def list_pending_payments(telegram_user_id: int) -> list:
    response = httpx.get(
        f"{BACKEND_BASE_URL}/v1/payments/pending",
        headers=_headers(telegram_user_id),
        timeout=15,
    )
    _raise_for_status(response, telegram_user_id)
    return response.json()


def approve_payment(telegram_user_id: int, payment_id: str) -> dict:
    response = httpx.post(
        f"{BACKEND_BASE_URL}/v1/payments/{payment_id}/approve",
        headers=_headers(telegram_user_id),
        timeout=15,
    )
    _raise_for_status(response, telegram_user_id)
    return response.json()


def reject_payment(telegram_user_id: int, payment_id: str) -> dict:
    response = httpx.post(
        f"{BACKEND_BASE_URL}/v1/payments/{payment_id}/reject",
        headers=_headers(telegram_user_id),
        timeout=15,
    )
    _raise_for_status(response, telegram_user_id)
    return response.json()


# ---- practice mode (questions served from the approved question bank; no AI call, no credits) ----------------
def _get(telegram_user_id: int, path: str, params: dict, timeout: int = 20) -> dict:
    response = httpx.get(
        f"{BACKEND_BASE_URL}{path}",
        params=params,
        headers=_headers(telegram_user_id),
        timeout=timeout,
    )
    _raise_for_status(response, telegram_user_id)
    return response.json()


def _post(telegram_user_id: int, path: str, body: dict, timeout: int = 20) -> dict:
    response = httpx.post(
        f"{BACKEND_BASE_URL}{path}",
        json=body,
        headers=_headers(telegram_user_id),
        timeout=timeout,
    )
    _raise_for_status(response, telegram_user_id)
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


# ---- ESSLCE (Grade-12 national exam past papers) mode -------------------------------------------------------
def esslce_subjects(telegram_user_id: int) -> dict:
    return _get(telegram_user_id, "/v1/esslce/subjects", {})


def esslce_papers(telegram_user_id: int, subject: str) -> dict:
    return _get(telegram_user_id, "/v1/esslce/papers", {"subject": subject})


def esslce_units(telegram_user_id: int, subject: str) -> dict:
    return _get(telegram_user_id, "/v1/esslce/units", {"subject": subject})


def esslce_skills(telegram_user_id: int, subject: str) -> dict:
    return _get(telegram_user_id, "/v1/esslce/skills", {"subject": subject})


def esslce_progress(telegram_user_id: int, subject: str) -> dict:
    return _get(telegram_user_id, "/v1/esslce/progress", {"subject": subject})


def esslce_diagnostic(telegram_user_id: int, subject: str, count: int = 15) -> dict:
    return _post(
        telegram_user_id, "/v1/esslce/diagnostic", {"subject": subject, "count": count}
    )


def esslce_next(
    telegram_user_id: int,
    subject: str,
    paper_id: int | None = None,
    unit: str | None = None,
    grade: int | None = None,
    skill: str | None = None,
    incorrect_only: bool = False,
    count: int = 5,
) -> dict:
    body = {"subject": subject, "count": count}
    if paper_id is not None:
        body["paper_id"] = paper_id
    if unit is not None:
        body["unit"] = unit
        body["grade"] = grade
    if skill is not None:
        body["skill"] = skill
    if incorrect_only:
        body["incorrect_only"] = True
    return _post(telegram_user_id, "/v1/esslce/next", body)


def esslce_answer(
    telegram_user_id: int, question_id: int, chosen_index: int, mode: str = "practice"
) -> dict:
    return _post(
        telegram_user_id,
        "/v1/esslce/answer",
        {"question_id": question_id, "chosen_index": chosen_index, "mode": mode},
    )


def esslce_exam_summary(telegram_user_id: int, paper_id: int) -> dict:
    return _post(telegram_user_id, "/v1/esslce/exam-summary", {"paper_id": paper_id})


def esslce_elaborate(telegram_user_id: int, question_id: int) -> dict:
    # a cache miss means a live LLM call (grounding retrieval, or a generated+verified example) - slower
    # than every other esslce_* call, which only ever touch the database
    return _post(
        telegram_user_id, "/v1/esslce/elaborate", {"question_id": question_id}, timeout=60
    )


def esslce_ask(telegram_user_id: int, question_id: int, message: str, history: list) -> dict:
    # NEVER cached server-side (unlike elaborate) - every call is a fresh LLM call
    return _post(
        telegram_user_id,
        "/v1/esslce/ask",
        {"question_id": question_id, "message": message, "history": history},
        timeout=60,
    )
