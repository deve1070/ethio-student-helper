import logging
import os

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PollAnswerHandler,
    filters,
)

from telegram_bot import mass_challenge, reminders, weekly_report
from telegram_bot.i18n import tr
from telegram_bot import store as bot_store
from telegram_bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_URL
from telegram_bot.handlers.auth_handler import login_command, login_text_handler, logout_command
from telegram_bot.handlers.esslce_handler import (
    esslce_callback,
    esslce_command,
    esslce_text_handler,
    weekly_practice_callback,
)
from telegram_bot.handlers.exam_handler import (
    exam_callback,
    exam_command,
    exam_photo_handler,
    exam_text_handler,
)
from telegram_bot.handlers.explain_handler import (
    explain_callback,
    explain_command,
    explain_text_handler,
)
from telegram_bot.handlers.payment_handler import (
    payment_review_callback,
    pending_payments_command,
    receipt_photo_handler,
    status_command,
    subscribe_command,
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
    BotCommand("catchup", "Answer today's mass practice privately"),
    BotCommand("status", "Check your subscription status"),
    BotCommand("subscribe", "Subscribe for a year of unlimited access"),
    BotCommand("help", "Get help or join our student group"),
    BotCommand("language", "English or Amharic / ቋንቋ"),
]

# The main menu's buttons (start_command below) each just call the exact same function its
# matching slash command already calls - menu_callback (also below) is the one place that maps
# a button tap to that function, so adding a command here never means writing its logic twice.
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Also reachable as the main menu's "Help" button - see api/routes_auth.py's ProfileResponse,
    which surfaces this same TELEGRAM_GROUP_URL on the app's Profile page, for the one shared place
    this link is kept (config/settings.py / this bot's own config.py, both reading the same .env)."""
    uid = update.effective_user.id
    if TELEGRAM_GROUP_URL:
        text = tr(uid, "Need help or have a question? Join our student group:\n{url}", url=TELEGRAM_GROUP_URL)
    else:
        text = tr(uid, "Having trouble? Use /login to link your account, or ask your question with /explain.")
    await update.effective_message.reply_text(text)


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("English", callback_data="lang|en"), InlineKeyboardButton("አማርኛ", callback_data="lang|am")]]
    )
    await update.effective_message.reply_text(tr(update.effective_user.id, "Choose your language:"), reply_markup=keyboard)


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    lang = query.data.split("|", 1)[1]
    uid = query.from_user.id
    bot_store.get_store().set_lang(uid, lang)
    await query.answer()
    await query.edit_message_text(
        tr(uid, "Language set to Amharic." if lang == "am" else "Language set to English."),
        reply_markup=_main_menu(uid),
    )


_MENU_ACTIONS = {
    "practice": practice_command,
    "progress": progress_command,
    "esslce": esslce_command,
    "explain": explain_command,
    "exam": exam_command,
    "remind": remind_command,
    "status": status_command,
    "subscribe": subscribe_command,
    "login": login_command,
    "logout": logout_command,
    "help": help_command,
    "language": language_command,
}


def _main_menu(uid: int) -> InlineKeyboardMarkup:
    def button(label: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(tr(uid, label), callback_data=f"m|{action}")

    return InlineKeyboardMarkup([
        [button("📝 Practice", "practice"), button("📊 Progress", "progress")],
        [button("🎓 ESSLCE past papers", "esslce")],
        [button("❓ Ask the textbook", "explain"), button("📷 Exam question", "exam")],
        [button("⏰ Reminders", "remind")],
        [button("💳 My status", "status"), button("🛒 Subscribe", "subscribe")],
        [button("🔐 Login", "login"), button("🚪 Logout", "logout")],
        [button("🆘 Help", "help"), button("🌐 Language", "language")],
    ])


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    await update.effective_message.reply_text(
        tr(
            uid,
            "Welcome to the Ethiopian Student Helper! Tap a button below, or type / to see every command.\n\n"
            "Tip: run /login once even if you're already logged in on the app - it links this chat to your "
            "account, which is also what lets you reset your password from the app later if you ever forget it.",
        ),
        reply_markup=_main_menu(uid),
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

    tz = reminders.local_tz()
    if mass_challenge.schedule_daily_event(application.job_queue, tz):
        logger.info("Scheduled daily mass-challenge event")
    else:
        logger.info("Daily mass-challenge event is OFF (TELEGRAM_PRIVATE_GROUP_ID not set)")
    mass_challenge.schedule_headsup(application.job_queue, tz)
    mass_challenge.schedule_sweep(application.job_queue, tz)
    mass_challenge.schedule_streak_nudge(application.job_queue, tz)
    weekly_report.schedule_weekly_report(application.job_queue, tz)
    await mass_challenge.resume_after_restart(application)


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
    app.add_handler(CallbackQueryHandler(explain_callback, pattern=r"^d[a-z]"))
    app.add_handler(CommandHandler("exam", exam_command))
    app.add_handler(CallbackQueryHandler(exam_callback, pattern=r"^x[a-z]"))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(CommandHandler("pending_payments", pending_payments_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CallbackQueryHandler(language_callback, pattern=r"^lang\|"))
    app.add_handler(CallbackQueryHandler(payment_review_callback, pattern=r"^PM\|"))
    app.add_handler(MessageHandler(filters.PHOTO, exam_photo_handler))
    # Different group (1, not the default 0): both this and exam_photo_handler above must see
    # every photo update, since each one checks its OWN caption prefix and silently no-ops on
    # the other's - PTB only runs one handler per group by default, so two handlers that both
    # match filters.PHOTO need separate groups to both get a chance to run.
    app.add_handler(MessageHandler(filters.PHOTO, receipt_photo_handler), group=1)
    # free text is only ever acted on while a student is mid-"Ask about this" chat (esslce_text_handler
    # checks session.asking_question_id itself), mid-guided /exam flow (exam_text_handler), mid-guided
    # /login flow (login_text_handler), or mid-guided /explain flow (explain_text_handler) - each
    # checks its own user_data key and silently ignores everything else. PTB only runs the first
    # matching handler within a given group per update, so these four - all plain
    # filters.TEXT & ~filters.COMMAND, all wanting a look at every text update - each need their own
    # group; sharing a group would silently starve whichever one is registered later.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, esslce_text_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, exam_text_handler), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, login_text_handler), group=2)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, explain_text_handler), group=3)
    app.add_handler(PollAnswerHandler(mass_challenge.on_poll_answer))
    app.add_handler(ChatJoinRequestHandler(mass_challenge.on_join_request))
    app.add_handler(CallbackQueryHandler(mass_challenge.on_ask_ai_callback, pattern=r"^mq\|"))
    app.add_handler(CommandHandler("catchup", mass_challenge.catchup_command))
    app.add_handler(CallbackQueryHandler(weekly_practice_callback, pattern=r"^wp\|"))
    app.add_handler(CallbackQueryHandler(mass_challenge.on_catchup_callback, pattern=r"^mc\|"))
    app.add_handler(CallbackQueryHandler(mass_challenge.on_catchup_answer, pattern=r"^ma\|"))
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # httpx logs every request URL at INFO, and a Telegram Bot API URL contains the bot token -
    # at INFO the token was written to the log on every single request.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if os.environ.get("SENTRY_DSN"):
        # Same project as the backend (both read SENTRY_DSN from the shared .env), told apart by the
        # "service" tag. Sentry's logging integration reports every logger.exception() call, which
        # is how the bot already records a failed send, a failed backend call or a job error.
        import sentry_sdk

        sentry_sdk.init(dsn=os.environ["SENTRY_DSN"], environment=os.environ.get("ENVIRONMENT", "development"))
        sentry_sdk.set_tag("service", "telegram_bot")
    build_application().run_polling()


if __name__ == "__main__":
    main()
