"""Parsing, validation and cross-checking of transcribed exam pages. No database, no model calls.

Markup (what the vision model writes, one page at a time; see extract.PROMPT):
  @part <text> | @section <text> | @passage <id> | <title>
  P<n>: <paragraph>            P<n>+: <continuation of that paragraph from the previous page>
  SOURCE: <text>
  Q<n> | <stem>                Q<n>+ | <continuation of that stem from the previous page>
  A. / B. / C. / D. <option>   (option lines may start a page: they continue the question of the previous page)
  DIAGRAM: <description>       the question needs a figure the text cannot carry
  [[word]] underlined, **word** bold
"""

import collections
import difflib
import re

# The period delimiter is what extract.PROMPT asks for, but a vision model occasionally mirrors the
# SOURCE page's own "A) ..." parenthesis style instead of normalizing it - confirmed for real on the
# 2005-2010 EC web-archive batch, whose own pages print options that way, and losing a whole page's
# worth of options to this one formatting slip is a real, repeated failure mode, not a hypothetical.
OPT = re.compile(r"^([A-D])[.)]\s?(.*)$")
# A further variant of the same source-mirroring habit, also confirmed for real: on one page the model
# wrote EVERY option line with the same constant "A." marker, regardless of true position, and instead
# put the real letter inside the text itself in the source's own style ("A. B) Ribosome", "A. C) DNA
# strand", ...) - so OPT alone would file every option of every question on the page under "A", silently
# discarding the rest. Whenever an OPT match's own text itself starts with "<letter>)", that embedded
# letter is the real one (even when it agrees with OPT's own letter, in which case this just strips the
# redundant duplicate marker from the stored text).
_DOUBLED_LETTER = re.compile(r"^([A-D])\)\s*(.*)$")
# A real @part/@section is always Roman-numeral-prefixed ("I. CHEMISTRY", "II. LANGUAGE FOCUS" -
# see extract.PROMPT); items are always Arabic-digit-prefixed ("34. ..."). So an @part/@section whose
# text starts with a plain number is never a real heading - it's the model misclassifying the start of
# a question, most often item 1 right after the directions, or any item right after a part/section change.
_MISCLASSIFIED_ITEM = re.compile(r"^(\d+)\.\s*(.*)$")


def _new_question(n, stem, cur_page, part, section, cur_pass, provisional=False):
    q = {
        "n": n,
        "stem": stem,
        "options": {},
        "printed_page": cur_page,
        "part": part,
        "section": section,
        # cur_pass is the passage an @passage tag opened earlier on this page or an earlier one, still in
        # effect because no @part/@section has fired since (a multi-page passage's own continuation lines,
        # "P1+: ..."/option lines, carry no tag at all - confirmed for real: a 4-item SAT Reading
        # Comprehension question block and a 14-item English one both spanned a page break with no
        # @passage line repeated on the later page, leaving every one of those questions unlinked before
        # this fix, even though the actual passage text was transcribed correctly and sitting right there).
        "passage": cur_pass,
        "diagram": None,
        "provisional": provisional,
    }
    if q["passage"] is None:
        # Fallback for a section heading that names the passage directly but never got its own @passage
        # tag (a separate, narrower transcription miss from the one above - kept as a second safety net).
        if section and "Reading Passage II" in section:
            q["passage"] = "P2"
        elif section and "Reading Passage I" in section:
            q["passage"] = "P1"
    return q


def parse_transcript(text: str) -> dict:
    qs, passages, problems = [], {}, []
    cur_page = part = section = cur_pass = None
    q = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("@page"):
            cur_page = int(
                line.split()[1]
            )  # q is kept: options may continue from the previous page
            continue
        if line.startswith("@part"):
            text_ = line[5:].strip()
            m = _MISCLASSIFIED_ITEM.match(text_)
            if m:
                # Provisional: a digit-prefixed @part is ALSO how a numbered bullet in the boilerplate
                # "GENERAL DIRECTIONS" cover-page text comes through (e.g. "1. FOLLOW THE FOLLOWING RULES
                # AND REGULATIONS...") - that is never a real question and never gets option lines after
                # it, unlike a genuinely misclassified item. Resolved once parsing finishes (see below):
                # kept only if it ended up with real options, dropped (and reported) otherwise.
                q = _new_question(int(m.group(1)), m.group(2), cur_page, part, section, cur_pass, provisional=True)
                qs.append(q)
                continue
            # A genuine new @part always ends whatever reading passage was active - a passage's own
            # continuation lines carry no tag of their own (see _new_question), so the only reliable signal
            # that one has ended is a real heading change to something else.
            part, q, cur_pass = text_, None, None
            continue
        if line.startswith("@section"):
            text_ = line[8:].strip()
            m = _MISCLASSIFIED_ITEM.match(text_)
            if m:
                q = _new_question(int(m.group(1)), m.group(2), cur_page, part, section, cur_pass, provisional=True)
                qs.append(q)
                continue
            section, q, cur_pass = text_, None, None
            continue
        if line.startswith("@passage"):
            head, _, title = line[8:].partition("|")
            pid, title = head.strip() or f"P{len(passages) + 1}", title.strip()
            if pid in passages and title and passages[pid]["title"] and title != passages[pid]["title"]:
                # Each page is transcribed in isolation (extract.transcribe_page has no memory of earlier
                # pages), so the model reliably defaults to "P1" every time a NEW reading passage starts,
                # even when an earlier, different passage already claimed that id (seen in real data: two
                # distinct ESSLCE reading passages both declared "@passage P1", silently overwriting the
                # first in this dict). A different title under the same id is the signal this is a
                # genuinely different passage, not a real reference back to the earlier one.
                pid = f"P{len(passages) + 1}"
            passages[pid] = {
                "id": pid,
                "title": title,
                "paragraphs": [],
                "source": None,
                "pages": set(),
            }
            cur_pass, q = pid, None
            continue
        m = re.match(r"^P(\d+)\+:\s*(.*)$", line)
        if m and cur_pass and passages[cur_pass]["paragraphs"]:
            passages[cur_pass]["paragraphs"][-1]["text"] += " " + m.group(2).strip()
            passages[cur_pass]["pages"].add(cur_page)
            continue
        m = re.match(r"^P(\d+):\s*(.*)$", line)
        if m and cur_pass:
            passages[cur_pass]["paragraphs"].append(
                {"n": int(m.group(1)), "text": m.group(2)}
            )
            passages[cur_pass]["pages"].add(cur_page)
            q = None
            continue
        if line.startswith("SOURCE:") and cur_pass:
            passages[cur_pass]["source"] = line[7:].strip()
            continue
        m = re.match(r"^Q(\d+)\.?\+\s*\|?\s*(.*)$", line)
        if m:
            n = int(m.group(1))
            if q is not None and q["n"] == n:
                q["stem"] += " " + m.group(2).strip()
                continue
            if n not in {qq["n"] for qq in qs}:
                # Claims to continue an earlier item, but item n was never opened - the model mislabeled
                # a FRESH item's opening line as a continuation (seen in real data: two items of a real
                # English paper, each fully self-contained on one page with no actual split). Recover it
                # as a new question rather than dropping it, but flag it: unlike the Arabic-digit
                # @section/@part recovery above, there's no second signal confirming this is safe.
                q = _new_question(n, m.group(2), cur_page, part, section, cur_pass)
                qs.append(q)
                problems.append(
                    f"Q{n}: recovered from an unmatched '+' continuation marker - verify it's complete"
                )
                continue
            # else: n was seen before but isn't the current question - a genuinely orphaned continuation,
            # falls through to the catch-all below like any other unattached line
        # The pipe is optional (see extract._KEEP's comment): a source page's own "59. stem" style,
        # mirrored instead of normalized to "Q59 | stem", must still open a new question here - not fall
        # through and silently pile its options onto whatever question was last open.
        m = re.match(r"^Q(\d+)\.?\s*\|?\s*(.*)$", line)
        if m:
            q = _new_question(int(m.group(1)), m.group(2), cur_page, part, section, cur_pass)
            qs.append(q)
            continue
        if line.startswith("DIAGRAM:") and q is not None:
            q["diagram"] = line[8:].strip()
            continue
        m = OPT.match(line)
        if m and q is not None:
            letter, text = m.group(1), m.group(2)
            doubled = _DOUBLED_LETTER.match(text)
            if doubled:
                letter, text = doubled.group(1), doubled.group(2)
            if letter in q["options"]:
                # A genuine continuation only ever fills in a MISSING option, never re-sets one already
                # present - this means a DIFFERENT question's options arrived with no opening Q line (the
                # model dropped that line entirely). Silently accepting them would overwrite q's real
                # answer with no warning at all (seen in real data: one question's options replaced
                # another's this way, undetected until a human happened to re-check the photo).
                problems.append(
                    f"Q{q['n']}: option {letter} already set - a later question's options may have "
                    f"arrived with no opening Q line (dropped): {line[:80]!r}"
                )
                continue
            q["options"][letter] = text.strip()
            continue
        # A bare "75. stem" with no @part/@section wrapper and no "Q" at all - the same source-mirroring
        # habit _MISCLASSIFIED_ITEM already recovers above when the model at least tagged it as a
        # heading, now with no tag at all (confirmed for real: 3 consecutive items lost this way on one
        # page, no @part/@section line in sight). Provisional for the same reason as those two: a bare
        # numbered bullet in boilerplate directions text matches this shape too and is never a real
        # question - the cleanup pass below keeps it only if it ended up with real options.
        m = _MISCLASSIFIED_ITEM.match(line)
        if m:
            q = _new_question(int(m.group(1)), m.group(2), cur_page, part, section, cur_pass, provisional=True)
            qs.append(q)
            continue
        # Not attached to any open question - almost always means an earlier line that SHOULD have
        # opened one (a Q line, or an item the model mistagged as @section/@passage/etc in a way the
        # recoveries above didn't catch) was itself lost. Drop it and say so rather than aborting the
        # whole transcript: the missing item still surfaces as a "missing question numbers" FAIL below,
        # which `load` already refuses unless told --allow-incomplete.
        problems.append(f"page {cur_page}: not attached to any question (dropped): {line[:80]!r}")
    for p in passages.values():
        p["pages"] = sorted(x for x in p["pages"] if x)
    kept = []
    for q in qs:
        provisional = q.pop("provisional", False)
        if provisional and not q["options"]:
            problems.append(
                f"page {q['printed_page']}: a '{q['part'] or q['section']}' heading starting with "
                f"'{q['n']}.' never got any options - treated as boilerplate/heading text, not "
                f"item {q['n']} (dropped: {q['stem'][:80]!r})"
            )
            continue
        kept.append(q)
    return {"questions": kept, "passages": passages, "problems": problems}


def validate(parsed: dict, expected=range(1, 101)) -> list:
    issues = []
    ns = [q["n"] for q in parsed["questions"]]
    missing = [n for n in expected if n not in ns]
    dup = [n for n, c in collections.Counter(ns).items() if c > 1]
    if missing:
        issues.append(("FAIL", f"missing question numbers: {missing}"))
    if dup:
        issues.append(("FAIL", f"duplicate question numbers: {dup}"))
    if ns != sorted(ns):
        issues.append(("FAIL", "questions are not in increasing order"))
    for q in parsed["questions"]:
        n, opts = q["n"], q["options"]
        if sorted(opts) != list("ABCD"):
            issues.append(("FAIL", f"Q{n}: options present {sorted(opts)}"))
        texts = [
            re.sub(r"\s+", " ", t).strip() for t in opts.values()
        ]  # exact: case/punctuation items differ only there
        # All four options blank, WITH a diagram note, is a real shape (e.g. "which of these four
        # DIAGRAMS shows..." - the options are pictures, never text) - not a transcription failure.
        # A diagram note with only SOME options blank, or non-identical real text that happens to
        # repeat, is still a genuine issue and still flagged below.
        all_blank_with_diagram = q["diagram"] and all(not t for t in texts)
        if not all_blank_with_diagram:
            if len(set(texts)) != len(texts):
                issues.append(("FAIL", f"Q{n}: two identical options"))
            if any(not t for t in texts):
                issues.append(("FAIL", f"Q{n}: an empty option"))
        if "[?]" in q["stem"] or any("[?]" in t for t in texts):
            issues.append(("WARN", f"Q{n}: the model marked unreadable text [?]"))
        if len(q["stem"].strip()) < 3:
            issues.append(("WARN", f"Q{n}: empty stem (instructions-only item?)"))
        if q["stem"].count("[[") != q["stem"].count("]]"):
            issues.append(("FAIL", f"Q{n}: unbalanced underline marks"))
        if q["passage"] and not parsed["passages"].get(q["passage"], {}).get(
            "paragraphs"
        ):
            issues.append(("FAIL", f"Q{n}: passage {q['passage']} has no text"))
    return issues


STOP = set(
    """the and for that this with from have has had was were are not but you your his her their they them our
what when which who whom whose where why how all any can could would should will shall may might must one two than then
there these those been being into onto over under about after before while also such only very more most some other each
both either neither just like too its it's don't didn't isn't is a an of to in on at by as or if so no do does did be""".split()
)


def words(s):
    return [
        w
        for w in re.findall(r"[a-z']+", s.lower().replace("\u2019", "'"))
        if len(w) > 3 and w not in STOP
    ]


def ocr_crosscheck(parsed: dict, ocr_pages: dict, threshold=0.6) -> list:
    """Stem and options are checked separately: share of their content words found on the question's page
    (or the next) in an INDEPENDENT OCR pass. ocr_pages: {printed page: [lines]}. Low = look at the photo."""
    bag = {int(p): set(words(" ".join(lines))) for p, lines in ocr_pages.items()}
    out = []
    for q in parsed["questions"]:
        pg = q["printed_page"]
        vocab = bag.get(pg, set()) | bag.get(pg + 1, set())
        parts = {
            "stem": words(q["stem"].replace("[[", "").replace("]]", "")),
            "options": words(" ".join(q["options"].values())),
        }
        worst, which = 1.0, None
        for name, ws in parts.items():
            if len(ws) < 2:
                continue
            hit = sum(
                1
                for w in ws
                if w in vocab or difflib.get_close_matches(w, vocab, n=1, cutoff=0.8)
            )
            if hit / len(ws) < worst:
                worst, which = hit / len(ws), name
        if worst < threshold:
            out.append((q["n"], round(worst, 2), pg, which))
    return out


def question_flags(parsed: dict, issues: list, ocr_low: list) -> dict:
    """{question number: [flag, ...]} so a reviewer sees WHY an item needs a look."""
    flags = collections.defaultdict(list)
    for lvl, msg in issues:
        m = re.match(r"Q(\d+):\s*(.*)", msg)
        if m:
            flags[int(m.group(1))].append(m.group(2))
    for n, share, pg, which in ocr_low:
        flags[n].append(
            f"ocr_mismatch: only {share:.0%} of {which} words confirmed by an independent OCR (page {pg})"
        )
    for q in parsed["questions"]:
        if q["diagram"]:
            flags[q["n"]].append("needs_figure")
    return dict(flags)


def to_records(parsed: dict, flags: dict) -> list:
    recs = []
    for q in parsed["questions"]:
        recs.append(
            {
                "item_no": q["n"],
                "part": q["part"],
                "section": q["section"],
                "stem": q["stem"].replace("[[", "").replace("]]", "").strip(),
                "underlined": re.findall(r"\[\[(.+?)\]\]", q["stem"]),
                "options": [q["options"].get(k, "") for k in "ABCD"],
                "passage_key": q["passage"],
                "printed_page": q["printed_page"],
                "has_diagram": bool(q["diagram"]),
                "diagram_note": q["diagram"],
                "flags": flags.get(q["n"], []),
            }
        )
    return recs
