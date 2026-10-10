"""
Helpers that work out, from a book's own text, what we used to find by hand:
  - the page offset (PDF pages before printed page 1)
  - the unit names and the PDF page where each unit starts

All functions take `pages`: the text of each PDF page as a list of strings
(use read_pages). They are plain functions, so they are easy to test.
"""
import re
from collections import Counter

import warnings

# Newer pypdfium2 prints a notice every time get_text_range() is called without
# arguments. It already behaves like get_text_bounded() (the whole page), so the
# results are the same; hide the notice so real warnings stay visible.
warnings.filterwarnings("ignore", message=r"get_text_range\(\) call with default params")

_SMALL = {"and", "of", "its", "the", "in", "to", "a", "an", "for", "on", "with", "or", "at", "by"}
_UNIT_WORDS = ["ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN", "TWELVE"]
TITLE_FIXES = {"Communitity": "Community", "Developmen ": "Development "}


def read_pages(pdf_path) -> list[str]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    out = []
    for i in range(len(pdf)):
        try:
            out.append(pdf[i].get_textpage().get_text_range().replace("\r", ""))
        except Exception:
            out.append("")
    return out


def has_text_layer(pages: list[str], min_fraction: float = 0.5) -> bool:
    if not pages:
        return False
    return sum(len(p.strip()) >= 40 for p in pages) / len(pages) >= min_fraction


# --------------------------------------------------------------------------
# page offset
# --------------------------------------------------------------------------
_NUM = re.compile(r"(?:^|\s)(\d{1,4})(?:\s|$)")


def detect_page_offset(pages: list[str], max_offset: int = 40) -> dict:
    """Printed page numbers sit in the first or last lines of most pages
    ("Grade 9 English Textbook 12", "117 Chemistry Grade 9 118", a lone "199").
    Each number n found on PDF page p votes for offset p - n; the real offset
    collects a vote on most pages, accidental numbers do not.

    Returns {"offset", "votes", "runner_up", "pages_with_text", "confident"}.
    "confident" needs >= 15 votes, >= 15% of the text pages, and at least twice
    the runner-up. Scanned PDFs (no text) are never confident."""
    votes: Counter = Counter()
    with_text = 0
    for i, text in enumerate(pages, start=1):
        lines = [" ".join(l.split()) for l in text.splitlines() if l.strip()]
        if not lines:
            continue
        with_text += 1
        candidates = set()
        for line in lines[:3] + lines[-3:]:
            if len(line) <= 60:
                candidates.update(int(m.group(1)) for m in _NUM.finditer(line))
        for n in candidates:
            if 0 <= i - n <= max_offset:
                votes[i - n] += 1
    if not votes:
        return {"offset": None, "votes": 0, "runner_up": 0, "pages_with_text": with_text, "confident": False}
    (best, top), *rest = votes.most_common(2)
    runner = rest[0][1] if rest else 0
    confident = top >= 15 and top >= 0.15 * with_text and top >= 2 * runner
    return {"offset": best, "votes": top, "runner_up": runner, "pages_with_text": with_text, "confident": confident}


# --------------------------------------------------------------------------
# unit names
# --------------------------------------------------------------------------
_LEADER = re.compile(r"(?:\s*[\ufffd.\u2026\u00b7_\u2022]\s*){2,}")


def strip_leaders(title: str) -> str:
    """Cut a Contents title at its dotted leader: "Money . . . . 67" or the
    replacement characters some PDFs print instead of dots ("Money � � � � 67")."""
    return _LEADER.split(title)[0].strip(" \t.:-")


def smart_title(title: str) -> str:
    """"CHEMISTRY AND ITS IMPORTANCE" -> "Chemistry and its Importance"."""
    if not title.isupper():
        return title
    words = title.lower().split()
    return " ".join(w if (i and w in _SMALL) else w.capitalize() for i, w in enumerate(words))


def clean_title(line: str) -> str:
    """Remove the word "Unit" and a misread big numeral ("L,", "1.", "= ,")."""
    line = re.sub(r"^\s*Unit\b[\s:.\-]*", "", line, flags=re.I)
    changed = True
    while changed:
        changed = False
        for pattern in (r"^[^A-Za-z]{1,6}", r"^[A-Za-z0-9]{1,2}\s*[,.;:]\s*"):
            new = re.sub(pattern, "", line)
            if new != line:
                line, changed = new, True
    return line.strip(" _-~()")


_RUNNING_UNIT = re.compile(r"^(Unit\s+\w+\s*:\s*.+)$", re.I)


def has_running_unit_headers(pages: list[str], min_pages: int = 5) -> bool:
    """True when pages carry a header like "Unit 4: Reproduction" (Biology,
    Maths): the ingestion script reads units from it, no sidecar needed."""
    n = 0
    for text in pages:
        for line in text.splitlines()[:3]:
            if _RUNNING_UNIT.match(" ".join(line.split())):
                n += 1
                break
    return n >= min_pages


def units_from_headers(pages: list[str]) -> list[dict]:
    """"TITLE IN CAPS / UNIT TWO / 37" headers (Geography)."""
    hdr = re.compile(r"^([A-Z][^\na-z]{5,})\n[ \t]*UNIT[ \t]+(" + "|".join(_UNIT_WORDS) + r")[ \t]*$", re.M)
    first = {}
    for i, text in enumerate(pages, start=1):
        m = hdr.search(text)
        if m:
            first.setdefault(_UNIT_WORDS.index(m.group(2)) + 1, (i, smart_title(m.group(1).strip())))
    return [{"start_pdf_page": first[n][0], "unit": f"Unit {n}: {first[n][1]}"} for n in sorted(first)]


def _opener_pages(pages: list[str], first_content_index: int) -> list[int]:
    return [i + 1 for i in range(first_content_index, len(pages))
            if re.search(r"Unit Outcomes|end of this unit", pages[i], re.I)]


def units_from_contents(pages: list[str], offset: int) -> list[dict]:
    """Units listed on the Contents page ("5. Horticulture ..... 106" or
    "Unit1: CHEMISTRY AND ITS IMPORTANCE 1"), start page = printed + offset.
    When the number of real opener pages equals the number of units, the
    opener pages are trusted instead (contents are sometimes off by one)."""
    toc = re.compile(r"^\s*(\d{1,2})\s*\.\s*([A-Za-z][A-Za-z ,&'\-]+?)\s*\.{2,}[\s.]*(\d{1,3})\s*$")
    toc_unit = re.compile(r"^\s*Unit\s*(\d{1,2})\s*:\s*(.+?)\s+(\d{1,3})\s*$", re.I)
    found = {}
    for text in pages[:20]:
        for line in text.splitlines():
            line = " ".join(line.split())
            if re.match(r"^\d{1,2}\.\d", line):
                continue
            m = toc.match(line) or toc_unit.match(line)
            if m:
                num, title, printed = int(m.group(1)), strip_leaders(m.group(2).strip()), int(m.group(3))
                title = smart_title(title)
                for bad, good in TITLE_FIXES.items():
                    title = title.replace(bad, good)
                found.setdefault(num, (title, printed))
    if not found:
        # Second pass, only when the first found nothing (so books that already
        # work are untouched): "1 Physics and Human Society 1" - unit number,
        # title, printed page, no dotted leader and no word "Unit".
        # Section lines ("1.1 Definition ... 2") do not match: "1.1" is not "1 ".
        toc_plain = re.compile(r"^\s*(\d{1,2})\s+([A-Z][A-Za-z ,&'\-/]+?)\s+(\d{1,3})\s*$")
        for text in pages[:20]:
            for line in text.splitlines():
                line = " ".join(line.split())
                m = toc_plain.match(line)
                if m:
                    num, title, printed = int(m.group(1)), m.group(2).strip(), int(m.group(3))
                    for bad, good in TITLE_FIXES.items():
                        title = title.replace(bad, good)
                    found.setdefault(num, (smart_title(title), printed))
    openers = _opener_pages(pages, offset)
    use_openers = len(openers) == len(found) and len(found) > 0
    out = []
    for idx, num in enumerate(sorted(found)):
        title, printed = found[num]
        out.append({"start_pdf_page": openers[idx] if use_openers else printed + offset,
                    "unit": f"Unit {num}: {title}"})
    return out


_WORD_NUM = {w.lower(): i + 1 for i, w in enumerate(_UNIT_WORDS)}
_NUM_TOKEN = r"(\d{1,2}(?!\d)|" + "|".join(w.lower() for w in _UNIT_WORDS) + r")(?![A-Za-z])"
# "Unit 5: Title", "Unit 2:Title", "Unit 1 : Title", "UNIT 5 : TITLE", "Unit 6 Money",
# "Unit Two: Title", and the same preceded by a page number ("2 Unit 1 Title")
_NUM_HDR = re.compile(r"^(?:\d{1,3}\s+)?Unit\s+" + _NUM_TOKEN + r"\s*[:.\-]?\s*(\S.*)$", re.I)
_UNIT_ONLY = re.compile(r"^Unit\s+" + _NUM_TOKEN + r"$", re.I)


def _unit_number(token: str) -> int:
    return int(token) if token.isdigit() else _WORD_NUM[token.lower()]


def _canonical_title(title: str) -> str:
    title = re.sub(r"\s+\d{1,3}$", "", " ".join(title.split())).strip(" .:-")
    return smart_title(title)


def _largest_cluster(pages: list[int], max_gap: int = 12) -> list[int]:
    """Header pages come in a run (every page or every other page). A few stray
    pages far away (a contents page, a cross-reference) are a different cluster
    and are ignored: keep the biggest run."""
    pages = sorted(pages)
    clusters, current = [], [pages[0]]
    for pg in pages[1:]:
        if pg - current[-1] <= max_gap:
            current.append(pg)
        else:
            clusters.append(current)
            current = [pg]
    clusters.append(current)
    return max(clusters, key=len)


def units_from_numbered_headers(pages: list[str], min_pages: int = 3, skip_first: int = 0) -> list[dict]:
    """Running headers that carry the unit number: "Unit 5: Title", "Unit 6 Money",
    "UNIT 5 : TITLE", "2 Unit 1 Title", or an opener "Unit 1" with the title on
    the next line. A unit counts only with at least `min_pages` pages in one run,
    so stray pages ("Unit 4 will discuss ...", a contents line) are ignored.
    Names come out as "Unit N: Title" whatever the header's spelling.
    `skip_first`: ignore this many front-matter pages (the Table of Contents
    starts with "UNIT 1 : ..." lines that are not unit pages)."""
    seen: dict[int, dict[str, list[int]]] = {}
    for i, text in enumerate(pages, start=1):
        if i <= skip_first:
            continue
        lines = [" ".join(l.split()) for l in text.splitlines() if l.strip()][:4]
        for j, line in enumerate(lines):
            m = _NUM_HDR.match(line)
            if m:
                num, title = _unit_number(m.group(1)), m.group(2)
            else:
                m2 = _UNIT_ONLY.match(line)
                if not (m2 and j + 1 < len(lines)):
                    continue
                num, title = _unit_number(m2.group(1)), lines[j + 1]
            title = _canonical_title(title)
            if 3 <= len(title) <= 90:
                seen.setdefault(num, {}).setdefault(title.lower(), []).append(i)
                break
    out = []
    for num in sorted(seen):
        # the title spelling seen on the most pages wins ("UNIT 5 : X" and "Unit 5 : X" count together)
        by_title = {t: _largest_cluster(pgs) for t, pgs in seen[num].items()}
        title_key, cluster = max(by_title.items(), key=lambda kv: len(kv[1]))
        if len(cluster) < min_pages:
            continue
        # canonical spelling: take the original text from the first page of the cluster
        first = cluster[0]
        original = next((_canonical_title(m.group(2)) for line in pages[first - 1].splitlines()
                         if (m := _NUM_HDR.match(" ".join(line.split()))) and _canonical_title(m.group(2)).lower() == title_key), None)
        if original is None:   # opener style: title is on the line after "Unit N"
            flat = [" ".join(l.split()) for l in pages[first - 1].splitlines() if l.strip()]
            original = next((_canonical_title(flat[k + 1]) for k, l in enumerate(flat[:-1])
                             if _UNIT_ONLY.match(l) and _canonical_title(flat[k + 1]).lower() == title_key), title_key)
        out.append({"start_pdf_page": first, "unit": f"Unit {num}: {original}"})
    return out


def units_from_openers(pages: list[str]) -> list[dict]:
    """Opener pages ("Learning Outcomes ... At the end of this unit"); the title
    is the line above "Learning Outcomes", the number is the opener's order."""
    entries = []
    for i, text in enumerate(pages):
        if not (re.search(r"end of this unit", text, re.I) and re.search(r"learning outcomes", text, re.I)):
            continue
        lines = [" ".join(l.split()) for l in text.splitlines() if l.strip()]
        idx = next((j for j, l in enumerate(lines) if re.search(r"learning outcomes", l, re.I)), 0)
        title = ""
        for l in reversed(lines[:idx]):
            if re.fullmatch(r"unit", l, re.I):
                continue
            l = clean_title(l)
            if len(l) >= 3:
                title = l
                break
        entries.append({"start_pdf_page": i + 1, "unit": f"Unit {len(entries) + 1}: {title or '(fix me)'}"})
    return entries


def plausible(entries: list[dict], n_pages: int) -> bool:
    """>= 3 units, numbered exactly 1..k with no gap (a gap means a unit was
    missed), start pages strictly increasing and inside the book, real titles."""
    if len(entries) < 3:
        return False
    starts = [e["start_pdf_page"] for e in entries]
    numbers = []
    for e in entries:
        m = re.match(r"Unit (\d+):", e["unit"])
        numbers.append(int(m.group(1)) if m else -1)
    return (numbers == list(range(1, len(entries) + 1))
            and all(a < b for a, b in zip(starts, starts[1:])) and 1 <= starts[0] and starts[-1] <= n_pages
            and not any("(fix me)" in e["unit"] or e["unit"].endswith(": ") for e in entries))


def _official_titles(pages: list[str], offset: int) -> dict[int, str]:
    """Unit titles as printed in the Contents ("Unit 6: Introduction to Money"),
    keyed by unit number. Empty when the Contents has no parsable unit lines."""
    try:
        return {int(m.group(1)): m.group(2) for e in units_from_contents(pages, offset)
                if (m := re.match(r"Unit (\d+): (.*)", e["unit"]))}
    except Exception:
        return {}


def auto_units(pages: list[str], offset: int | None):
    """Try the methods in order of reliability. Returns (mode, entries).
    Names are always "Unit N: Title". The legacy mode 'running headers' (no
    entries; ingestion reads a "Unit N: Title" header itself) is used only when
    nothing better produced a complete list; 'none' means nothing worked."""
    candidates = [("numbered headers", lambda: units_from_numbered_headers(pages, skip_first=offset or 0))]
    if offset is not None:
        candidates.append(("contents", lambda: units_from_contents(pages, offset)))
    candidates += [("headers", lambda: units_from_headers(pages)),
                   ("openers", lambda: units_from_openers(pages))]
    for mode, fn in candidates:
        entries = fn()
        if plausible(entries, len(pages)):
            if mode == "numbered headers" and offset is not None:
                # Unit 1 begins on printed page 1 (the page right after the front
                # matter). A header-based start can be a page or two late when the
                # opener page has no running header, so snap Unit 1 to it.
                if entries[0]["start_pdf_page"] <= offset + 5:
                    entries[0]["start_pdf_page"] = offset + 1
                # The running header is often a short form ("Money"); when the
                # Contents prints a longer title that contains it ("Introduction
                # to Money") use the official one. A Contents typo ("Markerts")
                # does not contain the header's spelling, so the header wins there.
                official = _official_titles(pages, offset)
                for e in entries:
                    num = int(re.match(r"Unit (\d+):", e["unit"]).group(1))
                    short = e["unit"].split(": ", 1)[1]
                    full = official.get(num)
                    if full and len(full) > len(short) and short.lower() in full.lower():
                        e["unit"] = f"Unit {num}: {full}"
            return mode, entries
    if has_running_unit_headers(pages):
        return "running headers", []
    return "none", []
