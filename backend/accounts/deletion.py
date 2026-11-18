"""Deleting a student's account at their own request (api/routes_auth.py's POST /v1/auth/me/delete).

What happens to each kind of data:
  - Everything about the person (profile, password, progress, answers, plans, Telegram link, reset
    codes, subscriptions, group membership) is deleted by the database itself: those tables' foreign
    keys to users are ON DELETE CASCADE.
  - Payments and referral payouts stay as the business's record of money received and sent: their
    foreign keys are ON DELETE SET NULL, so only the link to the person goes. A payment still waiting
    for review is closed first, since nobody is left to receive the subscription, and receipt photos
    (which show the person's name) are removed from storage.
  - Students this person referred keep their accounts; users.referred_by_user_id is SET NULL.

Deletion is refused while the student still has referral money waiting (a pending payout, or an
available balance), so nobody loses money by accident.
"""

import uuid

import httpx
from sqlalchemy import delete
from sqlalchemy.orm import Session

import storage
from config.settings import settings
from db.models import Payment, TelegramLink, User
from payments.referral import referral_balance
from utils.logging import logger

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


class DeletionBlocked(Exception):
    """Deleting now would lose the student's money; the message says what to do instead."""


def check_can_delete(db: Session, user: User) -> None:
    balance = referral_balance(db, user)
    if balance["pending"] > 0:
        raise DeletionBlocked(
            f"Your referral payout of {balance['pending']:.2f} ETB is still being sent. "
            "You can delete your account once it has arrived."
        )
    if balance["available"] > 0:
        raise DeletionBlocked(
            f"You have {balance['available']:.2f} ETB of referral earnings. Withdraw them from your "
            "Profile first, or they will be lost."
        )


def _remove_from_private_group(telegram_user_ids: list[int]) -> None:
    """Ban and immediately unban: removes the person without blocking them from ever rejoining,
    the same step the bot's expired-subscription sweep uses. Best-effort."""
    if not (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_PRIVATE_GROUP_ID):
        return
    for method in ("banChatMember", "unbanChatMember"):
        url = TELEGRAM_API.format(token=settings.TELEGRAM_BOT_TOKEN, method=method)
        for tg_id in telegram_user_ids:
            try:
                httpx.post(url, data={"chat_id": settings.TELEGRAM_PRIVATE_GROUP_ID, "user_id": tg_id}, timeout=15)
            except httpx.HTTPError as e:
                logger.warning(f"Could not remove Telegram user from the private group: {e}")


def delete_account(db: Session, user: User) -> None:
    """Call check_can_delete first. Commits."""
    user_id: uuid.UUID = user.id
    telegram_ids = [t for (t,) in db.query(TelegramLink.telegram_user_id).filter(TelegramLink.user_id == user_id)]

    receipts = []
    for payment in db.query(Payment).filter(Payment.user_id == user_id):
        if payment.status == "pending":
            payment.status = "failed"
            payment.verification_note = ((payment.verification_note or "") + " | account deleted before review").strip(" |")
        if payment.receipt_photo_path:
            receipts.append(payment.receipt_photo_path)
            payment.receipt_photo_path = None
    db.flush()

    # A bulk DELETE, not session.delete(user): the ORM would first try to null the user_id of each
    # loaded child row, which the NOT NULL columns refuse; the database's own ON DELETE rules do it right.
    db.execute(delete(User).where(User.id == user_id))
    db.commit()
    db.expunge_all()
    logger.info(f"Account {user_id} deleted at the student's request")

    # after the commit, so a failure here never leaves a half-deleted account
    for path in receipts:
        try:
            storage.delete("receipts", path)
        except Exception as e:  # noqa: BLE001 - the account is already gone; a leftover file is logged
            logger.warning(f"Could not delete receipt photo {path}: {e}")
    _remove_from_private_group(telegram_ids)
