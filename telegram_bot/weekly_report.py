"""The Sunday progress message: one private message per linked student with their week (days
practised, questions, accuracy, mass-practice rank) and a button straight into practice on their
weakest ESSLCE unit. The numbers are computed by the backend (/v1/progress/weekly-reports)."""

import asyncio
import logging
from datetime import time as dtime

from telegram.ext import ContextTypes

from telegram_bot import api_client, reminders
from telegram_bot.api_client import BackendError
from telegram_bot.config import WEEKLY_REPORT_TIME
from telegram_bot.handlers.esslce_handler import keyboard
from telegram_bot.practice_flow import Screen, clip, pretty_subject

logger = logging.getLogger(__name__)

SUNDAY = 0  # python-telegram-bot's run_daily numbers days 0-6 from Sunday


def schedule_weekly_report(job_queue, tz) -> bool:
    if job_queue is None:
        return False
    at = reminders.parse_time(WEEKLY_REPORT_TIME) or dtime(18, 0)
    for job in job_queue.get_jobs_by_name("weekly-report"):
        job.schedule_removal()
    job_queue.run_daily(send_weekly_reports, time=at.replace(tzinfo=tz), days=(SUNDAY,), name="weekly-report")
    return True


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def report_screen(r: dict) -> Screen:
    if not r["answered"]:
        text = (
            "📅 Your week: no practice in the last 7 days.\n\n"
            "A few questions a day adds up fast before the exam. Start with five now."
        )
        return Screen(text, [[("Start practising ➡", "m|esslce")]])

    lines = [
        "📅 Your week",
        f"Practised on {r['days_practised']} of 7 days · {r['answered']} questions · "
        f"{round(r['accuracy'] * 100)}% correct",
    ]
    if r["mass_rank"]:
        lines.append(f"Mass practice: {_ordinal(r['mass_rank'])} of {r['mass_participants']} this week")
    weakest = r["weakest"]
    buttons = []
    if weakest:
        lines.append(
            f"\nWeakest unit: {pretty_subject(weakest['subject'])} · Grade {weakest['grade']} · "
            f"{clip(weakest['unit'], 60)} ({round(weakest['accuracy'] * 100)}% correct)"
        )
        if weakest["unit_index"] is not None:
            buttons.append([("Practise this unit ➡", f"wp|{weakest['subject']}|{weakest['unit_index']}")])
    if not buttons:
        buttons.append([("Keep practising ➡", "m|esslce")])
    buttons.append([("📤 Share my week", "sh|week")])
    return Screen("\n".join(lines), buttons)


async def send_weekly_reports(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        reports = await asyncio.to_thread(api_client.weekly_reports)
    except BackendError:
        logger.exception("Could not fetch the weekly reports")
        return
    for r in reports:
        screen = report_screen(r)
        try:
            await context.bot.send_message(r["telegram_user_id"], screen.text, reply_markup=keyboard(screen))
        except Exception:
            logger.exception("Could not send the weekly report to %s", r["telegram_user_id"])
