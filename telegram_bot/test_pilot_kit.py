"""Tests for the pilot kit: saved logins, daily reminders, quick start, /logout.
Run from the project root (the folder that contains backend/ and telegram_bot/):
    python telegram_bot/test_pilot_kit.py
Needs python-telegram-bot[job-queue] and httpx installed (the bot's own requirements)."""

import asyncio
import base64
import json
import os
import stat
import sys
import tempfile
import time
import types
from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:ABC")
TMP = Path(tempfile.mkdtemp())
os.environ["BOT_DATA_DIR"] = str(TMP / "default")

from telegram import InlineKeyboardMarkup  # noqa: E402

from telegram_bot import api_client, reminders  # noqa: E402
from telegram_bot import store as S  # noqa: E402
from telegram_bot.api_client import BackendError  # noqa: E402
from telegram_bot.handlers import (  # noqa: E402
    auth_handler,
    practice_handler,
    reminder_handler,
)
from telegram_bot.practice_flow import PracticeSession  # noqa: E402

run = asyncio.run


def jwt(exp):
    b64 = (
        lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    )
    return f"{b64({'alg': 'HS256'})}.{b64({'sub': 'u', **({'exp': exp} if exp is not None else {})})}.sig"


FUTURE, PAST = time.time() + 7 * 86400, time.time() - 10

# ================= 1. the store =================
assert (
    S.token_expiry(jwt(1234567890)) == 1234567890.0
    and S.token_expiry("garbage") is None
    and S.token_expiry(jwt(None)) is None
)
assert (
    S.token_expired(jwt(PAST))
    and not S.token_expired(jwt(FUTURE))
    and not S.token_expired(jwt(None))
    and not S.token_expired("garbage")
)
assert S.token_expired(
    jwt(time.time() + 30)
)  # inside the 60 s safety margin counts as expired

path = TMP / "a" / "state.json"
st = S.Store(path)
st.set_token(1, jwt(FUTURE))
st.set_token(2, jwt(PAST))
st.set_reminder(1, 99, "18:00")
st.set_pref(1, 12, "chemistry")
st.mark_active(1, "2026-10-12")
assert (
    stat.S_IMODE(os.stat(path).st_mode) == 0o600
    and stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
)  # tokens: owner only
st2 = S.Store(path)  # "the bot restarted"
assert st2.get_token(1) == st.get_token(1) and st2.get_token(1) is not None
assert (
    st2.get_token(2) is None and "2" not in json.loads(path.read_text())["sessions"]
)  # expired token pruned and removed from the file
assert st2.get_reminder(1) == {
    "time": "18:00",
    "chat_id": 99,
} and st2.all_reminders() == {1: {"time": "18:00", "chat_id": 99}}
assert (
    st2.get_pref(1) == {"grade": 12, "subject": "chemistry"}
    and st2.active_on(1, "2026-10-12")
    and not st2.active_on(1, "2026-10-13")
    and not st2.active_on(5, "2026-10-12")
)
st2.drop_token(1)
st2.drop_reminder(1)
assert S.Store(path).get_token(1) is None and S.Store(path).get_reminder(1) is None
mtime = os.stat(path).st_mtime_ns
st2.set_pref(1, 12, "chemistry")
assert os.stat(path).st_mtime_ns == mtime  # unchanged pref: no disk write
path.write_text("{ this is not json")  # a corrupt file must not crash the bot
st3 = S.Store(path)
assert st3.get_token(1) is None and list(path.parent.glob("state.json.corrupt-*"))
st3.set_token(3, jwt(FUTURE))
assert S.Store(path).get_token(3)
assert not list(path.parent.glob(".state-*.tmp"))  # no temp files left behind

# ================= 2. api_client uses the saved login =================
S.set_store(S.Store(TMP / "b" / "state.json"))


class Resp:
    def __init__(self, code, body):
        self.status_code, self._b, self.text = code, body, json.dumps(body)

    def json(self):
        return self._b


import httpx

calls = []


def fake_post(url, json=None, headers=None, timeout=None):
    calls.append((url, headers))
    if url.endswith("/telegram-link"):
        return (
            Resp(200, {"access_token": jwt(FUTURE)})
            if json["password"] == "right"
            else Resp(401, {"detail": "Wrong password"})
        )
    return Resp(next_status["code"], {"detail": "x", "answer": "ok"})


next_status = {"code": 200}
real_post = httpx.post
httpx.post = fake_post
try:
    assert not api_client.is_logged_in(7)
    try:
        api_client.explain(7, 9, "chemistry", "q")
        raise SystemExit("should raise")
    except BackendError as e:
        assert e.status_code == 401
    try:
        api_client.link_account(7, "me", "wrong")
        raise SystemExit("should raise")
    except BackendError:
        pass
    assert not api_client.is_logged_in(7)
    api_client.link_account(7, "me", "right")
    assert api_client.is_logged_in(7)
    S.set_store(S.Store(TMP / "b" / "state.json"))  # bot restart
    assert api_client.is_logged_in(7), "login must survive a restart"
    assert api_client.explain(7, 9, "chemistry", "q")["answer"] == "ok" and calls[-1][
        1
    ]["Authorization"].startswith("Bearer ")
    next_status["code"] = 401  # backend says the token is dead (expired or revoked)
    try:
        api_client.explain(7, 9, "chemistry", "q")
        raise SystemExit("should raise")
    except BackendError as e:
        assert e.status_code == 401
    assert (
        not api_client.is_logged_in(7)
        and S.Store(TMP / "b" / "state.json").get_token(7) is None
    )  # forgotten in memory AND on disk
    next_status["code"] = 200
    api_client.link_account(7, "me", "right")
    api_client.logout(7)
    assert not api_client.is_logged_in(7)
finally:
    httpx.post = real_post

# ================= 3. reminders =================
for text, want in [
    ("18:00", dtime(18, 0)),
    ("6pm", dtime(18, 0)),
    ("6:30 pm", dtime(18, 30)),
    ("6:30PM", dtime(18, 30)),
    ("0630", dtime(6, 30)),
    ("06.30", dtime(6, 30)),
    ("7", dtime(7, 0)),
    ("12am", dtime(0, 0)),
    ("12pm", dtime(12, 0)),
    ("7:05am", dtime(7, 5)),
    ("23:59", dtime(23, 59)),
    ("630", dtime(6, 30)),
    ("  8pm ", dtime(20, 0)),
]:
    assert reminders.parse_time(text) == want, (text, reminders.parse_time(text))
for bad in [
    "",
    "abc",
    "25:00",
    "18:75",
    "13pm",
    "0pm",
    "6:3",
    "tomorrow",
    "18:00:00",
    None,
]:
    assert reminders.parse_time(bad) is None, bad
assert reminders.format_time(dtime(6, 5)) == "06:05"
tz = reminders.local_tz()
assert tz.utcoffset(datetime(2026, 10, 12)) == timedelta(
    hours=3
) and reminders.tz_label(tz)
assert datetime.now(tz).date().isoformat() == reminders.local_today(tz)


class FakeJob:
    def __init__(self, name):
        self.name, self.removed = name, False

    def schedule_removal(self):
        self.removed = True


class FakeJobQueue:
    def __init__(self):
        self.jobs = []

    def get_jobs_by_name(self, name):
        return [j for j in self.jobs if j.name == name and not j.removed]

    def run_daily(self, callback, time, name=None, chat_id=None, user_id=None, **kw):
        j = FakeJob(name)
        j.callback, j.time, j.chat_id, j.user_id = callback, time, chat_id, user_id
        self.jobs.append(j)
        return j


jq = FakeJobQueue()
reminders.schedule_reminder(jq, 5, 55, dtime(18, 0), tz)
live = jq.get_jobs_by_name("remind-5")
assert (
    len(live) == 1
    and live[0].time == dtime(18, 0, tzinfo=tz)
    and live[0].chat_id == 55
    and live[0].user_id == 5
    and live[0].callback is reminders.send_reminder
)
reminders.schedule_reminder(
    jq, 5, 55, dtime(7, 30), tz
)  # changing the time replaces the old job
live = jq.get_jobs_by_name("remind-5")
assert len(live) == 1 and live[0].time.hour == 7
reminders.cancel_reminder(jq, 5)
assert jq.get_jobs_by_name("remind-5") == []
reminders.cancel_reminder(None, 5)
store = S.Store(TMP / "c" / "state.json")
store.set_reminder(10, 100, "18:00")
store.set_reminder(11, 110, "6am")
store.set_reminder(12, 120, "nonsense")
jq = FakeJobQueue()
assert reminders.restore_all(jq, store, tz) == 2 and {j.user_id for j in jq.jobs} == {
    10,
    11,
}  # restored on start; the bad entry is skipped


# the daily job: skips active students, warns about a dead login, otherwise offers a Start button
class Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))


def job_ctx(uid, chat):
    return types.SimpleNamespace(
        job=types.SimpleNamespace(user_id=uid, chat_id=chat), bot=Bot()
    )


S.set_store(S.Store(TMP / "d" / "state.json"))
st = S.get_store()
st.set_token(20, jwt(FUTURE))
st.set_pref(20, 12, "information_technology")
c = job_ctx(20, 200)
run(reminders.send_reminder(c))
chat, text, markup = c.bot.sent[0]
assert (
    chat == 200
    and "Information Technology (Grade 12)" in text
    and "weakest units" in text
)
assert (
    isinstance(markup, InlineKeyboardMarkup)
    and markup.inline_keyboard[0][0].callback_data == "pd"
)
st.mark_active(20, reminders.local_today())
c = job_ctx(20, 200)
run(reminders.send_reminder(c))
assert c.bot.sent == []  # practised today: silence
c = job_ctx(21, 210)
run(reminders.send_reminder(c))
assert (
    "login has expired" in c.bot.sent[0][1] and c.bot.sent[0][2] is None
)  # not logged in
st.set_token(22, jwt(FUTURE))
c = job_ctx(22, 220)
run(reminders.send_reminder(c))
assert "choose a subject" in c.bot.sent[0][1]  # no preference yet

# a REAL job queue accepts the schedule and keeps the right local time
from telegram.ext import Application

app = Application.builder().token("123:ABC").build()
assert app.job_queue is not None
reminders.schedule_reminder(app.job_queue, 30, 300, dtime(18, 0), tz)
jobs = app.job_queue.get_jobs_by_name("remind-30")
assert len(jobs) == 1
reminders.schedule_reminder(app.job_queue, 30, 300, dtime(6, 30), tz)
assert len(app.job_queue.get_jobs_by_name("remind-30")) == 1


# ================= 4. /remind =================
class Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append(text)


def upd(uid=40, chat=400):
    return types.SimpleNamespace(
        effective_user=types.SimpleNamespace(id=uid),
        effective_chat=types.SimpleNamespace(id=chat),
        message=Msg(),
    )


def ctx(args, job_queue):
    return types.SimpleNamespace(
        args=args, user_data={}, application=types.SimpleNamespace(job_queue=job_queue)
    )


S.set_store(S.Store(TMP / "e" / "state.json"))
st = S.get_store()
u = upd()
run(reminder_handler.remind_command(u, ctx(["18:00"], FakeJobQueue())))
assert "/login" in u.message.sent[0] and st.get_reminder(40) is None  # login first
st.set_token(40, jwt(FUTURE))
jq = FakeJobQueue()
u = upd()
run(reminder_handler.remind_command(u, ctx([], jq)))
assert "no daily reminder" in u.message.sent[0] and "/remind 18:00" in u.message.sent[0]
u = upd()
run(
    reminder_handler.remind_command(u, ctx(["6:30", "pm"], jq))
)  # "6:30 pm" arrives as two words
assert (
    "18:30" in u.message.sent[0]
    and st.get_reminder(40) == {"time": "18:30", "chat_id": 400}
    and len(jq.get_jobs_by_name("remind-40")) == 1
)
u = upd()
run(reminder_handler.remind_command(u, ctx([], jq)))
assert "18:30" in u.message.sent[0]
u = upd()
run(reminder_handler.remind_command(u, ctx(["25:99"], jq)))
assert "couldn't read" in u.message.sent[0] and st.get_reminder(40)["time"] == "18:30"
u = upd()
run(reminder_handler.remind_command(u, ctx(["off"], jq)))
assert (
    "turned off" in u.message.sent[0]
    and st.get_reminder(40) is None
    and jq.get_jobs_by_name("remind-40") == []
)
u = upd()
run(reminder_handler.remind_command(u, ctx(["7am"], None)))
assert (
    "not available" in u.message.sent[0] and st.get_reminder(40) is None
)  # no job-queue package installed


# ================= 5. quick start (the reminder's button) =================
def question(i):
    return {
        "id": f"q{i}",
        "question": f"Question {i}: which statement is correct?",
        "options": ["a", "b", "c", "d"],
        "unit": "Unit 4: Periodic Classification",
        "difficulty": "easy",
    }


class FakeApi:
    def __init__(self, units, questions):
        self._units, self._q, self.calls = units, questions, []

    def is_logged_in(self, uid):
        return True

    def practice_units(self, uid, grade, subject):
        return {"units": self._units}

    def practice_next(self, uid, grade, subject, units=None, count=5):
        self.calls.append(units)
        return {"questions": self._q}

    def practice_subjects(self, uid, grade):
        return {"subjects": [{"subject": "chemistry", "questions": 5}]}

    def practice_answer(self, uid, qid, idx):
        return {
            "is_correct": True,
            "correct_index": idx,
            "explanation": "why",
            "supporting_quote": "q",
            "citation": {"textbook": "T", "unit": "U", "page": "1"},
        }


weak = [
    {"unit": "Unit 4: Periodic Classification", "questions": 9, "level": "weak"},
    {"unit": "Unit 1: Intro", "questions": 9, "level": "strong"},
]
api = FakeApi(weak, [question(1), question(2)])
s = PracticeSession(api, 1)
scr = s.quick_start(12, "chemistry")
assert (
    api.calls == [["Unit 4: Periodic Classification"]]
    and scr.text.startswith("Starting with your weakest units.")
    and "Question 1" in scr.text
)
assert [d for _, d in scr.buttons[0]] == ["pa|q1|0", "pa|q1|1", "pa|q1|2", "pa|q1|3"]
api = FakeApi([dict(weak[1])], [question(1)])
scr = PracticeSession(api, 1).quick_start(12, "chemistry")
assert api.calls == [None] and scr.text.startswith("A mix of questions")
scr = PracticeSession(FakeApi(weak, []), 1).quick_start(12, "chemistry")
assert "no new questions" in scr.text and scr.buttons[0][0][1] == "pm"


# ================= 6. the handler: button -> questions, preferences and activity remembered =================
class Query:
    def __init__(self, data, uid=50):
        self.data, self.from_user, self.answers, self.edits = (
            data,
            types.SimpleNamespace(id=uid),
            [],
            [],
        )

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


S.set_store(S.Store(TMP / "f" / "state.json"))
st = S.get_store()
practice_handler.api_client = fake = FakeApi(weak, [question(1), question(2)])
c = types.SimpleNamespace(user_data={})
q = Query("pd")
fake.is_logged_in = lambda uid: False
run(practice_handler.practice_callback(types.SimpleNamespace(callback_query=q), c))
assert q.answers[0][1] is True and "/login" in q.answers[0][0] and not q.edits
fake.is_logged_in = lambda uid: True
q = Query("pd")
run(
    practice_handler.practice_callback(types.SimpleNamespace(callback_query=q), c)
)  # no saved subject yet -> grade menu
assert "Which grade" in q.edits[0][0] and isinstance(
    q.edits[0][1], InlineKeyboardMarkup
)
for data in ("pg|12", "ps|0"):  # choosing a subject saves it
    q = Query(data)
    run(practice_handler.practice_callback(types.SimpleNamespace(callback_query=q), c))
assert st.get_pref(50) == {"grade": 12, "subject": "chemistry"} and not st.active_on(
    50, reminders.local_today()
)
q = Query("pu|all")
run(practice_handler.practice_callback(types.SimpleNamespace(callback_query=q), c))
assert "Question 1" in q.edits[0][0]
q = Query("pa|q1|1")
run(practice_handler.practice_callback(types.SimpleNamespace(callback_query=q), c))
assert st.active_on(50, reminders.local_today())  # answering counts as practice today
c2 = types.SimpleNamespace(user_data={})  # tomorrow's reminder, fresh session
q = Query("pd")
run(practice_handler.practice_callback(types.SimpleNamespace(callback_query=q), c2))
assert (
    q.answers == [(None, False)]
    and q.edits[0][0].startswith("Starting with your weakest units.")
    and "Question 1" in q.edits[0][0]
)
fake.practice_units = lambda uid, g, s_: (_ for _ in ()).throw(
    BackendError(400, "No questions for subject 'x'")
)  # saved subject vanished
q = Query("pd")
run(
    practice_handler.practice_callback(
        types.SimpleNamespace(callback_query=q), types.SimpleNamespace(user_data={})
    )
)
assert q.answers[0][1] is True and "didn't work" in q.answers[0][0] and not q.edits

# ================= 7. /logout =================
S.set_store(S.Store(TMP / "g" / "state.json"))
st = S.get_store()
st.set_token(60, jwt(FUTURE))
st.set_reminder(60, 600, "18:00")
jq = FakeJobQueue()
reminders.schedule_reminder(jq, 60, 600, dtime(18, 0), tz)
u = upd(60, 600)
run(auth_handler.logout_command(u, ctx([], jq)))
assert (
    "Logged out" in u.message.sent[0]
    and not api_client.is_logged_in(60)
    and st.get_reminder(60) is None
    and jq.get_jobs_by_name("remind-60") == []
)
u = upd(61, 610)
run(auth_handler.logout_command(u, ctx([], None)))
assert "Logged out" in u.message.sent[0]  # fine without a job queue / without a login
print("PILOT KIT TESTS PASSED (saved logins, reminders, quick start, /logout)")
