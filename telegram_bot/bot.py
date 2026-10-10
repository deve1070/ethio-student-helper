"""
Entrypoint for the Telegram bot client. Deliberately thin: every handler
calls the backend through telegram_bot/api_client.py — this file never
touches the database, vector store, or payment gateway directly, the
same way web/ and mobile/ shouldn't either.

Run with: python -m telegram_bot.bot
(requires TELEGRAM_BOT_TOKEN, and BACKEND_BASE_URL if not localhost)
"""

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from telegram_bot.config import TELEGRAM_BOT_TOKEN
from telegram_bot.handlers.auth_handler import login_command
from telegram_bot.handlers.exam_handler import exam_command, exam_photo_handler
from telegram_bot.handlers.explain_handler import explain_command
from telegram_bot.handlers.payment_handler import buy_command, credits_command
from telegram_bot.handlers.practice_handler import (
    practice_callback,
    practice_command,
    progress_command,
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Welcome to the Ethiopian Student Helper!\n\n"
        "/login <phone or email> <password>\n"
        "/practice  (multiple-choice questions from your textbooks)\n"
        "/progress  (your accuracy and weakest units)\n"
        "/explain <grade> <subject> <question>\n"
        "/exam <grade> <subject> <question>  (or send a photo with that as the caption)\n"
        "/credits\n"
        "/buy <bundle>"
    )


def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("login", login_command))
    app.add_handler(CommandHandler("practice", practice_command))
    app.add_handler(CommandHandler("progress", progress_command))
    app.add_handler(CallbackQueryHandler(practice_callback, pattern=r"^p[a-z]"))
    app.add_handler(CommandHandler("explain", explain_command))
    app.add_handler(CommandHandler("exam", exam_command))
    app.add_handler(CommandHandler("credits", credits_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(MessageHandler(filters.PHOTO, exam_photo_handler))

    app.run_polling()


if __name__ == "__main__":
    main()
