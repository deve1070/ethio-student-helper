"""
Batch ingestion job. Walks the MoE textbook content root, parses each PDF
with Docling, chunks it with docling-core's HierarchicalChunker (which
tracks heading trail + page provenance per chunk from the parsed
document structure — not from regex-matching exported text), and writes:

  - one Textbook row per source file
  - one Chunk row per chunk (citation metadata, joined to the vector
    store by vector_id)
  - the chunk text + metadata into the permanent "textbooks" Chroma
    collection, filterable later by grade + subject

Run as: python -m ingestion.textbook_ingest

Expects content laid out as:
  content/moe_textbooks/grade_<N>/<subject>/<file>.pdf

This replaces an earlier version of this file that split Docling's
exported markdown with MarkdownHeaderTextSplitter and pulled page
numbers from a placeholder "[page N]" regex that Docling doesn't
actually emit. Chunking off the DoclingDocument itself avoids both
problems in one step.
"""
import argparse
import json
import re
import unicodedata
import uuid
from pathlib import Path

from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.transforms.chunker import HierarchicalChunker
from retriever import vectorstore

from config import constants
from config.settings import settings
from db.models import Chunk, Textbook
from db.session import SessionLocal
from ingestion import book_tools
from retriever.builder import RetrieverBuilder
from utils.logging import logger


def normalize_subject(name: str) -> str:
    """Folder or typed subject -> stored subject: lowercase, spaces and hyphens
    become underscores ("Information Technology" -> "information_technology"),
    so every grade ends up under the same subject name."""
    return re.sub(r"[\s\-]+", "_", name.strip().lower())


def _subject_label(subject: str) -> str:
    """Stored snake_case subject -> a readable label for the embedding prefix below
    ("information_technology" -> "Information Technology")."""
    return subject.replace("_", " ").title()


def _embed_text(grade: int, subject: str, unit: str | None, section: str | None, text: str) -> str:
    """The string actually embedded (and stored as the retrievable document) for one
    textbook chunk: a short grade/subject/unit/section header ahead of the chunk's own
    text, so the embedding itself carries the chunk's place in the book - not just side
    metadata a filter can check after the fact. This is what lets retrieval disambiguate
    a generically-worded chunk ("this process occurs in three stages") by which unit it
    actually belongs to. Deliberately NOT applied to exam question embeddings
    (exams/store.py:embed_text, exams/cache.py) - those exist to match a student's own
    rephrasing of ONE question against its near-duplicate, and mixing in unit/paper
    context there would pull every question of the same unit together instead."""
    header = f"{_subject_label(subject)}, Grade {grade}"
    if unit:
        header += f"\n{unit}" + (f" > {section}" if section else "")
    return f"{header}\n\n{text}"


def _discover_files(root: Path, grades: list[int] | None = None):
    """Yield (grade, subject, path) for every PDF under the content root,
    lowest grade first (grade_9 before grade_10: sorted numerically, not as text)."""
    found = []
    for grade_dir in root.glob("grade_*"):
        try:
            grade = int(grade_dir.name.split("_")[1])
        except (IndexError, ValueError):
            logger.warning(f"Skipping folder with unexpected name: {grade_dir}")
            continue
        if grade not in constants.SUPPORTED_GRADES:
            logger.warning(f"Skipping unsupported grade folder: {grade_dir}")
            continue
        if grades and grade not in grades:
            continue
        found.append((grade, grade_dir))
    for grade, grade_dir in sorted(found, key=lambda t: t[0]):
        for subject_dir in sorted(p for p in grade_dir.iterdir() if p.is_dir()):
            for pdf_path in sorted(subject_dir.glob("*.pdf")):
                yield grade, normalize_subject(subject_dir.name), pdf_path


def _subject_set(only_subject: str | None) -> set[str] | None:
    """"physics, Economics" -> {"physics", "economics"}; None/"" -> no filter."""
    names = {normalize_subject(x) for x in (only_subject or "").split(",") if x.strip()}
    return names or None


def _heading_trail(chunk) -> tuple[str | None, str | None]:
    """(unit, section) from the chunk's heading trail. HierarchicalChunker
    walks the document's actual heading hierarchy, so headings[0] is the
    top-level heading in scope for this chunk (typically the unit/chapter
    title in MoE textbooks) and headings[1], if present, is the
    next level down (a numbered section).
    """
    headings = getattr(chunk.meta, "headings", None) or []
    unit = headings[0] if len(headings) > 0 else None
    section = headings[1] if len(headings) > 1 else None
    return unit, section


def _page_range(chunk) -> tuple[int | None, int | None]:
    """Page numbers from the provenance Docling attaches to each source
    item the chunk was built from — the real page(s) the chunk's text
    was extracted from, not a guess.
    """
    pages: set[int] = set()
    for item in getattr(chunk.meta, "doc_items", None) or []:
        for prov in getattr(item, "prov", None) or []:
            page_no = getattr(prov, "page_no", None)
            if page_no is not None:
                pages.add(page_no)
    if not pages:
        return None, None
    return min(pages), max(pages)


# Merge neighbouring tiny chunks (single sentences/list items) under the same
# heading so each stored chunk carries enough context to be retrievable.
MAX_CHUNK_CHARS = 800

_UNIT_RE = re.compile(r"^(Unit\s+\w+\s*:\s*[^\t\d]*?[A-Za-z][^\t]*?)\s*(?:\d+)?$", re.I)


_MATH_ALNUM = re.compile(r"[\U0001D400-\U0001D7FF]")


def _fold_math_alphanumerics(text: str) -> str:
    """Math textbooks set variables in Unicode "mathematical italic" letters
    (e.g. U+1D434 for A). Embedding models handle those poorly and a student
    typing "set A" never matches them. Fold just that block back to plain
    letters/digits. Deliberately NOT full NFKC, which would also turn x² into
    x2 and R-double-struck into R, changing the maths."""
    return _MATH_ALNUM.sub(lambda m: unicodedata.normalize("NFKC", m.group(0)), text)


def _has_text_layer(pdf_path: Path, min_fraction: float = 0.5) -> bool:
    """False for scanned PDFs (pages are pictures with no text). Docling would
    then fall back to its own OCR, which is very slow and unreliable here.
    Run `ocrmypdf` on the book first (see README) and ingest the result."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    n = len(pdf)
    if n == 0:
        return False
    with_text = 0
    for i in range(n):
        try:
            if len(pdf[i].get_textpage().get_text_range().strip()) >= 40:
                with_text += 1
        except Exception:
            pass
    return with_text / n >= min_fraction


def _units_from_sidecar(pdf_path: Path) -> dict[int, str] | None:
    """Optional "<book>.units.json" next to the PDF, for books without a
    running "Unit N: Title" header (e.g. the scanned English book):
        [{"start_pdf_page": 14, "unit": "Unit 1: Living in Urban Areas"}, ...]
    Each unit runs until the next one starts."""
    sidecar = pdf_path.with_suffix(".units.json")
    if not sidecar.exists():
        return None
    entries = sorted(json.loads(sidecar.read_text(encoding="utf-8")), key=lambda e: e["start_pdf_page"])
    units: dict[int, str] = {}
    for idx, e in enumerate(entries):
        end = entries[idx + 1]["start_pdf_page"] - 1 if idx + 1 < len(entries) else 10_000
        for page in range(e["start_pdf_page"], end + 1):
            units[page] = e["unit"]
    return units


_MARGIN_UNIT = re.compile(r"\bu\s+n\s+i\s+t(?:\s+\d{1,2})?\b")
_RUNNING_FOOTER = re.compile(r"^[ \t]*(?:\d+[ \t]+)?Grade \d+ \w+ Textbook(?:[ \t]+\d+)?[ \t]*$", re.M)
# Private-font bullets -> a normal bullet. \uf03f is the Symbol-font bullet in
# the Chemistry book; \uf8eb-\uf8f8 are pieces of large brackets (dropped).
_ODD_BULLETS = str.maketrans(
    {"\u0494": "\u2022", "\u02af": "\u2022", "\u25a0": "\u2022", "\uf03f": "\u2022",
     # Geography book: arrow/Wingdings bullets and emoji list markers
     "\u00de": "\u2022", "\uf0a7": "\u2022", "\u2705": "\u2022", "\U0001F30D": "\u2022",
     "\U0001F511": "\u2022",
     # pure decoration, dropped
     "\U0001F512": "", "\U0001F310": "",
     **{chr(c): "" for c in range(0xF8EB, 0xF8F9)}}
)
# Website watermark printed on every page of some PDFs ("Ethiofetena.com ...").
_WATERMARK = re.compile(r"[ \t]*Ethiofetena\.com[^\n]*\n?", re.I)
_UNIT_WORDS = "ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE"
# Running page headers: "TITLE IN CAPS / UNIT FOUR / 85", "Grade 9| Geography",
# "34 UNIT ONE". Removed so they don't pollute every chunk.
_HEADER_TITLE_BEFORE_UNIT = re.compile(
    r"^[ \t]*[A-Z][^\na-z]{8,}\n(?=[ \t]*UNIT[ \t]+(?:" + _UNIT_WORDS + r")[ \t]*$)", re.M
)
_HEADER_UNIT_LINE = re.compile(
    r"^[ \t]*(?:\d+[ \t]*)?UNIT[ \t]+(?:" + _UNIT_WORDS + r")[ \t]*(?:\d+[ \t]*)?$\n?", re.M
)
_HEADER_GRADE_LINE = re.compile(r"^[ \t]*(?:\d+[ \t]*)?Grade \d+[ \t]*\|[ \t]*[A-Za-z ]+$\n?", re.M)
# Running header at the start of a line: "117 Chemistry Grade 9 118",
# "Chemistry Grade 9 Chemistry and its Importance", or the same prefix glued
# to the first words of a paragraph ("Chemistry Grade 9 As the name suggests...").
# Only the "<Subject> Grade N" prefix (and page numbers) is removed; a unit
# title left after it is harmless context.
_HEADER_SUBJECT_GRADE = re.compile(
    r"^[ \t]*(?:\d+[ \t]*)?(?:Chemistry|Biology|Physics|Mathematics|Geography|History|English|Civics|Economics)"
    r" Grade \d+(?:[ \t]*\d+(?![\d.]))?[ \t]*\n?",
    re.M,
)
# Running header/footer "Grade 9 Information Technology Student's Textbook" (optionally
# with a page number before or after); it was repeated in 25 chunks of that book.
_HEADER_STUDENT_TEXTBOOK = re.compile(
    r"^[ \t]*(?:\d+[ \t]+)?Grade \d+ [A-Za-z ]{3,40} Student[\u2019']?s? Textbook(?:[ \t]+\d+)?[ \t]*\n?",
    re.M,
)
# Bare lesson-number footers ("LESSON 2" alone on a line — the History book
# prints one at the top of each lesson page). Titled lessons ("Lesson 3: ...")
# are real headings and survive; only the bare number line is furniture.
_FOOTER_LESSON_LINE = re.compile(r"(?m)^[ \t]*LESSON[ \t]+\d+[ \t]*$\n?", re.I)
# Some books print an "fi"/"fl" ligature as its own glyph and the extractor
# leaves a gap: "Defi ne", "scientifi c", "confi guration". Only joins when a
# letter precedes the ligature and a lowercase letter follows the gap.
_LIGATURE_GAP = re.compile(r"(?<=[A-Za-z])(ffi|ffl|fi|fl)[ \t]+(?=[a-z])")
# Same gap when the word STARTS with the ligature: "fi eld", "fi rst".
_LIGATURE_GAP_START = re.compile(r"(?<![A-Za-z])(fi|fl)[ \t]+(?=[a-z]{2})")
# U+FFFE is a hyphen in "non\ufffeliving" but a line break in
# "a. mega\ufffeb. kilo" (list items run together).
_FFFE_LISTBREAK = re.compile(r"\ufffe(?=[a-z]\.\s)")


def _clean_text(text: str) -> str:
    """Per-chunk cleanup of extraction noise: math letters folded to plain
    ASCII, vertical "u n i t 4" margin tabs, running footers, private-font
    bullets, split ligatures, stray tabs and U+FFFE."""
    text = _fold_math_alphanumerics(text)
    text = _WATERMARK.sub("", text)
    text = _HEADER_TITLE_BEFORE_UNIT.sub("", text)
    text = _HEADER_UNIT_LINE.sub("", text)
    text = _HEADER_GRADE_LINE.sub("", text)
    text = _HEADER_SUBJECT_GRADE.sub("", text)
    text = _HEADER_STUDENT_TEXTBOOK.sub("", text)
    text = _FOOTER_LESSON_LINE.sub("", text)
    text = _MARGIN_UNIT.sub(" ", text)
    text = _RUNNING_FOOTER.sub("", text)
    text = _FFFE_LISTBREAK.sub("\n", text).replace("\ufffe", "-")
    text = text.translate(_ODD_BULLETS)
    text = text.replace("\t", " ")
    text = _LIGATURE_GAP.sub(lambda m: m.group(1), text)
    text = _LIGATURE_GAP_START.sub(lambda m: m.group(1), text)
    text = re.sub(r" +\n", "\n", text)  # trailing spaces
    text = re.sub(r"(?m)^ +", "", text)  # leading spaces left by dropped icons
    return re.sub(r" {2,}", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


def _unit_by_page(pdf_path: Path) -> dict[int, str]:
    """MoE textbooks print a running header ("Unit 4: Reproduction") at the top
    of every page. Read it straight from the PDF text layer (pdfium) to get a
    reliable unit per PDF page; Docling's heading trail is often just the
    nearest sub-heading. Pages without a header inherit the previous unit."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    found: dict[int, str] = {}
    for i in range(len(pdf)):
        try:
            text = pdf[i].get_textpage().get_text_range()
        except Exception:
            continue
        for line in text.splitlines()[:3]:
            line = " ".join(line.split())
            m = _UNIT_RE.match(line)
            if m:
                found[i + 1] = m.group(1)[:120]
                break
    units: dict[int, str] = {}
    current = None
    for page in range(1, len(pdf) + 1):
        current = found.get(page, current)
        if current:
            units[page] = current
    return units


def _merge_chunks(raw: list[dict], max_chars: int = MAX_CHUNK_CHARS) -> list[dict]:
    """raw: [{"text", "headings": tuple, "p0", "p1"}] in reading order.
    Consecutive chunks with identical headings are joined until max_chars."""
    merged: list[dict] = []
    for item in raw:
        last = merged[-1] if merged else None
        if (
            last
            and last["headings"] == item["headings"]
            and len(last["text"]) + len(item["text"]) + 2 <= max_chars
        ):
            last["text"] += "\n\n" + item["text"]
            pages = [p for p in (last["p0"], last["p1"], item["p0"], item["p1"]) if p is not None]
            last["p0"], last["p1"] = (min(pages), max(pages)) if pages else (None, None)
        else:
            merged.append(dict(item))
    return merged


def _delete_vectors(vector_store, ids):
    try:
        if ids:
            vector_store.delete(ids=ids)
    except Exception as e:
        logger.warning(f"Could not clean up partial vectors: {e}")


def _plan_book(pdf_path: Path, cli_offset: int | None, allow_no_units: bool = False, write_units: bool = True) -> dict:
    """Decide how to ingest one PDF without any manual per-book numbers.

    offset  : --page-offset if given, else <book>.book.json {"page_offset": N},
              else detected from the printed page numbers (must be confident)
    units   : <book>.units.json if present, else the running "Unit N:" header,
              else built from the Contents / headers / opener pages (written
              next to the PDF as <book>.units.json so you can review and edit it)
    Returns {"status": "ok"|"scanned"|"no_offset"|"no_units", "offset", "offset_source",
             "units_source", "message"}.
    """
    pages = book_tools.read_pages(pdf_path)
    if not book_tools.has_text_layer(pages):
        return {"status": "scanned", "offset": None, "offset_source": "-", "units_source": "-",
                "message": "scanned PDF (no text layer); run: ocrmypdf --skip-text "
                           f'"{pdf_path}" "{pdf_path.with_name(pdf_path.stem + "_ocr.pdf")}"'}

    sidecar = pdf_path.with_suffix(".book.json")
    if cli_offset is not None:
        offset, source = cli_offset, "--page-offset"
    elif sidecar.exists():
        offset, source = int(json.loads(sidecar.read_text(encoding="utf-8"))["page_offset"]), "book.json"
    else:
        d = book_tools.detect_page_offset(pages)
        if not d["confident"]:
            return {"status": "no_offset", "offset": None, "offset_source": "-", "units_source": "-",
                    "message": f"could not detect the page offset reliably (best guess {d['offset']}, "
                               f"{d['votes']} votes). Create {sidecar.name} containing "
                               '{"page_offset": N}, or pass --page-offset N with --only-subject'}
        offset, source = d["offset"], f"auto ({d['votes']}/{d['pages_with_text']} pages agree)"

    units_file = pdf_path.with_suffix(".units.json")
    if units_file.exists():
        units_source = "units.json"
    else:
        mode, entries = book_tools.auto_units(pages, offset)
        if mode == "running headers":
            units_source = "running header"
        elif entries:
            units_source = f"built from {mode} ({len(entries)} units)"
            if write_units:
                units_file.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
                units_source += f" -> wrote {units_file.name}"
        elif allow_no_units:
            units_source = "NONE (falls back to nearest heading; unit names will be poor)"
        else:
            return {"status": "no_units", "offset": offset, "offset_source": source, "units_source": "-",
                    "message": f"could not find the unit names. Create {units_file.name} (see "
                               "make_units_json.py) or pass --allow-no-units"}
    return {"status": "ok", "offset": offset, "offset_source": source, "units_source": units_source, "message": ""}


def _remove_book(db, vector_store, textbook) -> None:
    """Delete one book completely: its vectors in Chroma, then its chunk rows
    and the textbook row. Vectors go first so a failure can't leave vectors
    that no database row points to."""
    ids = [v for (v,) in db.query(Chunk.vector_id).filter(Chunk.textbook_id == textbook.id)]
    for i in range(0, len(ids), 500):
        vector_store.delete(ids=ids[i : i + 500])
    db.query(Chunk).filter(Chunk.textbook_id == textbook.id).delete()
    db.delete(textbook)
    db.commit()
    logger.info(f"Removed '{textbook.title}': {len(ids)} chunks")


def list_status(db, vector_store, root: Path, grades: list[int] | None = None) -> None:
    """What is ingested, what is waiting on disk, and whether Chroma and the
    database agree (vectors without database rows = leftovers of a failed run)."""
    books = db.query(Textbook).order_by(Textbook.grade, Textbook.subject).all()
    print(f"\nINGESTED ({len(books)} books)")
    total_rows = 0
    for tb in books:
        if grades and tb.grade not in grades:
            continue
        n = db.query(Chunk).filter(Chunk.textbook_id == tb.id).count()
        total_rows += n
        print(f"  grade {tb.grade:>2}  {tb.subject:<26} {tb.title:<34} {n:>6} chunks")
    print("\nWAITING ON DISK (not ingested yet)")
    waiting = 0
    for grade, subject, pdf_path in _discover_files(root, grades):
        if db.query(Textbook).filter(Textbook.source_file_path == str(pdf_path)).first() is None:
            waiting += 1
            print(f"  grade {grade:>2}  {subject:<26} {pdf_path.name}")
    if not waiting:
        print("  (nothing)")
    if vector_store is not None:
        all_rows = db.query(Chunk).count()
        vectors = vectorstore.collection_count(constants.TEXTBOOK_COLLECTION_NAME)
        verdict = "OK" if vectors == all_rows else (
            f"MISMATCH: {abs(vectors - all_rows)} {'vectors with no database row (leftovers)' if vectors > all_rows else 'database rows with no vector'}")
        print(f"\nVector store rows: {vectors}   database chunks: {all_rows}   -> {verdict}")


def remove_books(db, vector_store, subjects: set[str], grades: list[int] | None,
                 assume_yes: bool = False, ask=input) -> int:
    """Delete ingested books (vectors, chunk rows, textbook row) by subject and
    optional grade. Shows what will go and asks for YES first. Returns how many
    books were removed."""
    q = db.query(Textbook).filter(Textbook.subject.in_(sorted(subjects)))
    if grades:
        q = q.filter(Textbook.grade.in_(grades))
    books = q.order_by(Textbook.grade, Textbook.subject).all()
    if not books:
        print("No ingested book matches that subject/grade. Nothing removed.")
        return 0
    print("These ingested books will be DELETED (vectors, chunks and quiz questions made from them):")
    for tb in books:
        n = db.query(Chunk).filter(Chunk.textbook_id == tb.id).count()
        print(f"  grade {tb.grade:>2}  {tb.subject:<26} {tb.title}  ({n} chunks)")
    if not assume_yes and ask("Type YES to delete them: ").strip() != "YES":
        print("Cancelled. Nothing removed.")
        return 0
    for tb in books:
        _remove_book(db, vector_store, tb)
    return len(books)


def ingest_all(
    content_root: str | None = None,
    page_offset: int | None = None,
    only_subject: str | None = None,
    replace: bool = False,
    dry_run: bool = False,
    allow_no_units: bool = False,
    grades: list[int] | None = None,
) -> None:
    """Ingest every book under the content root that is not ingested yet.

    Each book gets its OWN page offset (front-matter PDF pages before printed
    page 1; chunks on those pages are skipped and stored page numbers become
    the printed ones). See _plan_book for how it is found. `page_offset`
    forces one value for every book in this run: only use it with only_subject.
    dry_run: print the plan for every book and change nothing.
    grades: only these grades (books are always taken lowest grade first).
    only_subject: one subject or several separated by commas.

    only_subject: process just that subject folder (the offset is per book, so
    ingest one book at a time). replace: delete the book's existing vectors and
    rows first, then ingest it again (needs only_subject, so it can't touch
    other books)."""
    root = Path(content_root or constants.TEXTBOOK_CONTENT_ROOT)
    if not root.exists():
        raise FileNotFoundError(f"Content root not found: {root}")

    converter = chunker = vector_store = None
    if not dry_run:
        # Docling's default PDF parser can't decode some embedded fonts in MoE
        # PDFs: headings come out as "/gid00052/gid00079..." garbage. The pdfium
        # backend reads the same text correctly.
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    backend=PyPdfiumDocumentBackend,
                    # The PDF has a text layer (checked in _plan_book); Docling's
                    # own OCR would only slow ingestion down.
                    pipeline_options=PdfPipelineOptions(do_ocr=False),
                )
            }
        )
        chunker = HierarchicalChunker()
        embeddings = RetrieverBuilder().embeddings
        vector_store = vectorstore.get_vector_store(
            collection_name=constants.TEXTBOOK_COLLECTION_NAME,
            embedding_function=embeddings,
        )

    skipped: list[str] = []
    if page_offset is not None and not only_subject:
        logger.warning(f"--page-offset {page_offset} is applied to EVERY new book in this run. "
                       "Leave it out to detect each book's offset automatically.")
    db = SessionLocal()
    try:
        wanted_subjects = _subject_set(only_subject)
        for grade, subject, pdf_path in _discover_files(root, grades):
            if wanted_subjects and subject not in wanted_subjects:
                continue
            already = (
                db.query(Textbook)
                .filter(Textbook.source_file_path == str(pdf_path))
                .first()
            )
            if already and not replace:
                logger.info(f"Skipping {pdf_path.name}: already ingested")
                if dry_run:
                    print(f"  skip    {pdf_path.name}: already ingested")
                continue
            plan = _plan_book(pdf_path, page_offset, allow_no_units, write_units=not dry_run)
            if plan["status"] != "ok":
                skipped.append(pdf_path.name)
                logger.error(f"{pdf_path.name}: {plan['message']}")
                if dry_run:
                    print(f"  SKIPPED {pdf_path.name}: {plan['message']}")
                continue
            offset = plan["offset"]
            if dry_run:
                print(f"  ingest  {pdf_path.name}: grade {grade}, {subject}, offset {offset} [{plan['offset_source']}], "
                      f"units: {plan['units_source']}" + ("  (replaces existing copy)" if already else ""))
                continue
            if already and replace:
                logger.info(f"Replacing {pdf_path.name}: removing the existing copy first")
                _remove_book(db, vector_store, already)
            logger.info(f"Ingesting {pdf_path} (grade {grade}, {subject}); offset {offset} [{plan['offset_source']}]; "
                        f"units: {plan['units_source']}")

            textbook = Textbook(
                grade=grade,
                subject=subject,
                title=pdf_path.stem,
                source_file_path=str(pdf_path),
            )
            db.add(textbook)
            db.flush()  # assigns textbook.id before we build chunk rows

            dl_doc = converter.convert(str(pdf_path)).document
            chunk_rows, vector_texts, vector_metadatas, vector_ids = [], [], [], []
            unit_map = _units_from_sidecar(pdf_path) or _unit_by_page(pdf_path)

            raw = []
            for chunk in chunker.chunk(dl_doc):
                text = _clean_text(chunk.text or "")
                if not text:
                    continue
                p0, p1 = _page_range(chunk)
                if offset and p1 is not None and p1 <= offset:
                    continue  # front matter: covers, credits, contents
                headings = tuple(
                    _clean_text(h)
                    for h in (getattr(chunk.meta, "headings", None) or [])
                )
                raw.append({"text": text, "headings": headings, "p0": p0, "p1": p1})

            merged = _merge_chunks(raw)
            garbled = sum("/gid" in m["text"] or any("/gid" in h for h in m["headings"]) for m in merged)
            if garbled:
                logger.error(
                    f"{pdf_path.name}: {garbled}/{len(merged)} chunks contain '/gid' "
                    "glyph codes (font decoding failed); not ingesting this book."
                )
                db.rollback()
                continue

            for m in merged:
                pdf_p0 = m["p0"]
                unit = unit_map.get(pdf_p0) if pdf_p0 else None
                if not unit and m["headings"]:
                    unit = m["headings"][0]
                section = m["headings"][-1] if m["headings"] else None
                page_start, page_end = m["p0"], m["p1"]
                if offset and page_start is not None:
                    page_start = max(page_start - offset, 1)
                    page_end = max(page_end - offset, 1)
                text = m["text"]
                vector_id = str(uuid.uuid4())

                chunk_rows.append(
                    Chunk(
                        textbook_id=textbook.id,
                        unit_or_chapter=unit,
                        section=section,
                        page_start=page_start,
                        page_end=page_end,
                        text_excerpt=text[:280],
                        vector_id=vector_id,
                    )
                )
                vector_texts.append(_embed_text(grade, subject, unit, section, text))
                vector_metadatas.append(
                    {
                        "vector_id": vector_id,
                        "textbook_id": str(textbook.id),
                        "grade": grade,
                        "subject": subject,
                        "unit": unit or "",
                        "section": section or "",
                    }
                )
                vector_ids.append(vector_id)

            if not chunk_rows:
                logger.warning(f"No chunks extracted from {pdf_path}; skipping")
                db.rollback()
                continue

            db.add_all(chunk_rows)
            try:
                vectorstore.add_in_batches(vector_store, vector_texts, vector_metadatas, vector_ids)
                db.commit()
            except Exception:
                db.rollback()
                _delete_vectors(vector_store, vector_ids)  # no orphan vectors
                raise
            logger.info(f"Wrote {len(chunk_rows)} chunks for {pdf_path.name}")
    finally:
        db.close()
    if skipped:
        logger.warning(f"{len(skipped)} book(s) were skipped, see the messages above: {', '.join(skipped)}")


def _open_store_and_db():
    """Real database session and vector store (used by --status and --remove)."""
    embeddings = RetrieverBuilder().embeddings
    store = vectorstore.get_vector_store(
        collection_name=constants.TEXTBOOK_COLLECTION_NAME, embedding_function=embeddings
    )
    return SessionLocal(), store


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Ingest every textbook under the content folder that is not ingested yet, "
                    "lowest grade first. Each book's page offset and unit names are found automatically.")
    ap.add_argument("--content-root", default=None)
    ap.add_argument("--grade", type=int, nargs="+", default=None,
                    help="only these grades, e.g. --grade 9   or   --grade 9 10")
    ap.add_argument("--only-subject", default=None,
                    help="only these subject folders, comma-separated, e.g. physics,economics")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would happen to every book (offset, units, skips); change nothing")
    ap.add_argument("--status", action="store_true",
                    help="list ingested books, books still waiting on disk, and check Chroma against the database")
    ap.add_argument("--remove", action="store_true",
                    help="DELETE the ingested books matching --only-subject (and --grade); asks for YES first")
    ap.add_argument("--yes", action="store_true", help="with --remove: do not ask for confirmation")
    ap.add_argument("--replace", action="store_true",
                    help="delete the book's existing data and ingest it again (requires --only-subject)")
    ap.add_argument("--page-offset", type=int, default=None,
                    help="force ONE offset for every book in this run (use with --only-subject); "
                         "normally leave it out so each book's offset is detected")
    ap.add_argument("--allow-no-units", action="store_true",
                    help="ingest books even when no unit names can be found (unit labels will be poor)")
    args = ap.parse_args()

    if args.replace and not args.only_subject:
        ap.error("--replace requires --only-subject so other books are not touched")
    if args.remove and not args.only_subject:
        ap.error("--remove requires --only-subject (and should be combined with --grade)")

    root = Path(args.content_root or constants.TEXTBOOK_CONTENT_ROOT)
    if args.status:
        db, store = _open_store_and_db()
        try:
            list_status(db, store, root, args.grade)
        finally:
            db.close()
    elif args.remove:
        db, store = _open_store_and_db()
        try:
            n = remove_books(db, store, _subject_set(args.only_subject), args.grade, args.yes)
            print(f"\nRemoved {n} book(s).")
        finally:
            db.close()
    else:
        ingest_all(args.content_root, args.page_offset, args.only_subject, args.replace,
                   args.dry_run, args.allow_no_units, args.grade)
