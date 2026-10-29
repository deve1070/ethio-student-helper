"""
Push a payment-needs-review notification straight to every admin's Telegram chat, independent of
the running bot process - a direct call to Telegram's own Bot API (sendPhoto + an inline keyboard),
not something routed through telegram_bot/'s polling loop. The bot process still handles the
Approve/Reject button taps themselves (telegram_bot/handlers/payment_handler.py's callback
routing), same as every other inline button in this project. A private Telegram chat's id is the
user's own telegram_user_id, so TelegramLink.telegram_user_id doubles as the chat id here.
"""
import json
import uuid

import httpx
from sqlalchemy.orm import Session

from config.settings import settings
from db.models import TelegramLink, User
from utils.logging import logger

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def notify_admins_pending_payment(
    db: Session,
    payment_id: uuid.UUID,
    receipt_photo_bytes: bytes,
    student_name: str,
    bundle: str,
    amount_etb: float,
    submitted_transaction_id: str,
    note: str,
) -> None:
    """Best-effort: a missing token, an admin with no Telegram link, or a network error here never
    fails the student's payment submission - it only means the admin finds out later via the
    pending-list instead of a push."""
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("No TELEGRAM_BOT_TOKEN configured - cannot push admin payment notifications")
        return

    admin_chat_ids = [
        chat_id
        for (chat_id,) in db.query(TelegramLink.telegram_user_id)
        .join(User, User.id == TelegramLink.user_id)
        .filter(User.is_admin.is_(True))
        .all()
    ]
    if not admin_chat_ids:
        logger.warning(f"Payment {payment_id} needs review but no admin has a linked Telegram account")
        return

    caption = (
        "Payment needs review\n"
        f"Student: {student_name}\n"
        f"Bundle: {bundle} ({amount_etb} ETB)\n"
        f"Submitted transaction id: {submitted_transaction_id}\n"
        f"Why it wasn't auto-approved: {note}"
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "Approve", "callback_data": f"PM|approve|{payment_id}"},
                {"text": "Reject", "callback_data": f"PM|reject|{payment_id}"},
            ]
        ]
    }
    url = TELEGRAM_API.format(token=settings.TELEGRAM_BOT_TOKEN, method="sendPhoto")
    for chat_id in admin_chat_ids:
        try:
            response = httpx.post(
                url,
                data={"chat_id": chat_id, "caption": caption, "reply_markup": json.dumps(keyboard)},
                files={"photo": receipt_photo_bytes},
                timeout=15,
            )
            if response.status_code >= 400:
                logger.warning(f"Telegram push to admin {chat_id} failed: {response.text[:200]}")
        except httpx.HTTPError as e:
            logger.warning(f"Telegram push to admin {chat_id} failed: {e}")
