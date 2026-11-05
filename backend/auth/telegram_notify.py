"""Push a plain text message straight to a student's own Telegram chat, independent of the running
bot process - same direct call to Telegram's own Bot API as payments/admin_notify.py (sendMessage here,
rather than that module's sendPhoto), not something routed through telegram_bot/'s polling loop. Used
by api/routes_auth.py's password-reset flow and payments/referral.py's referral notification."""

import httpx
from sqlalchemy.orm import Session

from config.settings import settings
from db.models import TelegramLink, User
from utils.logging import logger

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def _chat_id_for(db: Session, user: User) -> int | None:
    """The most-recently-linked Telegram chat for this user, or None if they've never linked one.
    TelegramLink.user_id has no uniqueness constraint - a student could in principle have linked from
    more than one Telegram account over time (api/routes_auth.py's telegram_link() lets a later login
    from a different chat overwrite that chat's OWN mapping, but never deletes an older mapping from a
    different chat) - the latest one is the one actually still in use."""
    link = (
        db.query(TelegramLink)
        .filter(TelegramLink.user_id == user.id)
        .order_by(TelegramLink.linked_at.desc())
        .first()
    )
    return link.telegram_user_id if link else None


def send_text(db: Session, user: User, text: str) -> bool:
    """Best-effort: returns whether the message actually went out, so a caller (e.g. the password-reset
    request endpoint) never tells a student "check Telegram" when nothing was actually sent."""
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("No TELEGRAM_BOT_TOKEN configured - cannot push Telegram messages")
        return False
    chat_id = _chat_id_for(db, user)
    if chat_id is None:
        return False
    url = TELEGRAM_API.format(token=settings.TELEGRAM_BOT_TOKEN, method="sendMessage")
    try:
        response = httpx.post(url, data={"chat_id": chat_id, "text": text}, timeout=15)
        if response.status_code >= 400:
            logger.warning(f"Telegram push to {chat_id} failed: {response.text[:200]}")
            return False
        return True
    except httpx.HTTPError as e:
        logger.warning(f"Telegram push to {chat_id} failed: {e}")
        return False
