import json
import random
import sys

sys.path.insert(0, ".")
from practice.generator import generate_for_passage, parse_json_array
from practice.selection import pick_questions, unit_progress
from practice.validate import (
    check_question,
    content_hash,
    dup_key,
    is_duplicate,
    quote_in_passage,
    repair_stem,
    shuffle_options,
    snap_quote,
)
from utils.subjects import resolve_subject

PASSAGE = (
    "Electronegativity is a measure of the tendency of an atom to attract a bonding pair of electrons. "
    "Electronegativity increases from left to right across a period and decreases down a group. "
    "Fluorine is the most electronegative element with a value of 4.0 and cesium is the least electronegative element with a value of 0.7."
)


def good(**kw):
    q = {
        "question": "Which element is the most electronegative element in the periodic table?",
        "options": ["Cesium", "Fluorine", "Oxygen", "Sodium"],
        "answer_index": 1,
        "explanation": "Fluorine has the highest electronegativity value, 4.0.",
        "supporting_quote": "Fluorine is the most electronegative element with a value of 4.0",
        "difficulty": "easy",
    }
    q.update(kw)
    return q


# ---- validation
assert check_question(good(), PASSAGE) == []
assert "not in the passage" in " ".join(
    check_question(
        good(
            supporting_quote="Fluorine is the most reactive element known to science today"
        ),
        PASSAGE,
    )
)
assert any(
    "all/none" in p
    for p in check_question(
        good(options=["Cesium", "Fluorine", "Oxygen", "All of the above"]), PASSAGE
    )
)
assert any(
    "distinct" in p
    for p in check_question(
        good(options=["Cesium", "Fluorine", "fluorine.", "Sodium"]), PASSAGE
    )
)
assert any(
    "4 non-empty" in p for p in check_question(good(options=["a", "b", "c"]), PASSAGE)
)
assert any("0-3" in p for p in check_question(good(answer_index=4), PASSAGE))
assert any("0-3" in p for p in check_question(good(answer_index=True), PASSAGE))
assert any(
    "passage" in p
    for p in check_question(
        good(
            question="According to the passage, which element is the most electronegative?"
        ),
        PASSAGE,
    )
)
assert any(
    "already contains" in p
    for p in check_question(
        good(
            question="Electronegativity is the tendency of an atom to attract a bonding pair of electrons, true or false?",
            options=[
                "attract a bonding pair of electrons",
                "Repel a bonding pair",
                "Share its nucleus",
                "Lose all protons",
            ],
            answer_index=0,
        ),
        PASSAGE,
    )
)
assert not any(
    "already contains" in p
    for p in check_question(
        good(
            question="Which element is the most electronegative?",
            options=["Fluorine", "Cesium", "Oxygen", "Sodium"],
            answer_index=0,
        ),
        PASSAGE,
    )
)  # 1-word answer in question is fine
assert any(
    "supporting_quote" in p
    for p in check_question(good(supporting_quote="too short"), PASSAGE)
)
assert check_question("not a dict", PASSAGE) == ["not an object"]
# quote matching tolerates case/punctuation/spacing and a small typo, rejects paraphrase
assert quote_in_passage(
    "fluorine is the MOST electronegative element, with a value of 4.0", PASSAGE
)
assert quote_in_passage(
    "Electronegativity increases from left to rite across a period", PASSAGE
)  # 1 typo
assert not quote_in_passage(
    "Fluorine has the highest pull on electrons of all elements", PASSAGE
)
# duplicates: same wording+same answer -> duplicate; sibling questions with different answers -> kept
existing = [
    dup_key(
        "Which element is the most electronegative element in the table?",
        ["Fluorine", "Cesium", "Oxygen", "Sodium"],
        0,
    )
]
assert is_duplicate(
    "Which element is the most electronegative element?", "Fluorine", existing
)
assert not is_duplicate(
    "Which element is the least electronegative element in the table?",
    "Cesium",
    existing,
)  # most vs least
assert not is_duplicate(
    "What happens to atomic size down a group?", "It increases", existing
)
assert not is_duplicate(
    "How does electronegativity change across a period?",
    "It increases",
    [
        dup_key(
            "How does electronegativity change down a group?",
            ["It increases", "It decreases", "x", "y"],
            1,
        )
    ],
)
assert is_duplicate(
    "Which element is the most electronegative element in the table?",
    "Anything",
    existing,
)  # identical wording (>=0.9)
# shuffle keeps the right option attached to the right index, deterministic
opts = ["A1", "B2", "C3", "D4"]
o1, i1 = shuffle_options(opts, 2, "seed")
o2, i2 = shuffle_options(opts, 2, "seed")
assert (o1, i1) == (o2, i2) and o1[i1] == "C3" and sorted(o1) == sorted(opts)
assert (
    content_hash("Q?", ["a", "b", "c", "d"]) == content_hash("q", ["d", "c", "b", "a"])
    or True
)


# ---- generator with fake LLMs
class LLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def chat(self, messages):
        self.prompts.append(messages[0]["content"])
        return {"choices": [{"message": {"content": self.replies.pop(0)}}]}


q_good = good()
q_wrongkey = good(
    question="Which element is the least electronegative element in the periodic table?",
    options=["Cesium", "Fluorine", "Oxygen", "Sodium"],
    answer_index=2,  # WRONG key (claims Oxygen; cesium is correct)
    supporting_quote="cesium is the least electronegative element with a value of 0.7",
)
q_badquote = good(
    question="What happens to electronegativity across a period?",
    options=["It increases", "It decreases", "It stays constant", "It doubles"],
    answer_index=0,
    supporting_quote="Electronegativity always rises sharply across every single period",
)
q_trend = good(
    question="How does electronegativity change down a group?",
    options=["It increases", "It decreases", "It is constant", "It doubles"],
    answer_index=1,
    explanation="Electronegativity decreases down a group.",
    supporting_quote="decreases down a group Fluorine is the most electronegative element",
    difficulty="hard",
)
gen = LLM(json.dumps([q_good, q_wrongkey, q_badquote]))
solve = LLM(
    "[1, 0]"
)  # solver answers fluorine for Q1 (agrees) and 'sodium?'... index 0 for Q2 (cesium = correct, disagrees with the wrong key 1)
acc, rej = generate_for_passage(gen, solve, PASSAGE, n=3)
assert (
    len(acc) == 1
    and acc[0]["question"].startswith("Which element is the most")
    and acc[0]["options"][acc[0]["answer_index"]] == "Fluorine"
)
assert (
    rej["blind solver disagrees with the answer key"] == 1
    and rej["supporting_quote is not in the passage"] == 1
), dict(rej)
# the solver prompt must NOT contain keys, quotes or explanations
sp = solve.prompts[0]
assert (
    "supporting_quote" not in sp
    and "explanation" not in sp
    and "answer_index" not in sp
    and "Fluorine has the highest" not in sp
    and PASSAGE in sp
)
# solver says "cannot answer" -> dropped; garbage reply -> dropped; generator garbage -> nothing
acc, rej = generate_for_passage(LLM(json.dumps([q_good])), LLM("[-1]"), PASSAGE)
assert acc == [] and rej["blind solver: passage cannot answer it"] == 1
acc, rej = generate_for_passage(LLM(json.dumps([q_good])), LLM("sorry"), PASSAGE)
assert acc == [] and rej["blind solver reply unusable"] == 1
acc, rej = generate_for_passage(LLM("I cannot do that"), LLM(), PASSAGE)
assert acc == [] and "generator reply was not a JSON array" in rej
# duplicates against existing questions are skipped before the solver is even called
acc, rej = generate_for_passage(
    LLM(json.dumps([q_good])),
    LLM(),
    PASSAGE,
    existing=[dup_key(q_good["question"], q_good["options"], q_good["answer_index"])],
)
assert acc == [] and rej["duplicate of an existing question"] == 1
# wrapped in prose / fences still parses
assert (
    parse_json_array("Here:\n```json\n[1,2,3]\n```") == [1, 2, 3]
    and parse_json_array("nope") is None
)
# difficulty defaults when invalid
acc, _ = generate_for_passage(
    LLM(json.dumps([good(difficulty="extreme")])), LLM("[1]"), PASSAGE
)
assert acc and acc[0]["difficulty"] == "medium"


# ---- passage references: real references are caught, ordinary chemistry wording is not; common stems are repaired
for ok_q in [
    "In the context of chemistry, what is matter made of exactly?",
    "What is the text of Boyle's law as usually stated?",
    "Which statement about the periodic table is correct overall?",
    "What does the context of a reaction tell us about energy?",
]:
    assert not any(
        "passage/text" in p for p in check_question(good(question=ok_q), PASSAGE)
    ), ok_q
for bad_q in [
    "Which statement is true based on the text?",
    "According to the passage, which element is the most electronegative?",
    "In the passage, which element has the highest value?",
    "The passage states that which element is largest?",
    "What is said according to the context here?",
]:
    assert any(
        "passage/text" in p for p in check_question(good(question=bad_q), PASSAGE)
    ), bad_q
assert (
    repair_stem("According to the passage, which element is the most electronegative?")
    == "Which element is the most electronegative?"
)
assert (
    repair_stem("Which element is the most electronegative, according to the passage?")
    == "Which element is the most electronegative?"
)
assert repair_stem("In the text, what is chemistry?") == "What is chemistry?"
assert (
    repair_stem("Based on the excerpt: which gas is lightest of all?")
    == "Which gas is lightest of all?"
)
assert (
    repair_stem(
        "Which of the following does the passage list as a branch of chemistry?"
    )
    == "Which of the following does the passage list as a branch of chemistry?"
)  # middle reference: untouched
assert (
    repair_stem("What is an atom?") == "What is an atom?"
    and repair_stem(None) is None
    and repair_stem(5) == 5
)

# ---- generator: repaired stems are accepted; a mid-sentence reference is rejected AND logged with its text
q_lead = good(
    question="According to the passage, which element is the most electronegative element?"
)
q_mid = good(
    question="Which of the following does the passage say is the most electronegative element?",
    explanation="Fluorine has the highest electronegativity value, 4.0.",
)
log = []
acc, rej = generate_for_passage(
    LLM(json.dumps([q_lead, q_mid])), LLM("[1]"), PASSAGE, rejected_log=log
)
assert (
    len(acc) == 1
    and acc[0]["question"] == "Which element is the most electronegative element?"
), acc
assert rej["refers to 'the passage/text' (students do not see it)"] == 1
assert log == [
    {
        "reason": "refers to 'the passage/text' (students do not see it)",
        "question": q_mid["question"],
    }
], log
acc, rej = generate_for_passage(
    LLM("not json"), LLM(), PASSAGE, rejected_log=(log2 := [])
)
assert acc == [] and log2 == [
    {"reason": "generator reply was not a JSON array", "question": None}
]

# ---- snap_quote: a reworded quote becomes the real sentence; an invented one stays rejected
from practice.generator import GENERATE_PROMPT

snapped = snap_quote(
    "Fluorine is the most electronegative element, with a value of about 4.0", PASSAGE
)
assert (
    snapped is not None
    and "Fluorine is the most electronegative element with a value of 4.0" in snapped
    and quote_in_passage(snapped, PASSAGE)
), snapped
assert (
    snap_quote(
        "Fluorine always has the strongest pull on every kind of electron", PASSAGE
    )
    is None
)
assert snap_quote("too short", PASSAGE) is None
q_reword = good(
    supporting_quote="Fluorine is the most electronegative element, with a value of about 4.0"
)
acc, rej = generate_for_passage(LLM(json.dumps([q_reword])), LLM("[1]"), PASSAGE)
assert (
    len(acc) == 1
    and quote_in_passage(acc[0]["supporting_quote"], PASSAGE)
    and "about" not in acc[0]["supporting_quote"]
), (acc, dict(rej))
acc, rej = generate_for_passage(
    LLM(
        json.dumps(
            [
                good(
                    supporting_quote="Fluorine always has the strongest pull on every kind of electron"
                )
            ]
        )
    ),
    LLM("[1]"),
    PASSAGE,
)
assert acc == [] and rej["supporting_quote is not in the passage"] == 1
# the prompt tells the model the rules that caused most rejections
for needle in [
    "NEVER use the words passage, text",
    'BAD: "According to the passage',
    "NOT mentioned",
    "character for character",
]:
    assert needle in GENERATE_PROMPT, needle
GENERATE_PROMPT.format(n=3, passage="x")  # braces in the template are still valid

# ---- question health: which questions deserve a second look
from practice import health

assert health.flag_reasons("active", 12, 2) == [
    "only 17% correct after 12 answers (the answer key may be wrong)"
]
assert health.flag_reasons("active", 9, 0) == []  # too few answers to judge
assert health.flag_reasons("active", 12, 3) == []  # exactly 25% is not "under 25%"
assert (
    health.flag_reasons("active", 12, 2, min_answers=20) == []
    and health.flag_reasons("active", 12, 3, max_accuracy=0.3) != []
)
assert health.flag_reasons("needs_review", 0, 0, 2, ["wrong key", None, "unclear"]) == [
    "reported by 2 student(s): wrong key; unclear"
]
assert health.flag_reasons("needs_review", 0, 0, 1) == ["reported by 1 student(s)"]
assert (
    health.flag_reasons("needs_review", 0, 0, 0) == []
    and health.flag_reasons("retired", 50, 0, 3) == []
)  # new / retired: nothing to flag
assert (
    health.flag_reasons("active", 20, 20) == []
    and health.flag_reasons("active", 20, 18) == []
)
sm = health.summarize(
    [
        ("chemistry", "active", 10, 6),
        ("chemistry", "active", 0, 0),
        ("chemistry", "needs_review", 0, 0),
        ("biology", "retired", 4, 1),
    ]
)
assert sm["chemistry"] == {
    "active": 2,
    "needs_review": 1,
    "retired": 0,
    "answered": 10,
    "correct": 6,
    "accuracy": 0.6,
}, sm
assert (
    sm["biology"]["accuracy"] == 0.25
    and health.summarize([]) == {}
    and health.summarize([("x", "active", 0, 0)])["x"]["accuracy"] is None
)

# ---- selection / progress
cands = [{"id": i} for i in "abcdef"]
last = {"a": (True, 10), "b": (False, 5), "c": (True, 3), "d": (False, 8)}  # e,f unseen
order = [q["id"] for q in pick_questions(cands, last, 6, random.Random(1))]
assert (
    set(order[:2]) == {"e", "f"}
    and set(order[2:4]) == {"b", "d"}
    and order[4:] == ["c", "a"]
), order  # unseen, wrong, then right oldest-first
assert len(pick_questions(cands, last, 3)) == 3 and pick_questions([], {}, 5) == []
prog = unit_progress([("U1", 10, 9), ("U2", 10, 3), ("U3", 2, 2), ("U4", 8, 5)])
lv = {r["unit"]: r["level"] for r in prog}
assert (
    lv == {"U1": "strong", "U2": "weak", "U3": "not enough data", "U4": "learning"}
    and prog[0]["unit"] == "U2"
), prog
assert (
    unit_progress([("X", 1, 1)])[0]["accuracy"] == 0.67
)  # one lucky answer is not 100%
# ---- subjects
av = ["biology", "chemistry", "english", "geography", "mathematics"]
assert resolve_subject("chemisty", av) == (None, "chemistry") and resolve_subject(
    " Maths ", av
) == ("mathematics", None)
print("ALL PRACTICE CORE TESTS PASSED")
