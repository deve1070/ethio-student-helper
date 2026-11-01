"""Generates and caches a Study Note: a hierarchical breakdown of a whole textbook unit into subtopics
(+ key formulas and a worked example for calculation subjects), grounded in the textbook corpus the same
way ESSLCE elaborations are - retrieval, quote-verification, and a deterministic citation per subtopic,
never a bare LLM claim. Pure content generation; the caller (api/routes_notes.py) handles the DB cache
lookup and LaTeX-to-PNG rendering.

Section NUMBERING ("3.1", "3.1.2", ...) is assigned deterministically in code from the unit's own
leading number and each section's position - never trusted from the LLM's own text - but the numbers
are an organizational aid for studying, not a claim that they match the student's physical textbook's
own printed subsection numbers: real ingested chunk.section metadata is too inconsistent (often a
trailing caption or figure label, not a clean heading) to reconstruct the book's actual numbering."""

import re
from typing import Callable

from config.constants import CALCULATION_SUBJECTS, LANGUAGE_SKILL_SUBJECTS
from db.models import Chunk, Textbook
from llm.client import parse_json_object
from practice.validate import quote_in_passage
from retriever.citation import citation_for
from utils.units import unit_sort_key

from .models import StudyNote

UNIT_RETRIEVAL_K = 40  # generous enough to cover a whole unit's real content (seen up to ~80 chunks) -
# MAX_CONTEXT_CHARS below is what actually keeps the prompt within budget, since chunk length varies a
# lot (a long unit's 40 chunks can be 2-3x the characters of a short unit's 40 chunks)

# This account's Groq tier hard-caps a single request at 8000 tokens (input + the max_tokens reserved for
# output) - not a transient rate limit retrying can wait out, since the SAME oversized request fails the
# same way every time. A rich unit (many sections) also needs real output room, or the reply truncates
# mid-JSON and fails to parse (a second failure mode, distinct from the 8000-token ceiling, found when
# testing against a 15-section real unit) - 10000 chars of context (~2500 tokens) + the ~1700-char prompt
# template + a 2800-token output reservation (api/routes_notes.py) stays comfortably under the ceiling
# while still leaving enough output budget for a genuinely comprehensive breakdown to complete.
MAX_CONTEXT_CHARS = 10000


def available_subjects(db, grade: int) -> list[str]:
    """Subjects with at least one indexed textbook chunk for this grade."""
    return sorted(s for (s,) in db.query(Textbook.subject).filter(Textbook.grade == grade).distinct().all())


def available_units(db, grade: int, subject: str) -> list[str]:
    """Units with at least one indexed textbook chunk for this grade+subject, in natural textbook order."""
    rows = (
        db.query(Chunk.unit_or_chapter)
        .join(Textbook, Chunk.textbook_id == Textbook.id)
        .filter(Textbook.grade == grade, Textbook.subject == subject, Chunk.unit_or_chapter.isnot(None))
        .distinct()
        .all()
    )
    return sorted({u for (u,) in rows}, key=unit_sort_key)


UNIT_PROMPT = """You are writing hierarchical Study Notes for an Ethiopian Grade {grade} student on the \
topic "{unit}" ({subject}), based ONLY on the excerpts below, which cover the unit's content across many \
pages.

Break the unit into a hierarchical outline of subtopics that together cover everything the excerpts \
actually discuss - not just one part of the unit. Use two levels: a level-1 entry for each major theme, \
and a level-2 entry for a theme that genuinely needs breaking down further (not every level-1 topic needs \
sub-topics - use level 2 only where it earns its place).

For EACH entry (either level), give:
- "heading": a short, clear title (a few words - do NOT include any number, numbering is added separately)
- "level": 1 or 2 (a level-2 entry is a sub-topic of the level-1 entry immediately before it)
- "summary": 2-4 sentences grounded in the excerpts
- "source_index": the index of the ONE excerpt below that most directly supports that summary
- "supporting_quote": one verbatim quote from that excerpt backing the summary

Also write "overview": a 1-2 sentence overview of the whole unit, written after you've worked out the \
subtopics below it.

Excerpts:
{context}

Reply with ONLY a JSON object, no other text:
{{"overview": "...", "sections": [{{"heading": "...", "level": 1, "summary": "...", "source_index": 0, \
"supporting_quote": "..."}}, ...]}}
Include as many sections as the excerpts genuinely support - do not pad with filler, and do not invent \
content the excerpts don't contain. If the excerpts don't let you ground any real subtopic, reply \
{{"overview": null, "sections": []}} - no notes are better than ungrounded ones."""

# English units are named after a real-world theme ("Sustainable Development", "Crime") only because
# that theme supplies a reading passage or vocabulary list to practice on - it is never the unit's own
# taught content, and ESSLCE tests the language point, not the theme. A FULL separate prompt, not an
# addendum appended after UNIT_PROMPT's own generic schema: two rounds of appending extra rules after
# UNIT_PROMPT's "summary: 2-4 sentences" field description were both confirmed, live, to be followed only
# partially. Putting the real requirement (state the rule/meaning, back it with real examples - for both
# grammar AND vocabulary) INTO the field's own description, with nothing generic stated earlier to
# half-override, is what actually changed the output - confirmed by re-running against the same live unit.
# How MANY examples, and exactly how to teach a given point, is deliberately left to the model's own
# judgement per point and grade level (never a fixed count or a forced template) - confirmed directly by
# the user: over-constraining this produced correct but needlessly rigid, same-shaped notes. The one
# non-negotiable is that a point is actually explained with real examples, not just named or described as
# an activity. The JSON contract (overview/sections/heading/level/summary/source_index/supporting_quote)
# is identical to UNIT_PROMPT's, so numbering, citation and quote-verification are unaffected by which
# prompt produced the reply.
ENGLISH_UNIT_PROMPT = """You are writing hierarchical Study Notes for an Ethiopian Grade {grade} student on \
the English unit "{unit}", based ONLY on the excerpts below, which cover the unit's content across many \
pages.

This is an English LANGUAGE unit, not a content-knowledge unit. "{unit}" is only a real-world theme that \
supplies a reading passage or vocabulary list to practice on - it is NOT what this unit teaches, and not \
what these notes are about. These notes are about the LANGUAGE content the excerpts actually teach: a \
grammar point (a tense, clause type, voice, question form, reported speech rule, ...), vocabulary or \
word-formation, a reading/listening sub-skill (skimming, scanning, inference, ...), or a writing/speaking \
function (a letter format, an essay structure, a debate technique, ...). If the theme comes up in a \
section at all, it is only as a one-line example of what the language point was practiced on - never make \
the theme itself the subject of a section.

Break the unit into a hierarchical outline of its language points - not just one part of the unit, all of \
them. Use two levels: a level-1 entry per major point, and a level-2 entry only where a point genuinely \
needs breaking down further.

For EACH entry (either level), give:
- "heading": a short, clear title naming the language point (a few words, no number)
- "level": 1 or 2 (a level-2 entry is a sub-topic of the level-1 entry immediately before it)
- "source_index": the index of the ONE excerpt below that most directly supports this point
- "supporting_quote": one verbatim quote from that excerpt, anchoring that this point is really taught \
here (it does not have to contain the definition/example itself - the excerpt usually only poses the \
exercise, not the rule)
- "summary": the point, actually TAUGHT - however long that genuinely takes, there is no sentence limit \
and no fixed template here, and anything that skips what's below has not done the job:
  - State the rule/meaning itself (a grammar point's form/structure and when/why it's used; a vocabulary \
item's plain-language meaning) - never just name or describe the activity ("students practice/discuss/\
explore X") without ever stating what X actually is. Naming a general grammatical category is not stating \
it either: "an auxiliary verb that matches the statement" does not say what the real candidate words ARE \
(do/does/did; is/am/are/was/were; has/have/had; will/would; can/could; ...) or how one is picked for a \
given sentence - state the actual words and show, with an example, how the choice is made; a student \
cannot apply a rule described only by the grammatical label for its parts.
  - If the point is really a SET of related items - cohesive devices/connectors, a group of auxiliary or \
modal verbs, two tenses that are often confused, several prepositions with overlapping uses - teach EVERY \
item in that set on its own terms, not the set as one blurred idea: its own specific meaning/use, stated \
so it could not be swapped for a sibling's description, and its own example. "Moreover, besides, and \
furthermore all add information" is not that - it says nothing a student couldn't already guess, and \
does not let them choose correctly between the three. "Moreover introduces a further point that \
strengthens what was just said; besides adds a less central, almost incidental point; furthermore adds a \
new point as formally as moreover but without moreover's emphasis" - each with its own example sentence - \
is. English is not taught by saying a word or form "is used for" something in the abstract; it is taught \
by showing it in action and setting it against its near-neighbours so the difference is concrete, the same \
way a vocabulary definition already has to stand on its own and not just say "a word related to the \
topic".
  - Include real example sentences showing it in use - for ANY point, grammar or vocabulary alike, not \
examples for one kind and not the other, and for EVERY item of a set as just described, not a shared \
example for the whole set. YOU decide how many beyond that floor: enough that a Grade {grade} student can \
see the point actually working and would recognize it in a new sentence, not an arbitrary fixed count on \
top of what's required above. Mark each one clearly as an example (e.g. starting it with the word \
"Example:") so it reads as separate from the explanation.
  - If the excerpt itself doesn't spell out a definition, rule, or example (it usually won't - it only \
poses the exercise), supply the correct one yourself from your own knowledge of English, pitched at this \
grade level - the supporting_quote still proves this point is really taught in this unit, it does not \
have to be where the explanation or examples came from.

Also write "overview": a 1-2 sentence overview of the whole unit's language content, written after you've \
worked out the points below it.

Excerpts:
{context}

Reply with ONLY a JSON object, no other text:
{{"overview": "...", "sections": [{{"heading": "...", "level": 1, "summary": "...", "source_index": 0, \
"supporting_quote": "..."}}, ...]}}
Include as many sections as the excerpts genuinely support - do not pad with filler, and do not invent \
content the excerpts don't contain. If the excerpts don't let you ground any real point, reply \
{{"overview": null, "sections": []}} - no notes are better than ungrounded ones."""

CALC_SUPPLEMENT_PROMPT = """For the same topic "{unit}" ({subject}, Grade {grade}), using ONLY the \
excerpts below:
1. List the key formulas a student needs for this topic, each as a separate LaTeX fragment.
2. Write ONE worked example applying one of these formulas, solved step by step.

Excerpts:
{context}

Reply with ONLY a JSON object, no other text:
{{"key_formulas": ["...", "..."], "worked_example": "the full worked example, with LaTeX"}}
If the excerpts don't contain any real formulas for this topic, reply \
{{"key_formulas": [], "worked_example": null}}."""


def _retrieve_unit(tb_store, grade: int, subject: str, unit: str, k: int = UNIT_RETRIEVAL_K):
    """Chunks actually tagged with this (grade, subject, unit) - a topic-scoped search, not the broader
    cross-grade search a single exam question needs (exams.store.retrieve_cross_grade): a Study Note is
    about one textbook's own unit, not "wherever this concept shows up across every grade". k is large
    enough that, for most units, this returns everything tagged with this unit, not just a "top-k most
    similar to the unit title" slice - a whole-unit breakdown needs the whole unit's content."""
    flt = {"$and": [{"subject": subject}, {"grade": grade}, {"unit": unit}]}
    hits = tb_store.similarity_search_with_score(unit, k=k, filter=flt)
    return [doc for doc, _dist in hits]


def _cap_by_chars(docs: list, max_chars: int = MAX_CONTEXT_CHARS) -> list:
    """Keeps docs (already similarity-ranked by _retrieve_unit) up to a cumulative character budget, not
    just a fixed count - chunk length varies enough between units that a fixed chunk count alone doesn't
    reliably bound the prompt size (see MAX_CONTEXT_CHARS). Always keeps at least one doc, even if it
    alone exceeds the budget, so a single oversized chunk never empties the context entirely."""
    kept, total = [], 0
    for d in docs:
        if kept and total + len(d.page_content) > max_chars:
            break
        kept.append(d)
        total += len(d.page_content)
    return kept


def _unit_number(unit: str) -> str | None:
    m = re.search(r"\d+", unit or "")
    return m.group() if m else None


def _numbered_sections(db, data: dict, excerpts: list[str], vector_ids: list[str | None], unit_num: str | None):
    """Verifies each proposed section's quote independently and drops any that fail - one bad citation
    never fails the whole note, the same graceful-degradation the calc supplement already uses below.
    Numbers are assigned here, in order, from `unit_num` and each kept section's own level - never
    parsed from (or trusted to be consistent in) the LLM's own output."""
    top, sub = 0, 0
    out = []
    for s in data.get("sections") or []:
        if not isinstance(s, dict):
            continue
        heading, level, summary = s.get("heading"), s.get("level"), s.get("summary")
        src_idx, quote = s.get("source_index"), s.get("supporting_quote")
        if not (isinstance(heading, str) and heading.strip() and isinstance(summary, str) and summary.strip()):
            continue
        if not isinstance(src_idx, int) or not (0 <= src_idx < len(excerpts)):
            continue
        if not isinstance(quote, str) or not quote_in_passage(quote, excerpts[src_idx]):
            continue

        if level == 2 and top > 0:
            sub += 1
            number = f"{unit_num}.{top}.{sub}" if unit_num else f"{top}.{sub}"
        else:
            top += 1
            sub = 0
            number = f"{unit_num}.{top}" if unit_num else str(top)

        out.append(
            {
                "number": number,
                "heading": heading.strip(),
                "summary": summary.strip(),
                "citation": citation_for(db, vector_ids[src_idx]),
            }
        )
    return out


def _no_example_count(sections: list) -> int:
    """How many sections have literally no example at all - a section that isn't taught at all. Cheap,
    reliable, and deterministic, so it's what picks the best of up to 3 full regenerations in the main
    retry loop below; it is NOT what decides whether a set of related items (cohesive devices, auxiliary
    verbs, ...) got each item its own differentiating example - that needs real reading comprehension, see
    _judge_sections."""
    return sum(1 for s in sections if "Example" not in (s.get("summary") or ""))


# A section naming several related items is almost always teaching a SET (cohesive devices, auxiliary/
# modal verbs, easily-confused tenses) - and the observed failure mode is listing all of them with only
# ONE shared example (or one shared example PARAGRAPH using all of them together) instead of one example
# per item. A regex-based detector for this was tried first and kept finding new disguises it couldn't
# catch: the list marked with quotes, then with **bold**, then a bare comma list in parentheses, then
# finally items simply starting consecutive sentences inside one shared example with no marking at all -
# four real, different failure shapes from the SAME prompt. Pattern-matching how a list happens to be
# typeset this one time cannot keep up with that; an LLM judge that actually reads the content for whether
# every item got its own explanation and example is what the regex was always trying to approximate.
JUDGE_PROMPT = """You are reviewing Study Notes sections written for an English language unit, Grade \
{grade}. Each section should actually TEACH what it names, not just describe it.

A section FAILS this review if it names or lists several related items - cohesive devices, auxiliary or \
modal verbs, easily-confused tenses or forms, several vocabulary words, etc. - but does NOT give EVERY \
one of those items its own specific, differentiating explanation AND its own example sentence. This \
failure can look like many things: a list with one example shared across all the items; one example \
PARAGRAPH that uses several of the items together instead of a separate example per item; items named but \
never individually defined; or any other way of naming several items without actually teaching each one \
on its own terms. A section about a SINGLE point (one grammar rule, one vocabulary word) PASSES as long as \
it has a real explanation and at least one real example - it is not required to list multiple items.

Sections (0-indexed):
{sections_block}

Reply with ONLY a JSON object, no other text: {{"failing_indices": [0, 2]}} - the 0-based indices of \
sections that fail this review (an empty list if every section passes)."""


def _judge_sections(llm, sections: list, grade: int) -> set:
    """Indices into `sections` that an LLM judge finds teach a set of related items without
    differentiating each one - see JUDGE_PROMPT's own comment for why this needs a real judge, not a
    regex. Never raises and never blocks the note on a judge failure - an empty result just means nothing
    gets sent to the repair pass, not a crashed or degraded note."""
    if not sections:
        return set()
    block = "\n\n".join(f"[{i}] {s.get('heading', '')}: {s.get('summary', '')}" for i, s in enumerate(sections))
    try:
        raw = (
            llm.chat(messages=[{"role": "user", "content": JUDGE_PROMPT.format(grade=grade, sections_block=block)}])
            ["choices"][0]["message"]["content"]
            or ""
        ).strip()
    except Exception:  # noqa: BLE001
        return set()
    data = parse_json_object(raw)
    indices = data.get("failing_indices") if data else None
    if not isinstance(indices, list):
        return set()
    return {i for i in indices if isinstance(i, int) and 0 <= i < len(sections)}


REPAIR_SECTION_PROMPT = """The following Study Notes section about an English language point is \
incomplete - it names the point (or lists several related items) but doesn't actually teach it with real \
examples, or doesn't give EVERY item of a set its own differentiating explanation and own example.

Heading: "{heading}"
Current summary: {summary}

Rewrite ONLY the summary so it actually teaches this, for a Grade {grade} student: state what it means or \
how it works, and - if it names more than one distinct item (e.g. several cohesive devices, several \
auxiliary verbs) - give EVERY one of them its own specific explanation (never one shared description for \
the whole set) and its own example sentence marked "Example:". Reply with ONLY the rewritten summary \
text - no JSON, no heading, no quotation marks around it, nothing else."""


def generate_note(
    db, llm, tb_store, grade: int, subject: str, unit: str,
    on_stage: Callable[[str], None] | None = None,
) -> dict:
    """{"resolved": False} if nothing could be grounded; otherwise the full set of StudyNote fields.
    Never raises past this function - any LLM-provider error (rate limit, request-too-large, network)
    degrades to the same unresolved result a genuinely ungroundable topic gets, rather than a raw 500.
    on_stage, if given, is called with a short human-readable label before each real step below, for
    api/routes_notes.py's SSE progress stream - a plain callback, not a generator, since this function
    is already a long, mostly-linear sequence of steps rather than a graph (contrast with
    agents/workflow.py's AgentWorkflow.stream_full_pipeline, which streams via LangGraph's own
    per-node mechanism because that pipeline already IS a graph)."""
    if on_stage is None:
        on_stage = lambda _label: None  # noqa: E731
    unresolved = {"resolved": False}
    on_stage("Reading your textbook...")
    docs = _cap_by_chars(_retrieve_unit(tb_store, grade, subject, unit))
    if not docs:
        return unresolved

    excerpts = [d.page_content for d in docs]
    vector_ids = [(d.metadata or {}).get("vector_id") for d in docs]
    context = "\n\n".join(f"[{i}] {text}" for i, text in enumerate(excerpts))

    is_english = subject in LANGUAGE_SKILL_SUBJECTS
    if is_english:
        prompt = ENGLISH_UNIT_PROMPT.format(grade=grade, unit=unit, context=context)
    else:
        prompt = UNIT_PROMPT.format(grade=grade, subject=subject, unit=unit, context=context)

    on_stage("Writing your notes...")

    # ENGLISH_UNIT_PROMPT's requirement that every point come with a real example (never just a bare
    # definition/rule statement) is NOT reliably followed every call - confirmed for real: the identical
    # prompt, same temperature=0, same unit, produced a fully compliant reply on one call and a reply with
    # zero examples (reverted to describing the classroom activity) on the very next one. This is the one
    # check cheap and reliable enough to gate a full regeneration on - up to 3 attempts, keeping whichever
    # reply has the fewest examples missing outright, not infinite, since this is quality variance to
    # reduce, not a wrong-shaped response to fix outright (unlike the JSON-parse retry below, this one
    # only applies to English). The harder "does every item of a list get its own example" nuance is
    # checked separately, after sections are built - see _judge_sections.
    best_data, best_score = None, None
    attempts = 3 if is_english else 1
    for _attempt in range(attempts):
        try:
            raw = (
                llm.chat(messages=[{"role": "user", "content": prompt}])["choices"][0]["message"]["content"] or ""
            ).strip()
        except Exception:  # noqa: BLE001 - any provider failure (too-large, rate limit, network) falls back
            continue
        data = parse_json_object(raw)
        if not data or not data.get("overview"):
            continue
        if not is_english:
            best_data = data
            break
        score = _no_example_count(data.get("sections") or [])
        if best_data is None or score < best_score:
            best_data, best_score = data, score
        if score == 0:
            break
    if best_data is None:
        return unresolved
    data = best_data

    on_stage("Adding page references...")
    sections = _numbered_sections(db, data, excerpts, vector_ids, _unit_number(unit))
    if not sections:
        return unresolved

    # Regenerating the WHOLE unit up to 3 times (above) only guards against a section with NO example at
    # all - it can't reliably fix a section that lists several related items without differentiating each
    # one, since that needs an LLM to actually read and judge the content (_judge_sections), not a cheap
    # count. And even knowing WHICH section is wrong, a full regeneration re-rolls every section at once
    # and has no way to concentrate effort on just that one - confirmed for real: the same section came
    # back defective in 3 separate full regenerations of the same unit. A focused rewrite of just that
    # section's summary - same citation, same number, only the explanation improved - is what actually
    # gets there.
    if is_english:
        on_stage("Double-checking examples...")
        for i in _judge_sections(llm, sections, grade):
            s = sections[i]
            try:
                repaired = (
                    llm.chat(
                        messages=[{
                            "role": "user",
                            "content": REPAIR_SECTION_PROMPT.format(
                                heading=s["heading"], summary=s["summary"], grade=grade
                            ),
                        }]
                    )["choices"][0]["message"]["content"]
                    or ""
                ).strip()
            except Exception:  # noqa: BLE001 - keep the original summary rather than crash the whole note
                continue
            if repaired:
                s["summary"] = repaired

    is_calculation = subject in CALCULATION_SUBJECTS
    result = {
        "resolved": True,
        "overview": data["overview"].strip(),
        "sections": sections,
        "key_formulas": None,
        "worked_example": None,
        "is_calculation": is_calculation,
    }

    if is_calculation:
        on_stage("Adding formulas and a worked example...")
        try:
            raw2 = (
                llm.chat(
                    messages=[
                        {
                            "role": "user",
                            "content": CALC_SUPPLEMENT_PROMPT.format(
                                grade=grade, subject=subject, unit=unit, context=context
                            ),
                        }
                    ]
                )["choices"][0]["message"]["content"]
                or ""
            ).strip()
        except Exception:  # noqa: BLE001 - same fallback as above: no formulas beats a crash
            raw2 = ""
        data2 = parse_json_object(raw2)
        formulas = data2.get("key_formulas") if data2 else None
        example = data2.get("worked_example") if data2 else None
        # A note without a worked example still beats no note at all (the sections are already grounded
        # and verified) - the calc supplement just doesn't resolve, it never fails the whole note.
        if isinstance(formulas, list) and isinstance(example, str) and example.strip():
            result["key_formulas"] = [f.strip() for f in formulas if isinstance(f, str) and f.strip()]
            result["worked_example"] = example.strip()

    return result


def get_or_create_note(
    db, llm, tb_store, grade: int, subject: str, unit: str,
    on_stage: Callable[[str], None] | None = None,
) -> StudyNote | None:
    """The cache lookup + generate-on-miss entry point every caller should use - never call
    generate_note directly from a route, or every request becomes a fresh (slow, costly) LLM call.
    on_stage is only ever actually called on a cache miss - a hit returns immediately, with nothing
    for a progress stream to report."""
    existing = (
        db.query(StudyNote)
        .filter(StudyNote.grade == grade, StudyNote.subject == subject, StudyNote.unit == unit)
        .one_or_none()
    )
    if existing is not None:
        return existing

    result = generate_note(db, llm, tb_store, grade, subject, unit, on_stage=on_stage)
    if not result["resolved"]:
        return None
    row = StudyNote(
        grade=grade,
        subject=subject,
        unit=unit,
        overview=result["overview"],
        sections=result["sections"],
        key_formulas=result["key_formulas"],
        worked_example=result["worked_example"],
        is_calculation=result["is_calculation"],
    )
    db.add(row)
    db.commit()
    return row
