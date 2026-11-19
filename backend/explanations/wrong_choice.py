"""
Why a wrong option looked right, and what is wrong with it.

A student who picked B learns little from "C is correct because...": the useful part is the
misunderstanding that made B attractive. One LLM call writes a short note for each of the three
wrong options of a question at once, and the notes are stored on the question row itself
(QuizQuestion.wrong_option_notes, EsslceQuestion.wrong_option_notes), so every later student who
picks any wrong option of that question gets the note without another call.

Stored shape:
    {"fingerprint": "<sha256 of stem, options and answer_index>",
     "notes": [null | {"tempting": str, "wrong": str}, ...]}   # four entries, null at the answer

The fingerprint is checked on every read. When a reviewer re-keys a question or edits its options,
the stored notes no longer match and are treated as missing, so a note written for the old key is
never shown against the new one.

Entry points:
    note_for(row, stem, chosen_index)                     the cached note, or None (no LLM call)
    generate_notes(llm, stem, options, answer_index,      all three notes from one LLM call, not stored;
                   context) + store_notes(row, stem, n)   used by scripts/prefill_wrong_option_notes.py
    get_or_create_note(db, llm, row, stem, chosen_index,  the note, generating all three on a miss;
                       context)                           None if the model's reply was unusable
"""

import hashlib
import json
import re

from llm.client import LLMClient, parse_json_object
from pydantic import BaseModel

LETTERS = "ABCD"
MAX_NOTE_CHARS = 450  # per field; the reply is read on a phone, under the main explanation

PROMPT = """A student answered this multiple-choice question and picked a wrong option. For EACH wrong \
option, write two short parts:
- "tempting": why a student would pick it - the specific misunderstanding, confusion or slip that leads \
there. Be concrete ("it mixes up mitosis with meiosis"), not generic ("it sounds plausible").
- "wrong": what is actually wrong with it, in one or two sentences.

Question: {stem}
Options:
{options}
Correct answer: {correct_letter}) {correct}
{context}
Rules:
- The correct answer above is settled. Never suggest that a wrong option is also right, or that the \
correct answer is doubtful.
- Use the explanation and source text above when they are given. Do not add facts you are not sure of; \
if you cannot tell why someone would choose an option, say what it gets wrong instead of inventing a reason.
- Refer to options by their LETTER. Write plain text only: no LaTeX and no backslashes. Write a formula the \
way you would type it, e.g. d = 1/2 × a × t².
- Each part is at most two sentences.
{calculation_rules}
Reply with ONLY a JSON object with one entry per wrong option, keyed by its letter:
{example}"""


CALCULATION_RULES = """- This is a calculation question. When "tempting" names a slip (a forgotten 1/2, a unit not \
converted, a sign error), also give "slip_code": a short Python script, using only math and fractions, that \
follows exactly that slip with the question's own numbers and prints ONLY the resulting number on its last \
line, written like the option's number without its unit (e.g. 7/3, not 2.333). The slip is checked by running \
this code. If no single slip gives that option's value, set "slip_code" to null and do not describe a slip; \
say that the value does not follow from the given numbers.
"""

# shown instead of a slip the model claimed but whose code did not give the option's value
UNCHECKED_SLIP = "No single common slip that we could check leads to this value."


def fingerprint(stem: str, options: list, answer_index: int) -> str:
    payload = json.dumps([stem, list(options or []), answer_index], ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def stored_notes(row, stem: str) -> list | None:
    stored = row.wrong_option_notes
    if not isinstance(stored, dict):
        return None
    if stored.get("fingerprint") != fingerprint(stem, row.options, row.answer_index):
        return None  # written for an older key or older options
    notes = stored.get("notes")
    return notes if isinstance(notes, list) and len(notes) == len(row.options or []) else None


def note_for(row, stem: str, chosen_index: int) -> dict | None:
    """The stored note for one wrong option, or None. Never calls the LLM."""
    if chosen_index == row.answer_index:
        return None
    notes = stored_notes(row, stem)
    if notes is None or not 0 <= chosen_index < len(notes):
        return None
    return notes[chosen_index]


def _clean(value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if len(text) > MAX_NOTE_CHARS:
        text = text[: MAX_NOTE_CHARS - 1].rsplit(" ", 1)[0] + "…"
    return text


_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?(?:/\d+)?")


def slip_gives_option(code, option_text: str) -> bool:
    """Run the slip's code and compare its printed value with the option's printed number. Units and
    other words in the option are ignored: "100 m" matches a printed 100."""
    from exams.store import _results_match, run_verification_code

    if not isinstance(code, str) or not code.strip():
        return False
    computed = run_verification_code(code)
    if computed is None:
        return False
    if _results_match(computed, option_text):
        return True
    m = _NUMBER.search(option_text)
    if m is None:
        return False
    try:
        from fractions import Fraction

        return abs(float(Fraction(computed)) - float(Fraction(m.group()))) <= 1e-6 * max(1.0, abs(float(Fraction(m.group()))))
    except (ValueError, ZeroDivisionError):
        return _results_match(computed, m.group())


def parse_notes(raw: str, n_options: int, answer_index: int, options: list | None = None) -> list | None:
    """The model's reply as the stored notes list, or None unless every wrong option has both parts.
    With `options` (a calculation question), a slip whose code is missing or does not give that
    option's value is replaced by UNCHECKED_SLIP, so an invented slip is never shown."""
    data = parse_json_object(raw)
    if not data:
        return None
    notes: list = [None] * n_options
    for i in range(n_options):
        if i == answer_index:
            continue
        entry = data.get(LETTERS[i])
        if not isinstance(entry, dict):
            return None
        tempting, wrong = _clean(entry.get("tempting")), _clean(entry.get("wrong"))
        if not tempting or not wrong:
            return None
        if options is not None and not slip_gives_option(entry.get("slip_code"), options[i]):
            tempting = UNCHECKED_SLIP
        notes[i] = {"tempting": tempting, "wrong": wrong}
    return notes


def generate_notes(
    llm, stem: str, options: list, answer_index: int, context: str = "", calculation: bool = False
) -> list | None:
    wrong_letters = [LETTERS[i] for i in range(len(options)) if i != answer_index]
    entry = {"tempting": "...", "wrong": "...", **({"slip_code": "... or null"} if calculation else {})}
    example = json.dumps({L: entry for L in wrong_letters})
    prompt = PROMPT.format(
        stem=stem,
        options="\n".join(f"{L}) {opt}" for L, opt in zip(LETTERS, options)),
        correct_letter=LETTERS[answer_index],
        correct=options[answer_index],
        context=context,
        calculation_rules=CALCULATION_RULES if calculation else "",
        example=example,
    )
    raw = (llm.chat(messages=[{"role": "user", "content": prompt}])["choices"][0]["message"]["content"] or "").strip()
    return parse_notes(raw, len(options), answer_index, options if calculation else None)


class WrongChoiceNote(BaseModel):
    """What /answer, /mistakes and /why-wrong return for the option the student picked."""

    chosen_index: int
    tempting: str
    wrong: str


def as_response(note: dict | None, chosen_index: int) -> WrongChoiceNote | None:
    return WrongChoiceNote(chosen_index=chosen_index, **note) if note else None


def context_block(parts: list[tuple[str, str | None]]) -> str:
    """Labelled background lines for the prompt; empty values are left out."""
    lines = [f"{label}: {text}" for label, text in parts if text]
    return ("\n" + "\n".join(lines) + "\n") if lines else ""


PASSAGE_CONTEXT_CHARS = 4000  # a reading passage is the only source for its questions; long ones are cut


def practice_context(q) -> str:
    """Background for a textbook practice question (db/models_practice.QuizQuestion)."""
    return context_block([
        ("Explanation of the correct answer", q.explanation),
        ("Textbook sentence that proves it", q.supporting_quote),
    ])


def esslce_context(q) -> str:
    """Background for a past-exam question (exams/models.EsslceQuestion)."""
    passage = q.passage.text[:PASSAGE_CONTEXT_CHARS] if q.passage is not None else None
    return context_block([
        ("Instructions for this part of the exam", q.section),
        ("Reading passage the question is about", passage),
        ("Explanation of the correct answer", q.explanation),
        ("Source text that supports it", q.supporting_quote),
    ])


def note_llm() -> LLMClient:
    # the student is waiting on this, but it is an extra under the main explanation: a short retry
    # budget, so a busy provider gives "not available" in seconds instead of minutes
    return LLMClient(temperature=0, max_tokens=1500, retry_attempts=2, retry_max_wait=10)


def store_notes(row, stem: str, notes: list) -> None:
    row.wrong_option_notes = {"fingerprint": fingerprint(stem, row.options, row.answer_index), "notes": notes}


def get_or_create_note(
    db, llm, row, stem: str, chosen_index: int, context: str = "", calculation: bool = False
) -> dict | None:
    """The note for `chosen_index`, generating and storing notes for all wrong options on a miss."""
    if chosen_index == row.answer_index or not 0 <= chosen_index < len(row.options or []):
        return None
    cached = note_for(row, stem, chosen_index)
    if cached is not None:
        return cached
    notes = generate_notes(llm, stem, list(row.options), row.answer_index, context, calculation)
    if notes is None:
        return None
    store_notes(row, stem, notes)
    db.commit()
    return notes[chosen_index]
