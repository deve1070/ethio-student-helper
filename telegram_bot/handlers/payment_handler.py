"""
/credits — show current balance and, if applicable, subscription status
/buy <bundle> — start a Chapa checkout, e.g. /buy bundle_5
"""
from telegram import Update
from telegram.ext import ContextTypes

from telegram_bot import api_client
from telegram_bot.api_client import BackendError

BUNDLES_HELP = "Available bundles: bundle_5 (5 credits, 25 ETB), bundle_20 (20 credits, 90 ETB)"


async def credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await update.message.reply_text("Please /login first with your phone/email and password.")
        return

    try:
        data = api_client.get_credits(telegram_user_id)
    except BackendError:
        await update.message.reply_text("Couldn't check your balance right now — try again shortly.")
        return

    if data["has_active_subscription"]:
        await update.message.reply_text("You have an active subscription — unlimited exam solves.")
    else:
        await update.message.reply_text(f"You have {data['balance']} credit(s) remaining.\n\n{BUNDLES_HELP}")


async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await update.message.reply_text("Please /login first with your phone/email and password.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /buy <bundle>\n\n" + BUNDLES_HELP)
        return

    try:
        session = api_client.checkout(telegram_user_id, context.args[0])
    except BackendError as e:
        await update.message.reply_text(f"Couldn't start checkout: {e.detail}")
        return

    await update.message.reply_text(
        f"Tap to pay: {session['checkout_url']}\n\n"
        "Your credits will be added automatically once the payment is confirmed."
    )
