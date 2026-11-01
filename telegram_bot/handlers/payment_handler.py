"""
/credits — show current balance and, if applicable, subscription status
/buy <bundle> — shows manual-transfer instructions for that bundle

Send a photo with caption "/submit_receipt <bundle> <transaction_id>" to submit proof of payment.
The backend checks it automatically first (reads the receipt, compares the transaction id and
amount against what you typed) and only falls back to a human admin when it isn't confident -
see backend/payments/receipt_verification.py.

Admin-only (the backend checks the calling account's is_admin flag, not this file):
/pending_payments — list payments awaiting manual review, each with Approve/Reject buttons.
The same Approve/Reject buttons also appear on the notification pushed straight to an admin's
chat the moment a receipt needs review (backend/payments/admin_notify.py) - both call the same
payment_review_callback below.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from telegram_bot import api_client
from telegram_bot.api_client import BackendError

# Duplicated from backend/api/routes_payments.py's CREDIT_BUNDLES deliberately - this is display
# text for a different process (the bot) reached only over HTTP; the backend stays the only place
# that actually prices or validates a bundle.
BUNDLES_HELP = "Available bundles: bundle_5 (5 credits, 25 ETB), bundle_20 (20 credits, 90 ETB)"
BUNDLE_AMOUNTS_ETB = {"bundle_5": 25.0, "bundle_20": 90.0}

# The business's own receiving accounts - public by design (every student needs these to pay),
# not a secret, so plain module constants rather than something from settings/.env.
TELEBIRR_NUMBER = "0909575318"
CBE_ACCOUNT_NUMBER = "1000198942948"


def _buy_instructions(bundle: str) -> str:
    amount = BUNDLE_AMOUNTS_ETB[bundle]
    return (
        f"To buy {bundle}:\n"
        f"1. Send {amount:.0f} ETB to either:\n"
        f"   • Telebirr: {TELEBIRR_NUMBER}\n"
        f"   • CBE: {CBE_ACCOUNT_NUMBER}\n"
        f"2. Send a photo of the receipt here with this exact caption:\n"
        f"   /submit_receipt {bundle} <the transaction id from your receipt>\n\n"
        "Most receipts are verified automatically within seconds; if the photo isn't clear "
        "enough to read, an admin will check it manually instead."
    )


def _bundle_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{bundle} ({BUNDLE_AMOUNTS_ETB[bundle]:.0f} ETB)", callback_data=f"by|{bundle}")]
        for bundle in BUNDLE_AMOUNTS_ETB
    ])


async def credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # effective_message, not message: also called from bot.py's menu_callback with a
    # CallbackQuery-type Update when the main menu's My Credits button is tapped.
    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await update.effective_message.reply_text("Please /login first with your phone/email and password.")
        return

    try:
        data = api_client.get_credits(telegram_user_id)
    except BackendError:
        await update.effective_message.reply_text("Couldn't check your balance right now — try again shortly.")
        return

    if data["has_active_subscription"]:
        await update.effective_message.reply_text("You have an active subscription — unlimited exam solves.")
    else:
        await update.effective_message.reply_text(f"You have {data['balance']} credit(s) remaining.\n\n{BUNDLES_HELP}")


async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # effective_message, not message: also called from bot.py's menu_callback (the main menu's
    # Buy Credits button), which never carries typed args - that always falls into the button-
    # picker branch below, same as typing bare /buy.
    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await update.effective_message.reply_text("Please /login first with your phone/email and password.")
        return

    args = context.args or []
    if not args or args[0] not in BUNDLE_AMOUNTS_ETB:
        await update.effective_message.reply_text(
            f"Pick a bundle:\n\n{BUNDLES_HELP}", reply_markup=_bundle_keyboard()
        )
        return

    await update.effective_message.reply_text(_buy_instructions(args[0]))


async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The bundle buttons buy_command shows when typed with no args (or tapped from the main menu)."""
    query = update.callback_query
    await query.answer()
    bundle = query.data.split("|", 1)[1]
    try:
        await query.edit_message_text(_buy_instructions(bundle))
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def receipt_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A photo sent with caption '/submit_receipt <bundle> <transaction_id>'. Silently does
    nothing if the caption doesn't start with /submit_receipt, so it never interferes with
    exam_photo_handler's own '/exam ...'-captioned photos registered on the same update."""
    caption = update.message.caption or ""
    if not caption.startswith("/submit_receipt"):
        return

    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await update.message.reply_text("Please /login first with your phone/email and password.")
        return

    parts = caption.split(maxsplit=2)
    if len(parts) < 3 or parts[1] not in BUNDLE_AMOUNTS_ETB:
        await update.message.reply_text(
            "Caption format: /submit_receipt <bundle> <transaction_id>\n\n" + BUNDLES_HELP
        )
        return
    bundle, transaction_id = parts[1], parts[2].strip()

    photo = update.message.photo[-1]
    file = await photo.get_file()
    photo_bytes = bytes(await file.download_as_bytearray())

    await update.message.reply_text("Checking your receipt...")
    try:
        result = api_client.submit_receipt(telegram_user_id, bundle, transaction_id, photo_bytes)
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
        pending = api_client.list_pending_payments(telegram_user_id)
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
            f"Amount: {p['amount_etb']} ETB ({p['credits_granted']} credits)\n"
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
            api_client.approve_payment(telegram_user_id, payment_id)
            outcome = "Approved — credits added."
        else:
            api_client.reject_payment(telegram_user_id, payment_id)
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
