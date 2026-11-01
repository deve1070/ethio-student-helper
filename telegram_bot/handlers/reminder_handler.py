from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from telegram_bot import api_client, reminders
from telegram_bot import store as bot_store

USAGE = (
    "Set a daily practice reminder:\n"
    "/remind 18:00   (or 6pm, 7:30am)\n"
    "/remind off     to stop it"
)
QUICK_TIMES = ("6:00", "7:00", "18:00", "20:00")


def _quick_keyboard() -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(t, callback_data=f"rm|{t}") for t in QUICK_TIMES]
    return InlineKeyboardMarkup([row, [InlineKeyboardButton("Off", callback_data="rm|off")]])


def _turn_off(uid: int, job_queue) -> str:
    reminders.cancel_reminder(job_queue, uid)
    bot_store.get_store().drop_reminder(uid)
    return "Reminder turned off. Send /remind 18:00 whenever you want it back."


def _set_time(uid: int, chat_id: int, job_queue, at, tz) -> str:
    if job_queue is None:
        return (
            "Reminders are not available on this bot yet (the server needs the "
            "'python-telegram-bot[job-queue]' package). Please tell your teacher."
        )
    reminders.schedule_reminder(job_queue, uid, chat_id, at, tz)
    bot_store.get_store().set_reminder(uid, chat_id, reminders.format_time(at))
    return (
        f"Done. I'll remind you every day at {reminders.format_time(at)} ({reminders.tz_label(tz)}), "
        "unless you have already practised that day.\nSend /remind off to stop it."
    )


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # effective_message, not message: also called from bot.py's menu_callback with a
    # CallbackQuery-type Update when the main menu's Reminders button is tapped - that always
    # carries no args, same as typing bare /remind, landing on the status+quick-pick-buttons reply.
    uid, chat_id = update.effective_user.id, update.effective_chat.id
    if not api_client.is_logged_in(uid):
        await update.effective_message.reply_text("Please /login first, then set your reminder.")
        return
    st, tz = bot_store.get_store(), reminders.local_tz()
    arg = " ".join(context.args or []).strip()
    job_queue = context.application.job_queue

    if not arg:
        r = st.get_reminder(uid)
        status = (
            f"Your daily reminder is at {r['time']} ({reminders.tz_label(tz)})."
            if r
            else "You have no daily reminder."
        )
        await update.effective_message.reply_text(
            f"{status}\n\n{USAGE}\n\nOr pick one:", reply_markup=_quick_keyboard()
        )
        return
    if arg.lower() in ("off", "stop", "cancel", "none"):
        await update.effective_message.reply_text(_turn_off(uid, job_queue))
        return
    at = reminders.parse_time(arg)
    if at is None:
        await update.effective_message.reply_text(f"I couldn't read that time.\n\n{USAGE}")
        return
    await update.effective_message.reply_text(_set_time(uid, chat_id, job_queue, at, tz))


async def remind_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The quick-pick time/Off buttons shown by bare /remind above (callback_data rm|18:00,
    rm|off)."""
    query = update.callback_query
    await query.answer()
    uid, chat_id = query.from_user.id, update.effective_chat.id
    job_queue = context.application.job_queue
    value = query.data.split("|", 1)[1]
    if value == "off":
        text = _turn_off(uid, job_queue)
    else:
        text = _set_time(uid, chat_id, job_queue, reminders.parse_time(value), reminders.local_tz())
    await query.edit_message_text(text)
