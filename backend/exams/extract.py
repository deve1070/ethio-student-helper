"""Photos / PDF of an exam paper -> reviewable files. No database.

A vision model reads ONE page at a time and writes it in the markup defined in tools.py. The pages are joined,
validated (numbering, four distinct options, passage text, underline marks) and cross-checked against an
independent OCR pass. Nothing here decides an answer.

Output folder <out>/<subject>_<year>[_<stream>][_<round>]/ :
  paper.json  transcript.txt  questions.jsonl  passages.json  review.txt  p01.jpg p01.md ...
"""
import base64
import hashlib
import io
import json
import re
import time
from pathlib import Path

from .tools import ocr_crosscheck, parse_transcript, question_flags, to_records, validate

PROMPT = """You are transcribing ONE page of an Ethiopian national exam booklet (ESSLCE) from a phone photo.
Write the page in EXACTLY this markup and nothing else (no commentary, no code fences):

@part <text>              only when a new part heading starts on this page (e.g. II. LANGUAGE FOCUS)
@section <text>           a section heading together with its instructions
@passage <id> | <title>   when a reading passage starts (ids P1, P2, ...)
P<n>: <text>              paragraph n of the current passage on ONE line; P<n>+: <text> when this continues
                          a paragraph that started on the previous page
SOURCE: <text>            a source line under a passage
Q<number> | <stem>        one question stem on ONE line (write each blank as ______);
                          Q<number>+ | <text> when the stem continues from the previous page
A. <text>                 one line per option (A., B., C., D.); if a question's options continue from the previous
B. <text>                 page, start with just those option lines (no Q line)
DIAGRAM: <description>    after a question, only if answering needs a figure/graph/structure you cannot write as text

Rules:
- Copy the words exactly, including spelling mistakes. Never correct, translate, summarise or answer anything.
  This matters MOST on a word-spelling or vocabulary item: most of its options are DELIBERATELY misspelled on
  purpose (that is the whole point of the item) - copy each one exactly as printed even if it looks like a
  misspelled version of a word you recognize. Never "fix" it to the correctly-spelled word.
- A dialogue item is often more than one line before the blank (e.g. one speaker asks something, a second
  speaker adds context, and only THEN does the blank appear for a third line). Include EVERY given speaker's
  line that appears before the blank, not just the first one - the options frequently only make sense with
  that full context, and dropping the middle line loses it entirely with no way to recover it later.
- Underlined words: [[word]]. Bold words: **word**.
- Chemical/maths notation in plain text (H2SO4, Mg+2, x^2, 1/2).
- IGNORE page headers/footers (booklet code, subject code, page numbers, 'EAES/ESSLCE'), and IGNORE every pen mark:
  ticks, circles, crossed-out letters, notes in the margin. Never use them to decide anything.
- If a question has no printed stem (the section instructions are the question), write the stem as (instructions).
- If something is unreadable write [?] in its place."""

NO_SECTIONS_NOTE = """

This paper has NO part or section headings anywhere, on any page - it is a plain sequence of numbered \
questions from start to end. Never write an @part or @section line for this paper. If something looks like \
a heading (for example the first page after the general directions, or text right after a previous question's \
options), it is actually the start of the next numbered question - transcribe it as Q<number> | <text>."""

# Subjects whose real ESSLCE papers DO have part/section structure (English has "LANGUAGE FOCUS"-style
# parts; Scholastic Aptitude Test has distinct timed sections). Every other subject's paper is a flat,
# unsectioned sequence of items - confirmed in conversation, not guessed - so the model is told as much
# up front instead of being left to infer it (and occasionally hallucinate a section that isn't there).
SUBJECTS_WITH_SECTIONS = {"english", "scholastic_aptitude_test"}

_THINK = re.compile(r"<think>.*?</think>", re.S)
# Q\d+\.?\+?: a vision model occasionally writes "Q60. |" (a stray period before the pipe, seen in real
# Gemini output on a physics paper) instead of "Q60 |" - tolerated here so that line is still classified as
# a real question line, not commentary (tools.py's own Q-matching regexes tolerate the same stray period).
# [A-D][.)]: tools.py's OPT tolerates both "A." (what the prompt asks for) and "A)" (a source page's own
# style, which the model occasionally mirrors instead of normalizing) - this gate must accept the same
# set, or an "A)" line never reaches OPT at all and the whole page's options are dropped as commentary.
# Q\d+...\|?: the pipe is likewise optional - a source page numbered "59. stem" (no pipe at all) is
# sometimes mirrored literally instead of normalized to "Q59 | stem"; requiring the pipe dropped the
# WHOLE question line as commentary, and every option line that followed piled onto the previous
# question with no opening line of its own (confirmed for real: a cluster of 7 consecutive items lost
# this way on one page of the 2005-2010 EC batch). tools.py's own Q-line regexes make the same pipe
# optional, so a line this gate keeps is one tools.py can actually parse.
# \d+\.\s: a further step down the same habit - no "Q" at all, just a bare "75. stem" exactly as the
# source page prints it. tools.py's _MISCLASSIFIED_ITEM already recovers this shape when it shows up
# tagged as @part/@section; this lets an UNTAGGED bare numbered line reach that same recovery instead
# of being dropped as commentary before tools.py ever sees it (confirmed for real: items 75-77 lost
# outright on one page, no @part/@section wrapper at all).
_KEEP = re.compile(r"^(@(page|part|section|passage)\b|P\d+\+?:|SOURCE:|Q\d+\.?\+?\s*\|?|[A-D][.)]\s?|DIAGRAM:|#|\d+\.\s)")


def split_markup(markup: str) -> tuple[list, list]:
    """(kept lines, dropped lines): drops chatter a model sometimes adds (code fences, <think> blocks, 'Here is the page...')."""
    markup = _THINK.sub("", markup or "")
    kept, dropped = [], []
    for ln in markup.splitlines():
        s = ln.strip()
        if not s or s.startswith("```"):
            continue
        (kept if _KEEP.match(s) else dropped).append(s)
    return kept, dropped


def sanitize(markup: str) -> tuple[str, int]:
    kept, dropped = split_markup(markup)
    return "\n".join(kept), len(dropped)


# ---------------------------------------------------------------------------- images
def page_images(path: Path):
    """(index, PIL image) per page: the embedded photo of each page of a PDF, or the image files of a folder.

    A page photographed on a phone and inserted into a PDF holds exactly one embedded image object whose
    bounding box is the whole page - using that image directly (instead of re-rendering it) skips a lossy
    re-rasterization. A PDF printed from a web page is different: it has NO such single full-page image -
    Chrome prints vector text plus many small embedded icons (radio buttons, badges), sometimes dozens per
    page, each tiny relative to the page. Treating the FIRST of those tiny icons as "the whole page" (what
    this function used to do whenever ANY image object existed) silently hands the vision model an 80x80px
    crop of a radio button and nothing else - confirmed for real on the 2005-2010 EC web-archive batch,
    where every page came back "blank/out of focus" because that crop genuinely has no readable content.
    Only take the embedded-image shortcut when exactly one image object exists AND it covers most of the
    page's area; otherwise render the page itself, which captures vector text and small icons alike."""
    from PIL import Image
    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
        for i, f in enumerate(files, 1):
            yield i, Image.open(f).convert("RGB")
        return
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    for i in range(len(pdf)):
        page = pdf[i]
        objs = [o for o in page.get_objects() if o.type == 3]
        page_area = page.get_size()[0] * page.get_size()[1]
        is_full_page_scan = False
        if len(objs) == 1:
            x0, y0, x1, y1 = objs[0].get_pos()
            is_full_page_scan = abs((x1 - x0) * (y1 - y0)) >= 0.8 * page_area
        img = objs[0].get_bitmap().to_pil() if is_full_page_scan else page.render(scale=2).to_pil()
        yield i + 1, img.convert("RGB")


def prepare(img, max_side: int = 1600):
    """Even out the lighting of a phone photo and shrink it (a model needs ~1500 px, not 220 dpi of upsampling)."""
    try:
        import cv2
        import numpy as np
        a = np.array(img)
        g = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
        k = max(g.shape) // 6 | 1
        bg = cv2.GaussianBlur(g, (k, k), 0).astype("float32") + 1
        a = np.clip(a.astype("float32") * (bg.mean() / bg)[..., None], 0, 255).astype("uint8")
        h, w = a.shape[:2]
        if max(h, w) > max_side:
            s = max_side / max(h, w)
            a = cv2.resize(a, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        from PIL import Image
        return Image.fromarray(a)
    except ImportError:
        from PIL import ImageOps
        im = ImageOps.autocontrast(img)
        im.thumbnail((max_side, max_side))
        return im


def jpeg_bytes(img, limit: int = 1_500_000) -> bytes:
    """JPEG small enough for an API request (base64 adds a third; some providers cap at ~4 MB)."""
    for q in (88, 80, 70, 60):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q)
        if buf.tell() <= limit:
            break
    return buf.getvalue()


def _band_angle(binary):
    import cv2
    import numpy as np
    inv = 255 - binary
    h, w = inv.shape
    best, best_a = -1.0, 0.0
    for a in np.arange(-10, 10.01, 0.5):
        r = cv2.warpAffine(inv, cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0), (w, h), flags=cv2.INTER_NEAREST)
        v = float(np.var(r.sum(axis=1).astype("float64")))
        if v > best:
            best, best_a = v, a
    return best_a


def ocr_lines(img, nbands: int = 6) -> list:
    """Independent OCR of a phone photo, used only as a cross-check. Each horizontal band is deskewed on its own
    because the top of a photographed page is usually tilted differently from the bottom."""
    import pytesseract
    try:
        import cv2
        import numpy as np
    except ImportError:
        return pytesseract.image_to_string(img.resize((img.width * 2, img.height * 2)), config="--psm 4").splitlines()
    from PIL import Image
    g = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    g = cv2.resize(g, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    _, bw = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    H, W = g.shape
    bh = H // nbands
    found = []
    for b in range(nbands):
        c0, c1 = b * bh, ((b + 1) * bh if b < nbands - 1 else H)
        y0, y1 = max(c0 - bh // 2, 0), min(c1 + bh // 2, H)
        ang = _band_angle(cv2.resize(bw[y0:y1], None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA))
        band = g[y0:y1]
        h, w = band.shape
        rot = cv2.warpAffine(band, cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0), (w, h),
                             flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        d = pytesseract.image_to_data(Image.fromarray(rot), config="--psm 6", output_type=pytesseract.Output.DICT)
        rows = {}
        for i, t in enumerate(d["text"]):
            if t.strip() and float(d["conf"][i]) >= 0:
                rows.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append((d["left"][i], d["top"][i], t))
        for ws in rows.values():
            ws.sort()
            y = y0 + sum(w_[1] for w_ in ws) / len(ws)
            if c0 <= y < c1:
                found.append((y, " ".join(w_[2] for w_ in ws)))
    return [t for _, t in sorted(found)]


# ---------------------------------------------------------------------------- the vision call (your LLMClient)
def make_groq_call(model_id: str, has_sections: bool = True):
    """Returns call(jpeg_bytes, note) -> markup text, through llm.client.LLMClient (the same adapter your agents use).
    reasoning_effort=None: that parameter is only valid for some Groq models, and a vision model may reject it.
    has_sections: pass False for a subject not in SUBJECTS_WITH_SECTIONS so the prompt rules out @part/@section
    for this paper up front, instead of the model occasionally inventing one."""
    from llm.client import LLMClient
    try:
        llm = LLMClient(model_id=model_id, temperature=0, max_tokens=6000, reasoning_effort=None)
    except TypeError:        # an LLMClient without a reasoning_effort option (only some models have one)
        llm = LLMClient(model_id=model_id, temperature=0, max_tokens=6000)
    prompt = PROMPT if has_sections else PROMPT + NO_SECTIONS_NOTE

    def call(jpg: bytes, note: str) -> str:
        content = [
            {"type": "text", "text": prompt + "\n\n" + note},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpg).decode()}},
        ]
        r = llm.chat(messages=[{"role": "user", "content": content}])
        return r["choices"][0]["message"]["content"] or ""

    return call


def make_gemini_call(model_id: str, has_sections: bool = True):
    """Same contract as make_groq_call (call(jpeg_bytes, note) -> markup text). Thin wrapper around
    llm.vision.make_gemini_vision_call (shared with payments/receipt_verification.py) that supplies
    this module's exam-transcription PROMPT - not through llm.client.LLMClient, since that adapter
    is typed to Groq's SDK exceptions (llm/retry.py) and to GROQ_API_KEY. Groq's vision model lineup
    was empty on this account as of 2026-10-21 (every known vision model id came back either
    model_not_found or decommissioned); Gemini's models are multimodal by default, so no separate
    "vision model" id exists the way Groq used to have one - any chat model id accepts an image."""
    from llm.vision import make_gemini_vision_call

    prompt = PROMPT if has_sections else PROMPT + NO_SECTIONS_NOTE
    return make_gemini_vision_call(model_id, prompt)


# A second source format found for real in the 2005-2010 EC archive batch: instead of one hand-marked photo
# per paper, the answer comes as its OWN separate document - a printed copy of a completed online exam,
# where each question re-shows its four options with a checkmark after whichever one the site graded as
# correct, and a "Not Answered" badge that is never itself an answer. This is a DIFFERENT read than PROMPT
# above (which deliberately ignores every pen/tick mark while transcribing the question text) - here the
# tick IS the only thing being asked for, and the question text itself is discarded.
ANSWER_KEY_PROMPT = """This is one page from a printed copy of a completed online multiple-choice exam. Each \
question shows four lettered options (A-D); the option the exam system graded as CORRECT is followed by a \
checkmark (✔ or similar tick mark) directly after its text. A box reading "Not Answered" may appear next \
to a question's number or stem - it is NOT an answer and never marks a correct option; ignore it entirely.

For EACH numbered question on this page, write EXACTLY one line:
<item number>: <letter>

where <letter> is the single capital letter (A, B, C, or D) of the option that has the checkmark next to it \
on THIS page. Write nothing else - no commentary, no headers, no blank lines, no repeating the question text. \
If a question truly has no checkmark on any of its four options, write:
<item number>: ?
Never guess an answer from the question's own content - only report what is actually marked with a checkmark."""

_KEY_LINE = re.compile(r"(?<!\d)(\d{1,3})\s*[:.\-]\s*([A-Da-d?])\b")


def make_gemini_keyvision_call(model_id: str):
    """Same contract as make_gemini_call, reading a checkmarked answer page instead of a question page."""
    from llm.vision import make_gemini_vision_call

    return make_gemini_vision_call(model_id, ANSWER_KEY_PROMPT)


def transcribe_answer_page(call, jpg: bytes, pg: int, tries: int = 3) -> tuple[str, str]:
    """Returns (markup, problem) - same retry contract as transcribe_page: an empty answer or an exception
    is retried, and a page is never silently lost."""
    problem = ""
    for _attempt in range(tries):
        try:
            text = (call(jpg, f"This is printed page {pg} of the answer booklet.") or "").strip()
            if text:
                return text, ""
            problem = "the model returned nothing usable"
        except Exception as e:  # noqa: BLE001
            problem = f"{type(e).__name__}: {str(e)[:120]}"
    return "", f"FAILED after {tries} tries: {problem}"


def run_keyvision(source: Path, call, pause_seconds: float = 10.0, log=print) -> dict:
    """Reads a 'completed exam' style answer-key document page by page and returns {"key": {item_no: 'A'..'D'},
    "unresolved": [item_no, ...], "problems": [...]} - the same {item: letter} shape store.read_key_file
    produces from a hand-typed text file, built directly from the checkmarked pages instead."""
    key, unresolved, problems = {}, [], []
    for i, (idx, img) in enumerate(page_images(source)):
        if i > 0 and pause_seconds:
            time.sleep(pause_seconds)  # same per-minute budget reasoning as run_extract's own pause
        jpg = jpeg_bytes(prepare(img))
        text, problem = transcribe_answer_page(call, jpg, idx)
        if problem:
            problems.append(f"page {idx}: {problem}")
        for n_str, letter in _KEY_LINE.findall(text):
            n, letter = int(n_str), letter.upper()
            if letter == "?":
                unresolved.append(n)
                continue
            if n in key and key[n] != letter:
                problems.append(f"item {n}: conflicting letters read ({key[n]} vs {letter}), page {idx}")
                continue
            key[n] = letter
        log(f"page {idx}: {len(key)} answers so far" + (f"  [{problem}]" if problem else ""))
    return {"key": key, "unresolved": sorted(set(unresolved)), "problems": problems}


def transcribe_page(call, jpg: bytes, pg: int, tries: int = 3) -> tuple[str, str]:
    """Returns (markup, problem). An empty answer or an exception is retried; a page is never silently lost.
    Lines that were dropped are SHOWN in the problem text: a stem the model wrapped onto a second line without the
    Q+ marker would otherwise vanish without a trace."""
    problem = ""
    for attempt in range(1, tries + 1):
        try:
            kept, dropped = split_markup(call(jpg, f"This is printed page {pg} of the booklet."))
            if kept:
                shown = "; ".join(repr(d[:60]) for d in dropped[:3])
                return "\n".join(kept), (f"{len(dropped)} lines of commentary dropped (e.g. {shown})" if dropped else "")
            problem = "the model returned nothing usable"
        except Exception as e:  # noqa: BLE001
            problem = f"{type(e).__name__}: {str(e)[:120]}"
    return "", f"FAILED after {tries} tries: {problem}"


def assemble(page_texts: dict) -> str:
    return "\n".join(f"@page {pg}\n{page_texts[pg].strip()}\n" for pg in sorted(page_texts))


# ---------------------------------------------------------------------------- run
def paper_dirname(subject, year_ec, stream="", round_="", region="", delivery_mode=""):
    return "_".join(x for x in (subject, str(year_ec), stream, round_, region, delivery_mode) if x)


def run_extract(source: Path, out_root: Path, meta: dict, call, first_printed_page: int = 1,
                expected: tuple = (1, 100), use_ocr: bool = True, log=print, pause_seconds: float = 10.0) -> dict:
    out = out_root / paper_dirname(meta["subject"], meta["year_ec"], meta.get("stream", ""),
                                   meta.get("round", ""), meta.get("region", ""), meta.get("delivery_mode", ""))
    out.mkdir(parents=True, exist_ok=True)
    pages, ocr, problems, n_pages = {}, {}, [], 0
    for i, (idx, img) in enumerate(page_images(source)):
        if i > 0 and pause_seconds:
            # A vision call on a full page photo is token-heavy; Groq's free tier is 8,000 tokens/minute
            # (see llm/retry.py). Firing pages back-to-back burns that budget faster than a single call's
            # own retry/backoff can recover from, and starves LATER pages entirely rather than just one.
            # A pause between pages keeps the whole paper under budget instead of relying only on
            # reacting after a 429.
            time.sleep(pause_seconds)
        n_pages += 1
        pg = idx + first_printed_page - 1
        prep = prepare(img)
        jpg = jpeg_bytes(prep)
        (out / f"p{pg:02d}.jpg").write_bytes(jpg)
        text, problem = transcribe_page(call, jpg, pg)
        pages[pg] = text
        (out / f"p{pg:02d}.md").write_text(text, encoding="utf-8")
        if problem:
            problems.append(f"page {pg}: {problem}")
        if use_ocr:
            try:
                ocr[pg] = ocr_lines(prep)
            except Exception as e:  # noqa: BLE001  (no tesseract installed)
                use_ocr = False
                problems.append(f"OCR cross-check skipped: {type(e).__name__}")
        log(f"page {pg}: {len(text.splitlines())} lines" + (f"  [{problem}]" if problem else ""))

    failed_pages = sorted(pg for pg, t in pages.items() if not t.strip())
    transcript = assemble(pages)
    (out / "transcript.txt").write_text(transcript, encoding="utf-8")
    parsed = parse_transcript(transcript)
    issues = validate(parsed, range(expected[0], expected[1] + 1))
    for prob in parsed.get("problems", []):
        issues.append(("WARN", prob))
    for pg in failed_pages:       # a page with no transcription may hold passage text or instructions, not only questions
        issues.insert(0, ("FAIL", f"page {pg} produced no transcription - re-run it before loading"))
    low = ocr_crosscheck(parsed, ocr) if ocr else []
    recs = to_records(parsed, question_flags(parsed, issues, low))

    sha = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None
    paper = {**meta, "source_file": source.name, "source_sha256": sha, "page_count": n_pages,
             "expected_first": expected[0], "expected_last": expected[1], "first_printed_page": first_printed_page,
             "failed_pages": failed_pages,
             # paper-level problems (missing / duplicate / out-of-order item numbers); load refuses them unless told otherwise
             "issues": [[lvl, msg] for lvl, msg in issues]}
    (out / "paper.json").write_text(json.dumps(paper, indent=2), encoding="utf-8")
    (out / "questions.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs), encoding="utf-8")
    passages = {k: {**v, "pages": list(v["pages"])} for k, v in parsed["passages"].items()}
    (out / "passages.json").write_text(json.dumps(passages, ensure_ascii=False, indent=2), encoding="utf-8")
    review = (["PAGE PROBLEMS"] + [f"  {p}" for p in problems] + ["", "VALIDATION"]
              + [f"  {lvl}: {msg}" for lvl, msg in issues]
              + ["", "COMPARE WITH THE PHOTO (not confirmed by an independent OCR pass):"]
              + [f"  Q{n}: {sh:.0%} of the {w} words found; printed page {pg}" for n, sh, pg, w in low]
              + ["", f"{len(recs)} questions, {sum(1 for r in recs if r['flags'])} flagged."])
    (out / "review.txt").write_text("\n".join(review), encoding="utf-8")
    log("\n".join(review))
    return {"dir": out, "questions": len(recs), "issues": issues, "problems": problems}