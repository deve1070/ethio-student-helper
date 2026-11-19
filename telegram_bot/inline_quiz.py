"""Inline mode: a student types "@esh_bot biology" in any chat (a class group, a friend) and sends a
real past ESSLCE question into it. Everyone in that chat can tap A-D; whoever taps sees privately
(a pop-up only they get) whether they were right and why. The message carries a "Practise more"
button with the sender's referral link, so friends who sign up from it count as the sender's
referrals.

Telegram's inline mode cannot send polls, so the question is a text message with buttons. Inline
mode has to be switched on once in @BotFather (/setinline)."""

import asyncio
import logging
from urllib.parse import urlencode

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent, Update
from telegram.ext import ContextTypes

from telegram_bot import api_client
from telegram_bot.api_client import BackendError
from telegram_bot.practice_flow import LETTERS, clip, pretty_subject

logger = logging.getLogger(__name__)

ALERT_CHARS = 200  # Telegram's limit for a callback pop-up
_referral_codes: dict[int, str] = {}  # telegram user -> their referral code, once known
_web_app_url: list[str] = []  # read once from /public-config


def _web_url() -> str:
    if not _web_app_url:
        _web_app_url.append(api_client.public_config()["web_app_url"].rstrip("/"))
    return _web_app_url[0]


def _referral_code(uid: int) -> str | None:
    """Kept once found; not kept while unknown, so a student who logs in later gets their link."""
    if uid not in _referral_codes and api_client.is_logged_in(uid):
        try:
            _referral_codes[uid] = api_client.profile(uid)["referral_code"]
        except BackendError:
            pass
    return _referral_codes.get(uid)


def practise_link(code: str | None) -> str:
    params = {"src": "inline", **({"ref": code} if code else {})}
    return f"{_web_url()}/signup?{urlencode(params)}"


def question_text(q: dict) -> str:
    options = "\n".join(f"{L}) {o}" for L, o in zip(LETTERS, q["options"]))
    return (
        f"📝 ESSLCE {pretty_subject(q['subject'])}, {q['year_ec']} E.C.\n\n{q['stem']}\n\n{options}\n\n"
        "Tap your answer. Only you will see if you're right."
    )


def question_markup(q: dict, code: str | None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(L, callback_data=f"iq|{q['question_id']}|{i}") for i, L in enumerate(LETTERS)],
        [InlineKeyboardButton("📚 Practise more past questions", url=practise_link(code))],
    ])


def build_results(questions: list, code: str | None) -> list:
    return [
        InlineQueryResultArticle(
            id=str(q["question_id"]),
            title=f"{pretty_subject(q['subject'])} {q['year_ec']}: {clip(q['stem'], 60)}",
            description=clip(" · ".join(q["options"]), 90),
            input_message_content=InputTextMessageContent(question_text(q)),
            reply_markup=question_markup(q, code),
        )
        for q in questions
    ]


async def on_inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.inline_query
    try:
        questions = await asyncio.to_thread(api_client.inline_questions, query.query)
        code = await asyncio.to_thread(_referral_code, query.from_user.id)
        results = await asyncio.to_thread(build_results, questions, code)
    except BackendError:
        logger.exception("Inline search failed for %r", query.query)
        return
    # personal: each sender's results carry their own referral link
    await query.answer(results, cache_time=30, is_personal=True)


async def on_answer_tap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """iq|<question_id>|<option>: the pop-up only the tapper sees."""
    query = update.callback_query
    try:
        _, qid, chosen = query.data.split("|")
        key = await asyncio.to_thread(api_client.answer_key, int(qid))
    except (ValueError, BackendError):
        await query.answer("This question is no longer available.", show_alert=True)
        return
    right = LETTERS[key["correct_index"]]
    text = "✅ Correct!" if int(chosen) == key["correct_index"] else f"❌ Not quite. The answer is {right}."
    if key.get("explanation"):
        text = clip(f"{text} {key['explanation']}", ALERT_CHARS)
    await query.answer(text, show_alert=True)
