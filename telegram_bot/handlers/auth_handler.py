"""
/login <identifier> <password> — links this Telegram account to an
existing account (students sign up on the web app first; this just
connects the bot to that same account).

The bot attempts to delete the incoming message afterward so the
password doesn't sit in the visible chat history. This only works in
private chats and isn't guaranteed by the Telegram API — treat it as
chat hygiene, not a real security boundary.
"""

from telegram import Update
from telegram.ext import ContextTypes

from telegram_bot import api_client
from telegram_bot.api_client import BackendError


async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_user_id = update.effective_user.id
    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "Usage: /login <phone or email> <password>\n"
            "(Sign up first on the web app if you don't have an account yet.)"
        )
        return

    identifier, password = args
    try:
        api_client.link_account(telegram_user_id, identifier, password)
    except BackendError:
        await update.message.reply_text(
            "Login failed — check your phone/email and password and try again."
        )
        return
    finally:
        try:
            await update.message.delete()
        except Exception:
            pass  # best-effort; not fatal if the bot lacks delete permission

    await update.message.reply_text(
        "Logged in! Try:\n"
        "/practice  (multiple-choice questions)\n"
        "/explain 11 Biology What is mitosis?\n"
        "/exam 12 Physics <question>"
    )
