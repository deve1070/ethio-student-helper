import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from telegram_bot import api_client, reminders
from telegram_bot import store as bot_store
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
    # effective_message, not message: this also runs when the main menu's Practice/Progress
    # button (bot.py's menu_callback) calls this same function with a CallbackQuery-type Update,
    # which has no .message of its own - effective_message resolves to the button's own message
    # in that case, the typed command's message in the usual case.
    user_id = update.effective_user.id
    if not api_client.is_logged_in(user_id):
        await update.effective_message.reply_text(LOGIN_FIRST)
        return
    session = PracticeSession(api_client, user_id, mode)
    context.user_data[SESSION_KEY] = session
    screen = session.start()
    await update.effective_message.reply_text(screen.text, reply_markup=keyboard(screen))


async def practice_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _start(update, context, "practice")


async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _start(update, context, "progress")


async def _quick_start(query, context) -> None:
    """The Start button of the daily reminder: no menus, straight to questions."""
    user_id = query.from_user.id
    if not api_client.is_logged_in(user_id):
        await query.answer(
            "Please /login first, then tap Start again.", show_alert=True
        )
        return
    session = PracticeSession(api_client, user_id, "practice")
    context.user_data[SESSION_KEY] = session
    pref = bot_store.get_store().get_pref(user_id)
    try:
        screen = (
            await asyncio.to_thread(session.quick_start, pref["grade"], pref["subject"])
            if pref
            else session.start()
        )
    except BackendError as e:
        await query.answer(friendly_practice_error(e), show_alert=True)
        return
    await query.answer()
    await _show(query, screen)


async def _show(query, screen) -> None:
    try:
        await query.edit_message_text(text=screen.text, reply_markup=keyboard(screen))
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def practice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Every button of the practice and progress menus."""
    query = update.callback_query
    if query.data == "pd":
        await _quick_start(query, context)
        return
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
    st, user_id = bot_store.get_store(), query.from_user.id
    if session.grade and session.subject:
        st.set_pref(
            user_id, session.grade, session.subject
        )  # what the reminder will offer next time
    if query.data.startswith("pa|"):
        st.mark_active(
            user_id, reminders.local_today()
        )  # they practised today: no reminder
    await _show(query, screen)
