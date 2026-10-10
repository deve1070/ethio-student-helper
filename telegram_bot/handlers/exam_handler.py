"""
/exam <grade> <subject> <question...>  — text questions
Or send a photo of the question with caption "/exam <grade> <subject>"

Both paths hit the same cache-first /v1/exam/solve endpoint, so a
question another student already asked comes back instantly regardless
of which way this one was submitted.
"""

import base64

from telegram import Update
from telegram.ext import ContextTypes

from telegram_bot import api_client
from telegram_bot.api_client import BackendError
from telegram_bot.handlers.explain_handler import format_answer, friendly_error

USAGE = (
    "Usage: /exam <grade> <subject> <question>\n"
    "Or send a photo of the question with caption: /exam <grade> <subject>"
)


async def exam_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Plain text /exam command (no photo)."""
    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await update.message.reply_text(
            "Please /login first with your phone/email and password."
        )
        return

    args = context.args
    if len(args) < 3:
        await update.message.reply_text(USAGE)
        return

    try:
        grade = int(args[0])
    except ValueError:
        await update.message.reply_text(
            "Grade must be a number between 9 and 12.\n\n" + USAGE
        )
        return

    subject = args[1]
    question = " ".join(args[2:])
    await _solve_and_reply(
        update, telegram_user_id, grade, subject, question_text=question
    )


async def exam_photo_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """A photo sent with caption "/exam <grade> <subject>"."""
    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await update.message.reply_text(
            "Please /login first with your phone/email and password."
        )
        return

    caption_args = (update.message.caption or "").replace("/exam", "").split()
    if len(caption_args) < 2:
        await update.message.reply_text(
            "Send the photo with a caption like: /exam 12 Physics"
        )
        return

    try:
        grade = int(caption_args[0])
    except ValueError:
        await update.message.reply_text("Grade must be a number between 9 and 12.")
        return
    subject = caption_args[1]

    photo = update.message.photo[-1]  # highest resolution variant Telegram sends
    file = await photo.get_file()
    image_bytes = await file.download_as_bytearray()
    image_base64 = base64.b64encode(bytes(image_bytes)).decode()

    await _solve_and_reply(
        update, telegram_user_id, grade, subject, image_base64=image_base64
    )


async def _solve_and_reply(
    update: Update,
    telegram_user_id: int,
    grade: int,
    subject: str,
    question_text: str | None = None,
    image_base64: str | None = None,
) -> None:
    await update.message.reply_text(
        "Checking if this question's been answered before..."
    )
    try:
        result = api_client.exam_solve(
            telegram_user_id,
            grade,
            subject,
            question_text=question_text,
            image_base64=image_base64,
        )
    except BackendError as e:
        if e.status_code == 402:
            await update.message.reply_text(
                "You're out of credits for new exam questions. Use /buy to get more."
            )
            return
        await update.message.reply_text(friendly_error(e))
        return

    prefix = {
        "cache": "(Answered before, instant)",
        "generated": "(New answer, generated just now)",
        "unverified": "(New answer. It could not be double-checked, so no credit was used)",
        "no_match": "(Your textbooks don't cover this question, so no credit was used)",
    }.get(result["source"], "(New answer)")
    await update.message.reply_text(
        f"{prefix}\n\n" + format_answer(result["answer"], result["citations"])
    )
