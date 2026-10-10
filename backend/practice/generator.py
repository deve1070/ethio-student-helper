"""
Generate exam-style multiple-choice questions from a textbook passage, keeping
only the ones that survive every check. The language model is passed in
(`llm.chat(messages=[...])`), so this is testable with a fake.

Flow for one passage:
  1. GENERATE   ask for n questions as JSON, each with a supporting quote
  2. VALIDATE   schema + quote-in-passage + banned patterns + duplicates
  3. BLIND SOLVE a second call answers each question from the passage ALONE,
                 without seeing the key or the quote; if it picks a different
                 option (or says the passage can't answer), the question is
                 wrong or ambiguous and is dropped
  4. SHUFFLE    options are shuffled deterministically
"""

import json
import logging
from collections import Counter

from practice.validate import (
    VALID_DIFFICULTY,
    check_question,
    content_hash,
    dup_key,
    is_duplicate,
    normalize,
    repair_stem,
    shuffle_options,
    snap_quote,
)

logger = logging.getLogger(__name__)

GENERATE_PROMPT = """You write multiple-choice practice questions for school students preparing for exams.
Use ONLY the passage below. Do not use outside knowledge.

Write {n} questions. Rules:
- Each question has exactly 4 options and exactly ONE correct option.
- Wrong options must be plausible (typical misunderstandings), not silly, and similar in length to the right one.
- Each question must make sense on its own, as if it were printed in a national exam with no reading beside it.
  NEVER use the words passage, text, excerpt, paragraph, context, reading, "above" or "provided" in the question, the options or the explanation.
  BAD: "According to the passage, what is chemistry?"   GOOD: "What is chemistry?"
  Do not write "which of the following is NOT mentioned" questions: they cannot be answered without the reading.
- Do not use "all of the above", "none of the above" or "both A and B".
- Ask about definitions, relationships, causes, comparisons and reasoning that the passage states or directly supports. Do NOT ask for calculations.
- Mix difficulty: "easy" = recall a stated fact, "medium" = understand or compare, "hard" = apply or infer (must still follow from the passage).
- "supporting_quote" must be copied character for character from the passage (6 to 40 words): do not shorten, reword or correct it. It must prove the correct option.
- "explanation" is 1 to 2 sentences saying why the correct option is right.

Reply with a JSON array only, no other text. Each item:
{{"question": "...", "options": ["...", "...", "...", "..."], "answer_index": 0, "explanation": "...", "supporting_quote": "...", "difficulty": "easy"}}

PASSAGE:
{passage}
"""

SOLVE_PROMPT = """Answer each multiple-choice question using ONLY the passage below.
For each question reply with the number (0-3) of the correct option. If the passage does not contain
enough information to answer a question with certainty, reply -1 for it.
Reply with a JSON array of integers only, one per question, in order.

PASSAGE:
{passage}

QUESTIONS:
{questions}
"""


def _ask(llm, prompt: str) -> str:
    response = llm.chat(messages=[{"role": "user", "content": prompt}])
    return (response["choices"][0]["message"]["content"] or "").strip()


def parse_json_array(raw: str):
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def blind_solve(llm, passage: str, questions: list[dict]) -> list[int | None]:
    """Answers chosen by a second call that sees no keys. None = unusable reply."""
    listing = "\n\n".join(
        f"{i + 1}. {q['question']}\n"
        + "\n".join(f"   {j}) {o}" for j, o in enumerate(q["options"]))
        for i, q in enumerate(questions)
    )
    data = parse_json_array(
        _ask(llm, SOLVE_PROMPT.format(passage=passage, questions=listing))
    )
    if data is None or len(data) != len(questions):
        return [None] * len(questions)
    return [
        a if isinstance(a, int) and not isinstance(a, bool) and -1 <= a <= 3 else None
        for a in data
    ]


def generate_for_passage(
    gen_llm,
    solve_llm,
    passage: str,
    n: int = 3,
    existing=(),
    rejected_log: list | None = None,
):
    """existing: dup_key(...) tuples of questions we already have.
    rejected_log: if given, every rejected question is appended as {"reason", "question"}
    so you can read what is being thrown away.
    Returns (accepted_questions, Counter of rejection reasons)."""

    def reject(reason: str, q=None):
        rejected[reason] += 1
        if rejected_log is not None:
            rejected_log.append(
                {
                    "reason": reason,
                    "question": (q or {}).get("question")
                    if isinstance(q, dict)
                    else None,
                }
            )

    rejected: Counter = Counter()
    raw = parse_json_array(_ask(gen_llm, GENERATE_PROMPT.format(n=n, passage=passage)))
    if raw is None:
        reject("generator reply was not a JSON array")
        return [], rejected

    seen = list(existing)
    candidates = []
    for q in raw[: n + 2]:
        if isinstance(q, dict):
            q["question"] = repair_stem(
                q.get("question")
            )  # drop a leading/trailing "according to the passage"
            quote = q.get("supporting_quote")
            if (
                isinstance(quote, str)
                and len(quote.split()) >= 4
                and normalize(quote) not in normalize(passage)
            ):
                snapped = snap_quote(
                    quote, passage
                )  # a reworded quote -> the words as printed in the book
                if snapped:
                    q["supporting_quote"] = snapped
        problems = check_question(q, passage)
        if problems:
            reject(problems[0], q)
            continue
        if is_duplicate(q["question"], q["options"][q["answer_index"]], seen):
            reject("duplicate of an existing question", q)
            continue
        seen.append(dup_key(q["question"], q["options"], q["answer_index"]))
        candidates.append(q)
    if not candidates:
        return [], rejected

    answers = blind_solve(solve_llm, passage, candidates)
    accepted = []
    for q, solver_answer in zip(candidates, answers):
        if solver_answer is None:
            reject("blind solver reply unusable", q)
        elif solver_answer == -1:
            reject("blind solver: passage cannot answer it", q)
        elif solver_answer != q["answer_index"]:
            reject("blind solver disagrees with the answer key", q)
        else:
            h = content_hash(q["question"], q["options"])
            options, idx = shuffle_options(q["options"], q["answer_index"], h)
            difficulty = (
                q.get("difficulty")
                if q.get("difficulty") in VALID_DIFFICULTY
                else "medium"
            )
            accepted.append(
                {
                    "question": q["question"].strip(),
                    "options": [o.strip() for o in options],
                    "answer_index": idx,
                    "explanation": q["explanation"].strip(),
                    "supporting_quote": q["supporting_quote"].strip(),
                    "difficulty": difficulty,
                    "content_hash": h,
                }
            )
    return accepted, rejected
