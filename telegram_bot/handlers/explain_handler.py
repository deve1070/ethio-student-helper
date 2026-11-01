"""
/explain <grade> <subject> <question...>
e.g. /explain 11 Biology What is the difference between mitosis and meiosis?

Calls the same /v1/explain endpoint the web app and mobile app use.
"""

from telegram import Update
from telegram.ext import ContextTypes

from telegram_bot import api_client
from telegram_bot.api_client import BackendError

USAGE = "Usage: /explain <grade> <subject> <question>\nExample: /explain 11 Biology What is mitosis?"


async def explain_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # effective_message, not message: also called from bot.py's menu_callback with a
    # CallbackQuery-type Update (no .message of its own) when the main menu's Explain button is
    # tapped - that always lands on the USAGE reply below (no typed args to work with from a
    # button tap), pointing the student at the typed form since the question itself must stay typed.
    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await update.effective_message.reply_text(
            "Please /login first with your phone/email and password."
        )
        return

    # context.args is only ever populated by CommandHandler from the typed message text - a
    # CallbackQueryHandler call (the menu button) leaves it None, hence the `or []` below.
    args = context.args or []
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

    await update.effective_message.reply_text("Looking that up in your textbook...")
    try:
        result = api_client.explain(telegram_user_id, grade, subject, question)
    except BackendError as e:
        await update.effective_message.reply_text(friendly_error(e))
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
    if e.status_code == 503:
        return "The AI tutor is busy right now. Please try again in a minute."
    return "Something went wrong on our end — please try again in a moment."
