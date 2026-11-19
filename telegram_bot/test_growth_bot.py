"""growth.py (nudges, share cards), inline_quiz.py and the Sunday top-schools post, with a fake
bot and a fake backend.   Run from the repo root:   backend/venv/bin/python telegram_bot/test_growth_bot.py"""

import asyncio
import os
import sys
import tempfile
import types
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ["BOT_DATA_DIR"] = tempfile.mkdtemp()

from telegram.error import Forbidden  # noqa: E402

from telegram_bot import channel_posts as CP  # noqa: E402
from telegram_bot import growth as G  # noqa: E402
from telegram_bot import inline_quiz as IQ  # noqa: E402
from telegram_bot.api_client import BackendError  # noqa: E402

run = asyncio.run
WEAK = {"subject": "chemistry", "grade": 11, "unit": "Unit 3: Chemical Kinetics", "accuracy": 0.42, "unit_index": 4}
BASE = {"telegram_user_id": 5, "first_name": "Sara", "price_etb": 300.0}


def datas(rows):
    return [d for row in rows for _, d in row]


# ---- every nudge is worded, has the off button, and the right action
cases = {
    "trial_ending": {"days_left": 2, "answered": 140, "streak": 6},
    "trial_ended": {"answered": 140, "streak": 0},
    "countdown": {"days_left": 30, "weakest": WEAK},
    "previews_used": {"answered": 25, "weakest": None},
    "inactive": {"days_away": 3, "weakest": WEAK},
}
for kind, extra in cases.items():
    text, rows = G.nudge_message({**BASE, "kind": kind, **extra})
    assert text.startswith(("⏳ Sara", "Sara", "📅 Sara", "👋 Sara")), (kind, text)
    assert rows[-1] == [G.OFF_BUTTON] and "{" not in text, (kind, rows, text)
t, rows = G.nudge_message({**BASE, "kind": "trial_ending", **cases["trial_ending"]})
assert "ends in 2 days" in t and "140 questions" in t and "6-day streak" in t and "300 ETB" in t and "m|subscribe" in datas(rows)
assert "ends tomorrow" in G.nudge_message({**BASE, "kind": "trial_ending", "days_left": 1, "answered": 3, "streak": 0})[0]
t, rows = G.nudge_message({**BASE, "kind": "countdown", **cases["countdown"]})
assert "30 days to your ESSLCE" in t and "Chemical Kinetics (42% correct)" in t and "wp|chemistry|4" in datas(rows)
assert "m|esslce" in datas(G.nudge_message({**BASE, "kind": "previews_used", **cases["previews_used"]})[1])
assert "1 day to your" in G.nudge_message({**BASE, "kind": "countdown", "days_left": 1, "weakest": None})[0]
assert G.nudge_message({**BASE, "first_name": None, "kind": "inactive", "days_away": 3, "weakest": None})[0].startswith("👋 it's been 3 days")


class FakeBot:
    def __init__(self, blocked=()):
        self.sent, self.blocked = [], set(blocked)

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        if chat_id in self.blocked:
            raise Forbidden("bot was blocked by the user")
        self.sent.append((chat_id, text, reply_markup))


G.api_client.due_nudges = lambda: [{**BASE, "kind": "inactive", "days_away": 3, "weakest": None},
                                   {**BASE, "telegram_user_id": 6, "kind": "countdown", "days_left": 7, "weakest": None}]
bot = FakeBot(blocked={6})
run(G.send_nudges(types.SimpleNamespace(bot=bot)))
assert [c for c, _, _ in bot.sent] == [5], bot.sent  # a student who blocked the bot does not stop the rest


class Msg:
    def __init__(self, chat_type="private"):
        self.chat = types.SimpleNamespace(type=chat_type)
        self.replies = []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append(text)


class Query:
    def __init__(self, data, uid=5, chat_type="private"):
        self.data, self.from_user, self.message, self.answers = data, types.SimpleNamespace(id=uid), Msg(chat_type), []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


def tap(handler, data, **kw):
    q = Query(data, **kw)
    ctx = types.SimpleNamespace(bot=kw.pop("bot", FakeBot()) if "bot" in kw else FakeBot())
    run(handler(types.SimpleNamespace(callback_query=q), ctx))
    return q, ctx.bot


# ---- turning tips off and on
calls = []
G.api_client.set_nudges_off = lambda uid, off: calls.append((uid, off)) or {"off": off}
q, _ = tap(G.nudges_off_callback, "nz|off")
assert calls == [(5, True)] and "no more tips" in q.message.replies[0]
tap(G.nudges_off_callback, "nz|on")
assert calls[-1] == (5, False)

# ---- share: the card arrives in private with a Telegram share button; a group tap says so
G.api_client.is_logged_in = lambda uid: uid != 99
G.api_client.share_card = lambda uid, kind, cid=None: {"text": f"I got 5/6 ({kind},{cid})", "link": "https://app/signup?ref=ABC&src=share",
                                                      "share_url": "https://t.me/share/url?url=x&text=y"}
q, bot = tap(G.share_callback, "sh|mass|12", chat_type="supergroup")
chat, text, markup = bot.sent[0]
assert chat == 5 and "I got 5/6 (mass,12)" in text and "ref=ABC" in text
assert markup.inline_keyboard[0][0].url == "https://t.me/share/url?url=x&text=y"
assert q.answers == [("I sent your card in our private chat.", False)]
q, bot = tap(G.share_callback, "sh|week")
assert "(week,None)" in bot.sent[0][1] and q.answers == [(None, False)]
q, bot = tap(G.share_callback, "sh|week", uid=99)
assert bot.sent == [] and "login" in q.answers[0][0]


def not_found(*a, **k):
    raise BackendError(404, "Nothing to share yet")


G.api_client.share_card = not_found
q, _ = tap(G.share_callback, "sh|mass|12", chat_type="supergroup")
assert q.answers[0] == ("You didn't take part in this one.", True)

# ---- inline: results carry the question, A-D buttons and the sender's referral link
IQ.api_client.public_config = lambda: {"web_app_url": "https://app.example/"}
IQ.api_client.profile = lambda uid: {"referral_code": "SARA12"}
IQ.api_client.inline_questions = lambda text: [{"question_id": 41, "subject": "chemistry", "year_ec": 2015,
                                                "stem": "Which gas is a noble gas?", "options": ["Neon", "Oxygen", "Nitrogen", "Hydrogen"]}]
answered = []


class Inline:
    def __init__(self, uid):
        self.query, self.from_user = "chem", types.SimpleNamespace(id=uid)

    async def answer(self, results, cache_time, is_personal):
        answered.append((results, is_personal))


run(IQ.on_inline_query(types.SimpleNamespace(inline_query=Inline(5)), None))
results, personal = answered[-1]
r = results[0]
assert personal and r.id == "41" and r.title.startswith("Chemistry 2015: Which gas")
assert "A) Neon" in r.input_message_content.message_text and "Only you will see" in r.input_message_content.message_text
row1, row2 = r.reply_markup.inline_keyboard
assert [b.callback_data for b in row1] == ["iq|41|0", "iq|41|1", "iq|41|2", "iq|41|3"]
link = urlparse(row2[0].url)
assert link.netloc == "app.example" and link.path == "/signup" and parse_qs(link.query) == {"src": ["inline"], "ref": ["SARA12"]}
run(IQ.on_inline_query(types.SimpleNamespace(inline_query=Inline(99)), None))  # not logged in: no referral code
assert parse_qs(urlparse(answered[-1][0][0].reply_markup.inline_keyboard[1][0].url).query) == {"src": ["inline"]}

IQ.api_client.answer_key = lambda qid: {"correct_index": 0, "explanation": "Neon is in group 18. " * 30}
q, _ = tap(IQ.on_answer_tap, "iq|41|0")
assert q.answers[0][0].startswith("✅ Correct! Neon is in group 18.") and len(q.answers[0][0]) <= 200 and q.answers[0][1]
q, _ = tap(IQ.on_answer_tap, "iq|41|2")
assert q.answers[0][0].startswith("❌ Not quite. The answer is A.")
IQ.api_client.answer_key = not_found
q, _ = tap(IQ.on_answer_tap, "iq|41|2")
assert q.answers[0] == ("This question is no longer available.", True)

# ---- Sunday: top schools after the quiz, with the class deal
config = {"web_app_url": "https://app.example", "telegram_bot_url": "https://t.me/esh_bot", "subscription_price_etb": 300.0,
          "referral_reward_etb": 50.0, "group_price_etb": 250.0, "group_min_students": 10}
ranking = [{"school": "Menelik II", "answered": 340, "active_students": 12}, {"school": "Lideta", "answered": 120, "active_students": 4}]
text = CP.schools_text(ranking, config)
assert "🥇 Menelik II: 340 questions, 12 student(s)" in text and "🥈 Lideta" in text
assert "10 or more students" in text and "250 ETB each instead of 300" in text and "ambassador" in text
CP.SUPPORT_CONTACT = "@dawit"
assert "Message @dawit" in CP.schools_text(ranking, config)


class ChannelBot(FakeBot):
    polls = 0

    async def send_poll(self, chat_id, **kw):
        ChannelBot.polls += 1


CP.api_client.public_config = lambda: config
CP.api_client.channel_question_of_the_day = lambda: {"question_id": 1, "subject": "biology", "year_ec": 2016, "stem": "Q?",
                                                    "options": ["a", "b", "c", "d"], "correct_index": 0, "explanation": None}
CP.api_client.school_ranking = lambda: ranking
CP.CHANNEL_CHAT_ID, CP.CHANNEL_FEATURE_DAYS = "@ch", "tue,thu,sat"
CP.reminders.local_today = lambda tz=None: "2026-11-22"  # a Sunday
bot = ChannelBot()
assert run(CP.post_today(types.SimpleNamespace(bot=bot))) is None
assert ChannelBot.polls == 1 and len(bot.sent) == 1 and bot.sent[0][1].startswith("🏫 Top schools")
CP.api_client.school_ranking = lambda: []
bot = ChannelBot()
run(CP.post_today(types.SimpleNamespace(bot=bot)))
assert bot.sent == []  # no school practised yet: nothing posted
print("GROWTH BOT TESTS PASSED")
