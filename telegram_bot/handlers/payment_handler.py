"""
/status — show subscription status, or how many free previews are left
/subscribe — shows manual-transfer instructions for the one-year plan

Send a photo with caption "/submit_receipt <transaction_id>" to submit proof of payment.
The backend checks it automatically first (reads the receipt, compares the transaction id and
amount against what you typed) and only falls back to a human admin when it isn't confident -
see backend/payments/receipt_verification.py.

Admin-only (the backend checks the calling account's is_admin flag, not this file):
/pending_payments — list payments awaiting manual review, each with Approve/Reject buttons.
/grant <phone or email> [days] — free access without payment (e.g. a school ambassador), default 365 days.
/pending_payouts — list referral payout requests with the amount and the account to send it to,
each with Mark paid/Reject buttons (the same buttons are on the push sent when a student asks).
The same Approve/Reject buttons also appear on the notification pushed straight to an admin's
chat the moment a receipt needs review (backend/payments/admin_notify.py) - both call the same
payment_review_callback below.
"""
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from telegram_bot import api_client
from telegram_bot.api_client import BackendError



def subscribe_instructions(config: dict) -> str:
    """The price and receiving accounts come from the backend's /v1/auth/public-config, the one place
    they are set, so a price change never needs a bot release."""
    return (
        "One payment, a full year of unlimited access:\n"
        f"1. Send {config['subscription_price_etb']:g} ETB to either:\n"
        f"   • Telebirr: {config['payment_telebirr_number']}\n"
        f"   • CBE: {config['payment_cbe_account']}\n"
        "2. Send a photo of the receipt here with this exact caption:\n"
        "   /submit_receipt <the transaction id from your receipt>\n\n"
        "Most receipts are verified automatically within seconds; if the photo isn't clear "
        "enough to read, an admin will check it manually instead."
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # effective_message, not message: also called from bot.py's menu_callback with a
    # CallbackQuery-type Update when the main menu's My Status button is tapped.
    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await update.effective_message.reply_text("Please /login first with your phone/email and password.")
        return

    try:
        data = await asyncio.to_thread(api_client.get_entitlement, telegram_user_id)
    except BackendError:
        await update.effective_message.reply_text("Couldn't check your status right now — try again shortly.")
        return

    if data["has_active_subscription"]:
        await update.effective_message.reply_text(
            "You have an active subscription — unlimited access to every AI feature."
        )
    else:
        used, quota = data["free_actions_used"], data["free_actions_quota"]
        await update.effective_message.reply_text(
            f"You've used {used} of {quota} free previews.\n\n"
            "Use /subscribe for a full year of unlimited access."
        )


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # effective_message, not message: also called from bot.py's menu_callback (the main menu's
    # Subscribe button), which carries no args either.
    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await update.effective_message.reply_text("Please /login first with your phone/email and password.")
        return
    try:
        config = await asyncio.to_thread(api_client.public_config)
    except BackendError:
        await update.effective_message.reply_text("Couldn't load the payment details right now — try again shortly.")
        return
    await update.effective_message.reply_text(subscribe_instructions(config))


async def receipt_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A photo sent with caption '/submit_receipt <transaction_id>'. Silently does nothing if
    the caption doesn't start with /submit_receipt, so it never interferes with
    exam_photo_handler's own '/exam ...'-captioned photos registered on the same update."""
    caption = update.message.caption or ""
    if not caption.startswith("/submit_receipt"):
        return

    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await update.message.reply_text("Please /login first with your phone/email and password.")
        return

    parts = caption.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text(
            "Caption format: /submit_receipt <the transaction id from your receipt>"
        )
        return
    transaction_id = parts[1].strip()

    # a photo, or an image sent as a file (the backend converts either to JPEG)
    attachment = update.message.photo[-1] if update.message.photo else update.message.document
    file = await attachment.get_file()
    photo_bytes = bytes(await file.download_as_bytearray())

    await update.message.reply_text("Checking your receipt...")
    try:
        result = await asyncio.to_thread(api_client.submit_receipt, telegram_user_id, transaction_id, photo_bytes)
    except BackendError as e:
        await update.message.reply_text(f"Couldn't submit that receipt: {e.detail}")
        return

    await update.message.reply_text(result["message"])


def _review_keyboard(payment_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Approve", callback_data=f"PM|approve|{payment_id}"),
                InlineKeyboardButton("Reject", callback_data=f"PM|reject|{payment_id}"),
            ]
        ]
    )


async def pending_payments_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await update.message.reply_text("Please /login first with your phone/email and password.")
        return

    try:
        pending = await asyncio.to_thread(api_client.list_pending_payments, telegram_user_id)
    except BackendError as e:
        if e.status_code == 403:
            await update.message.reply_text("This command is for admins only.")
            return
        await update.message.reply_text("Couldn't load pending payments right now — try again shortly.")
        return

    if not pending:
        await update.message.reply_text("No payments are waiting for review.")
        return

    for p in pending:
        text = (
            f"Student: {p['student_name']}\n"
            f"Amount: {p['amount_etb']} ETB\n"
            f"Submitted transaction id: {p['submitted_transaction_id']}\n"
            f"Why it needs review: {p['verification_note']}"
        )
        await update.message.reply_text(text, reply_markup=_review_keyboard(p["payment_id"]))


async def payment_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the Approve/Reject buttons, whether they came from /pending_payments or a pushed
    admin_notify.py notification (both use the same 'PM|approve|<id>' / 'PM|reject|<id>' data)."""
    query = update.callback_query
    await query.answer()
    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Please /login first with your phone/email and password.")
        return

    _, action, payment_id = query.data.split("|", 2)
    try:
        if action == "approve":
            await asyncio.to_thread(api_client.approve_payment, telegram_user_id, payment_id)
            outcome = "Approved — subscription granted/extended."
        else:
            await asyncio.to_thread(api_client.reject_payment, telegram_user_id, payment_id)
            outcome = "Rejected."
    except BackendError as e:
        if e.status_code == 403:
            await query.message.reply_text("This action is for admins only.")
            return
        if e.status_code == 409:
            outcome = "Already reviewed by someone else."
        else:
            await query.message.reply_text(f"Couldn't update that payment: {e.detail}")
            return

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(outcome)


def _payout_keyboard(payout_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Mark paid", callback_data=f"RP|paid|{payout_id}"),
                InlineKeyboardButton("Reject", callback_data=f"RP|reject|{payout_id}"),
            ]
        ]
    )


async def pending_payouts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await update.message.reply_text("Please /login first with your phone/email and password.")
        return

    try:
        pending = await asyncio.to_thread(api_client.list_pending_payouts, telegram_user_id)
    except BackendError as e:
        if e.status_code == 403:
            await update.message.reply_text("This command is for admins only.")
            return
        await update.message.reply_text("Couldn't load payout requests right now — try again shortly.")
        return

    if not pending:
        await update.message.reply_text("No referral payouts are waiting.")
        return

    total = sum(p["amount_etb"] for p in pending)
    await update.message.reply_text(f"{len(pending)} payout(s) waiting, {total:.2f} ETB in total.")
    for p in pending:
        await update.message.reply_text(p["text"], reply_markup=_payout_keyboard(p["payout_id"]))


async def payout_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The Mark paid/Reject buttons, from /pending_payouts or the push sent when a student asks."""
    query = update.callback_query
    await query.answer()
    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await query.message.reply_text("Please /login first with your phone/email and password.")
        return

    _, action, payout_id = query.data.split("|", 2)
    try:
        await asyncio.to_thread(api_client.review_payout, telegram_user_id, payout_id, action)
        outcome = "Marked paid. The student has been told." if action == "paid" else "Rejected. The amount is back in the student's balance."
    except BackendError as e:
        if e.status_code == 403:
            await query.message.reply_text("This action is for admins only.")
            return
        if e.status_code == 409:
            outcome = "Already handled by someone else."
        else:
            await query.message.reply_text(f"Couldn't update that payout: {e.detail}")
            return

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(outcome)


async def grant_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/grant <phone or email> [days]"""
    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await update.message.reply_text("Please /login first with your phone/email and password.")
        return
    args = context.args or []
    days = 365
    if len(args) >= 2 and args[-1].isdigit():
        days = int(args[-1])
        args = args[:-1]
    identifier = " ".join(args).strip()
    if not identifier:
        await update.message.reply_text("Usage: /grant <phone or email> [days]\nExample: /grant 0912345678 180")
        return
    try:
        result = await asyncio.to_thread(api_client.grant_subscription, telegram_user_id, identifier, days)
    except BackendError as e:
        if e.status_code == 403:
            await update.message.reply_text("This command is for admins only.")
        else:
            await update.message.reply_text(f"Couldn't grant access: {e.detail}")
        return
    await update.message.reply_text(
        f"Done. {result['student_name']} has free access until {result['expires_at'][:10]}. They've been told on Telegram if linked."
    )
