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
import time
import unicodedata
import uuid
from pathlib import Path

from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.transforms.chunker import HierarchicalChunker
from langchain_community.vectorstores import Chroma

from config import constants
from config.settings import settings
from db.models import Chunk, Textbook
from db.session import SessionLocal
from retriever.builder import RetrieverBuilder
from utils.logging import logger


def _discover_files(root: Path):
    """Yield (grade, subject, path) for every PDF under the content root."""
    for grade_dir in sorted(root.glob("grade_*")):
        try:
            grade = int(grade_dir.name.split("_")[1])
        except (IndexError, ValueError):
            logger.warning(f"Skipping folder with unexpected name: {grade_dir}")
            continue
        if grade not in constants.SUPPORTED_GRADES:
            logger.warning(f"Skipping unsupported grade folder: {grade_dir}")
            continue
        for subject_dir in sorted(p for p in grade_dir.iterdir() if p.is_dir()):
            for pdf_path in sorted(subject_dir.glob("*.pdf")):
                yield grade, subject_dir.name.strip().lower(), pdf_path


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
    entries = sorted(
        json.loads(sidecar.read_text(encoding="utf-8")),
        key=lambda e: e["start_pdf_page"],
    )
    units: dict[int, str] = {}
    for idx, e in enumerate(entries):
        end = (
            entries[idx + 1]["start_pdf_page"] - 1 if idx + 1 < len(entries) else 10_000
        )
        for page in range(e["start_pdf_page"], end + 1):
            units[page] = e["unit"]
    return units


_MARGIN_UNIT = re.compile(r"\bu\s+n\s+i\s+t(?:\s+\d{1,2})?\b")
_RUNNING_FOOTER = re.compile(
    r"^[ \t]*(?:\d+[ \t]+)?Grade \d+ \w+ Textbook(?:[ \t]+\d+)?[ \t]*$", re.M
)
# Private-font bullets -> a normal bullet. \uf03f is the Symbol-font bullet in
# the Chemistry book; \uf8eb-\uf8f8 are pieces of large brackets (dropped).
_ODD_BULLETS = str.maketrans(
    {
        "\u0494": "\u2022",
        "\u02af": "\u2022",
        "\u25a0": "\u2022",
        "\uf03f": "\u2022",
        # Geography book: arrow/Wingdings bullets and emoji list markers
        "\u00de": "\u2022",
        "\uf0a7": "\u2022",
        "\u2705": "\u2022",
        "\U0001f30d": "\u2022",
        "\U0001f511": "\u2022",
        # pure decoration, dropped
        "\U0001f512": "",
        "\U0001f310": "",
        **{chr(c): "" for c in range(0xF8EB, 0xF8F9)},
    }
)
# Website watermark printed on every page of some PDFs ("Ethiofetena.com ...").
_WATERMARK = re.compile(r"[ \t]*Ethiofetena\.com[^\n]*\n?", re.I)
_UNIT_WORDS = "ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE"
# Running page headers: "TITLE IN CAPS / UNIT FOUR / 85", "Grade 9| Geography",
# "34 UNIT ONE". Removed so they don't pollute every chunk.
_HEADER_TITLE_BEFORE_UNIT = re.compile(
    r"^[ \t]*[A-Z][^\na-z]{8,}\n(?=[ \t]*UNIT[ \t]+(?:" + _UNIT_WORDS + r")[ \t]*$)",
    re.M,
)
_HEADER_UNIT_LINE = re.compile(
    r"^[ \t]*(?:\d+[ \t]*)?UNIT[ \t]+(?:" + _UNIT_WORDS + r")[ \t]*(?:\d+[ \t]*)?$\n?",
    re.M,
)
_HEADER_GRADE_LINE = re.compile(
    r"^[ \t]*(?:\d+[ \t]*)?Grade \d+[ \t]*\|[ \t]*[A-Za-z ]+$\n?", re.M
)
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
            pages = [
                p
                for p in (last["p0"], last["p1"], item["p0"], item["p1"])
                if p is not None
            ]
            last["p0"], last["p1"] = (min(pages), max(pages)) if pages else (None, None)
        else:
            merged.append(dict(item))
    return merged


def _add_in_batches(vector_store, texts, metadatas, ids, batch_size=50, retries=4):
    """Embed + store in small batches, retrying on rate-limit/transient errors
    (a whole book in one call can exceed free-tier embedding quotas)."""
    for i in range(0, len(texts), batch_size):
        sl = slice(i, i + batch_size)
        for attempt in range(1, retries + 1):
            try:
                vector_store.add_texts(
                    texts=texts[sl], metadatas=metadatas[sl], ids=ids[sl]
                )
                break
            except Exception as e:
                if attempt == retries:
                    raise
                wait = 10 * attempt
                logger.warning(
                    f"Batch {i}-{i + batch_size} failed ({e}); retrying in {wait}s"
                )
                time.sleep(wait)
        logger.info(f"  embedded {min(i + batch_size, len(texts))}/{len(texts)} chunks")


def _delete_vectors(vector_store, ids):
    try:
        if ids:
            vector_store.delete(ids=ids)
    except Exception as e:
        logger.warning(f"Could not clean up partial vectors: {e}")


def _remove_book(db, vector_store, textbook) -> None:
    """Delete one book completely: its vectors in Chroma, then its chunk rows
    and the textbook row. Vectors go first so a failure can't leave vectors
    that no database row points to."""
    ids = [
        v for (v,) in db.query(Chunk.vector_id).filter(Chunk.textbook_id == textbook.id)
    ]
    for i in range(0, len(ids), 500):
        vector_store.delete(ids=ids[i : i + 500])
    db.query(Chunk).filter(Chunk.textbook_id == textbook.id).delete()
    db.delete(textbook)
    db.commit()
    logger.info(f"Removed '{textbook.title}': {len(ids)} chunks")


def ingest_all(
    content_root: str | None = None,
    page_offset: int = 0,
    only_subject: str | None = None,
    replace: bool = False,
) -> None:
    """page_offset = number of front-matter PDF pages before printed page 1
    (covers, credits, table of contents). Chunks on those pages are skipped and
    stored page numbers become the printed ones (pdf page - offset).

    only_subject: process just that subject folder (the offset is per book, so
    ingest one book at a time). replace: delete the book's existing vectors and
    rows first, then ingest it again (needs only_subject, so it can't touch
    other books)."""
    root = Path(content_root or constants.TEXTBOOK_CONTENT_ROOT)
    if not root.exists():
        raise FileNotFoundError(f"Content root not found: {root}")

    # Docling's default PDF parser can't decode some embedded fonts in MoE
    # PDFs: headings come out as "/gid00052/gid00079..." garbage. The pdfium
    # backend reads the same text correctly.
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                backend=PyPdfiumDocumentBackend,
                # The PDF has a text layer (checked above); Docling's own OCR
                # would only slow ingestion down.
                pipeline_options=PdfPipelineOptions(do_ocr=False),
            )
        }
    )
    chunker = HierarchicalChunker()
    embeddings = RetrieverBuilder().embeddings
    vector_store = Chroma(
        collection_name=constants.TEXTBOOK_COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=settings.CHROMA_DB_PATH,
    )

    db = SessionLocal()
    try:
        for grade, subject, pdf_path in _discover_files(root):
            if only_subject and subject != only_subject.strip().lower():
                continue
            already = (
                db.query(Textbook)
                .filter(Textbook.source_file_path == str(pdf_path))
                .first()
            )
            if already and replace:
                logger.info(
                    f"Replacing {pdf_path.name}: removing the existing copy first"
                )
                _remove_book(db, vector_store, already)
            elif already:
                logger.info(f"Skipping {pdf_path.name}: already ingested")
                continue
            if not _has_text_layer(pdf_path):
                logger.error(
                    f"{pdf_path.name} looks like a scanned PDF (no text layer). Make it "
                    f"searchable first, then ingest the result:\n"
                    f'    ocrmypdf --skip-text "{pdf_path}" "{pdf_path.with_name(pdf_path.stem + "_ocr.pdf")}"'
                )
                continue
            logger.info(f"Ingesting {pdf_path} (grade {grade}, {subject})")

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
                if page_offset and p1 is not None and p1 <= page_offset:
                    continue  # front matter: covers, credits, contents
                headings = tuple(
                    _clean_text(h)
                    for h in (getattr(chunk.meta, "headings", None) or [])
                )
                raw.append({"text": text, "headings": headings, "p0": p0, "p1": p1})

            merged = _merge_chunks(raw)
            garbled = sum(
                "/gid" in m["text"] or any("/gid" in h for h in m["headings"])
                for m in merged
            )
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
                if page_offset and page_start is not None:
                    page_start = max(page_start - page_offset, 1)
                    page_end = max(page_end - page_offset, 1)
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
                vector_texts.append(text)
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
                _add_in_batches(
                    vector_store, vector_texts, vector_metadatas, vector_ids
                )
                db.commit()
            except Exception:
                db.rollback()
                _delete_vectors(vector_store, vector_ids)  # no orphan vectors
                raise
            logger.info(f"Wrote {len(chunk_rows)} chunks for {pdf_path.name}")
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--page-offset",
        type=int,
        default=0,
        help="front-matter PDF pages before printed page 1 (Grade 9 Biology: 7)",
    )
    ap.add_argument("--content-root", default=None)
    ap.add_argument(
        "--only-subject",
        default=None,
        help="ingest just this subject folder, e.g. chemistry",
    )
    ap.add_argument(
        "--replace",
        action="store_true",
        help="delete the book's existing data and ingest it again "
        "(requires --only-subject)",
    )
    args = ap.parse_args()
    if args.replace and not args.only_subject:
        ap.error("--replace requires --only-subject so other books are not touched")
    ingest_all(args.content_root, args.page_offset, args.only_subject, args.replace)
