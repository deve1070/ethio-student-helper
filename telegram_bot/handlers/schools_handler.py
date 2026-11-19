"""Admin commands for schools and ambassadors (backend api/routes_schools.py):
  /add_school <name>                      add a school students can pick
  /ambassador <phone or email> <school>   make a student their school's ambassador
  /schools                                every school with its students and ambassadors"""

import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from telegram_bot import api_client
from telegram_bot.api_client import BackendError


async def _admin_call(update: Update, fn, *args):
    """Runs an admin-only backend call; replies and returns None on any refusal."""
    uid = update.effective_user.id
    if not api_client.is_logged_in(uid):
        await update.message.reply_text("Please /login first with your phone/email and password.")
        return None
    try:
        return await asyncio.to_thread(fn, uid, *args)
    except BackendError as e:
        await update.message.reply_text("This command is for admins only." if e.status_code == 403 else f"That didn't work: {e.detail}")
        return None


async def add_school_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = " ".join(context.args or []).strip()
    if not name:
        await update.message.reply_text("Usage: /add_school <school name>\nExample: /add_school Menelik II Secondary School")
        return
    school = await _admin_call(update, api_client.add_school, name)
    if school:
        await update.message.reply_text(f"Added {school['name']} (id {school['id']}). Students can now pick it on their Profile.")


async def ambassador_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /ambassador <phone or email> <school name or id>\nExample: /ambassador 0912345678 Menelik II Secondary School"
        )
        return
    result = await _admin_call(update, api_client.make_ambassador, args[0], " ".join(args[1:]))
    if result:
        await update.message.reply_text(
            f"{result['student_name']} is now the ambassador for {result['school']}. Their referral code is "
            f"{result['referral_code']}: students who sign up with it join {result['school']} and count as their referrals. "
            "To give them free access too, use /grant."
        )


async def schools_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = await _admin_call(update, api_client.schools_overview)
    if data is None:
        return
    if not data["schools"]:
        await update.message.reply_text("No schools yet. Add one with /add_school <name>.")
        return
    lines = ["Schools:"]
    for s in data["schools"]:
        amb = f", ambassador: {', '.join(s['ambassadors'])}" if s["ambassadors"] else ""
        lines.append(f"• {s['name']} (id {s['id']}): {s['students']} student(s){amb}")
    await update.message.reply_text("\n".join(lines))
