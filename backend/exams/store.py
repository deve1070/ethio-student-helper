"""Database + vector-store operations for the exam bank. Each function does one step, so every step can be
reviewed before the next one runs:  load -> key/solve -> approve -> link -> index.
Nothing here guesses an answer."""

import ast
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from llm.client import parse_json_object
from retriever.citation import citation_for

from .models import (
    EsslceAttempt,
    EsslceElaboration,
    EsslcePaper,
    EsslcePassage,
    EsslceQuestion,
    EsslceTopicLink,
)


# ---------------------------------------------------------------------------- load
def find_paper(db, subject, year_ec, stream="", round_="", region="", delivery_mode=""):
    q = db.query(EsslcePaper).filter(
        EsslcePaper.subject == subject, EsslcePaper.year_ec == year_ec
    )
    if stream:
        q = q.filter(EsslcePaper.stream == stream)
    if round_:
        q = q.filter(EsslcePaper.round == round_)
    if region:
        q = q.filter(EsslcePaper.region == region)
    if delivery_mode:
        q = q.filter(EsslcePaper.delivery_mode == delivery_mode)
    found = q.all()
    if not found:
        raise LookupError(
            f"no exam paper for {subject} {year_ec} {stream} {round_} {region} {delivery_mode}".strip()
        )
    if len(found) > 1:
        names = ", ".join(
            f"[stream={p.stream or '-'} round={p.round or '-'} region={p.region or '-'} "
            f"mode={p.delivery_mode or '-'}]"
            for p in found
        )
        raise LookupError(
            f"{len(found)} papers match ({names}); add --stream / --round / --region / --delivery-mode"
        )
    return found[0]


def load_paper(
    db, folder: Path, replace: bool = False, allow_incomplete: bool = False, log=print
) -> EsslcePaper:
    """Read the files written by extract.run_extract into the exam tables. Idempotent."""
    meta = json.loads((folder / "paper.json").read_text(encoding="utf-8"))
    recs = [
        json.loads(l)
        for l in (folder / "questions.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    passages = json.loads((folder / "passages.json").read_text(encoding="utf-8"))
    if not recs:
        raise ValueError("questions.jsonl is empty - nothing to load")
    if meta.get("failed_pages") and not allow_incomplete:
        raise ValueError(
            f"pages {meta['failed_pages']} produced no transcription (passages or questions may be missing). "
            "Re-run extract, or pass --allow-incomplete if you know those pages hold nothing you need."
        )
    paper_level = [
        m
        for lvl, m in meta.get("issues", [])
        if lvl == "FAIL" and not re.match(r"Q\d+:", m)
    ]
    if paper_level and not allow_incomplete:
        raise ValueError(
            "the paper as a whole has problems: "
            + "; ".join(paper_level)
            + ". Fix transcript.txt and re-run extract, or pass --allow-incomplete to load it anyway "
            "(an incomplete paper cannot be used as a mock exam)."
        )

    existing = (
        db.query(EsslcePaper)
        .filter(
            EsslcePaper.subject == meta["subject"],
            EsslcePaper.year_ec == meta["year_ec"],
            EsslcePaper.stream == meta.get("stream", ""),
            EsslcePaper.round == meta.get("round", ""),
            EsslcePaper.region == meta.get("region", ""),
            EsslcePaper.delivery_mode == meta.get("delivery_mode", ""),
        )
        .first()
    )
    if existing:
        keyed = sum(1 for q in existing.questions if q.answer_index is not None)
        approved = sum(1 for q in existing.questions if q.review_status == "approved")
        if not replace:
            raise FileExistsError(
                f"paper already loaded ({len(existing.questions)} questions, {keyed} with a key, {approved} approved). "
                f"--replace deletes ALL of that (keys and approvals included) and loads the new files."
            )
        log(
            f"replacing: deleting {len(existing.questions)} questions ({keyed} keyed, {approved} approved)"
        )
        db.delete(existing)
        db.flush()

    paper = EsslcePaper(
        subject=meta["subject"],
        stream=meta.get("stream", ""),
        year_ec=meta["year_ec"],
        year_gc=meta.get("year_gc"),
        round=meta.get("round", ""),
        region=meta.get("region", ""),
        delivery_mode=meta.get("delivery_mode", ""),
        booklet_code=meta.get("booklet_code"),
        source_file=meta.get("source_file"),
        source_sha256=meta.get("source_sha256"),
        source_dir=str(folder),
        page_count=meta.get("page_count"),
        expected_first=meta.get("expected_first", 1),
        expected_last=meta.get("expected_last"),
        duration_minutes=meta.get("duration_minutes"),
        notes=meta.get("notes") or ("; ".join(paper_level) if paper_level else None),
    )
    db.add(paper)
    db.flush()

    pid = {}
    for key, p in passages.items():
        text = "\n\n".join(f"({para['n']}) {para['text']}" for para in p["paragraphs"])
        row = EsslcePassage(
            paper_id=paper.id,
            passage_key=key,
            title=p.get("title"),
            text=text,
            source_note=p.get("source"),
        )
        db.add(row)
        db.flush()
        pid[key] = row.id

    for r in recs:
        opts = r["options"]
        db.add(
            EsslceQuestion(
                paper_id=paper.id,
                item_no=r["item_no"],
                part=r.get("part"),
                section=r.get("section"),
                stem=r["stem"],
                options=opts,
                underlined=r.get("underlined") or [],
                passage_id=pid.get(r.get("passage_key")),
                printed_page=r.get("printed_page"),
                has_diagram=bool(r.get("has_diagram")),
                diagram_note=r.get("diagram_note"),
                review_status="needs_key",
                flags=r.get("flags") or [],
            )
        )
    db.commit()
    log(
        f"loaded {meta['subject']} {meta['year_ec']}: {len(recs)} questions, {len(passages)} passages "
        f"({sum(1 for r in recs if r.get('flags'))} flagged)"
    )
    return paper


# ---------------------------------------------------------------------------- key
def read_key_file(path: Path) -> dict:
    """{item number: 'A'..'D'} from .json ({"1": "A"} or [{"item": 1, "answer": "A"}]) or any text/CSV with 'number letter' pairs."""
    raw = Path(path).read_text(encoding="utf-8")
    if str(path).lower().endswith(".json"):
        data = json.loads(raw)
        if isinstance(data, dict):
            return {int(k): str(v).strip().upper() for k, v in data.items()}
        return {
            int(d.get("item") or d.get("item_no") or d["number"]): str(d["answer"])
            .strip()
            .upper()
            for d in data
        }
    pairs = re.findall(r"(?<!\d)(\d{1,3})\s*[.):,;\-\s]\s*([A-Za-z])(?![A-Za-z])", raw)
    key, conflicts = {}, set()
    for n, letter in pairs:
        n, letter = int(n), letter.upper()
        if n in key and key[n] != letter:
            conflicts.add(n)
        key[n] = letter
    if conflicts:
        raise ValueError(
            f"the key file gives different answers for item(s) {sorted(conflicts)}"
        )
    return key


def attach_key(
    db, paper: EsslcePaper, key: dict, source: str = "official_key", log=print
) -> dict:
    """Attach answers from a REAL key. A letter that is not among the options, or a number the paper does not have,
    is reported and skipped. Keyed questions go to 'needs_review' (a person approves them)."""
    by_no = {q.item_no: q for q in paper.questions}
    problems, set_n = [], 0
    for n, letter in sorted(key.items()):
        q = by_no.get(n)
        if q is None:
            problems.append(f"key has item {n}, the paper does not")
            continue
        if letter not in "ABCD" or len(letter) != 1:
            problems.append(f"item {n}: {letter!r} is not A-D")
            continue
        new_index = "ABCD".index(letter)
        if (
            q.review_status == "approved"
            and q.answer_index is not None
            and q.answer_index != new_index
        ):
            q.review_status, q.reviewed_by, q.reviewed_at = (
                "needs_review",
                None,
                None,
            )  # the approved answer just changed
            problems.append(
                f"item {n}: key changed from {'ABCD'[q.answer_index]} to {letter}; approval withdrawn, review it again"
            )
        q.answer_index = new_index
        q.answer_source = source
        if q.review_status in ("needs_key", "needs_review"):
            q.review_status = "needs_review"
        set_n += 1
    missing = sorted(
        n for n, q in by_no.items() if q.answer_index is None
    )  # no usable key: absent OR an invalid letter
    db.commit()
    log(f"key attached to {set_n} questions; {len(missing)} without a key")
    return {"attached": set_n, "missing": missing, "problems": problems}


# ---------------------------------------------------------------------------- review
def approve(db, paper: EsslcePaper, items=None, all_clean=False, who: str = "") -> int:
    """items: item numbers to approve. all_clean: every keyed question with NO flags.
    A question without a key can never be approved."""
    n = 0
    for q in paper.questions:
        wanted = (items and q.item_no in items) or (all_clean and not (q.flags or []))
        if not wanted:
            continue
        if q.answer_index is None:
            continue
        q.review_status, q.reviewed_by, q.reviewed_at = (
            "approved",
            who or None,
            datetime.utcnow(),
        )
        n += 1
    db.commit()
    return n


# ---------------------------------------------------------------------------- topic links (suggestions)
def retrieve_cross_grade(
    store, query, subject, grades=(9, 10, 11, 12), k_per_grade=3, final_k=6, margin=0.2
):
    """Search each grade separately so a topic taught in four books shows up in each, then keep the best per
    grade (if close to the overall best) and fill with the best of the rest. Same idea as retrieval/cross_grade_retrieval."""
    hits = []
    for g in grades:
        flt = {"$and": [{"subject": subject}, {"grade": g}]}
        for doc, dist in store.similarity_search_with_score(
            query, k=k_per_grade, filter=flt
        ):
            hits.append((float(dist), g, doc))
    hits.sort(key=lambda h: h[0])
    if not hits:
        return []
    best, chosen, seen = hits[0][0], [], set()
    firsts = {}
    for h in hits:
        firsts.setdefault(h[1], h)
    for g in sorted(firsts):
        if firsts[g][0] - best <= margin:
            chosen.append(firsts[g])
            seen.add(id(firsts[g]))
    for h in hits:
        if len(chosen) >= final_k:
            break
        if id(h) not in seen:
            chosen.append(h)
            seen.add(id(h))
    return sorted(chosen[:final_k], key=lambda h: (h[1], h[0]))


def link_query(q: EsslceQuestion) -> str:
    stem = (q.stem or "").strip()
    if len(stem) < 25 or stem.startswith("(instructions)"):
        stem = f"{q.section or ''} {' '.join(q.options or [])}"
    prefix = f"{q.passage.title}. " if q.passage is not None and q.passage.title else ""
    return (prefix + stem)[:600]


def link_topics(
    db, paper: EsslcePaper, store, grades=(9, 10, 11, 12), per_question=6, log=print
) -> dict:
    """Store the textbook chunks that look related to each question. SUGGESTIONS with their distance - not
    provenance. Skipped entirely for ESSLCE_SKILL_STRAND_SUBJECTS (English, SAT): best_unit() ignores any
    link for these subjects regardless (they're categorized by skill_strand() instead), so running the
    retrieval here would only store suggestions nothing ever reads."""
    if paper.subject in ESSLCE_SKILL_STRAND_SUBJECTS:
        log(f"skipped linking - {paper.subject} is organized by skill strand, not textbook chapter")
        return {"links": 0}
    total = 0
    for q in paper.questions:
        db.query(EsslceTopicLink).filter(
            EsslceTopicLink.question_id == q.id, EsslceTopicLink.verified.is_(False)
        ).delete()
        found = retrieve_cross_grade(
            store, link_query(q), paper.subject, grades, final_k=per_question
        )
        for rank, (dist, g, doc) in enumerate(found, 1):
            md = doc.metadata or {}
            db.add(
                EsslceTopicLink(
                    question_id=q.id,
                    rank=rank,
                    score=dist,
                    textbook_id=str(md["textbook_id"])
                    if md.get("textbook_id")
                    else None,
                    vector_id=md.get("vector_id"),
                    grade=g,
                    unit=md.get("unit"),
                    section=md.get("section"),
                )
            )
            total += 1
    db.commit()
    log(f"{total} suggested links for {len(paper.questions)} questions")
    return {"links": total}


# ---------------------------------------------------------------------------- calculation subjects: code-executed derivation
# Lives in config.constants now (no longer ESSLCE-exclusive knowledge - Study Notes needs it too).
from config.constants import CALCULATION_SUBJECTS, ESSLCE_SKILL_STRAND_SUBJECTS  # noqa: E402

DERIVE_PROMPT = """You are given one multiple-choice question from an Ethiopian Grade 12 national exam \
(ESSLCE) that requires a calculation or symbolic derivation, not a fact lookup.

Question: {question}
Options:
{options}

Solve it step by step. In latex_solution, refer to options by their printed LETTER (A, B, C, D) exactly as \
shown above - never by a number or position. Then reply with ONLY a JSON object, no other text:
{{"answer_index": 0,
  "latex_solution": "a full step-by-step derivation in LaTeX, one or more \\\\[...\\\\] blocks",
  "verification_code": "a short Python script, using ONLY sympy/math/fractions, that independently computes \
the final result and prints ONLY that result on its last line, formatted exactly like the matching option's \
printed text (e.g. a fraction as '7/3', not a decimal)"}}

answer_index is the option's 0-3 POSITION (A=0, B=1, C=2, D=3) - only used internally, never write this \
number in latex_solution itself.

If you cannot determine the answer with real confidence, or this question is not actually a single computable \
value (e.g. a conceptual or true/false question about a graph's properties), reply with answer_index -1 and \
null for the other two fields - it will be solved a different way, not guessed here."""

# Defense in depth, not a full sandbox: paired with subprocess isolation, a timeout, cleared environment, and
# resource limits in run_verification_code. The code's source is our own chosen LLM, not an arbitrary public
# user, but it is still untrusted input and is never exec()'d in-process.
_ALLOWED_MODULES = {"sympy", "math", "fractions"}
_FORBIDDEN_NAMES = {
    "open", "eval", "exec", "compile", "__import__", "os", "sys", "subprocess", "socket",
    "input", "getattr", "setattr", "vars", "globals", "locals", "delattr", "memoryview", "breakpoint",
}


def _code_is_safe(code: str) -> bool:
    """Static allowlist check run BEFORE any untrusted code is executed: only sympy/math/fractions may be
    imported, and no file/process/network/introspection primitive may even be referenced."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] not in _ALLOWED_MODULES for alias in node.names):
                return False
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in _ALLOWED_MODULES:
                return False
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            return False
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return False
    return True


def run_verification_code(code: str, timeout: float = 5.0) -> str | None:
    """Actually EXECUTES the LLM's derivation code in a separate process (never exec() in-process) and
    returns its last line of stdout, or None if it fails the static safety check, errors, times out, or
    prints nothing. The answer is trusted only if this independently matches a printed option - never on
    the LLM's say-so alone."""
    if not _code_is_safe(code):
        return None
    kwargs = {}
    try:
        import resource

        def _limit():
            resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
            resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))

        kwargs["preexec_fn"] = _limit
    except ImportError:  # pragma: no cover - resource is POSIX-only
        pass
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=timeout, env={}, **kwargs,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    return lines[-1] if lines else None


# An LLM's raw JSON output sometimes double-escapes a backslash before a newline it meant to write (JSON
# text "\\n" decodes to the literal characters backslash+n, not an actual newline) - seen once in real
# output (exams/latex_render.py has the same fix, for the same reason, applied again at render time as a
# second line of defense). A real LaTeX command starting "\n" (\neq, \nabla, ...) is always followed by
# more letters, so this never touches one.
_DOUBLE_ESCAPED_NEWLINE = re.compile(r"\\n(?![a-zA-Z])")


def _clean_latex(text: str) -> str:
    return _DOUBLE_ESCAPED_NEWLINE.sub("\n", text)


def _normalize_math_text(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _results_match(computed: str, option_text: str) -> bool:
    if _normalize_math_text(computed) == _normalize_math_text(option_text):
        return True
    try:
        import sympy

        return sympy.simplify(sympy.sympify(computed) - sympy.sympify(option_text)) == 0
    except Exception:  # noqa: BLE001 - option text is often not a bare math expression at all
        return False


def solve_question_calculation(llm, q: EsslceQuestion) -> dict:
    """For a calculation subject: the LLM writes a step-by-step LaTeX solution AND independent verification
    code; the code is actually run, and the answer is trusted only if its computed result matches the
    claimed option's printed text - not just that the LLM says so. Unresolved if the code is unsafe, fails,
    or its result doesn't match any claimed option (including when the question isn't really computational)."""
    unresolved = {"resolved": False}
    options = q.options or []
    options_listing = "\n".join(f"{L}) {opt}" for L, opt in zip("ABCD", options))
    prompt = DERIVE_PROMPT.format(question=q.stem, options=options_listing)
    raw = (
        llm.chat(messages=[{"role": "user", "content": prompt}])["choices"][0]["message"]["content"] or ""
    ).strip()
    data = parse_json_object(raw)
    if not data or not isinstance(data.get("answer_index"), int) or data["answer_index"] == -1:
        return unresolved

    idx, code, latex = data["answer_index"], data.get("verification_code"), data.get("latex_solution")
    if (
        isinstance(idx, bool)
        or not (0 <= idx < len(options))
        or not isinstance(code, str)
        or not isinstance(latex, str)
    ):
        return unresolved

    computed = run_verification_code(code)
    if computed is None or not _results_match(computed, options[idx]):
        return unresolved

    return {
        "resolved": True,
        "answer_index": idx,
        "explanation": _clean_latex(latex.strip()),
        "verification_code": code.strip(),
        "verification_output": computed,
    }


# ---------------------------------------------------------------------------- AI-derived answers
SOLVE_PROMPT = """You are given one multiple-choice question from an Ethiopian Grade 12 national exam (ESSLCE), \
and several numbered excerpts that might contain the answer (either Grade 9-12 textbook passages, or - for a \
reading-comprehension item - the passage the question is actually about).

Question: {question}
Options:
{options}

Excerpts:
{context}

Using ONLY the excerpts above: if exactly one excerpt clearly supports one option as correct, reply with that \
option's index (0-3), which excerpt number it came from, a 1-2 sentence explanation, and a supporting_quote copied \
character-for-character from that excerpt. If the excerpts do not let you determine the answer with real \
confidence, reply with answer_index -1 and null for the other fields - a wrong guess here is worse than no answer \
at all.

The explanation is shown directly to a student who only ever sees the lettered options above (A/B/C/D) and \
never sees these numbered excerpts at all. So in explanation: refer to the chosen option by its printed \
LETTER, never by a number or position; and state the fact directly (e.g. "Neon is a noble gas") rather than \
citing it as coming from a numbered excerpt (never write phrases like "Excerpt [2] states" or "excerpt 1 \
says" - the student has no idea what that means).

Reply with ONLY a JSON object, no other text:
{{"answer_index": 0, "source_index": 0, "explanation": "...", "supporting_quote": "..."}}"""


def solve_query(q: EsslceQuestion) -> str:
    return link_query(q)


def solve_question(
    llm, tb_store, paper: EsslcePaper, q: EsslceQuestion, grades=(9, 10, 11, 12), k=6
) -> dict:
    """Grounds a question and asks the LLM to pick an answer, trusting it only if its supporting_quote actually
    appears in the cited excerpt (practice.validate.quote_in_passage - the same trust gate the practice engine
    already uses). A reading-passage question is self-contained: it is grounded against its OWN passage text,
    not the textbook corpus. For a calculation subject, a code-executed derivation (solve_question_calculation)
    is tried FIRST - grounding doesn't apply to a derived numeric answer; this path is the fallback for
    whatever that one doesn't resolve (including every question in a non-calculation subject). Never raises,
    never guesses past what the evidence supports."""
    if paper.subject in CALCULATION_SUBJECTS:
        calc = solve_question_calculation(llm, q)
        if calc["resolved"]:
            return calc

    from practice.validate import quote_in_passage

    unresolved = {"resolved": False}
    if q.passage is not None:
        excerpts = [q.passage.text]
    else:
        hits = retrieve_cross_grade(tb_store, solve_query(q), paper.subject, grades, final_k=k)
        if not hits:
            return unresolved
        excerpts = [doc.page_content for _, _, doc in hits]

    options_listing = "\n".join(f"{L}) {opt}" for L, opt in zip("ABCD", q.options or []))
    context = "\n\n".join(f"[{i}] {text}" for i, text in enumerate(excerpts))
    prompt = SOLVE_PROMPT.format(question=q.stem, options=options_listing, context=context)
    raw = (
        llm.chat(messages=[{"role": "user", "content": prompt}])["choices"][0]["message"][
            "content"
        ]
        or ""
    ).strip()
    data = parse_json_object(raw)
    if not data or not isinstance(data.get("answer_index"), int) or data["answer_index"] == -1:
        return unresolved

    idx, src_idx = data["answer_index"], data.get("source_index")
    if (
        isinstance(idx, bool)
        or not (0 <= idx <= 3)
        or not isinstance(src_idx, int)
        or not (0 <= src_idx < len(excerpts))
    ):
        return unresolved

    quote = data.get("supporting_quote")
    if not isinstance(quote, str) or not quote_in_passage(quote, excerpts[src_idx]):
        return unresolved

    return {
        "resolved": True,
        "answer_index": idx,
        "explanation": (data.get("explanation") or "").strip() or None,
        "supporting_quote": quote.strip(),
    }


def solve_paper(
    db, paper: EsslcePaper, llm, tb_store, grades=(9, 10, 11, 12), log=print
) -> dict:
    """AI-proposes an answer for every question that doesn't already have a REAL answer (never overwrites
    answer_source 'official_key' or 'manual'). Always leaves review_status at needs_review - the existing
    `approve` step still gates every question before a student can see it. Mirrors attach_key: if an
    already-approved question's answer changes, its approval is withdrawn."""
    solved, unresolved_n, withdrawn = 0, 0, 0
    for q in paper.questions:
        if q.answer_source in ("official_key", "manual"):
            continue
        result = solve_question(llm, tb_store, paper, q, grades)
        if not result["resolved"]:
            unresolved_n += 1
            continue
        new_index = result["answer_index"]
        if (
            q.review_status == "approved"
            and q.answer_index is not None
            and q.answer_index != new_index
        ):
            q.review_status, q.reviewed_by, q.reviewed_at = "needs_review", None, None
            withdrawn += 1
        q.answer_index = new_index
        q.answer_source = "ai_derived"
        q.explanation = result["explanation"]
        # Only one of these two is ever populated, depending on which path resolved this question
        # (solve_question_calculation vs the textbook-grounded path) - the other stays/becomes None.
        q.supporting_quote = result.get("supporting_quote")
        q.verification_code = result.get("verification_code")
        q.verification_output = result.get("verification_output")
        if q.review_status in ("needs_key", "needs_review"):
            q.review_status = "needs_review"
        solved += 1
    db.commit()
    log(
        f"solved {solved} question(s), {unresolved_n} left unresolved, "
        f"{withdrawn} approval(s) withdrawn"
    )
    return {"solved": solved, "unresolved": unresolved_n, "withdrawn": withdrawn}


# ---------------------------------------------------------------------------- on-demand elaboration
# "I still don't get it, explain more" - a deeper, on-demand explanation. Cached per QUESTION (not per
# student) in EsslceElaboration: the first request generates it, every later request for the same
# question is free and instant. The LLM has real freedom in HOW it explains (structure, analogies, a
# worked example) - the constraint is WHAT it's allowed to assert: for a grounded subject, every factual
# claim still needs a verbatim quote from the retrieved textbook excerpts (same gate as solve_question);
# for a calculation subject, a fresh similar example is generated and its OWN stated answer is checked
# against independently-executed code, the same trust gate as solve_question_calculation.
ELABORATE_GROUNDED_PROMPT = """A student found this ESSLCE question difficult and wants it explained more \
deeply.

Question: {question}
Options:
{options}
Correct answer: {correct}

Using ONLY the excerpts below, write an explanation covering ALL of the following:
1. Explain the underlying concept the excerpts describe, in whatever way is clearest for a student - you \
have full freedom in HOW (structure, analogy), but every factual claim must be grounded in these excerpts.
2. Give one worked example or illustration of the concept, different from the question itself.
3. Explain why the correct option is correct.
4. For EACH of the other three options, explain specifically why it is incorrect - not just "it's wrong", \
but what misunderstanding or error it reflects.

You have full freedom in HOW you explain, but at least one verbatim quote from the excerpts must ground \
part 1 (the core concept) - part 2-4 can reason from that same grounded concept without needing their own \
separate quotes.

The student only ever sees the lettered options above (A/B/C/D) and never sees these numbered excerpts at \
all. So in explanation: refer to options by their printed LETTER, never by a number; and state facts \
directly rather than citing a numbered excerpt (never write "Excerpt [2] states" or similar - the student \
has no idea what that means).

Excerpts:
{context}

Reply with ONLY a JSON object, no other text:
{{"explanation": "...", "source_index": 0, "supporting_quote": "..."}}
If the excerpts don't actually let you ground the core concept, reply \
{{"explanation": null, "source_index": null, "supporting_quote": null}} - no explanation is better than an \
ungrounded one."""

ELABORATE_CALC_PROMPT = """A student found this ESSLCE question difficult. Help them by making up a SIMILAR \
example problem (different numbers or scenario, same underlying concept) and solving it step by step, so \
they can see the method worked through on a fresh case.

Original question: {question}
Options:
{options}

Reply with ONLY a JSON object, no other text:
{{"example_problem": "the new example problem, in full",
  "latex_solution": "a full step-by-step LaTeX derivation of the new example, ending in its final answer",
  "final_answer": "just the final numeric/symbolic answer, formatted plainly (e.g. '7/3')",
  "verification_code": "a short Python script, using ONLY sympy/math/fractions, that independently computes \
the new example's answer and prints ONLY that result on its last line, formatted exactly like final_answer"}}"""


def elaborate_grounded(
    db, llm, tb_store, paper: EsslcePaper, q: EsslceQuestion, grades=(9, 10, 11, 12), k=6
) -> dict:
    """Textbook-grounded deeper explanation - same retrieval and quote-verification gate as solve_question's
    grounded path, but free-form prose instead of picking one of the 4 options. Also resolves a structured
    citation (see retriever.citation.citation_for) for the excerpt the explanation actually grounds on."""
    from practice.validate import quote_in_passage

    unresolved = {"resolved": False}
    if q.passage is not None:
        excerpts, vector_ids = [q.passage.text], [None]  # the exam's own passage, not a textbook chunk
    else:
        hits = retrieve_cross_grade(tb_store, solve_query(q), paper.subject, grades, final_k=k)
        if not hits:
            return unresolved
        excerpts = [doc.page_content for _, _, doc in hits]
        vector_ids = [(doc.metadata or {}).get("vector_id") for _, _, doc in hits]

    options_listing = "\n".join(f"{L}) {opt}" for L, opt in zip("ABCD", q.options or []))
    correct = q.options[q.answer_index] if q.answer_index is not None else "(not yet keyed)"
    context = "\n\n".join(f"[{i}] {text}" for i, text in enumerate(excerpts))
    prompt = ELABORATE_GROUNDED_PROMPT.format(
        question=q.stem, options=options_listing, correct=correct, context=context
    )
    raw = (
        llm.chat(messages=[{"role": "user", "content": prompt}])["choices"][0]["message"]["content"] or ""
    ).strip()
    data = parse_json_object(raw)
    if not data or not data.get("explanation"):
        return unresolved

    src_idx, quote = data.get("source_index"), data.get("supporting_quote")
    if not isinstance(src_idx, int) or not (0 <= src_idx < len(excerpts)):
        return unresolved
    if not isinstance(quote, str) or not quote_in_passage(quote, excerpts[src_idx]):
        return unresolved

    return {
        "resolved": True,
        "content": data["explanation"].strip(),
        "is_calculation": False,
        "citation": citation_for(db, vector_ids[src_idx]),
    }


def elaborate_calculation(llm, q: EsslceQuestion) -> dict:
    """A fresh, similar worked example for a calculation subject - verified the same way
    solve_question_calculation verifies the original: the code is actually executed, and the example is
    trusted only if its result matches what the LLM itself claimed as the final answer."""
    unresolved = {"resolved": False}
    options_listing = "\n".join(f"{L}) {opt}" for L, opt in zip("ABCD", q.options or []))
    prompt = ELABORATE_CALC_PROMPT.format(question=q.stem, options=options_listing)
    raw = (
        llm.chat(messages=[{"role": "user", "content": prompt}])["choices"][0]["message"]["content"] or ""
    ).strip()
    data = parse_json_object(raw)
    if not data:
        return unresolved

    problem, latex, final_answer, code = (
        data.get("example_problem"), data.get("latex_solution"),
        data.get("final_answer"), data.get("verification_code"),
    )
    if not all(isinstance(x, str) and x.strip() for x in (problem, latex, final_answer, code)):
        return unresolved

    computed = run_verification_code(code)
    if computed is None or not _results_match(computed, final_answer):
        return unresolved

    content = f"{problem.strip()}\n\n{_clean_latex(latex.strip())}"
    return {"resolved": True, "content": content, "is_calculation": True}


def elaborate_question(
    db, llm, tb_store, paper: EsslcePaper, q: EsslceQuestion, grades=(9, 10, 11, 12)
) -> dict:
    if paper.subject in CALCULATION_SUBJECTS:
        calc = elaborate_calculation(llm, q)
        if calc["resolved"]:
            return calc
    return elaborate_grounded(db, llm, tb_store, paper, q, grades)


def get_or_create_elaboration(db, llm, tb_store, paper: EsslcePaper, q: EsslceQuestion) -> EsslceElaboration | None:
    """The cache lookup + generate-on-miss entry point every caller should use - never call
    elaborate_question directly from a route, or every request becomes a fresh (slow, costly) LLM call."""
    existing = db.query(EsslceElaboration).filter(EsslceElaboration.question_id == q.id).one_or_none()
    if existing is not None:
        return existing

    result = elaborate_question(db, llm, tb_store, paper, q)
    if not result["resolved"]:
        return None
    row = EsslceElaboration(
        question_id=q.id,
        content=result["content"],
        is_calculation=result["is_calculation"],
        citation=result.get("citation"),
    )
    db.add(row)
    db.commit()
    return row


ASK_PROMPT = """You are helping an Ethiopian Grade 12 student understand ONE specific ESSLCE exam question - \
stay strictly within the context below. If the student asks something this context genuinely cannot answer, \
say plainly that you don't have enough grounded information for that, rather than inventing facts. Never \
state a textbook page or section number unless it is explicitly given to you below.

Question: {question}
Options:
{options}
Correct answer: {correct}
{context_block}

Refer to options by their printed LETTER (A-D), never by a number or "excerpt N". Keep replies focused and \
concise - the student is reading this on a phone."""


def ask_about_question(llm, q: EsslceQuestion, elaboration: EsslceElaboration | None, history: list, message: str) -> str:
    """A follow-up conversation about one question, grounded in its own content plus whatever's already
    resolved for it (the cached elaboration's explanation and citation) - NOT re-verified per message the
    way solve/elaborate's core claims are (a hard quote-verification gate isn't practical for open-ended
    dialogue). This is a softer, PROMPT-LEVEL grounding only: the model is instructed to decline rather
    than invent when asked something outside this context, but unlike quote_in_passage that instruction is
    never independently checked. Every call here is a fresh, uncached LLM call - unlike /elaborate, there
    is no per-question caching for conversation turns, so this is the more expensive path per use."""
    options_listing = "\n".join(f"{L}) {opt}" for L, opt in zip("ABCD", q.options or []))
    correct = q.options[q.answer_index] if q.answer_index is not None else "(not yet keyed)"
    context_lines = []
    if elaboration is not None:
        context_lines.append(f"Prepared explanation: {elaboration.content}")
        c = elaboration.citation
        if c:
            page = (
                f"p.{c['page_start']}"
                + (f"-{c['page_end']}" if c.get("page_end") and c["page_end"] != c["page_start"] else "")
                if c.get("page_start")
                else None
            )
            parts = [c["textbook"], f"Grade {c['grade']}", c.get("unit_or_chapter"), c.get("section"), page]
            context_lines.append("Source: " + ", ".join(p for p in parts if p))
    system_prompt = ASK_PROMPT.format(
        question=q.stem, options=options_listing, correct=correct, context_block="\n".join(context_lines)
    )
    messages = [{"role": "system", "content": system_prompt}] + list(history) + [
        {"role": "user", "content": message}
    ]
    return (llm.chat(messages=messages)["choices"][0]["message"]["content"] or "").strip()


# ---------------------------------------------------------------------------- index
def embed_text(paper: EsslcePaper, q: EsslceQuestion) -> str:
    """Only what the question SAYS (passage title, stem, options). The paper, year and item number go into the
    vector's metadata: put in the text they would pull every question of one paper towards each other and away from
    a student's own wording, which is what matching a typed or photographed question needs."""
    opts = "\n".join(f"{k}. {t}" for k, t in zip("ABCD", q.options or []))
    passage = (
        f"{q.passage.title}\n" if q.passage is not None and q.passage.title else ""
    )
    return f"{passage}{q.stem}\n{opts}"


def index_questions(
    db, paper: EsslcePaper, store, include_unreviewed: bool = False, log=print
) -> int:
    """Embed APPROVED questions (or all, with include_unreviewed) into the exam collection - never the textbook one.
    Ids are deterministic (exam-<question id>), and EVERY question of the paper is removed first, so running it again
    replaces instead of duplicating, and a question whose approval was withdrawn (e.g. its key changed) disappears
    from the index instead of staying searchable."""
    rows = [
        q
        for q in paper.questions
        if include_unreviewed or q.review_status == "approved"
    ]
    try:
        store.delete(ids=[f"exam-{q.id}" for q in paper.questions])
    except Exception:  # noqa: BLE001  (first run: nothing to delete)
        pass
    if not rows:
        log(
            "nothing to index (no approved questions; use approve, or --include-unreviewed to test)"
        )
        return 0

    def _metadata(q: EsslceQuestion) -> dict:
        md = {
            "kind": "esslce_question",
            "paper_id": paper.id,
            "question_id": q.id,
            "subject": paper.subject,
            "stream": paper.stream,
            "year_ec": paper.year_ec,
            "item_no": q.item_no,
            "review_status": q.review_status,
            "has_key": q.answer_index is not None,
        }
        unit_info = best_unit(q)  # (grade, unit, verified) or None - omit the keys entirely
        if unit_info is not None:  # rather than pass None, which Chroma's metadata rejects
            md["grade"], md["unit"], md["unit_verified"] = unit_info
        return md

    store.add_texts(
        texts=[embed_text(paper, q) for q in rows],
        metadatas=[_metadata(q) for q in rows],
        ids=[f"exam-{q.id}" for q in rows],
    )
    log(f"indexed {len(rows)} questions into the exam collection")
    return len(rows)


# ---------------------------------------------------------------------------- units, time, completeness
def set_unit(
    db, paper: EsslcePaper, items, grade: int, unit: str, section: str | None = None
) -> int:
    """A person says which textbook unit these questions belong to. Stored as the rank-0 link, verified; it replaces
    earlier verified links and is used before any search suggestion (and survives `link` being run again)."""
    n = 0
    for q in paper.questions:
        if q.item_no not in items:
            continue
        db.query(EsslceTopicLink).filter(
            EsslceTopicLink.question_id == q.id, EsslceTopicLink.verified.is_(True)
        ).delete()
        db.add(
            EsslceTopicLink(
                question_id=q.id,
                rank=0,
                score=0.0,
                grade=grade,
                unit=unit,
                section=section,
                verified=True,
            )
        )
        n += 1
    db.commit()
    return n


def set_duration(db, paper: EsslcePaper, minutes) -> None:
    paper.duration_minutes = minutes
    db.commit()


def paper_complete(paper: EsslcePaper) -> bool:
    """Every item number from the first to the last expected one is present."""
    have = {q.item_no for q in paper.questions}
    return paper.expected_last is not None and all(
        n in have for n in range(paper.expected_first or 1, paper.expected_last + 1)
    )


def question_page_image(q: EsslceQuestion) -> bytes | None:
    """The real source photo of this question's printed page, for the (rare) item that genuinely needs a
    figure/table/diagram the vision model couldn't transcribe as text. Always the literal page photo
    captured during extraction - NEVER regenerated or redrawn, so nothing here can be a fabricated
    recreation of a real exam figure. None if the paper predates `source_dir` being recorded, or the
    expected file is missing on disk (never guessed, never a broken reference shown to a student)."""
    paper = q.paper
    if not paper or not paper.source_dir or not q.printed_page:
        return None
    path = Path(paper.source_dir) / f"p{q.printed_page:02d}.jpg"
    if not path.is_file():
        return None
    return path.read_bytes()


def eligible(q: EsslceQuestion) -> bool:
    """Can be shown to a student: approved, has a key, and - if it needs a figure - the real source page
    photo is actually available to show alongside it (never shown with a figure silently missing)."""
    if q.review_status != "approved" or q.answer_index is None:
        return False
    if not q.has_diagram:
        return True
    return question_page_image(q) is not None


def best_unit(q: EsslceQuestion):
    """(grade, unit, verified) for a question, or None. A human-verified link wins; otherwise the closest
    search result. Always None for ESSLCE_SKILL_STRAND_SUBJECTS (English, SAT) - those are organized by
    skill strand (skill_strand(), below), never by textbook chapter, even if the generic embedding-based
    chapter-linker already produced a link for one of their questions (confirmed live: English chapter
    links exist, e.g. "Unit 1: Sustainable Development" - a reading-passage theme, not a grammar point)."""
    if q.paper.subject in ESSLCE_SKILL_STRAND_SUBJECTS:
        return None
    # `rank` follows the review order (by grade, then distance), so the closest match is chosen by SCORE
    links = sorted(
        q.links,
        key=lambda l: (not l.verified, l.score if l.score is not None else 9.0, l.rank),
    )
    if not links or not links[0].unit:
        return None
    return links[0].grade, links[0].unit, bool(links[0].verified)


# ---------------------------------------------------------------------------- statistics
def unit_stats(db, subject: str | None = None) -> list:
    """Deterministic (no LLM) per-(subject, grade, unit) question counts across every loaded paper, using
    best_unit(q) - the same attribution reviewers and index_questions already use - to attribute each question
    to a unit. Surfaces which units are most heavily tested; this is a count, not a ranking decision."""
    q = db.query(EsslcePaper)
    if subject:
        q = q.filter(EsslcePaper.subject == subject)
    rows: dict = {}
    for paper in q.all():
        for question in paper.questions:
            unit_info = best_unit(question)
            if unit_info is None:
                continue
            grade, unit, verified = unit_info
            key = (paper.subject, grade, unit)
            row = rows.setdefault(
                key,
                {
                    "subject": paper.subject,
                    "grade": grade,
                    "unit": unit,
                    "all_count": 0,
                    "approved_count": 0,
                    "years": set(),
                    "verified": False,
                },
            )
            row["all_count"] += 1
            if question.review_status == "approved":
                row["approved_count"] += 1
            row["years"].add(paper.year_ec)
            row["verified"] = row["verified"] or verified
    out = [{**row, "years": sorted(row["years"])} for row in rows.values()]
    out.sort(key=lambda r: r["all_count"], reverse=True)
    return out


# English and the Scholastic Aptitude Test (extract.SUBJECTS_WITH_SECTIONS) aren't organized by textbook
# topic the way every other subject is - a grammar question isn't "about" any one textbook unit, and a bare
# vocabulary/spelling item often has no textbook passage to ground against at all (this is why English's
# solve yield is lower than other subjects: quote_in_passage has nothing to cite for those). The exam's OWN
# printed section headings ("Word Spelling", "Sentence Correction", "Analogy", "Quantitative Reasoning", ...)
# already carry this structure - already captured for free in `part`/`section` during parsing (tools.py's
# @part/@section markup, confirmed against the real loaded English 2018 paper and the real SAT 2018 photos)
# - so this needs no new LLM call and no new column, just a deterministic keyword match against the
# official, recurring EAES section vocabulary (grounded in the real papers, not guessed).
_SKILL_STRAND_KEYWORDS = [
    # Specific labels first - every one below this point is a narrower match that must win over a
    # generic fallback further down (e.g. "letter writing"/"paragraph writing" over bare "writing";
    # "vocabulary" over the bare "incomplete sentence" fill-in-the-blank boilerplate shared by both a
    # grammar and a vocabulary section). skill_strand() returns on the FIRST match, so order is the rule.
    ("spelling", "Spelling"),
    ("punctuation", "Punctuation & Capitalization"),
    ("capitalization", "Punctuation & Capitalization"),
    ("paragraph coherence", "Paragraph Coherence"),
    ("letter writing", "Letter Writing"),
    ("paragraph writing", "Paragraph Writing"),
    ("reading passage", "Reading Comprehension"),
    ("reading comprehension", "Reading Comprehension"),
    ("comprehnsion", "Reading Comprehension"),  # confirmed real typo in a loaded paper's own section heading
    ("classification", "Classification"),
    ("sentence correction", "Sentence Correction"),
    ("analogy", "Analogy"),
    ("antonym", "Antonyms"),
    ("synonym", "Synonyms"),
    ("word substitution", "Word Substitution"),
    ("substitution", "Word Substitution"),  # a paper's own heading sometimes drops "word" ("Substitution (47-57)")
    ("completion", "Sentence Completion"),
    ("sentence comprehension", "Sentence Comprehension"),
    ("complete the dialogue", "Sentence Comprehension"),
    ("communicative activities", "Sentence Comprehension"),  # same dialogue-completion skill, bare section heading
    ("quantitative reasoning", "Quantitative Reasoning"),
    ("use the information given in the table", "Quantitative Reasoning"),  # a table-based item whose own section
    ("based on the data given in the table", "Quantitative Reasoning"),    # heading didn't repeat "Quantitative
    ("based on the table", "Quantitative Reasoning"),                      # Reasoning" (confirmed: SAT items 56-60)
    ("compare quantity", "Quantitative Reasoning"),
    ("vocabulary", "Vocabulary"),
    ("meaning of the underlined", "Vocabulary"),
    ("word order", "Word Order"),
    ("not in the right order", "Word Order"),
    ("language focus", "Grammar"),
    ("writing", "Writing"),  # generic - after letter/paragraph writing above, which are the specific cases
    # Lowest priority: the bare "fill in the blank, choose the word/phrase that completes the sentence"
    # instruction text is reused for BOTH a grammar section and a vocabulary section in the same paper,
    # distinguished only by whether the heading itself said "Vocabulary" - so this only ever fires once
    # every more specific label above it has already failed to match.
    ("incomplete sentence", "Grammar"),
]


def skill_strand(q: EsslceQuestion) -> str | None:
    """A deterministic (no LLM) skill-strand label for a question, for subjects that aren't organized by
    textbook topic - parallel to best_unit(), but along the skill axis (Grammar, Vocabulary, Reading
    Comprehension, ...) rather than the topic axis. A self-contained reading-comprehension item is
    unambiguous (it has a passage); everything else is read off the exam's own section/part headings.
    None when nothing is recognized - never guessed."""
    if q.passage_id is not None:
        return "Reading Comprehension"
    haystack = f"{q.part or ''} {q.section or ''}".lower()
    for needle, label in _SKILL_STRAND_KEYWORDS:
        if needle in haystack:
            return label
    return None


def eligible_skill_strands(db, subject: str) -> list:
    """Skill strands with >=1 eligible question, for a student-facing picker - parallel to eligible_units(),
    along the skill axis instead of the topic axis."""
    counts: dict = {}
    for paper in db.query(EsslcePaper).filter(EsslcePaper.subject == subject).all():
        for question in paper.questions:
            if not eligible(question):
                continue
            strand = skill_strand(question)
            if strand is None:
                continue
            counts[strand] = counts.get(strand, 0) + 1
    return [{"skill": s, "questions": n} for s, n in sorted(counts.items())]


def diagnostic_questions(db, subject: str, count: int = 15, stream: str | None = None) -> list:
    """A fixed, one-shot set of questions DELIBERATELY spread across this subject's units/skills, for a
    baseline check - unlike practice.selection.pick_questions (optimized for mastery over an ongoing
    session), this optimizes for topic COVERAGE in a single short test. Round-robins one question per
    topic group (best_unit, falling back to skill_strand, falling back to "uncategorized") in stable
    sorted order, cycling until `count` is reached or every eligible question has been used. Never
    excludes previously-attempted questions - this is a rough baseline, not a bias-controlled instrument,
    and over-engineering that guarantee isn't worth it for a once-in-a-while check."""
    papers_q = db.query(EsslcePaper).filter(EsslcePaper.subject == subject)
    if stream:
        papers_q = papers_q.filter(EsslcePaper.stream == stream)
    groups: dict = {}
    for paper in papers_q.all():
        for q in paper.questions:
            if not eligible(q):
                continue
            unit_info = best_unit(q)
            key = f"unit:{unit_info[0]}:{unit_info[1]}" if unit_info else None
            if key is None:
                strand = skill_strand(q)
                key = f"skill:{strand}" if strand else "uncategorized"
            groups.setdefault(key, []).append(q)

    picked: list = []
    group_keys = sorted(groups)
    cursors = {k: 0 for k in group_keys}
    while len(picked) < count and any(cursors[k] < len(groups[k]) for k in group_keys):
        for k in group_keys:
            if cursors[k] < len(groups[k]):
                picked.append(groups[k][cursors[k]])
                cursors[k] += 1
                if len(picked) >= count:
                    break
    return picked


def eligible_units(db, subject: str) -> list:
    """Units with >=1 eligible (approved, keyed, no-diagram) question, for a student-facing unit picker -
    unlike unit_stats (admin-facing, counts every loaded question regardless of review state), this only
    ever surfaces what a student could actually be served right now."""
    counts: dict = {}
    for paper in db.query(EsslcePaper).filter(EsslcePaper.subject == subject).all():
        for question in paper.questions:
            if not eligible(question):
                continue
            unit_info = best_unit(question)
            if unit_info is None:
                continue
            grade, unit, _ = unit_info
            counts[(grade, unit)] = counts.get((grade, unit), 0) + 1
    return [
        {"grade": grade, "unit": unit, "questions": n}
        for (grade, unit), n in sorted(counts.items())
    ]


# ---------------------------------------------------------------------------- student progress + recommendation
# Fewer attempts than this isn't a real signal that a topic is weak - it's noise from one lucky or unlucky
# guess (GPT's own review of this project put it well: "do not label a topic mastered based on one correct
# answer" - the same caution applies in the other direction, to calling something weak).
MIN_ATTEMPTS_FOR_SIGNAL = 3


def student_progress(db, user_id, subject: str) -> dict:
    """Per-unit and per-skill-strand accuracy for one student in one subject, from their own attempt
    history. The LATEST attempt per question wins (same ordered-by-timestamp pattern as /next's practice
    pool and /exam-summary), so retrying a question updates its contribution instead of double-counting
    both tries. Units and skills are two independent breakdowns of the SAME attempts (a Reading
    Comprehension item has both a unit via best_unit() and a skill via skill_strand()) - a student can see
    either axis, whichever the subject actually has."""
    paper_ids = [
        p.id for p in db.query(EsslcePaper.id).filter(EsslcePaper.subject == subject).all()
    ]
    empty = {"units": [], "skills": [], "attempted": 0, "correct": 0}
    if not paper_ids:
        return empty

    latest: dict[int, bool] = {}
    for qid, ok, _ts in (
        db.query(EsslceAttempt.question_id, EsslceAttempt.is_correct, EsslceAttempt.created_at)
        .filter(EsslceAttempt.user_id == user_id, EsslceAttempt.paper_id.in_(paper_ids))
        .order_by(EsslceAttempt.created_at)
    ):
        latest[qid] = ok  # ordered by time, so the latest attempt wins
    if not latest:
        return empty

    questions = {
        q.id: q
        for q in db.query(EsslceQuestion).filter(EsslceQuestion.id.in_(latest.keys())).all()
    }

    unit_rows: dict = {}
    skill_rows: dict = {}
    for qid, ok in latest.items():
        q = questions.get(qid)
        if q is None:
            continue
        unit_info = best_unit(q)
        if unit_info is not None:
            grade, unit, _verified = unit_info
            row = unit_rows.setdefault(
                (grade, unit), {"grade": grade, "unit": unit, "attempted": 0, "correct": 0}
            )
            row["attempted"] += 1
            row["correct"] += int(ok)
        strand = skill_strand(q)
        if strand is not None:
            row = skill_rows.setdefault(strand, {"skill": strand, "attempted": 0, "correct": 0})
            row["attempted"] += 1
            row["correct"] += int(ok)

    for row in list(unit_rows.values()) + list(skill_rows.values()):
        row["accuracy"] = row["correct"] / row["attempted"]

    return {
        "units": sorted(unit_rows.values(), key=lambda r: (r["accuracy"], -r["attempted"])),
        "skills": sorted(skill_rows.values(), key=lambda r: (r["accuracy"], -r["attempted"])),
        "attempted": len(latest),
        "correct": sum(latest.values()),
    }


def recommend_focus(progress: dict) -> dict | None:
    """The single lowest-accuracy unit or skill with enough attempts to be a real signal - None when
    nothing has reached MIN_ATTEMPTS_FOR_SIGNAL yet, rather than guessing from too little data."""
    candidates = [
        {**r, "kind": "unit", "skill": None}
        for r in progress["units"]
        if r["attempted"] >= MIN_ATTEMPTS_FOR_SIGNAL
    ] + [
        {**r, "kind": "skill", "grade": None, "unit": None}
        for r in progress["skills"]
        if r["attempted"] >= MIN_ATTEMPTS_FOR_SIGNAL
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda r: r["accuracy"])


# ---------------------------------------------------------------------------- status
def status_rows(db) -> list:
    out = []
    for p in (
        db.query(EsslcePaper).order_by(EsslcePaper.subject, EsslcePaper.year_ec).all()
    ):
        qs = p.questions
        counts = {}
        for q in qs:
            counts[q.review_status] = counts.get(q.review_status, 0) + 1
        out.append(
            {
                "paper": f"{p.subject} {p.year_ec} E.C. {p.stream} {p.round} "
                f"{p.region} {p.delivery_mode}".strip(),
                "questions": len(qs),
                "complete": paper_complete(p),
                "flagged": sum(1 for q in qs if q.flags),
                "keyed": sum(1 for q in qs if q.answer_index is not None),
                "ready_for_students": sum(1 for q in qs if eligible(q)),
                "links": sum(len(q.links) for q in qs),
                "minutes": p.duration_minutes,
                "by_status": counts,
            }
        )
    return out
