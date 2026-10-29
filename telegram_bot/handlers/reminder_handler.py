from telegram import Update
from telegram.ext import ContextTypes

from telegram_bot import api_client, reminders
from telegram_bot import store as bot_store

USAGE = (
    "Set a daily practice reminder:\n"
    "/remind 18:00   (or 6pm, 7:30am)\n"
    "/remind off     to stop it"
)


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid, chat_id = update.effective_user.id, update.effective_chat.id
    if not api_client.is_logged_in(uid):
        await update.message.reply_text("Please /login first, then set your reminder.")
        return
    st, tz = bot_store.get_store(), reminders.local_tz()
    arg = " ".join(context.args).strip()
    job_queue = context.application.job_queue

    if not arg:
        r = st.get_reminder(uid)
        status = (
            f"Your daily reminder is at {r['time']} ({reminders.tz_label(tz)})."
            if r
            else "You have no daily reminder."
        )
        await update.message.reply_text(f"{status}\n\n{USAGE}")
        return
    if arg.lower() in ("off", "stop", "cancel", "none"):
        reminders.cancel_reminder(job_queue, uid)
        st.drop_reminder(uid)
        await update.message.reply_text(
            "Reminder turned off. Send /remind 18:00 whenever you want it back."
        )
        return
    at = reminders.parse_time(arg)
    if at is None:
        await update.message.reply_text(f"I couldn't read that time.\n\n{USAGE}")
        return
    if job_queue is None:
        await update.message.reply_text(
            "Reminders are not available on this bot yet (the server needs the "
            "'python-telegram-bot[job-queue]' package). Please tell your teacher."
        )
        return
    reminders.schedule_reminder(job_queue, uid, chat_id, at, tz)
    st.set_reminder(uid, chat_id, reminders.format_time(at))
    await update.message.reply_text(
        f"Done. I'll remind you every day at {reminders.format_time(at)} ({reminders.tz_label(tz)}), "
        "unless you have already practised that day.\nSend /remind off to stop it."
    )
