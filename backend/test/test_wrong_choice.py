"""explanations/wrong_choice.py with a fake LLM and a stand-in question row: reply checking, storage,
reuse of stored notes, and notes being dropped when the question is re-keyed.
Run from backend/:   python test/test_wrong_choice.py"""

import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import explanations.wrong_choice as W  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("PASS " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls, self.prompts = reply, 0, []

    def chat(self, messages):
        self.calls += 1
        self.prompts.append(messages[0]["content"])
        return {"choices": [{"message": {"content": self.reply}}]}


class FakeDB:
    commits = 0

    def commit(self):
        FakeDB.commits += 1


GOOD = json.dumps({
    "A": {"tempting": "It mixes up mitosis with meiosis.", "wrong": "Mitosis keeps the chromosome number."},
    "B": {"tempting": "Gametes are mentioned in the question.", "wrong": "Gametes are made by meiosis, not repaired by it."},
    "D": {"tempting": "Both divisions copy DNA first.", "wrong": "Only meiosis halves the number."},
})

row = SimpleNamespace(options=["mitosis", "fertilization", "meiosis", "budding"], answer_index=2, wrong_option_notes=None)
STEM = "Which division halves the chromosome number?"
db = FakeDB()

# ---- generated once, for all wrong options --------------------------------------------------------------
llm = FakeLLM("Here you go:\n" + GOOD)
note = W.get_or_create_note(db, llm, row, STEM, 1, W.context_block([("Explanation of the correct answer", "Meiosis halves it."), ("Source", None)]))
check("note for the picked option", note == {"tempting": "Gametes are mentioned in the question.", "wrong": "Gametes are made by meiosis, not repaired by it."})
check("stored with a fingerprint and four entries, none at the answer",
      row.wrong_option_notes["fingerprint"] == W.fingerprint(STEM, row.options, 2)
      and len(row.wrong_option_notes["notes"]) == 4 and row.wrong_option_notes["notes"][2] is None)
check("committed", FakeDB.commits == 1)
prompt = llm.prompts[0]
check("prompt names the correct answer", "Correct answer: C) meiosis" in prompt)
check("prompt carries given context and leaves out empty parts", "Meiosis halves it." in prompt and "Source:" not in prompt)
check("prompt asks for exactly the wrong letters", '"A"' in prompt and '"B"' in prompt and '"D"' in prompt and '"C": {' not in prompt)

# ---- reused for another wrong option, no new call -------------------------------------------------------
note_d = W.get_or_create_note(db, llm, row, STEM, 3)
check("other option served from storage", llm.calls == 1 and note_d["wrong"] == "Only meiosis halves the number.")
check("note_for reads storage only", W.note_for(row, STEM, 0)["tempting"] == "It mixes up mitosis with meiosis.")
check("no note for the correct option", W.note_for(row, STEM, 2) is None and W.get_or_create_note(db, llm, row, STEM, 2) is None)
check("out-of-range option refused", W.get_or_create_note(db, llm, row, STEM, 7) is None and llm.calls == 1)

# ---- re-keyed or edited question: stored notes are not shown -------------------------------------------
row.answer_index = 1
check("re-keyed question: old notes ignored", W.note_for(row, STEM, 2) is None)
row.answer_index = 2
row.options = ["mitosis", "fertilisation", "meiosis", "budding"]
check("edited option text: old notes ignored", W.note_for(row, STEM, 1) is None)
row.options = ["mitosis", "fertilization", "meiosis", "budding"]
check("same question again: notes valid", W.note_for(row, STEM, 1) is not None)

# ---- unusable replies are not stored --------------------------------------------------------------------
fresh = SimpleNamespace(options=list(row.options), answer_index=2, wrong_option_notes=None)
missing = json.loads(GOOD)
del missing["D"]
blank = json.loads(GOOD)
blank["A"]["wrong"] = "  "
for name, reply in [
    ("not JSON", "sorry, I cannot help"),
    ("one wrong option missing", json.dumps(missing)),
    ("an empty part", json.dumps(blank)),
]:
    check(f"{name}: nothing stored", W.get_or_create_note(db, FakeLLM(reply), fresh, STEM, 0) is None and fresh.wrong_option_notes is None)

long = json.loads(GOOD)
long["A"]["wrong"] = "word " * 200
notes = W.parse_notes(json.dumps(long), 4, 2)
check("an over-long part is cut at a word", len(notes[0]["wrong"]) <= W.MAX_NOTE_CHARS and notes[0]["wrong"].endswith("…"))

check("response model", W.as_response(note, 1).model_dump() == {"chosen_index": 1, **note} and W.as_response(None, 1) is None)

print(f"\n{failures} failure(s)")
sys.exit(1 if failures else 0)
