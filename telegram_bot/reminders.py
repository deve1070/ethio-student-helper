import logging
import os
import re
from datetime import datetime, timedelta, timezone
from datetime import time as dtime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from telegram_bot import api_client
from telegram_bot import store as bot_store
from telegram_bot.practice_flow import pretty_subject

logger = logging.getLogger(__name__)

_TIME = re.compile(r"^\s*(\d{1,2})(?:[:.]?(\d{2}))?\s*(am|pm)?\s*$", re.I)


def local_tz():
    name = os.environ.get("BOT_TIMEZONE", "Africa/Addis_Ababa")
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        return timezone(timedelta(hours=3))  # Ethiopia has no daylight saving time


def tz_label(tz) -> str:
    return getattr(tz, "key", None) or "UTC+3"


def local_today(tz=None) -> str:
    return datetime.now(tz or local_tz()).date().isoformat()


def parse_time(text: str):
    """ "18:00", "6pm", "6:30 pm", "0630", "06.30", "7" -> datetime.time, or None if it makes no sense."""
    m = _TIME.match(text or "")
    if not m:
        return None
    hour, minute, ampm = (
        int(m.group(1)),
        int(m.group(2) or 0),
        (m.group(3) or "").lower(),
    )
    if minute > 59:
        return None
    if ampm:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    elif hour > 23:
        return None
    return dtime(hour, minute)


def format_time(t: dtime) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def job_name(uid: int) -> str:
    return f"remind-{uid}"


def reminder_message(pref) -> str:
    if pref:
        return (
            f"📚 Time to practise {pretty_subject(pref['subject'])} (Grade {pref['grade']})!\n"
            "Today: 5 questions, starting with your weakest units."
        )
    return "📚 Time to practise! Tap below to choose a subject."


async def send_reminder(context) -> None:
    """The daily job."""
    job = context.job
    uid, chat_id = job.user_id, job.chat_id
    st = bot_store.get_store()
    if st.active_on(uid, local_today()):
        return  # already practised today: do not nag
    if not api_client.is_logged_in(uid):
        await context.bot.send_message(
            chat_id,
            "Your login has expired, so I can't prepare today's questions. "
            "Please /login again to keep your daily reminder going.",
        )
        return
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Start now ➡", callback_data="pd")]]
    )
    await context.bot.send_message(
        chat_id, reminder_message(st.get_pref(uid)), reply_markup=keyboard
    )


def cancel_reminder(job_queue, uid: int) -> None:
    if job_queue is None:
        return
    for job in job_queue.get_jobs_by_name(job_name(uid)):
        job.schedule_removal()


def schedule_reminder(job_queue, uid: int, chat_id: int, at: dtime, tz) -> None:
    """One daily job per student; calling it again replaces the old time."""
    cancel_reminder(job_queue, uid)
    job_queue.run_daily(
        send_reminder,
        time=at.replace(tzinfo=tz),
        name=job_name(uid),
        chat_id=chat_id,
        user_id=uid,
    )


def restore_all(job_queue, store, tz) -> int:
    """Re-create every saved reminder (called once when the bot starts)."""
    count = 0
    for uid, r in store.all_reminders().items():
        at = parse_time(r.get("time", ""))
        if at is None:
            continue
        schedule_reminder(job_queue, uid, r["chat_id"], at, tz)
        count += 1
    return count
