"""channel_posts.py with a fake bot and a fake backend: the daily quiz poll, the rotating feature
posts, the link tags, and what happens when Telegram or the backend refuses.
Run from the repo root:   backend/venv/bin/python telegram_bot/test_channel_posts.py"""

import asyncio
import os
import sys
import tempfile
import types
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ["BOT_DATA_DIR"] = tempfile.mkdtemp()

from telegram.error import Forbidden  # noqa: E402

from telegram_bot import channel_posts as CP  # noqa: E402
from telegram_bot.api_client import BackendError  # noqa: E402

CONFIG = {"web_app_url": "https://app.example", "telegram_bot_url": "https://t.me/esh_bot",
          "subscription_price_etb": 300.0, "referral_reward_etb": 50.0}
QUESTION = {"question_id": 9, "subject": "biology", "year_ec": 2016, "stem": "Which organelle makes ATP?",
            "options": ["Ribosome", "Mitochondrion", "Nucleus", "Vacuole"], "correct_index": 1,
            "explanation": "It is where respiration happens. " * 20}


class FakeBot:
    def __init__(self, refuse=False):
        self.polls, self.messages, self.refuse = [], [], refuse

    async def send_poll(self, chat_id, **kw):
        if self.refuse:
            raise Forbidden("bot is not a member of the channel chat")
        self.polls.append((chat_id, kw))

    async def send_message(self, chat_id, text, reply_markup=None):
        self.messages.append((chat_id, text, reply_markup))


def urls(markup):
    return [b.url for row in markup.inline_keyboard for b in row]


CP.api_client.public_config = lambda: CONFIG
CP.api_client.channel_question_of_the_day = lambda: QUESTION
CP.CHANNEL_CHAT_ID = "@ethio_student_helper"
CP.CHANNEL_FEATURE_DAYS = "tue,thu,sat"


def run_on(day: date, bot, **kw):
    CP.reminders.local_today = lambda tz=None: day.isoformat()
    return asyncio.run(CP.post_today(types.SimpleNamespace(bot=bot), **kw))


TUESDAY = date(2026, 11, 17)
WEDNESDAY = TUESDAY + timedelta(days=1)
assert TUESDAY.weekday() == 1

# ---- quiz every day, as an anonymous quiz poll with a tagged button
bot = FakeBot()
assert run_on(WEDNESDAY, bot) is None
chat, poll = bot.polls[0]
assert chat == "@ethio_student_helper" and poll["type"] == "quiz" and poll["is_anonymous"] is True
assert poll["correct_option_id"] == 1 and poll["options"][1] == "Mitochondrion" and poll["question"] == QUESTION["stem"]
assert len(poll["explanation"]) <= 200  # Telegram's limit
assert urls(poll["reply_markup"]) == ["https://app.example/?src=channel"] and "Biology" in poll["reply_markup"].inline_keyboard[0][0].text
assert bot.messages == []  # Wednesday is not a feature day

# ---- feature day: the quiz, then a feature post with app, bot and subscribe buttons
bot = FakeBot()
run_on(TUESDAY, bot)
chat, text, markup = bot.messages[0]
assert len(bot.polls) == 1 and chat == "@ethio_student_helper"
assert urls(markup) == ["https://app.example/?src=channel", "https://t.me/esh_bot?start=channel", "https://app.example/subscribe?src=channel"]
assert "300 ETB" in text and "{" not in text  # price filled in, no placeholder left
assert "300 ETB / year" in markup.inline_keyboard[1][0].text

# ---- every feature post comes round before any repeats, on any choice of days
seen = [CP.feature_index(TUESDAY + timedelta(days=7 * w + d), ("tue", "thu", "sat")) for w in range(5) for d in (0, 2, 4)]
assert sorted(set(seen[: len(CP.FEATURE_POSTS)])) == list(range(len(CP.FEATURE_POSTS))), seen
assert all(b == (a + 1) % len(CP.FEATURE_POSTS) for a, b in zip(seen, seen[1:])), seen
for i in range(len(CP.FEATURE_POSTS)):
    t = CP.feature_text(i, CONFIG)
    assert "{" not in t and len(t) < 4096, i
assert "50 ETB" in CP.feature_text(6, CONFIG)  # the referral post uses the configured reward

# ---- admin "post now" on a non-feature day still sends a feature post (the next day's)
bot = FakeBot()
assert run_on(WEDNESDAY, bot, force_feature=True) is None and len(bot.messages) == 1
assert bot.messages[0][1] == CP.feature_text(CP.feature_index(WEDNESDAY + timedelta(days=1), ("tue", "thu", "sat")), CONFIG)

# ---- refusals are reported, never raised
problem = run_on(TUESDAY, FakeBot(refuse=True))
assert problem and "admin of the channel" in problem, problem


def no_question():
    raise BackendError(404, "No question fits a channel quiz right now.")


CP.api_client.channel_question_of_the_day = no_question
bot = FakeBot()
problem = run_on(TUESDAY, bot)
assert bot.polls == [] and len(bot.messages) == 1 and "no exam question" in problem  # the feature post still goes out

# ---- settings parsing
assert CP.parse_days(" Tue, thursday,sat,tue, xyz") == ("tue", "thu", "sat")
assert CP.next_feature_day(WEDNESDAY, ()) is None
print("CHANNEL POSTS TESTS PASSED")
