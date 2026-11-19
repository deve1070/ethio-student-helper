"""The ESSLCE feedback screen's "why did my choice look right" note (esslce_flow.py), with a fake API.
Run from the repo root:   backend/venv/bin/python telegram_bot/test_esslce_why_wrong.py"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ["BOT_DATA_DIR"] = tempfile.mkdtemp()

from telegram_bot.esslce_flow import EsslceSession  # noqa: E402
from telegram_bot.practice_flow import FlowError  # noqa: E402

NOTE = {"chosen_index": 0, "tempting": "Both are noble gases.", "wrong": "Argon is in period 3, not period 2."}


class FakeApi:
    calls = 0

    def esslce_why_wrong(self, uid, qid, idx):
        FakeApi.calls += 1
        return {**NOTE, "chosen_index": idx}


q = {"id": 41, "stem": "Which noble gas is in period 2?", "options": ["Argon", "Neon", "Helium", "Krypton"]}
wrong = {"is_correct": False, "correct_index": 1, "explanation": "Neon has two shells.", "supporting_quote": None,
         "explanation_image_base64": None, "why_wrong": None}

s = EsslceSession(FakeApi(), 7)
scr = s._feedback_screen(q, 0, wrong)
assert scr.buttons[0] == [("🤔 Why did A look right?", "ew|41|0")], scr.buttons
why = s.handle("ew|41|0")
assert why.text.startswith(scr.text) and "🤔 Why A looked right: Both are noble gases.\nWhy it's wrong: Argon is in period 3" in why.text, why.text
assert why.buttons == scr.buttons[1:] and why.image_base64 is None  # text only: the photos were already sent
try:
    s.handle("ew|41|0")
    raise SystemExit("a second tap should be refused")
except FlowError:
    pass

stored = s._feedback_screen(q, 2, {**wrong, "why_wrong": {**NOTE, "chosen_index": 2}})
assert "🤔 Why C looked right:" in stored.text and "ew|" not in str(stored.buttons) and FakeApi.calls == 1

right = s._feedback_screen(q, 1, {**wrong, "is_correct": True})
assert "ew|" not in str(right.buttons) and "🤔" not in right.text
print("ESSLCE WHY-WRONG TESTS PASSED")
