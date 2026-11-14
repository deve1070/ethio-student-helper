"""
/explain <grade> <subject> <question...>
e.g. /explain 11 Biology What is the difference between mitosis and meiosis?
Or just /explain with nothing after it — a button picks the grade, then the subject, then
type the question (mirrors exam_handler.py's guided /exam flow exactly).

Calls the same /v1/explain endpoint the web app and mobile app use.
"""

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from telegram_bot import api_client
from telegram_bot.api_client import BackendError
from telegram_bot.keyboards import grade_keyboard

logger = logging.getLogger(__name__)

FLOW_KEY = "explain_flow"  # context.user_data entry while a grade/subject has been picked
# by button but the question itself hasn't been typed yet.
USAGE = "Usage: /explain <grade> <subject> <question>\nExample: /explain 11 Biology What is mitosis?"
# Shown when something NEITHER a BackendError catches goes wrong (an LLM call that outlasts even
# the bumped client timeout, a dropped connection, ...) - "Looking that up..." must never be the
# last thing the student sees with no way forward.
UNEXPECTED_ERROR = "That took too long or something went wrong. Please try again."


async def explain_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # effective_message, not message: also called from bot.py's menu_callback with a
    # CallbackQuery-type Update (no .message of its own) when the main menu's Explain button is
    # tapped - that starts the same guided grade-button flow as typing bare /explain.
    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await update.effective_message.reply_text(
            "Please /login first with your phone/email and password."
        )
        return

    # context.args is only ever populated by CommandHandler from the typed message text - a
    # CallbackQueryHandler call (the menu button) leaves it None, hence the `or []` below.
    args = context.args or []
    if not args:
        context.user_data[FLOW_KEY] = {}
        await update.effective_message.reply_text(
            "Which grade is this question from?", reply_markup=grade_keyboard("dg")
        )
        return
    if len(args) < 3:
        await update.effective_message.reply_text(USAGE)
        return

    try:
        grade = int(args[0])
    except ValueError:
        await update.effective_message.reply_text(
            "Grade must be a number between 9 and 12.\n\n" + USAGE
        )
        return

    subject = args[1]
    question = " ".join(args[2:])
    await _explain_and_reply(update, telegram_user_id, grade, subject, question)


async def explain_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Grade and subject buttons from the guided /explain flow above (callback_data dg|<grade>,
    ds|<subject>) - reuses api_client.practice_subjects for the subject list, the same per-grade
    textbook-subject pool exam_handler.py's guided /exam flow already validates against."""
    query = update.callback_query
    await query.answer()
    telegram_user_id = query.from_user.id
    kind, value = query.data.split("|", 1)

    if kind == "dg":
        grade = int(value)
        context.user_data[FLOW_KEY] = {"grade": grade}
        subjects = [
            s["subject"]
            for s in (await asyncio.to_thread(api_client.practice_subjects, telegram_user_id, grade))["subjects"]
        ]
        if not subjects:
            await query.edit_message_text(
                f"No subjects available for Grade {grade} yet. Try /explain {grade} <subject> <question> directly."
            )
            return
        rows = [[InlineKeyboardButton(s.replace("_", " ").title(), callback_data=f"ds|{s}")] for s in subjects]
        await query.edit_message_text(f"Grade {grade}: which subject?", reply_markup=InlineKeyboardMarkup(rows))
        return

    # kind == "ds"
    flow = context.user_data.get(FLOW_KEY)
    if not flow or "grade" not in flow:
        await query.answer("This menu expired. Send /explain to start again.", show_alert=True)
        return
    flow["subject"] = value
    await query.edit_message_text(
        f"Grade {flow['grade']}, {value.replace('_', ' ').title()}: now type your question."
    )


async def explain_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Free text while a grade+subject is pending from the guided /explain button flow - the
    question itself still has to be typed (it's open-ended), this is just the part after the
    buttons. Silently ignores everything else, same convention as exam_text_handler/
    esslce_text_handler registered on the same filter (each checks its own state)."""
    flow = context.user_data.get(FLOW_KEY)
    if not flow or "grade" not in flow or "subject" not in flow:
        return
    telegram_user_id = update.effective_user.id
    grade, subject = flow["grade"], flow["subject"]
    context.user_data.pop(FLOW_KEY, None)  # one-shot: the next message needs a fresh /explain
    await _explain_and_reply(update, telegram_user_id, grade, subject, update.message.text)


async def _explain_and_reply(
    update: Update, telegram_user_id: int, grade: int, subject: str, question: str
) -> None:
    await update.effective_message.reply_text("Looking that up in your textbook...")
    try:
        result = await asyncio.to_thread(api_client.explain, telegram_user_id, grade, subject, question)
    except BackendError as e:
        await update.effective_message.reply_text(friendly_error(e))
        return
    except Exception:
        logger.exception("Unexpected error in /explain")
        await update.effective_message.reply_text(UNEXPECTED_ERROR)
        return

    await update.effective_message.reply_text(
        format_answer(result["answer"], result["citations"])
    )


def format_answer(answer: str, citations: list[dict]) -> str:
    text = answer
    if citations:
        refs = "\n".join(
            f"- {c['textbook']}, {c['unit']}"
            + (f", p.{c['page']}" if c.get("page") else "")
            for c in citations
        )
        text += f"\n\nSources:\n{refs}"
    return text


def friendly_error(e: BackendError) -> str:
    if e.status_code == 401:
        return "Your session expired — please /login again."
    if e.status_code == 400:
        return f"That didn't work: {e.detail}"
    if e.status_code == 402:
        return "You've used all your free previews. Use /subscribe for a full year of unlimited access."
    if e.status_code == 503:
        return "The AI tutor is busy right now. Please try again in a minute."
    return "Something went wrong on our end — please try again in a moment."
