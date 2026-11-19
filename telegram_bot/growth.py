"""Messages that bring students back and in.

Daily nudges: at NUDGE_TIME the backend hands over today's messages (backend growth/nudges.py
decides who gets which, at most one per student a day, each moment once) and this module words
and sends them. Every nudge has a "🔕 No more tips" button.

Share cards: "📤 Share" buttons on the Sunday report and on the evening group's results. A tap
sends the student their own card in a private chat, with a button that opens Telegram's chat
picker, so they can post it to friends with their referral link in it."""

import asyncio
import logging
from datetime import time as dtime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes

from telegram_bot import api_client, reminders
from telegram_bot.api_client import BackendError
from telegram_bot.config import NUDGE_TIME
from telegram_bot.practice_flow import clip, pretty_subject

logger = logging.getLogger(__name__)

OFF_BUTTON = ("🔕 No more tips", "nz|off")
SUBSCRIBE_BUTTON = ("⭐ Subscribe", "m|subscribe")


def _price(value) -> str:
    value = float(value)
    return str(int(value)) if value.is_integer() else f"{value:.2f}"


def _practise_button(weakest: dict | None) -> tuple[str, str]:
    if weakest and weakest.get("unit_index") is not None:
        return ("Practise this unit ➡", f"wp|{weakest['subject']}|{weakest['unit_index']}")
    return ("Start practising ➡", "m|esslce")


def _weakest_line(weakest: dict | None) -> str:
    if not weakest:
        return ""
    return (
        f"\n\nYour weakest unit right now: {pretty_subject(weakest['subject'])}, "
        f"{clip(weakest['unit'], 60)} ({round(weakest['accuracy'] * 100)}% correct)."
    )


def nudge_message(n: dict) -> tuple[str, list]:
    """The text and button rows for one nudge from the backend."""
    hi = f"{n['first_name']}, " if n.get("first_name") else ""
    price = _price(n["price_etb"])
    kind = n["kind"]
    if kind == "trial_ending":
        when = "today" if n["days_left"] == 0 else "tomorrow" if n["days_left"] == 1 else f"in {n['days_left']} days"
        text = f"⏳ {hi}your free trial ends {when}. So far you've answered {n['answered']} questions"
        text += f" and you're on a {n['streak']}-day streak." if n["streak"] > 1 else "."
        text += f"\n\nKeep everything, including the evening group, for {price} ETB for a full year."
        rows = [[SUBSCRIBE_BUTTON]]
    elif kind == "trial_ended":
        text = (
            f"{hi}your free trial has ended. You answered {n['answered']} questions in it. "
            f"\n\nPick up where you left off: a full year of everything is {price} ETB."
        )
        rows = [[SUBSCRIBE_BUTTON]]
    elif kind == "countdown":
        d = n["days_left"]
        text = f"📅 {hi}{d} day{'s' if d != 1 else ''} to your ESSLCE." + _weakest_line(n.get("weakest"))
        text += "\n\nA few questions every day now counts more than a long session the night before."
        rows = [[_practise_button(n.get("weakest"))]]
    elif kind == "previews_used":
        text = (
            f"{hi}you've used your free previews, and you've answered {n['answered']} questions so far. "
            f"\n\nFor {price} ETB a year you get every past paper, unlimited explanations, the evening "
            "group practice and your study plan."
        )
        rows = [[SUBSCRIBE_BUTTON], [_practise_button(n.get("weakest"))]]
    else:  # inactive
        text = f"👋 {hi}it's been {n['days_away']} days since you practised. One question is enough to restart."
        text += _weakest_line(n.get("weakest"))
        rows = [[_practise_button(n.get("weakest"))]]
    rows.append([OFF_BUTTON])
    return text, rows


def markup(rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data) for label, data in row] for row in rows])


def schedule_nudges(job_queue, tz) -> bool:
    if job_queue is None:
        return False
    at = reminders.parse_time(NUDGE_TIME) or dtime(17, 30)
    for job in job_queue.get_jobs_by_name("nudges"):
        job.schedule_removal()
    job_queue.run_daily(send_nudges, time=at.replace(tzinfo=tz), name="nudges")
    return True


async def send_nudges(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        nudges = await asyncio.to_thread(api_client.due_nudges)
    except BackendError:
        logger.exception("Could not fetch today's nudges")
        return
    sent = 0
    for n in nudges:
        text, rows = nudge_message(n)
        try:
            await context.bot.send_message(n["telegram_user_id"], text, reply_markup=markup(rows))
            sent += 1
        except TelegramError as e:  # blocked the bot, or never started a chat
            logger.info("Nudge to %s not delivered: %s", n["telegram_user_id"], e)
        await asyncio.sleep(0.05)  # stay well under Telegram's 30 messages a second
    logger.info("Sent %d of %d nudge(s)", sent, len(nudges))


async def nudges_off_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """nz|off and nz|on."""
    query = update.callback_query
    off = query.data == "nz|off"
    try:
        await asyncio.to_thread(api_client.set_nudges_off, query.from_user.id, off)
    except BackendError:
        await query.answer("Please /login first, then tap this again.", show_alert=True)
        return
    await query.answer()
    text = (
        "🔕 Done: no more tips from me. Your daily reminder (/remind) and the Sunday report still come."
        if off
        else "🔔 Tips are back on."
    )
    await query.message.reply_text(text, reply_markup=markup([[("🔔 Turn tips back on", "nz|on")]]) if off else None)


# ---- share cards --------------------------------------------------------------------------------------------
async def share_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """sh|week (the Sunday report) and sh|mass|<challenge_id> (the evening group's results)."""
    query = update.callback_query
    uid = query.from_user.id
    parts = query.data.split("|")
    kind = parts[1] if len(parts) > 1 else ""
    challenge_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    if not api_client.is_logged_in(uid):
        await query.answer("Open a private chat with me and /login first, then tap Share again.", show_alert=True)
        return
    try:
        card = await asyncio.to_thread(api_client.share_card, uid, kind, challenge_id)
    except BackendError as e:
        await query.answer("You didn't take part in this one." if e.status_code == 404 else "Couldn't make your card right now.", show_alert=True)
        return
    text = f"{card['text']}\n{card['link']}"
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("📤 Share with friends", url=card["share_url"])]])
    try:
        await context.bot.send_message(uid, f"Here's your card. Friends who sign up from your link count as your referrals.\n\n{text}", reply_markup=buttons)
    except Forbidden:
        await query.answer("Open a private chat with me first (press Start), then tap Share again.", show_alert=True)
        return
    in_private = query.message is not None and query.message.chat.type == "private"
    await query.answer(None if in_private else "I sent your card in our private chat.")
