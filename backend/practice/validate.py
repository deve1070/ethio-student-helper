"""
Quality gates for generated multiple-choice questions. Pure functions, no
database or model calls, so they are easy to test.

A wrong answer key does more damage than a missing question, so a question is
only kept if it passes ALL of these (see practice/generator.py for the flow):
  - well-formed (4 distinct options, one valid answer index, an explanation)
  - the "supporting quote" really appears in the textbook passage
  - no "all of the above" style options, no references to "the passage"
  - not a near-duplicate of a question we already have
"""

import difflib
import hashlib
import random
import re
import unicodedata

VALID_DIFFICULTY = ("easy", "medium", "hard")

_BANNED_OPTION = re.compile(
    r"\b(all|none) of the (above|these|options)\b|\bboth [a-d] and [a-d]\b|\ball options\b",
    re.IGNORECASE,
)
_PASSAGE_REF = re.compile(
    # "according to / based on / from / in / as stated in the passage|text|excerpt|paragraph..."
    r"\b(?:according to|based on|from|in|as (?:stated|mentioned|described|given|shown) in|refers? to|referring to)\s+(?:the|this)\s+"
    r"(?:passage|text|excerpt|extract|paragraph|reading|selection|section above)\b"
    # "the passage says ...", "this excerpt ..."
    r"|\b(?:the|this)\s+(?:passage|excerpt|extract)\b"
    # "the context" only in the same prepositional uses ("in the context of chemistry" is fine)
    r"|\b(?:according to|based on|from)\s+the\s+context\b",
    re.IGNORECASE,
)
_LEADING_REF = re.compile(
    r"^\s*(?:according to|based on|as (?:stated|mentioned|described|given|shown) in|from|in)\s+(?:the|this)\s+"
    r"(?:passage|text|excerpt|extract|paragraph|reading|selection|context)\s*[,:;-]?\s*",
    re.IGNORECASE,
)
_TRAILING_REF = re.compile(
    r",?\s*(?:according to|based on|as (?:stated|mentioned|described|given|shown) in|in|from)\s+(?:the|this)\s+"
    r"(?:passage|text|excerpt|extract|paragraph|reading|selection|context)\s*(?=[?.!]?\s*$)",
    re.IGNORECASE,
)


def repair_stem(question):
    """ "According to the passage, which element ...?" -> "Which element ...?"
    Only a reference at the very start or very end of the question is removed;
    anything in the middle is left for check_question to reject."""
    if not isinstance(question, str):
        return question
    fixed = _LEADING_REF.sub("", question, count=1)
    fixed = _TRAILING_REF.sub("", fixed, count=1)
    fixed = fixed.strip()
    if fixed and fixed != question.strip():
        fixed = fixed[0].upper() + fixed[1:]
        if not fixed.endswith(("?", ".", ":")):
            fixed += "?"
    return fixed if fixed else question


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text)).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def quote_in_passage(quote: str, passage: str, min_ratio: float = 0.9) -> bool:
    """True if `quote` is in `passage` (ignoring case, punctuation, spacing),
    allowing tiny differences such as a dropped hyphen."""
    nq, npass = normalize(quote), normalize(passage)
    if not nq:
        return False
    if nq in npass:
        return True
    words, qlen = npass.split(), len(nq.split())
    for start in range(max(1, len(words) - qlen + 1)):
        window = " ".join(words[start : start + qlen])
        m = difflib.SequenceMatcher(None, nq, window)
        if (
            m.real_quick_ratio() >= min_ratio
            and m.quick_ratio() >= min_ratio
            and m.ratio() >= min_ratio
        ):
            return True
    return False


def snap_quote(quote: str, passage: str, min_ratio: float = 0.8, max_words: int = 45):
    """The model sometimes rewords its "exact" quote (adds "about", drops a comma).
    If the quote is clearly a rewording of a stretch of the passage (similarity
    >= min_ratio), return that stretch exactly as printed in the passage, so the
    stored quote is verbatim; otherwise None."""
    nq = normalize(quote)
    n = len(nq.split())
    if n < 4:
        return None
    tokens = passage.split()
    best, best_ratio = None, 0.0
    for size in range(max(4, n - 2), min(max_words, n + 2) + 1):
        for start in range(max(1, len(tokens) - size + 1)):
            window = " ".join(tokens[start : start + size])
            matcher = difflib.SequenceMatcher(None, nq, normalize(window))
            if (
                matcher.real_quick_ratio() < min_ratio
                or matcher.quick_ratio() < min_ratio
            ):
                continue
            ratio = matcher.ratio()
            if ratio > best_ratio:
                best, best_ratio = window, ratio
    return best if best_ratio >= min_ratio else None


def check_question(q: dict, passage: str) -> list[str]:
    """Return a list of problems; an empty list means the question is acceptable."""
    problems: list[str] = []
    if not isinstance(q, dict):
        return ["not an object"]

    question = q.get("question")
    options = q.get("options")
    idx = q.get("answer_index")
    explanation = q.get("explanation")
    quote = q.get("supporting_quote")

    if not isinstance(question, str) or not (15 <= len(question.strip()) <= 300):
        problems.append("question missing or wrong length")
    if (
        not isinstance(options, list)
        or len(options) != 4
        or not all(isinstance(o, str) and o.strip() for o in options)
    ):
        problems.append("need exactly 4 non-empty options")
        return problems
    if any(len(o) > 200 for o in options):
        problems.append("an option is too long")
    if len({normalize(o) for o in options}) != 4:
        problems.append("options are not distinct")
    if isinstance(idx, bool) or not isinstance(idx, int) or not (0 <= idx <= 3):
        problems.append("answer_index must be an integer 0-3")
    if not isinstance(explanation, str) or not (10 <= len(explanation.strip()) <= 600):
        problems.append("explanation missing or wrong length")
    if not isinstance(quote, str) or len(quote.split()) < 4:
        problems.append("supporting_quote missing or too short")
    elif not quote_in_passage(quote, passage):
        problems.append("supporting_quote is not in the passage")

    if any(_BANNED_OPTION.search(o) for o in options):
        problems.append("uses an 'all/none of the above' style option")
    if isinstance(question, str) and (
        _PASSAGE_REF.search(question) or any(_PASSAGE_REF.search(o) for o in options)
    ):
        problems.append("refers to 'the passage/text' (students do not see it)")

    if (
        isinstance(question, str)
        and isinstance(idx, int)
        and not isinstance(idx, bool)
        and 0 <= idx <= 3
    ):
        correct = normalize(options[idx])
        if len(correct.split()) >= 3 and correct in normalize(question):
            problems.append("the question already contains the correct answer")
    return problems


def content_hash(question: str, options: list[str]) -> str:
    key = normalize(question) + "|" + "|".join(sorted(normalize(o) for o in options))
    return hashlib.sha1(key.encode()).hexdigest()


def dup_key(question: str, options: list[str], answer_index: int) -> tuple[str, str]:
    """What we remember about an existing question to detect repeats: its
    normalized text and its normalized correct answer."""
    return normalize(question), normalize(options[answer_index])


def is_duplicate(
    question: str, correct_answer: str, existing: list[tuple[str, str]]
) -> bool:
    """A repeat = nearly the same wording (Jaccard >= 0.9), or similar wording
    (>= 0.6) asking for the SAME answer. Questions that differ in one key word
    ("most" vs "least", "across a period" vs "down a group") have different
    answers, so they are kept."""
    words = set(normalize(question).split())
    answer = normalize(correct_answer)
    if not words:
        return True
    for other_q, other_a in existing:
        ow = set(other_q.split())
        if not ow:
            continue
        jaccard = len(words & ow) / len(words | ow)
        if jaccard >= 0.9 or (jaccard >= 0.6 and answer == other_a):
            return True
    return False


def shuffle_options(
    options: list[str], answer_index: int, seed: str
) -> tuple[list[str], int]:
    """Deterministically shuffle so the key is not always in the same slot
    (models like to put the right answer first or longest)."""
    order = list(range(4))
    random.Random(seed).shuffle(order)
    return [options[i] for i in order], order.index(answer_index)
