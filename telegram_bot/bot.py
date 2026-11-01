import logging

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
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
from telegram_bot.handlers.exam_handler import (
    exam_callback,
    exam_command,
    exam_photo_handler,
    exam_text_handler,
)
from telegram_bot.handlers.explain_handler import explain_command
from telegram_bot.handlers.payment_handler import (
    buy_callback,
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
from telegram_bot.handlers.reminder_handler import remind_callback, remind_command

logger = logging.getLogger(__name__)

# Every slash command this bot answers, for Telegram's native "/" menu (set_my_commands below) -
# that menu never existed before, since nothing called set_my_commands anywhere in this bot.
COMMANDS = [
    BotCommand("start", "Main menu"),
    BotCommand("login", "Log in"),
    BotCommand("logout", "Log out"),
    BotCommand("practice", "Practice questions from your textbooks"),
    BotCommand("progress", "Your accuracy and weakest units"),
    BotCommand("esslce", "Grade 12 national exam past papers"),
    BotCommand("explain", "Ask the textbook a question"),
    BotCommand("exam", "Get help with an exam question"),
    BotCommand("remind", "Set a daily practice reminder"),
    BotCommand("credits", "Check your credit balance"),
    BotCommand("buy", "Buy more credits"),
]

# The main menu's buttons (start_command below) each just call the exact same function its
# matching slash command already calls - menu_callback (also below) is the one place that maps
# a button tap to that function, so adding a command here never means writing its logic twice.
_MENU_ACTIONS = {
    "practice": practice_command,
    "progress": progress_command,
    "esslce": esslce_command,
    "explain": explain_command,
    "exam": exam_command,
    "remind": remind_command,
    "credits": credits_command,
    "buy": buy_command,
    "login": login_command,
    "logout": logout_command,
}


def _main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Practice", callback_data="m|practice"), InlineKeyboardButton("📊 Progress", callback_data="m|progress")],
        [InlineKeyboardButton("🎓 ESSLCE past papers", callback_data="m|esslce")],
        [InlineKeyboardButton("❓ Ask the textbook", callback_data="m|explain"), InlineKeyboardButton("📷 Exam question", callback_data="m|exam")],
        [InlineKeyboardButton("⏰ Reminders", callback_data="m|remind")],
        [InlineKeyboardButton("💳 My credits", callback_data="m|credits"), InlineKeyboardButton("🛒 Buy credits", callback_data="m|buy")],
        [InlineKeyboardButton("🔐 Login", callback_data="m|login"), InlineKeyboardButton("🚪 Logout", callback_data="m|logout")],
    ])


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Welcome to the Ethiopian Student Helper! Tap a button below, "
        "or type / to see every command.",
        reply_markup=_main_menu(),
    )


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Every button of the main menu (callback_data m|<action>) - calls the exact same function
    its matching slash command calls, so the menu never has logic of its own to drift out of
    sync with the typed commands."""
    query = update.callback_query
    await query.answer()
    action = query.data.split("|", 1)[1]
    handler = _MENU_ACTIONS.get(action)
    if handler is None:
        return
    await handler(update, context)


async def post_init(application: Application) -> None:
    """Runs once at start-up: populate Telegram's native "/" command menu (never done before -
    without this, typing "/" shows nothing until the student already knows a command's exact
    name), then bring back every saved daily reminder."""
    await application.bot.set_my_commands(COMMANDS)
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
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^m\|"))
    app.add_handler(CommandHandler("login", login_command))
    app.add_handler(CommandHandler("logout", logout_command))
    app.add_handler(CommandHandler("practice", practice_command))
    app.add_handler(CommandHandler("progress", progress_command))
    app.add_handler(CommandHandler("remind", remind_command))
    app.add_handler(CallbackQueryHandler(remind_callback, pattern=r"^rm\|"))
    app.add_handler(CallbackQueryHandler(practice_callback, pattern=r"^p[a-z]"))
    app.add_handler(CommandHandler("esslce", esslce_command))
    app.add_handler(CallbackQueryHandler(esslce_callback, pattern=r"^e[a-z]"))
    app.add_handler(CommandHandler("explain", explain_command))
    app.add_handler(CommandHandler("exam", exam_command))
    app.add_handler(CallbackQueryHandler(exam_callback, pattern=r"^x[a-z]"))
    app.add_handler(CommandHandler("credits", credits_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CallbackQueryHandler(buy_callback, pattern=r"^by\|"))
    app.add_handler(CommandHandler("pending_payments", pending_payments_command))
    app.add_handler(CallbackQueryHandler(payment_review_callback, pattern=r"^PM\|"))
    app.add_handler(MessageHandler(filters.PHOTO, exam_photo_handler))
    # Different group (1, not the default 0): both this and exam_photo_handler above must see
    # every photo update, since each one checks its OWN caption prefix and silently no-ops on
    # the other's - PTB only runs one handler per group by default, so two handlers that both
    # match filters.PHOTO need separate groups to both get a chance to run.
    app.add_handler(MessageHandler(filters.PHOTO, receipt_photo_handler), group=1)
    # free text is only ever acted on while a student is mid-"Ask about this" chat (esslce_text_handler
    # checks session.asking_question_id itself) or mid-guided /exam flow (exam_text_handler checks its
    # own user_data key) - each silently ignores everything else, and (same reasoning as the two photo
    # handlers above) both need to see every text update, hence the separate group for the second one.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, esslce_text_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, exam_text_handler), group=1)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    build_application().run_polling()


if __name__ == "__main__":
    main()
