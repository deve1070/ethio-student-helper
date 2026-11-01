import asyncio
import base64
import io

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from telegram_bot import api_client
from telegram_bot.api_client import BackendError
from telegram_bot.esslce_flow import EsslceSession
from telegram_bot.practice_flow import FlowError

SESSION_KEY = "esslce_session"
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


def friendly_esslce_error(e: BackendError) -> str:
    if e.status_code == 401:
        return "Your session expired. Please /login again."
    if e.status_code in (400, 404, 409, 422):
        return f"That didn't work: {e.detail}"
    if e.status_code == 503:
        return "The service is busy right now. Please try again in a minute."
    return "Something went wrong on our side. Please try again in a moment."


async def esslce_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # effective_message, not message: also called from bot.py's menu_callback with a
    # CallbackQuery-type Update (no .message of its own) when the main menu's ESSLCE button
    # is tapped.
    user_id = update.effective_user.id
    if not api_client.is_logged_in(user_id):
        await update.effective_message.reply_text(LOGIN_FIRST)
        return
    session = EsslceSession(api_client, user_id)
    context.user_data[SESSION_KEY] = session
    screen = session.start()
    await update.effective_message.reply_text(screen.text, reply_markup=keyboard(screen))


async def _show(query, screen) -> None:
    """Edits the existing message with the screen text (same as the practice flow), then sends the
    rendered LaTeX explanation as a separate photo message when the screen carries one - Telegram can't
    turn an existing text message into a photo message via edit. The photo upload is a slower network
    round trip than the text edit; if the student answers the next question before it finishes, that
    question's (fast, text-only) edit can land before this (slow, image) message in the chat. The photo's
    caption therefore repeats the verdict+options itself (Screen.image_caption) so the message is still
    fully self-contained however the two end up ordered, rather than relying on staying next to the text
    message it answers."""
    try:
        await query.edit_message_text(text=screen.text, reply_markup=keyboard(screen))
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise
    if screen.image_base64:
        photo = io.BytesIO(base64.b64decode(screen.image_base64))
        photo.name = "solution.png"
        await query.message.chat.send_photo(photo, caption=screen.image_caption)


async def esslce_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Free-text messages, routed here ONLY while the student is mid-"Ask about this" conversation
    (session.asking_question_id set by on_ask_start). Any other free text - no active esslce session, or
    one that isn't currently in a chat - is silently ignored here, not treated as an error: this handler
    has no way to know whether some other feature meant to claim that message instead."""
    session = context.user_data.get(SESSION_KEY)
    if (
        session is None
        or session.asking_question_id is None
        or not api_client.is_logged_in(update.effective_user.id)
    ):
        return
    # esslce_ask (api_client.py) is always a fresh LLM call, never cached - the slowest call this
    # handler makes, so it's the one most worth a "something's happening" signal (explain_handler.py
    # and exam_handler.py already do this; this was the one slow-call pair missing it).
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    await update.message.reply_text("Thinking...")
    try:
        screen = await asyncio.to_thread(session.on_chat_message, update.message.text)
    except BackendError as e:
        await update.message.reply_text(friendly_esslce_error(e))
        return
    await update.message.reply_text(screen.text, reply_markup=keyboard(screen))
    if screen.image_base64:
        photo = io.BytesIO(base64.b64decode(screen.image_base64))
        photo.name = "solution.png"
        await update.message.chat.send_photo(photo, caption=screen.image_caption)


async def esslce_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Every button of the /esslce menu."""
    query = update.callback_query
    session = context.user_data.get(SESSION_KEY)
    if session is None or not api_client.is_logged_in(query.from_user.id):
        await query.answer(
            "This menu has expired. Send /esslce to start again.", show_alert=True
        )
        return
    if query.data.startswith("ee|"):
        # on_elaborate (esslce_flow.py) is always a fresh LLM call, same as esslce_ask above -
        # same "something's happening" signal, done as an edit of the tapped message itself
        # rather than a new reply (matching how practice_callback/esslce_callback already only
        # ever edit the one message in place, never append a second one for a button tap).
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        try:
            await query.edit_message_text("Working it out...")
        except BadRequest:
            pass
    try:
        screen = await asyncio.to_thread(session.handle, query.data)
    except FlowError as e:
        await query.answer(str(e), show_alert=True)
        return
    except BackendError as e:
        await query.answer(friendly_esslce_error(e), show_alert=True)
        return
    await query.answer()
    if screen is None:  # e.g. the student tapped the same answer twice
        return
    await _show(query, screen)
