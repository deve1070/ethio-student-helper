import logging

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from telegram_bot import reminders
from telegram_bot import store as bot_store
from telegram_bot.config import TELEGRAM_BOT_TOKEN
from telegram_bot.handlers.auth_handler import login_command, logout_command
from telegram_bot.handlers.esslce_handler import (
    esslce_callback,
    esslce_command,
    esslce_text_handler,
)
from telegram_bot.handlers.exam_handler import exam_command, exam_photo_handler
from telegram_bot.handlers.explain_handler import explain_command
from telegram_bot.handlers.payment_handler import (
    buy_command,
    credits_command,
    payment_review_callback,
    pending_payments_command,
    receipt_photo_handler,
)
from telegram_bot.handlers.practice_handler import (
    practice_callback,
    practice_command,
    progress_command,
)
from telegram_bot.handlers.reminder_handler import remind_command

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Welcome to the Ethiopian Student Helper!\n\n"
        "/login <phone or email> <password>\n"
        "/practice  (multiple-choice questions from your textbooks)\n"
        "/progress  (your accuracy and weakest units)\n"
        "/esslce  (Grade 12 national exam past papers)\n"
        "/remind 18:00  (a daily practice reminder)\n"
        "/explain <grade> <subject> <question>\n"
        "/exam <grade> <subject> <question>  (or send a photo with that as the caption)\n"
        "/credits\n"
        "/buy <bundle>  (then send your receipt photo as instructed)\n"
        "/logout"
    )


async def post_init(application: Application) -> None:
    """Runs once at start-up: bring back every saved daily reminder."""
    if application.job_queue is None:
        logger.warning(
            'Daily reminders are OFF: install them with  pip install "python-telegram-bot[job-queue]"'
        )
        return
    restored = reminders.restore_all(
        application.job_queue, bot_store.get_store(), reminders.local_tz()
    )
    logger.info("Restored %d daily reminder(s)", restored)


def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("login", login_command))
    app.add_handler(CommandHandler("logout", logout_command))
    app.add_handler(CommandHandler("practice", practice_command))
    app.add_handler(CommandHandler("progress", progress_command))
    app.add_handler(CommandHandler("remind", remind_command))
    app.add_handler(CallbackQueryHandler(practice_callback, pattern=r"^p[a-z]"))
    app.add_handler(CommandHandler("esslce", esslce_command))
    app.add_handler(CallbackQueryHandler(esslce_callback, pattern=r"^e[a-z]"))
    app.add_handler(CommandHandler("explain", explain_command))
    app.add_handler(CommandHandler("exam", exam_command))
    app.add_handler(CommandHandler("credits", credits_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("pending_payments", pending_payments_command))
    app.add_handler(CallbackQueryHandler(payment_review_callback, pattern=r"^PM\|"))
    app.add_handler(MessageHandler(filters.PHOTO, exam_photo_handler))
    # Different group (1, not the default 0): both this and exam_photo_handler above must see
    # every photo update, since each one checks its OWN caption prefix and silently no-ops on
    # the other's - PTB only runs one handler per group by default, so two handlers that both
    # match filters.PHOTO need separate groups to both get a chance to run.
    app.add_handler(MessageHandler(filters.PHOTO, receipt_photo_handler), group=1)
    # free text is only ever acted on while a student is mid-"Ask about this" chat (esslce_text_handler
    # checks session.asking_question_id itself and silently ignores everything else) - safe to register
    # unconditionally since no other handler currently claims plain text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, esslce_text_handler))
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    build_application().run_polling()


if __name__ == "__main__":
    main()
