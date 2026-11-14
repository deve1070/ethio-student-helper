import asyncio
from telegram import Update
from telegram.ext import ContextTypes

from telegram_bot import api_client, reminders
from telegram_bot import store as bot_store
from telegram_bot.api_client import BackendError

LOGIN_FLOW_KEY = "login_flow"  # context.user_data entry while the guided flow is mid-way -
# {"step": "identifier"} right after the Login button/bare /login, then {"step": "password",
# "identifier": ...} once the identifier has been typed.


async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # effective_message, not message: also called from bot.py's menu_callback with a
    # CallbackQuery-type Update when the main menu's Login button is tapped - that carries no
    # args either, so it starts the same guided prompt flow as typing bare /login.
    args = context.args or []
    if len(args) == 2:
        # The one-line power-user shortcut - kept working unchanged alongside the guided flow,
        # same as /exam's and /explain's typed forms coexisting with their own guided buttons.
        identifier, password = args
        await _do_login(update, update.effective_user.id, identifier, password, delete_message=True)
        return
    if args:
        # Wrong number of typed args (not zero) - still a usage error, not a reason to start a
        # fresh guided flow underneath a half-typed command.
        await update.effective_message.reply_text(
            "Usage: /login <phone or email> <password>\n"
            "(Sign up first on the web app if you don't have an account yet.)"
        )
        return

    context.user_data[LOGIN_FLOW_KEY] = {"step": "identifier"}
    await update.effective_message.reply_text("What's your phone number or email?")


async def login_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Free text while the guided /login flow above is waiting for the identifier or the
    password. Silently ignores everything else, same convention as exam_text_handler/
    explain_text_handler registered on the same filter (each checks its own state)."""
    flow = context.user_data.get(LOGIN_FLOW_KEY)
    if not flow:
        return

    if flow["step"] == "identifier":
        flow["identifier"] = update.message.text.strip()
        flow["step"] = "password"
        await update.message.reply_text("And your password?")
        return

    # step == "password"
    identifier = flow["identifier"]
    password = update.message.text
    context.user_data.pop(LOGIN_FLOW_KEY, None)  # one-shot: the next message needs a fresh /login
    await _do_login(update, update.effective_user.id, identifier, password, delete_message=True)


async def _do_login(
    update: Update, telegram_user_id: int, identifier: str, password: str, delete_message: bool
) -> None:
    """Shared by the typed one-liner and the guided flow's final step, so success/failure/
    message-deletion handling is written once. In the guided flow, the message being deleted
    contains ONLY the password (not identifier+password together like the old one-liner) -
    strictly less plaintext password exposure left in the chat than before this flow existed."""
    try:
        await asyncio.to_thread(api_client.link_account, telegram_user_id, identifier, password)
    except BackendError:
        await update.message.reply_text(
            "Login failed — check your phone/email and password and try again."
        )
        return
    finally:
        if delete_message:
            try:
                await update.message.delete()
            except Exception:
                pass  # best-effort; not fatal if the bot lacks delete permission

    await update.message.reply_text(
        "Logged in! Try:\n"
        "/practice  (multiple-choice questions)\n"
        "/remind 18:00  (a daily practice reminder)\n"
        "/explain  (ask the textbook a question)\n"
        "/exam  (get help with an exam question)"
    )


async def logout_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forget the saved login and the daily reminder (useful on a shared phone). effective_message,
    not message: also called from bot.py's menu_callback when the main menu's Logout button is
    tapped - this one needs no typed input at all, so the button form fully replaces typing it."""
    uid = update.effective_user.id
    api_client.logout(uid)
    bot_store.get_store().drop_reminder(uid)
    reminders.cancel_reminder(context.application.job_queue, uid)
    await update.effective_message.reply_text(
        "Logged out. Your reminder is off too. Use /login to come back."
    )
