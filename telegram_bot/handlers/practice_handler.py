"""
/practice  — choose grade, subject and unit, then answer multiple-choice questions with buttons
/progress  — see your accuracy per unit and your weakest units

The conversation itself is in telegram_bot/practice_flow.py; this file only connects it to Telegram.
Backend calls run in a worker thread so one student's slow request never freezes the bot for everyone.
"""

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from telegram_bot import api_client
from telegram_bot.api_client import BackendError
from telegram_bot.practice_flow import FlowError, PracticeSession

SESSION_KEY = "practice_session"
LOGIN_FIRST = "Please /login first with your phone/email and password."


def keyboard(screen) -> InlineKeyboardMarkup | None:
    if not screen.buttons:
        return None
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, callback_data=data) for label, data in row]
            for row in screen.buttons
        ]
    )


def friendly_practice_error(e: BackendError) -> str:
    if e.status_code == 401:
        return "Your session expired. Please /login again."
    if e.status_code in (400, 404):
        return f"That didn't work: {e.detail}"
    if e.status_code == 503:
        return "The service is busy right now. Please try again in a minute."
    return "Something went wrong on our side. Please try again in a moment."


async def _start(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str) -> None:
    user_id = update.effective_user.id
    if not api_client.is_logged_in(user_id):
        await update.message.reply_text(LOGIN_FIRST)
        return
    session = PracticeSession(api_client, user_id, mode)
    context.user_data[SESSION_KEY] = session
    screen = session.start()
    await update.message.reply_text(screen.text, reply_markup=keyboard(screen))


async def practice_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _start(update, context, "practice")


async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _start(update, context, "progress")


async def practice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Every button of the practice and progress menus."""
    query = update.callback_query
    session = context.user_data.get(SESSION_KEY)
    if session is None or not api_client.is_logged_in(query.from_user.id):
        await query.answer(
            "This menu has expired. Send /practice to start again.", show_alert=True
        )
        return
    try:
        screen = await asyncio.to_thread(session.handle, query.data)
    except FlowError as e:
        await query.answer(str(e), show_alert=True)
        return
    except BackendError as e:
        await query.answer(friendly_practice_error(e), show_alert=True)
        return
    await query.answer()
    if screen is None:  # e.g. the student tapped the same answer twice
        return
    try:
        await query.edit_message_text(text=screen.text, reply_markup=keyboard(screen))
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise
