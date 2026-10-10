"""Tests for /practice and /progress with a fake backend (no Telegram, no network).
Run from the project root (the folder that contains backend/ and telegram_bot/):
    python telegram_bot/test_practice_flow.py
"""

import asyncio
import os
import sys
import types
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault(
    "TELEGRAM_BOT_TOKEN", "test-token"
)  # config.py insists on one at import time

from telegram_bot.practice_flow import (
    FlowError,
    PracticeSession,
    clip,
    pretty_subject,
)


def make_question(i):
    return {
        "id": str(uuid.uuid4()),
        "question": f"Question number {i}: which statement about atoms is correct?",
        "options": [f"option {i}-A", f"option {i}-B", f"option {i}-C", f"option {i}-D"],
        "unit": "Unit 4: Periodic Classification of Elements",
        "difficulty": "medium",
        "key": 1 if i % 2 == 0 else 2,
    }


class FakeApi:
    def __init__(self, batches):
        self.batches, self.next_calls, self.reports, self.answers = (
            list(batches),
            [],
            [],
            [],
        )
        self.keys = {q["id"]: q["key"] for b in batches for q in b}

    def practice_subjects(self, uid, grade):
        return (
            {
                "subjects": [
                    {"subject": "chemistry", "questions": 83},
                    {"subject": "information_technology", "questions": 12},
                ]
            }
            if grade == 9
            else {"subjects": []}
        )

    def practice_units(self, uid, grade, subject):
        return {
            "units": [
                {
                    "unit": "Unit 1: Chemistry and its Importance",
                    "questions": 20,
                    "attempts": 12,
                    "accuracy": 0.82,
                    "level": "strong",
                },
                {
                    "unit": "Unit 4: Periodic Classification of Elements",
                    "questions": 30,
                    "attempts": 11,
                    "accuracy": 0.45,
                    "level": "weak",
                },
            ]
        }

    def practice_next(self, uid, grade, subject, units=None, count=5):
        self.next_calls.append(
            {"grade": grade, "subject": subject, "units": units, "count": count}
        )
        batch = self.batches.pop(0) if self.batches else []
        return {
            "questions": [{k: v for k, v in q.items() if k != "key"} for q in batch]
        }

    def practice_answer(self, uid, qid, idx):
        self.answers.append((qid, idx))
        key = self.keys[qid]
        return {
            "is_correct": idx == key,
            "correct_index": key,
            "explanation": "Because the book says so, in one clear sentence.",
            "supporting_quote": "quote",
            "citation": {
                "textbook": "Chemistry Grade 9",
                "unit": "Unit 4: Periodic Classification of Elements",
                "page": "127",
            },
        }

    def practice_report(self, uid, qid, reason=None):
        self.reports.append(qid)
        return {"ok": True}

    def practice_progress(self, uid, grade, subject):
        if subject == "information_technology":
            return {
                "grade": grade,
                "subject": subject,
                "attempts": 0,
                "accuracy": None,
                "weakest_units": [],
                "units": [],
            }
        return {
            "grade": grade,
            "subject": subject,
            "attempts": 23,
            "accuracy": 0.7,
            "weakest_units": ["Unit 4: Periodic Classification of Elements"],
            "units": [
                {
                    "unit": "Unit 4: Periodic Classification of Elements",
                    "attempts": 11,
                    "correct": 5,
                    "accuracy": 0.46,
                    "level": "weak",
                },
                {
                    "unit": "Unit 1: Chemistry and its Importance",
                    "attempts": 12,
                    "correct": 11,
                    "accuracy": 0.86,
                    "level": "strong",
                },
            ],
        }


def all_buttons(screen):
    return [b for row in screen.buttons for b in row]


def check_limits(screen):
    assert len(screen.text) < 4000, len(screen.text)
    for label, data in all_buttons(screen):
        assert len(data.encode()) <= 64, data  # Telegram's limit for callback data
        assert label


# ---- helpers
assert (
    pretty_subject("information_technology") == "Information Technology"
    and clip("a  b   c", 10) == "a b c"
    and clip("x" * 30, 10).endswith("…")
    and len(clip("x" * 30, 10)) == 10
)

# ---- the full practice conversation
batches = [
    [make_question(i) for i in range(5)],
    [make_question(i) for i in range(5, 8)],
    [],
]
api = FakeApi(batches)
s = PracticeSession(api, 111, "practice")
scr = s.start()
check_limits(scr)
assert [d for _, d in all_buttons(scr)] == ["pg|9", "pg|10", "pg|11", "pg|12"]
scr = s.handle("pg|9")
check_limits(scr)
assert (
    [d for _, d in all_buttons(scr)] == ["ps|0", "ps|1", "pm"]
    and "Chemistry (83)" in scr.buttons[0][0][0]
    and "Information Technology (12)" in scr.buttons[1][0][0]
)
assert (
    "no practice questions for Grade 12" in s.handle("pg|12").text
    and s.handle("pg|12").text.count("/explain") == 1
)
s.handle("pg|9")
scr = s.handle("ps|0")
check_limits(scr)
datas = [d for _, d in all_buttons(scr)]
assert (
    datas[:2] == ["pu|all", "pu|weak"]
    and "pu|0" in datas
    and "pu|1" in datas
    and datas[-1] == "pg|9"
)  # 'weak' offered because a unit is weak
scr = s.handle("pu|weak")
check_limits(scr)
assert api.next_calls[-1] == {
    "grade": 9,
    "subject": "chemistry",
    "units": ["Unit 4: Periodic Classification of Elements"],
    "count": 5,
}
assert (
    "Question 1" in scr.text
    and "A) option 0-A" in scr.text
    and "D) option 0-D" in scr.text
    and "Chemistry · Grade 9" in scr.text
)
qid0 = s.current["id"]
assert (
    [d for _, d in scr.buttons[0]] == [f"pa|{qid0}|{i}" for i in range(4)]
    and scr.buttons[1][0][1] == f"pr|{qid0}"
    and scr.buttons[1][1][1] == "px"
)
# wrong answer (key is B = 1; we pick C = 2)
res = s.handle(f"pa|{qid0}|2")
check_limits(res)
assert (
    res.text.startswith("❌ Not quite. The correct answer is B.")
    and "B) option 0-B  ✅" in res.text
    and "C) option 0-C  ❌ (your answer)" in res.text
)
assert (
    "Why: Because the book says so" in res.text
    and "Book: Chemistry Grade 9, Unit 4: Periodic Classification of Elements, p.127"
    in res.text
)
assert (
    s.handle(f"pa|{qid0}|2") is None and len(api.answers) == 1
)  # a double tap is ignored and not counted twice
try:
    s.handle(f"pa|{uuid.uuid4()}|1")
    raise SystemExit("should raise")
except FlowError:
    pass
# correct answer on the next one (key for i=1 is C = 2)
scr = s.handle("pn")
assert "Question 2" in scr.text
res = s.handle(f"pa|{s.current['id']}|2")
assert res.text.startswith("✅ Correct!") and "(your answer)" not in res.text
assert (s.answered, s.correct) == (2, 1)
# answering without a current question, or a stale button, is refused
try:
    s.handle(f"pa|{qid0}|1")
except FlowError:
    pass
# keep going through the batch, then a second batch is fetched; the session never repeats a question
for _ in range(3):
    s.handle("pn")
    s.handle(f"pa|{s.current['id']}|1")
assert s.answered == 5 and len(api.next_calls) == 1
scr = s.handle("pn")
assert len(api.next_calls) == 2 and "Question 6" in scr.text
s.handle(f"pa|{s.current['id']}|1")
s.handle("pn")
s.handle(f"pa|{s.current['id']}|1")
s.handle("pn")
s.handle(f"pa|{s.current['id']}|1")
assert s.answered == 8
scr = s.handle("pn")  # third fetch is empty -> finished screen
assert (
    "answered every available question" in scr.text
    and "8 answered" in scr.text
    and ("ps|0" in [d for _, d in all_buttons(scr)])
)
stop = s.handle("px")
assert (
    "Session finished" in stop.text
    and "8 answered" in stop.text
    and "/progress" in stop.text
    and stop.buttons == []
)

# ---- report: the question is pulled and the student continues
api2 = FakeApi([[make_question(i) for i in range(3)], []])
s2 = PracticeSession(api2, 222)
s2.handle("pg|9")
s2.handle("ps|0")
s2.handle("pu|all")
assert api2.next_calls[-1]["units"] is None
bad = s2.current["id"]
scr = s2.handle(f"pr|{bad}")
assert (
    api2.reports == [bad]
    and s2.current is None
    and "taken out" in scr.text
    and scr.buttons[0][0][1] == "pn"
)
scr = s2.handle("pn")
assert (
    "Question 1" in scr.text and s2.current["id"] != bad
)  # counter did not move: nothing was answered
# one unit chosen by number
s3 = PracticeSession(FakeApi([[make_question(0)], []]), 333)
s3.handle("pg|9")
s3.handle("ps|0")
s3.handle("pu|0")
assert s3.api.next_calls[-1]["units"] == ["Unit 1: Chemistry and its Importance"]

# ---- progress mode
p = PracticeSession(FakeApi([]), 444, "progress")
assert p.start().text.startswith("Progress")
p.handle("pg|9")
scr = p.handle("ps|0")
check_limits(scr)
assert (
    "Answered 23 · 70% correct" in scr.text
    and "Needs work:" in scr.text
    and "• Unit 4: Periodic Classification of Elements" in scr.text
    and "weak, 11 answered" in scr.text
)
scr = p.handle("pg|9") and p.handle("ps|1")
assert "haven't answered any questions yet" in scr.text

# ---- expired / unknown buttons
for bad_data in ["zz", "ps|9", "pu|7", "pa|only-two"]:
    try:
        PracticeSession(FakeApi([]), 5).handle(bad_data)
        raise SystemExit(f"should have raised for {bad_data}")
    except (FlowError, ValueError):
        pass
try:
    PracticeSession(FakeApi([]), 5).handle("ps|0")
    raise SystemExit("should raise")
except FlowError:
    pass
print("PRACTICE FLOW TESTS PASSED")

# ---- Telegram glue (needs python-telegram-bot; skipped if it is not installed)
try:
    from telegram import InlineKeyboardMarkup

    from telegram_bot import api_client as real_client
    from telegram_bot.api_client import BackendError
    from telegram_bot.handlers import practice_handler as H
except ImportError as e:
    print("Telegram glue tests SKIPPED:", e)
    sys.exit(0)


class FakeClient(FakeApi):
    logged_in = True

    def is_logged_in(self, uid):
        return self.logged_in


class Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append((text, reply_markup))


class Query:
    def __init__(self, data, uid=7):
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


def run(coro):
    return asyncio.run(coro)


ctx = lambda: types.SimpleNamespace(user_data={})
H.api_client = fake = FakeClient([[make_question(i) for i in range(5)], []])

# not logged in -> asked to log in, nothing else
fake.logged_in = False
upd = types.SimpleNamespace(effective_user=types.SimpleNamespace(id=7), message=Msg())
c = ctx()
run(H.practice_command(upd, c))
assert upd.message.sent[0][0] == H.LOGIN_FIRST and H.SESSION_KEY not in c.user_data
fake.logged_in = True
run(H.practice_command(upd, c))
text, markup = upd.message.sent[-1]
assert isinstance(markup, InlineKeyboardMarkup) and [
    b.callback_data for b in markup.inline_keyboard[0]
] == ["pg|9", "pg|10", "pg|11", "pg|12"]
# a button press edits the message in place; the session survives between presses
q = Query("pg|9")
run(H.practice_callback(types.SimpleNamespace(callback_query=q), c))
assert (
    q.answers == [(None, False)]
    and "choose a subject" in q.edits[0][0]
    and isinstance(q.edits[0][1], InlineKeyboardMarkup)
)
q = Query("ps|0")
run(H.practice_callback(types.SimpleNamespace(callback_query=q), c))
assert "which unit" in q.edits[0][0]
# no session (bot restarted) -> a pop-up, not a crash
q = Query("ps|0")
run(H.practice_callback(types.SimpleNamespace(callback_query=q), ctx()))
assert q.answers[0][1] is True and "expired" in q.answers[0][0] and not q.edits
# stale button -> pop-up
q = Query("zz")
run(H.practice_callback(types.SimpleNamespace(callback_query=q), c))
assert q.answers[0][1] is True and "expired" in q.answers[0][0]
# backend errors become friendly pop-ups
for code, word in [
    (401, "/login"),
    (503, "busy"),
    (500, "went wrong"),
    (400, "That didn't work"),
]:

    def boom(uid, grade, _c=code):
        raise BackendError(_c, "detail")

    fake.practice_subjects = boom
    q = Query("pg|9")
    run(H.practice_callback(types.SimpleNamespace(callback_query=q), c))
    assert q.answers[0][1] is True and word in q.answers[0][0], (code, q.answers)
# Telegram's "message is not modified" is not an error
from telegram.error import BadRequest


class Same(Query):
    async def edit_message_text(self, text, reply_markup=None):
        raise BadRequest("Message is not modified")


fake.practice_subjects = FakeApi.practice_subjects.__get__(fake)
q = Same("pg|9")
run(H.practice_callback(types.SimpleNamespace(callback_query=q), c))
print("TELEGRAM GLUE TESTS PASSED")
