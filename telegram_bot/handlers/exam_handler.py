"""
/exam <grade> <subject> <question...>  — text questions, all in one line
Or send a photo of the question with caption "/exam <grade> <subject>"
Or just /exam with nothing after it — a button picks the grade, then the subject, then
either type the question or send a photo (no caption needed at that point: the grade and
subject are already known from the buttons).

All paths hit the same cache-first /v1/exam/solve endpoint, so a question another student
already asked comes back instantly regardless of which way this one was submitted.
"""

import base64

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from telegram_bot import api_client
from telegram_bot.api_client import BackendError
from telegram_bot.handlers.explain_handler import format_answer, friendly_error

FLOW_KEY = "exam_flow"  # context.user_data entry while a grade/subject has been picked
# by button but the question itself (typed or photographed) hasn't arrived yet.
LOGIN_FIRST = "Please /login first with your phone/email and password."
USAGE = (
    "Usage: /exam <grade> <subject> <question>\n"
    "Or send a photo of the question with caption: /exam <grade> <subject>"
)


def _grade_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"Grade {g}", callback_data=f"xg|{g}") for g in (9, 10, 11, 12)]])


async def exam_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Plain text /exam command (no photo). effective_message, not message: also called from
    bot.py's menu_callback when the main menu's Explain-an-exam-question button is tapped, which
    carries no args either - same as typing bare /exam, that starts the grade-button flow below."""
    telegram_user_id = update.effective_user.id
    if not api_client.is_logged_in(telegram_user_id):
        await update.effective_message.reply_text(LOGIN_FIRST)
        return

    args = context.args or []
    if not args:
        context.user_data[FLOW_KEY] = {}
        await update.effective_message.reply_text("Which grade is this question from?", reply_markup=_grade_keyboard())
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
    await _solve_and_reply(
        update, telegram_user_id, grade, subject, question_text=question
    )


async def exam_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Grade and subject buttons from the guided /exam flow above (callback_data xg|<grade>,
    xs|<subject>) - mirrors practice_handler.py's pg|/ps| pattern, reusing api_client.practice_subjects
    for the subject list since it's the same per-grade textbook-subject pool /explain and /exam
    both validate against."""
    query = update.callback_query
    await query.answer()
    telegram_user_id = query.from_user.id
    kind, value = query.data.split("|", 1)

    if kind == "xg":
        grade = int(value)
        context.user_data[FLOW_KEY] = {"grade": grade}
        subjects = [s["subject"] for s in api_client.practice_subjects(telegram_user_id, grade)["subjects"]]
        if not subjects:
            await query.edit_message_text(
                f"No subjects available for Grade {grade} yet. Try /exam {grade} <subject> <question> directly."
            )
            return
        rows = [[InlineKeyboardButton(s.replace("_", " ").title(), callback_data=f"xs|{s}")] for s in subjects]
        await query.edit_message_text(f"Grade {grade}: which subject?", reply_markup=InlineKeyboardMarkup(rows))
        return

    # kind == "xs"
    flow = context.user_data.get(FLOW_KEY)
    if not flow or "grade" not in flow:
        await query.answer("This menu expired. Send /exam to start again.", show_alert=True)
        return
    flow["subject"] = value
    await query.edit_message_text(
        f"Grade {flow['grade']}, {value.replace('_', ' ').title()}: now type your question, or send a photo of it."
    )


async def exam_photo_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """A photo sent with caption "/exam <grade> <subject>", OR a bare photo (any caption, or none)
    while a grade+subject is already pending from the guided button flow above. Silently does
    nothing on any other caption (e.g. "/submit_receipt ...") with no pending flow, so it never
    interferes with payment_handler's own receipt_photo_handler registered on the same update."""
    caption = update.message.caption or ""
    telegram_user_id = update.effective_user.id
    flow = context.user_data.get(FLOW_KEY)

    if caption.startswith("/exam"):
        if not api_client.is_logged_in(telegram_user_id):
            await update.message.reply_text(LOGIN_FIRST)
            return
        caption_args = caption.replace("/exam", "").split()
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
    elif flow and flow.get("grade") is not None and flow.get("subject"):
        grade, subject = flow["grade"], flow["subject"]
        context.user_data.pop(FLOW_KEY, None)  # one-shot: the next photo needs a fresh /exam
    else:
        return

    photo = update.message.photo[-1]  # highest resolution variant Telegram sends
    file = await photo.get_file()
    image_bytes = await file.download_as_bytearray()
    image_base64 = base64.b64encode(bytes(image_bytes)).decode()

    await _solve_and_reply(
        update, telegram_user_id, grade, subject, image_base64=image_base64
    )


async def exam_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Plain text while a grade+subject is pending from the guided /exam button flow - the
    question itself still has to be typed (it's open-ended), this is just the part after the
    buttons. Silently ignores everything else, same convention as esslce_handler.esslce_text_handler
    registered on the same filter (both check their own state, see bot.py for why they need
    separate handler groups)."""
    flow = context.user_data.get(FLOW_KEY)
    if not flow or flow.get("grade") is None or not flow.get("subject"):
        return
    telegram_user_id = update.effective_user.id
    grade, subject = flow["grade"], flow["subject"]
    context.user_data.pop(FLOW_KEY, None)  # one-shot: the next message needs a fresh /exam
    await _solve_and_reply(update, telegram_user_id, grade, subject, question_text=update.message.text)


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
