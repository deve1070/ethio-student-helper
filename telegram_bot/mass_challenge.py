"""The daily subscriber-only mass ESSLCE practice: one scheduled job posts an announcement, then a
timed sequence of native Telegram polls (visible to the whole group, so students can discuss each
one together), then a leaderboard reveal, all to the private group - gated by subscription
(ChatJoinRequestHandler) and swept daily for lapsed subscriptions. One day can run TWO such
sequences back to back (one per stream) when that day's subject isn't common to both - see
exams/store.py's pick_todays_challenges. See docs/dev_plans/mass_esslce_practice.md for the full
design. Mirrors reminders.py's shape (module-level helpers, functions taking job_queue/context,
reminders.local_tz() for timezone), but as ONE global job rather than one per student - there is
only ever one (or two, same trigger) shared daily event(s).

Polls are type="regular", not "quiz" - a quiz poll shows the correct answer and explanation to
whoever votes the instant they vote, which would defeat the whole point of a shared reveal later.
A regular poll only records the vote (and shows the live tally, which is fine - it's meant to fuel
discussion, not leak the answer); correctness is still computed and recorded server-side exactly
the same way, just never surfaced to the student until reveal()."""

import asyncio
import base64
import io
import logging
from datetime import datetime, timedelta
from datetime import time as dtime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden, NetworkError, TimedOut
from telegram.ext import ContextTypes

from telegram_bot import api_client
from telegram_bot import reminders
from telegram_bot.api_client import BackendError
from telegram_bot.config import (
    MASS_CHALLENGE_HEADSUP_MINUTES,
    MASS_CHALLENGE_NATURAL_TOPIC_ID,
    MASS_CHALLENGE_NUDGE_MINUTES,
    MASS_CHALLENGE_SOCIAL_TOPIC_ID,
    MASS_CHALLENGE_TIME,
    TELEGRAM_PRIVATE_GROUP_ID,
)
from telegram_bot.esslce_flow import EsslceSession
from telegram_bot.handlers.esslce_handler import SESSION_KEY, keyboard
from telegram_bot.practice_flow import Screen, clip, pretty_subject

logger = logging.getLogger(__name__)

BREATHER_SECONDS = 15  # fixed pause between one poll closing and the next opening
RESUME_OPEN_WINDOW = 30 * 60  # resume_after_restart: how late a swallowed opening is still started
START_ME_FIRST = "Open a private chat with me first (press Start there), then tap this again."
RESUME_REVEAL_GRACE = 120  # ...and how long after the last poll closed a reveal is still owed
STREAM_LABELS = {"natural_science": "🌿 Natural stream", "social_science": "🏛 Social stream"}
# Two separate topics so natural-stream and social-stream polls never interleave in the same
# thread; a common-subject day (stream="") uses the natural topic, the one general space.
TOPIC_IDS = {
    "": MASS_CHALLENGE_NATURAL_TOPIC_ID,
    "natural_science": MASS_CHALLENGE_NATURAL_TOPIC_ID,
    "social_science": MASS_CHALLENGE_SOCIAL_TOPIC_ID,
}

# telegram_poll_id -> (challenge_id, question_id). Populated by post_question, read by
# on_poll_answer. Only a speed shortcut - mass_challenge_polls on the backend is the durable copy,
# consulted on a miss (e.g. right after a bot restart, mid-event).
_poll_lookup: dict[str, tuple[int, int]] = {}


def schedule_daily_event(job_queue, tz) -> bool:
    if TELEGRAM_PRIVATE_GROUP_ID == 0 or job_queue is None:
        return False
    at = reminders.parse_time(MASS_CHALLENGE_TIME) or dtime(20, 0)
    for job in job_queue.get_jobs_by_name("mass-challenge-open"):
        job.schedule_removal()
    job_queue.run_daily(open_challenge, time=at.replace(tzinfo=tz), name="mass-challenge-open")
    return True


def schedule_headsup(job_queue, tz) -> bool:
    if TELEGRAM_PRIVATE_GROUP_ID == 0 or job_queue is None:
        return False
    at = reminders.parse_time(MASS_CHALLENGE_TIME) or dtime(20, 0)
    headsup_dt = datetime.combine(datetime.today(), at) - timedelta(minutes=MASS_CHALLENGE_HEADSUP_MINUTES)
    for job in job_queue.get_jobs_by_name("mass-challenge-headsup"):
        job.schedule_removal()
    job_queue.run_daily(
        send_headsup, time=headsup_dt.time().replace(tzinfo=tz), name="mass-challenge-headsup"
    )
    return True


def schedule_sweep(job_queue, tz) -> bool:
    if TELEGRAM_PRIVATE_GROUP_ID == 0 or job_queue is None:
        return False
    for job in job_queue.get_jobs_by_name("mass-challenge-sweep"):
        job.schedule_removal()
    # 03:00 local - well outside the challenge window, so a slow sweep never collides with it.
    job_queue.run_daily(
        sweep_expired_memberships, time=dtime(3, 0, tzinfo=tz), name="mass-challenge-sweep"
    )
    return True


async def send_headsup(context: ContextTypes.DEFAULT_TYPE) -> None:
    """One heads-up message per challenge, MASS_CHALLENGE_HEADSUP_MINUTES before open_challenge
    fires. Calls /today itself (idempotent - the exact same lookup-or-create open_challenge will
    perform again later) so the message can name the actual subject/unit instead of a generic
    "get ready", resolving today's pick early rather than waiting for the real opening."""
    if TELEGRAM_PRIVATE_GROUP_ID == 0:
        return
    try:
        result = await asyncio.to_thread(api_client.mass_challenge_today)
    except BackendError:
        logger.exception("Could not resolve today's mass challenge(s) for the heads-up")
        return

    for challenge in result["challenges"]:
        label = STREAM_LABELS.get(challenge["stream"], "")
        prefix = f"{label} " if label else ""
        await context.bot.send_message(
            TELEGRAM_PRIVATE_GROUP_ID,
            f"⏰ {prefix}Mass practice starts in {MASS_CHALLENGE_HEADSUP_MINUTES} minutes: "
            f"{pretty_subject(challenge['subject'])} - {challenge['unit']}. Get ready!",
            message_thread_id=TOPIC_IDS.get(challenge["stream"]),
        )


async def open_challenge(context: ContextTypes.DEFAULT_TYPE) -> None:
    """The daily job. Starts every one of today's challenges (1, or 2 on a stream-split day) at
    once, in parallel - each runs its own independent announcement -> polls -> reveal chain, since
    they're for non-overlapping audiences and neither should make the other's stream wait."""
    if TELEGRAM_PRIVATE_GROUP_ID == 0:
        return
    try:
        result = await asyncio.to_thread(api_client.mass_challenge_today)
    except BackendError:
        logger.exception("Could not create/fetch today's mass challenge(s)")
        return

    for challenge in result["challenges"]:
        await _start_challenge(context, challenge)


async def _start_challenge(context: ContextTypes.DEFAULT_TYPE, challenge: dict) -> None:
    question_ids = challenge["question_ids"]
    label = STREAM_LABELS.get(challenge["stream"], "")
    prefix = f"{label} " if label else ""

    await _send_with_retry(
        lambda: context.bot.send_message(
            TELEGRAM_PRIVATE_GROUP_ID,
            (
                f"🎯 {prefix}Today's mass practice: {pretty_subject(challenge['subject'])} - {challenge['unit']}\n"
                f"{len(question_ids)} questions, {challenge['question_seconds']}s each. "
                "Get ready - the first one is next!"
            ),
            message_thread_id=TOPIC_IDS.get(challenge["stream"]),
        )
    )
    _schedule_questions(context.job_queue, challenge, list(enumerate(question_ids)), first_delay=0)


def _schedule_questions(job_queue, challenge: dict, pending: list, first_delay: float) -> None:
    """Schedules `pending` - (index, question_id) pairs, index being the question's position in
    the day's full list - one poll every question_seconds + BREATHER_SECONDS starting after
    `first_delay` seconds, then the reveal once the last poll has closed. Shared by a normal
    opening (every question pending, no delay) and resume_after_restart (only the questions the
    previous bot process never got to post)."""
    question_seconds = challenge["question_seconds"]
    challenge_id = challenge["id"]
    label = STREAM_LABELS.get(challenge["stream"], "")
    topic_id = TOPIC_IDS.get(challenge["stream"])
    step = question_seconds + BREATHER_SECONDS

    for slot, (index, question_id) in enumerate(pending):
        job_queue.run_once(
            post_question,
            when=first_delay + slot * step,
            data={
                "challenge_id": challenge_id,
                "question_id": question_id,
                "index": index,
                "total": len(challenge["question_ids"]),
                "question_seconds": question_seconds,
                "label": label,
                "topic_id": topic_id,
            },
            name=f"mass-challenge-{challenge_id}-q{index}",
        )

    reveal_delay = first_delay + max(len(pending) - 1, 0) * step + question_seconds + 5
    job_queue.run_once(
        reveal,
        when=reveal_delay,
        data={
            "challenge_id": challenge_id,
            "label": label,
            "topic_id": topic_id,
            "question_ids": challenge["question_ids"],
        },
        name=f"mass-challenge-{challenge_id}-reveal",
    )


async def resume_after_restart(application) -> None:
    """Called once at boot. The question/reveal jobs of an event in progress live only in the
    previous bot process's memory, so a restart (a deploy, a crash) mid-event used to drop every
    remaining question and the reveal. mass_challenge_polls on the backend records which
    questions were actually posted, so this reschedules exactly the rest:
      - some questions posted, some not: the remaining ones, then the reveal;
      - all posted, last poll still open or only just closed: the reveal alone;
      - none posted, and the daily opening time passed less than RESUME_OPEN_WINDOW ago (the
        restart swallowed the opening job itself): the whole event, starting now.
    Anything older is left alone - replaying a finished event would post a second reveal."""
    if TELEGRAM_PRIVATE_GROUP_ID == 0 or application.job_queue is None:
        return
    try:
        state = await asyncio.to_thread(api_client.mass_challenge_today_state)
    except BackendError:
        logger.exception("Could not fetch today's mass-challenge state to resume")
        return

    tz = reminders.local_tz()
    opens = reminders.parse_time(MASS_CHALLENGE_TIME) or dtime(20, 0)
    now_local = datetime.now(tz)
    since_open = (now_local - datetime.combine(now_local.date(), opens, tzinfo=tz)).total_seconds()

    for challenge in state["challenges"]:
        posted = set(challenge["posted_question_ids"])
        pending = [(i, q) for i, q in enumerate(challenge["question_ids"]) if q not in posted]
        since_last = challenge["seconds_since_last_poll"]
        step = challenge["question_seconds"] + BREATHER_SECONDS
        if posted and pending:
            delay = max(step - since_last, 1)
            _schedule_questions(application.job_queue, challenge, pending, first_delay=delay)
            logger.info("Resumed mass challenge %s: %d question(s) left", challenge["id"], len(pending))
        elif posted and not pending and since_last < challenge["question_seconds"] + RESUME_REVEAL_GRACE:
            application.job_queue.run_once(
                reveal,
                when=max(challenge["question_seconds"] + 5 - since_last, 1),
                data={
                    "challenge_id": challenge["id"],
                    "label": STREAM_LABELS.get(challenge["stream"], ""),
                    "topic_id": TOPIC_IDS.get(challenge["stream"]),
                    "question_ids": challenge["question_ids"],
                },
                name=f"mass-challenge-{challenge['id']}-reveal",
            )
            logger.info("Resumed mass challenge %s: reveal only", challenge["id"])
        elif not posted and 0 <= since_open < RESUME_OPEN_WINDOW:
            _schedule_questions(application.job_queue, challenge, pending, first_delay=1)
            logger.info("Resumed mass challenge %s: opening was missed, starting now", challenge["id"])


async def _send_with_retry(send, attempts: int = 3):
    """Runs `send()` (a zero-argument callable returning a fresh Telegram request coroutine),
    retrying a timeout or dropped connection. Without this, one transient network error on a
    question's photo or poll aborted that whole job and the question was silently skipped
    (observed in two of three live test runs). `send` is called again per attempt, so a photo's
    BytesIO is rebuilt rather than re-read from its exhausted position. A request that timed out
    on our side can still have been delivered, so a retry can occasionally post a duplicate."""
    for attempt in range(1, attempts + 1):
        try:
            return await send()
        except (TimedOut, NetworkError):
            if attempt == attempts:
                raise
            logger.warning("Telegram send failed (try %d/%d), retrying", attempt, attempts)
            await asyncio.sleep(2 * attempt)


async def post_question(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    challenge_id, question_id = data["challenge_id"], data["question_id"]
    label = data.get("label", "")
    prefix = f"{label} " if label else ""
    topic_id = data.get("topic_id")
    try:
        q = await asyncio.to_thread(api_client.mass_challenge_question_content, question_id)
    except BackendError:
        logger.exception("Could not fetch mass-challenge question %s", question_id)
        return

    # Full stem+options go in a message BEFORE the poll - a poll caps its question at 300
    # characters and each option at 100 (confirmed against telegram.constants.PollLimit), far below
    # a typical ESSLCE stem, and a poll has no way to show a rendered math image at all. Posting it
    # as its own message (not just the poll) is also what makes group discussion possible.
    header = f"{prefix}Item {data['index'] + 1}/{data['total']} (#{q['item_no']})"
    if q["diagram_image_base64"]:
        png = base64.b64decode(q["diagram_image_base64"])
        caption = f"{header}\n\n{q['stem']}\n\n" + "\n".join(
            f"{L}) {opt}" for L, opt in zip("ABCD", q["options"])
        )
        await _send_with_retry(
            lambda: context.bot.send_photo(
                TELEGRAM_PRIVATE_GROUP_ID, io.BytesIO(png), caption=caption[:1024], message_thread_id=topic_id
            )
        )
    elif q["stem_image_base64"]:
        png = base64.b64decode(q["stem_image_base64"])
        await _send_with_retry(
            lambda: context.bot.send_photo(
                TELEGRAM_PRIVATE_GROUP_ID, io.BytesIO(png), caption=header, message_thread_id=topic_id
            )
        )
    else:
        text = f"{header}\n\n{q['stem']}\n\n" + "\n".join(
            f"{L}) {opt}" for L, opt in zip("ABCD", q["options"])
        )
        await _send_with_retry(
            lambda: context.bot.send_message(TELEGRAM_PRIVATE_GROUP_ID, text, message_thread_id=topic_id)
        )

    ask_ai_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("💬 Ask AI about this", callback_data=f"mq|{question_id}")]]
    )
    message = await _send_with_retry(
        lambda: context.bot.send_poll(
            TELEGRAM_PRIVATE_GROUP_ID,
            question=f"{prefix}Item {data['index'] + 1}: choose the best answer",
            options=["A", "B", "C", "D"][: len(q["options"])],
            is_anonymous=False,  # "regular" (the default when type is omitted) - no built-in
            # grading, so nobody sees correctness until reveal(); is_anonymous=False still lets
            # on_poll_answer identify the voter to score it server-side
            open_period=data["question_seconds"],
            reply_markup=ask_ai_markup,
            message_thread_id=topic_id,
        )
    )
    poll_id = message.poll.id
    _poll_lookup[poll_id] = (challenge_id, question_id)
    try:
        await asyncio.to_thread(api_client.mass_challenge_record_poll, challenge_id, question_id, poll_id)
    except BackendError:
        logger.exception("Could not record poll %s for challenge %s", poll_id, challenge_id)


async def on_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    answer = update.poll_answer
    if not answer.option_ids:
        return  # a vote retraction - a real possibility on a "regular" poll, just ignore it

    pair = _poll_lookup.get(answer.poll_id)
    if pair is None:
        try:
            looked_up = await asyncio.to_thread(api_client.mass_challenge_lookup_poll, answer.poll_id)
            pair = looked_up["challenge_id"], looked_up["question_id"]
        except BackendError:
            logger.warning("Unknown poll id %s - cannot record this vote", answer.poll_id)
            return

    challenge_id, question_id = pair
    telegram_user_id = answer.user.id
    try:
        await asyncio.to_thread(
            api_client.mass_challenge_answer,
            telegram_user_id, challenge_id, question_id, answer.option_ids[0]
        )
    except BackendError as exc:
        if exc.status_code == 401:
            await context.bot.send_message(
                telegram_user_id,
                "Your login expired, so that mass-practice answer couldn't be recorded. "
                "Please /login again so your next answers count.",
            )
        else:
            logger.exception("Could not record mass-challenge answer for %s", telegram_user_id)


async def reveal(context: ContextTypes.DEFAULT_TYPE) -> None:
    challenge_id = context.job.data["challenge_id"]
    label = context.job.data.get("label", "")
    prefix = f"{label} " if label else ""
    topic_id = context.job.data.get("topic_id")
    try:
        board = await asyncio.to_thread(api_client.mass_challenge_leaderboard, challenge_id)
    except BackendError:
        logger.exception("Could not fetch leaderboard for challenge %s", challenge_id)
        return

    if board["entries"]:
        lines = [f"🏁 {prefix}Results - {pretty_subject(board['subject'])}, {board['unit']}:"]
        medals = ["🥇", "🥈", "🥉"]
        for i, entry in enumerate(board["entries"][:10]):
            medal = medals[i] if i < len(medals) else f"{i + 1}."
            lines.append(f"{medal} {entry['display_name']} - {entry['correct']}/{board['total_questions']}")
        results = "\n".join(lines)
    else:
        results = (
            f"⏱ {prefix}That's today's {board['total_questions']} questions! Nobody answered this "
            "time - tomorrow's another chance."
        )
    await _send_with_retry(
        lambda: context.bot.send_message(TELEGRAM_PRIVATE_GROUP_ID, results, message_thread_id=topic_id)
    )
    await _post_answer_key(context, challenge_id, context.job.data.get("question_ids", []), prefix, topic_id)


def _has_math(text: str | None) -> bool:
    return bool(text) and ("$" in text or "\\" in text)


async def _post_answer_key(context, challenge_id: int, question_ids: list, prefix: str, topic_id) -> None:
    """After the results: each question's correct option (and its explanation, when it is plain
    text - raw LaTeX would be unreadable in a message; "Ask AI" on that poll covers those), plus
    the button that opens the private catch-up flow for anyone who missed the polls."""
    lines = [f"✅ {prefix}Answers:"]
    for i, question_id in enumerate(question_ids):
        try:
            q = await asyncio.to_thread(api_client.mass_challenge_question_content, question_id)
        except BackendError:
            logger.exception("Could not fetch question %s for the answer key", question_id)
            continue
        letter = "ABCD"[q["answer_index"]]
        option = q["options"][q["answer_index"]]
        line = f"{i + 1}. {letter}" if _has_math(option) else f"{i + 1}. {letter}) {clip(option, 120)}"
        if q["explanation"] and not _has_math(q["explanation"]):
            line += f"\n   {clip(q['explanation'], 220)}"
        lines.append(line)
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📝 Missed it? Catch up privately", callback_data=f"mc|{challenge_id}")]]
    )
    text = "\n\n".join(lines)[:4000]
    await _send_with_retry(
        lambda: context.bot.send_message(
            TELEGRAM_PRIVATE_GROUP_ID, text, reply_markup=markup, message_thread_id=topic_id
        )
    )


def _question_text_and_image(header: str, q: dict) -> tuple[str, str | None]:
    """A question as (message text, optional base64 image). A diagram question keeps its text and
    adds the source page photo; a math-bearing one shows only the header as text, since its raw
    stem is unrendered LaTeX and the rendered image carries the stem and options instead."""
    body = "\n".join(f"{L}) {opt}" for L, opt in zip("ABCD", q["options"]))
    if q["diagram_image_base64"]:
        return f"{header}\n\n{q['stem']}\n\n{body}", q["diagram_image_base64"]
    if q["stem_image_base64"]:
        return header, q["stem_image_base64"]
    return f"{header}\n\n{q['stem']}\n\n{body}", None


async def _dm_question(bot, user_id: int, header: str, q: dict, buttons: list) -> None:
    text, image = _question_text_and_image(header, q)
    if image:  # photo first, so the answer buttons end up below it
        photo = io.BytesIO(base64.b64decode(image))
        photo.name = "question.png"
        await bot.send_photo(user_id, photo)
    await bot.send_message(user_id, text, reply_markup=keyboard(Screen(text, buttons)))


async def on_ask_ai_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The "💬 Ask AI about this" button attached to a mass-challenge poll (tapped from the GROUP).
    DMs the tapping student that question with the existing /esslce elaborate/ask buttons, by
    creating a fresh EsslceSession for them - on_elaborate and on_ask_start (esslce_flow.py) don't
    read any prior session state, so a brand-new session works even if this student never ran
    /esslce before. context.user_data is keyed by user id across every chat (confirmed directly
    against the installed library), so this session is the SAME one esslce_callback finds when
    they later tap those buttons inside their own DM, not a separate, group-scoped one."""
    query = update.callback_query
    question_id = int(query.data.split("|", 1)[1])
    user_id = query.from_user.id

    if not api_client.is_logged_in(user_id):
        await query.answer("Please /login with me first, then tap this again.", show_alert=True)
        return
    try:
        q = await asyncio.to_thread(api_client.mass_challenge_question_content, question_id)
    except BackendError:
        logger.exception("Could not fetch mass-challenge question %s for Ask AI", question_id)
        await query.answer("Couldn't load that question. Please try again.", show_alert=True)
        return

    context.user_data[SESSION_KEY] = EsslceSession(api_client, user_id)
    buttons = [[("🔍 Explain more", f"ee|{question_id}")], [("💬 Ask about this", f"eq|{question_id}")]]
    try:
        await _dm_question(context.bot, user_id, f"Item #{q['item_no']}", q, buttons)
    except Forbidden:
        await query.answer(START_ME_FIRST, show_alert=True)
        return
    await query.answer("Sent to your DM!")


# ---- catch-up: the day's questions answered privately, after (or instead of) the group polls ----
async def catchup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/catchup - today's mass practice in this private chat, for a student who missed the polls."""
    user_id = update.effective_user.id
    if not api_client.is_logged_in(user_id):
        await update.effective_message.reply_text("Please /login first with your phone/email and password.")
        return
    try:
        state = await asyncio.to_thread(api_client.mass_challenge_today_state)
    except BackendError:
        await update.effective_message.reply_text("Couldn't load today's practice. Please try again shortly.")
        return
    challenges = state["challenges"]
    if not challenges:
        await update.effective_message.reply_text("Today's mass practice hasn't been set yet. Check back this evening.")
    elif len(challenges) == 1:
        await _send_catchup_question(context, user_id, challenges[0]["id"])
    else:
        rows = [
            [(f"{STREAM_LABELS.get(c['stream'], 'Everyone')}: {pretty_subject(c['subject'])}", f"mc|{c['id']}")]
            for c in challenges
        ]
        text = "Which of today's practices?"
        await update.effective_message.reply_text(text, reply_markup=keyboard(Screen(text, rows)))


async def on_catchup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """mc|<challenge_id> - "Missed it? Catch up privately" under the group's answer key, "Next" in
    the catch-up flow itself, and the streak reminder's button. Always continues in the student's
    own chat, wherever it was tapped."""
    query = update.callback_query
    user_id = query.from_user.id
    if not api_client.is_logged_in(user_id):
        await query.answer("Please /login with me first, then tap this again.", show_alert=True)
        return
    try:
        await _send_catchup_question(context, user_id, int(query.data.split("|")[1]))
    except Forbidden:
        await query.answer(START_ME_FIRST, show_alert=True)
        return
    await query.answer("Sent to your DM!" if query.message.chat.type != "private" else None)


async def _send_catchup_question(context, user_id: int, challenge_id: int) -> None:
    try:
        progress = await asyncio.to_thread(api_client.mass_challenge_remaining, user_id, challenge_id)
    except BackendError as e:
        await context.bot.send_message(
            user_id,
            "Your session expired. Please /login again." if e.status_code == 401
            else "Couldn't load today's practice. Please try again shortly.",
        )
        return
    remaining = progress["remaining_question_ids"]
    if not remaining:
        await context.bot.send_message(
            user_id,
            f"✅ You've answered all {progress['total']} of today's questions. Today counts toward your streak.",
        )
        return
    question_id = remaining[0]
    try:
        q = await asyncio.to_thread(api_client.mass_challenge_question_content, question_id)
    except BackendError:
        await context.bot.send_message(user_id, "Couldn't load the next question. Please try /catchup again.")
        return
    number = progress["total"] - len(remaining) + 1
    header = f"{pretty_subject(progress['subject'])} - {progress['unit']}\nQuestion {number}/{progress['total']}"
    buttons = [[(L, f"ma|{challenge_id}|{question_id}|{i}") for i, L in enumerate("ABCD"[: len(q["options"])])]]
    await _dm_question(context.bot, user_id, header, q, buttons)


async def on_catchup_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ma|<challenge_id>|<question_id>|<chosen_index>. The backend decides whether the answer is
    late (that question's group poll already closed). A late answer gets its result at once - the
    correct answers are already posted in the group; one given while the poll is still open is
    only acknowledged, same as a vote on the poll itself."""
    query = update.callback_query
    user_id = query.from_user.id
    _, challenge_id, question_id, chosen = query.data.split("|")
    challenge_id, question_id, chosen = int(challenge_id), int(question_id), int(chosen)
    try:
        res = await asyncio.to_thread(api_client.mass_challenge_answer, user_id, challenge_id, question_id, chosen)
        q = await asyncio.to_thread(api_client.mass_challenge_question_content, question_id)
    except BackendError as e:
        await query.answer(
            "Your session expired. Please /login again." if e.status_code == 401
            else "Couldn't record that. Please try again.",
            show_alert=True,
        )
        return
    await query.answer()

    if not res["late"]:
        text = "Recorded. Results come with the group's reveal."
    else:
        correct_letter = "ABCD"[q["answer_index"]]
        text = "✅ Correct!" if res["is_correct"] else f"❌ Not quite. The correct answer is {correct_letter}."
        if not res["recorded"]:
            text += "\n(You had already answered this one - your first answer stands.)"
        if q["explanation"] and not _has_math(q["explanation"]):
            text += f"\n\nWhy: {clip(q['explanation'], 600)}"
    context.user_data[SESSION_KEY] = EsslceSession(api_client, user_id)  # for "Explain more" below
    buttons = [[("Next ➡", f"mc|{challenge_id}")]]
    if res["late"]:
        buttons.append([("🔍 Explain more", f"ee|{question_id}")])
    try:
        await query.edit_message_text(text, reply_markup=keyboard(Screen(text, buttons)))
    except BadRequest:
        await context.bot.send_message(user_id, text, reply_markup=keyboard(Screen(text, buttons)))


# ---- streak reminder ----------------------------------------------------------------------------
def schedule_streak_nudge(job_queue, tz) -> bool:
    if TELEGRAM_PRIVATE_GROUP_ID == 0 or job_queue is None:
        return False
    opens = reminders.parse_time(MASS_CHALLENGE_TIME) or dtime(20, 0)
    at = datetime.combine(datetime.today(), opens) + timedelta(minutes=MASS_CHALLENGE_NUDGE_MINUTES)
    for job in job_queue.get_jobs_by_name("mass-challenge-nudge"):
        job.schedule_removal()
    job_queue.run_daily(send_streak_nudges, time=at.time().replace(tzinfo=tz), name="mass-challenge-nudge")
    return True


async def send_streak_nudges(context: ContextTypes.DEFAULT_TYPE) -> None:
    """One private message to each student whose streak ends tonight (took part yesterday, nothing
    yet today) - never a message to the whole group. The list comes from the backend's /at-risk."""
    try:
        students = await asyncio.to_thread(api_client.mass_challenge_at_risk)
    except BackendError:
        logger.exception("Could not fetch at-risk students for the streak reminder")
        return
    for student in students:
        days = student["streak_days"]
        text = (
            f"🔥 Your {days}-day mass-practice streak ends tonight - you haven't answered today's "
            "questions yet. Catch up now and keep it going."
        )
        buttons = [[("Catch up ➡", f"mc|{student['challenge_id']}")]]
        try:
            await context.bot.send_message(
                student["telegram_user_id"], text, reply_markup=keyboard(Screen(text, buttons))
            )
        except Exception:
            logger.exception("Could not send the streak reminder to %s", student["telegram_user_id"])


async def on_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    request = update.chat_join_request
    if request.chat.id != TELEGRAM_PRIVATE_GROUP_ID:
        return
    telegram_user_id = request.from_user.id
    try:
        eligible = await asyncio.to_thread(api_client.mass_challenge_group_eligibility, telegram_user_id)
    except BackendError:
        logger.exception("Could not check group eligibility for %s", telegram_user_id)
        return

    if eligible:
        await context.bot.approve_chat_join_request(request.chat.id, telegram_user_id)
    else:
        await context.bot.decline_chat_join_request(request.chat.id, telegram_user_id)
        await context.bot.send_message(
            telegram_user_id,
            "The daily mass-practice group is for subscribers only. Use /subscribe to join, "
            "then request to join the group again.",
        )


async def sweep_expired_memberships(context: ContextTypes.DEFAULT_TYPE) -> None:
    if TELEGRAM_PRIVATE_GROUP_ID == 0:
        return
    try:
        lapsed_ids = await asyncio.to_thread(api_client.mass_challenge_lapsed_memberships)
    except BackendError:
        logger.exception("Could not fetch lapsed mass-challenge memberships")
        return

    for telegram_user_id in lapsed_ids:
        try:
            await context.bot.ban_chat_member(TELEGRAM_PRIVATE_GROUP_ID, telegram_user_id)
            await context.bot.unban_chat_member(TELEGRAM_PRIVATE_GROUP_ID, telegram_user_id)
        except Exception:
            logger.exception("Could not remove %s from the private group", telegram_user_id)
