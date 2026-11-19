"""Regular posts to the public channel, to keep students coming back and to bring them to the app.

Every day at CHANNEL_POST_TIME: a real past ESSLCE question as a Telegram quiz poll. Students tap an
answer and Telegram shows them the right one with a short explanation. Polls in a channel are always
anonymous, so nobody sees who answered what.

On CHANNEL_FEATURE_DAYS: a post about one feature of the app follows the quiz. The posts rotate
through FEATURE_POSTS in order, so every feature comes round before any repeats. The price and the
referral reward are read from the backend's /public-config when each post goes out, so they always
match what the app charges.

Every button link carries src=channel (the web app) or start=channel (the bot). The web app stores
the tag at signup, and admins see the counts with /channel_stats.

Setup: the bot must be an admin of the channel with the "Post messages" right. Without it, Telegram
refuses each post and it is logged, nothing else breaks."""

import asyncio
import logging
from datetime import date, timedelta
from datetime import time as dtime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Poll, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from telegram_bot import api_client, reminders
from telegram_bot.api_client import BackendError
from telegram_bot.config import (
    CHANNEL_CHAT_ID,
    CHANNEL_FEATURE_DAYS,
    CHANNEL_POST_TIME,
    CHANNEL_POSTS_ON,
    SUPPORT_CONTACT,
)
from telegram_bot.practice_flow import clip, pretty_subject

logger = logging.getLogger(__name__)

SOURCE = "channel"
POLL_EXPLANATION_CHARS = 200  # Telegram's limit for a quiz poll's explanation
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # date.weekday() order

# {price} and {reward} are filled from /public-config when the post is sent.
FEATURE_POSTS = [
    (
        "📚 Every ESSLCE past paper, with answers and explanations\n\n"
        "Practise real national exam questions by subject, by year or by unit. Every answer comes "
        "with an explanation, so you learn from each question, not just your score.",
        "📚 ሁሉም ያለፉ የESSLCE ፈተናዎች፣ ከመልሶቻቸውና ከማብራሪያዎቻቸው ጋር\n"
        "በትምህርት፣ በዓመት ወይም በምዕራፍ ይለማመዱ። እያንዳንዱ መልስ ማብራሪያ አለው።",
    ),
    (
        "🤔 Why did your wrong answer look right?\n\n"
        "When you pick a wrong option, the app explains what made it tempting and what is wrong "
        "with it. That is how you stop making the same mistake in the real exam.",
        "🤔 የተሳሳተው መልስ ለምን ትክክል መሰለዎት?\n"
        "የተሳሳተ አማራጭ ሲመርጡ፣ ለምን እንደሳበዎትና ስህተቱ ምን እንደሆነ መተግበሪያው ያብራራል።",
    ),
    (
        "🏆 Practise together every evening\n\n"
        "Subscribers join a private group where everyone answers the same ESSLCE questions at the "
        "same time, then sees the results and the leaderboard. Keep your streak going every day.",
        "🏆 በየምሽቱ አብረው ይለማመዱ\n"
        "ተመዝጋቢዎች ሁሉም አንድ አይነት ጥያቄዎችን በአንድ ጊዜ የሚመልሱበት የግል ቡድን ውስጥ ይገባሉ፤ ከዚያም ውጤቱንና ደረጃውን ያያሉ።",
    ),
    (
        "💬 Ask about any question\n\n"
        "Stuck on a question or a topic from your textbook? Ask, and get an explanation based on "
        "the Ethiopian textbooks, with the page it comes from.",
        "💬 ስለማንኛውም ጥያቄ ይጠይቁ\n"
        "ጥያቄ ወይም ርዕስ ግራ ገባዎት? ይጠይቁ፤ በኢትዮጵያ መማሪያ መጽሐፍት ላይ የተመሰረተ ማብራሪያ ከገጹ ጋር ያገኛሉ።",
    ),
    (
        "🗓 A study plan for your exam date\n\n"
        "Tell the app your exam date and how long you can study each day. It plans your units, "
        "reminds you daily, and sends you a progress report every Sunday.",
        "🗓 ለፈተናዎ ቀን የሚሆን የጥናት እቅድ\n"
        "የፈተና ቀንዎንና በቀን ስንት ሰዓት እንደሚያጠኑ ይንገሩት፤ እቅድ ያወጣል፣ በየቀኑ ያስታውሳል፣ በየእሁዱ የእድገት ሪፖርት ይልካል።",
    ),
    (
        "🎯 Find your weak units before the exam does\n\n"
        "The app tracks every answer, shows which units you are weakest in, and brings back the "
        "questions you missed a few days later so they stick.",
        "🎯 ደካማ ምዕራፎችዎን ከፈተናው በፊት ይወቁ\n"
        "መተግበሪያው እያንዳንዱን መልስ ይከታተላል፣ ደካማ ምዕራፎችዎን ያሳያል፣ የሳቷቸውን ጥያቄዎች ከጥቂት ቀናት በኋላ መልሶ ያመጣል።",
    ),
    (
        "🎁 Invite friends, earn {reward} ETB each\n\n"
        "Share your referral code from the Profile page. When a friend you invited subscribes, you "
        "earn {reward} ETB, paid to your Telebirr or CBE account.",
        "🎁 ጓደኞችዎን ይጋብዙ፣ ለእያንዳንዳቸው {reward} ብር ያግኙ\n"
        "የጋባዥ ኮድዎን ያጋሩ፤ የጋበዙት ጓደኛ ሲመዘገብ {reward} ብር ወደ ቴሌብር ወይም ሲቢኢ ሂሳብዎ ይከፈልዎታል።",
    ),
]


def _number(value) -> str:
    value = float(value)
    return str(int(value)) if value.is_integer() else f"{value:.2f}"


def links(config: dict) -> dict:
    web = config["web_app_url"].rstrip("/")
    bot = (config.get("telegram_bot_url") or "").rstrip("/")
    return {
        "app": f"{web}/?src={SOURCE}",
        "subscribe": f"{web}/subscribe?src={SOURCE}",
        "bot": f"{bot}?start={SOURCE}" if bot else None,
    }


def feature_keyboard(config: dict) -> InlineKeyboardMarkup:
    url = links(config)
    rows = [[InlineKeyboardButton("📱 Open the app", url=url["app"])]]
    if url["bot"]:
        rows[0].append(InlineKeyboardButton("🤖 Start the bot", url=url["bot"]))
    rows.append([InlineKeyboardButton(f"⭐ Subscribe: {_number(config['subscription_price_etb'])} ETB / year", url=url["subscribe"])])
    return InlineKeyboardMarkup(rows)


def feature_index(day: date, days: tuple[str, ...]) -> int:
    """Which FEATURE_POSTS entry a feature day gets: counts feature days since a fixed Monday, so
    every post comes round in turn whatever the chosen days are."""
    weeks = (day - date(2026, 1, 5)).days // 7  # 2026-01-05 is a Monday
    position = sorted(WEEKDAYS.index(d) for d in days).index(day.weekday())
    return (weeks * len(days) + position) % len(FEATURE_POSTS)


def feature_text(index: int, config: dict) -> str:
    english, amharic = FEATURE_POSTS[index]
    values = {"price": _number(config["subscription_price_etb"]), "reward": _number(config["referral_reward_etb"])}
    return (
        f"{english.format(**values)}\n\n{amharic.format(**values)}\n\n"
        f"Free to try. A full year of everything: {values['price']} ETB."
    )


SCHOOLS_DAY = "sun"  # the weekly top-schools post follows Sunday's quiz


def schools_text(ranking: list, config: dict) -> str:
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏫 Top schools this week, by questions practised:"]
    for i, s in enumerate(ranking):
        mark = medals[i] if i < len(medals) else f"{i + 1}."
        lines.append(f"{mark} {s['school']}: {s['answered']} questions, {s['active_students']} student(s)")
    lines.append(
        "\nIs your school missing? Pick your school on your Profile in the app, and every question you "
        "answer counts for it."
    )
    group = (
        f"\n👥 Class deal: {config['group_min_students']} or more students from one school subscribe together "
        f"for {_number(config['group_price_etb'])} ETB each instead of {_number(config['subscription_price_etb'])}."
    )
    group += f" Message {SUPPORT_CONTACT} to arrange it." if SUPPORT_CONTACT else " Ask your school's ambassador."
    lines.append(group)
    return "\n".join(lines)


def parse_days(raw: str) -> tuple[str, ...]:
    days = tuple(d for d in (part.strip().lower()[:3] for part in raw.split(",")) if d in WEEKDAYS)
    return tuple(dict.fromkeys(days))  # drop repeats, keep order


def schedule_channel_posts(job_queue, tz) -> bool:
    if not (CHANNEL_POSTS_ON and CHANNEL_CHAT_ID) or job_queue is None:
        return False
    at = reminders.parse_time(CHANNEL_POST_TIME) or dtime(19, 0)
    for job in job_queue.get_jobs_by_name("channel-posts"):
        job.schedule_removal()
    job_queue.run_daily(post_today, time=at.replace(tzinfo=tz), name="channel-posts")
    return True


async def post_quiz(bot, chat_id, config: dict) -> bool:
    try:
        q = await asyncio.to_thread(api_client.channel_question_of_the_day)
    except BackendError as e:
        logger.warning("Channel quiz skipped: no question (%s %s)", e.status_code, e.detail)
        return False
    explanation = clip(q["explanation"], POLL_EXPLANATION_CHARS) if q.get("explanation") else None
    button = InlineKeyboardButton(
        f"📚 Practise more {pretty_subject(q['subject'])} past questions", url=links(config)["app"]
    )
    await bot.send_poll(
        chat_id,
        question=q["stem"],
        options=q["options"],
        type=Poll.QUIZ,
        correct_option_id=q["correct_index"],
        explanation=explanation,
        is_anonymous=True,
        reply_markup=InlineKeyboardMarkup([[button]]),
    )
    return True


def next_feature_day(day: date, days: tuple[str, ...]) -> date | None:
    """`day` itself if it is a feature day, otherwise the next one; None when no days are set."""
    for ahead in range(7):
        candidate = day + timedelta(days=ahead)
        if WEEKDAYS[candidate.weekday()] in days:
            return candidate
    return None


async def post_today(context: ContextTypes.DEFAULT_TYPE, force_feature: bool = False) -> str | None:
    """The daily job: the quiz, then a feature post on feature days. With force_feature (an admin's
    "post now"), the feature post that the next feature day would get is sent today. Returns why
    posting failed, or None."""
    today = date.fromisoformat(reminders.local_today())
    days = parse_days(CHANNEL_FEATURE_DAYS)
    feature_day = next_feature_day(today, days)
    try:
        config = await asyncio.to_thread(api_client.public_config)
    except BackendError as e:
        logger.warning("Channel posts skipped: backend unavailable (%s)", e.detail)
        return "the backend is not reachable"
    try:
        posted_quiz = await post_quiz(context.bot, CHANNEL_CHAT_ID, config)
        if feature_day is not None and (feature_day == today or force_feature):
            text = feature_text(feature_index(feature_day, days), config)
            await context.bot.send_message(CHANNEL_CHAT_ID, text, reply_markup=feature_keyboard(config))
        if WEEKDAYS[today.weekday()] == SCHOOLS_DAY:
            await post_schools(context.bot, CHANNEL_CHAT_ID, config)
    except TelegramError as e:
        # most often: the bot is not an admin of the channel, or CHANNEL_CHAT_ID is wrong
        logger.warning("Channel post to %s refused by Telegram: %s", CHANNEL_CHAT_ID, e)
        return f"Telegram refused it ({e}). Check the bot is an admin of the channel with \"Post messages\"."
    return None if posted_quiz else "no exam question fits a quiz poll right now"


async def post_schools(bot, chat_id, config: dict) -> None:
    """The weekly top-schools post; skipped while no school has any practice."""
    try:
        ranking = await asyncio.to_thread(api_client.school_ranking)
    except BackendError as e:
        logger.warning("Top-schools post skipped (%s %s)", e.status_code, e.detail)
        return
    if ranking:
        await bot.send_message(chat_id, schools_text(ranking, config), reply_markup=feature_keyboard(config))


# ---- admin: /channel_stats ---------------------------------------------------------------------------------
async def channel_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admins: signups in the last 30 days by where they came from, and a button to post now."""
    uid = update.effective_user.id
    if not api_client.is_logged_in(uid):
        await update.message.reply_text("Please /login first with your phone/email and password.")
        return
    try:
        stats = await asyncio.to_thread(api_client.signup_sources, uid, 30)
    except BackendError as e:
        await update.message.reply_text(
            "This command is for admins only." if e.status_code == 403 else "Couldn't load the numbers right now."
        )
        return
    lines = [f"Signups in the last {stats['days']} days, by where they came from:"]
    for s in stats["sources"]:
        name = "no link tag (direct, search, word of mouth)" if s["source"] == "(none)" else s["source"]
        lines.append(f"• {name}: {s['signups']} signed up, {s['subscribed']} subscribed")
    if len(lines) == 1:
        lines.append("• none yet")
    target = CHANNEL_CHAT_ID or "not set (set CHANNEL_CHAT_ID)"
    state = "on" if CHANNEL_POSTS_ON and CHANNEL_CHAT_ID else "off"
    lines.append(
        f"\nChannel posts are {state}: {target}, daily quiz at {CHANNEL_POST_TIME}, "
        f"feature posts on {', '.join(parse_days(CHANNEL_FEATURE_DAYS)) or 'no days'}."
    )
    markup = (
        InlineKeyboardMarkup([[InlineKeyboardButton("📣 Post a quiz and a feature post now", callback_data="cp|now")]])
        if CHANNEL_CHAT_ID
        else None
    )
    await update.message.reply_text("\n".join(lines), reply_markup=markup)


async def post_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """cp|now from /channel_stats. Checked again here: only an admin's login can read the stats."""
    query = update.callback_query
    uid = query.from_user.id
    try:
        await asyncio.to_thread(api_client.signup_sources, uid, 1)
    except BackendError:
        await query.answer("This is for admins only.", show_alert=True)
        return
    await query.answer("Posting...")
    problem = await post_today(context, force_feature=True)
    await query.message.reply_text(f"Not fully posted: {problem}" if problem else f"Posted to {CHANNEL_CHAT_ID}.")
