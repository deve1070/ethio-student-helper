from telegram import Update
from telegram.ext import ContextTypes

from telegram_bot import api_client, reminders
from telegram_bot import store as bot_store
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
        "/remind 18:00  (a daily practice reminder)\n"
        "/explain 11 Biology What is mitosis?\n"
        "/exam 12 Physics <question>"
    )


async def logout_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forget the saved login and the daily reminder (useful on a shared phone)."""
    uid = update.effective_user.id
    api_client.logout(uid)
    bot_store.get_store().drop_reminder(uid)
    reminders.cancel_reminder(context.application.job_queue, uid)
    await update.message.reply_text(
        "Logged out. Your reminder is off too. Use /login to come back."
    )
