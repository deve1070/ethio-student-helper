"""Resolving a grounded quote back to a structured, trustworthy citation - general textbook/RAG
infrastructure, not specific to any one content type (ESSLCE elaborations and Study Notes both need it)."""

from db.models import Chunk, Textbook


def citation_for(db, vector_id: str | None) -> dict | None:
    """The structured {textbook, grade, subject, unit_or_chapter, section, page_start, page_end} a
    grounding quote actually came from - looked up from Chunk/Textbook by vector_id (the same uuid
    textbook_ingest.py writes into both the Chroma document's metadata and the Chunk row, so this is an
    exact join, never a guess). A page number is exactly the kind of fact an LLM must never be trusted to
    state on its own - this is the only place that field is ever set. None if there's no vector_id (e.g.
    an ESSLCE reading-comprehension question grounded in the exam's own passage, not a textbook) or the
    Chunk was since removed (e.g. a textbook re-ingestion) - never a stale or fabricated citation."""
    if not vector_id:
        return None
    chunk = db.query(Chunk).filter(Chunk.vector_id == vector_id).one_or_none()
    if chunk is None:
        return None
    textbook = db.get(Textbook, chunk.textbook_id)
    if textbook is None:
        return None
    return {
        "textbook": textbook.title,
        "grade": textbook.grade,
        "subject": textbook.subject,
        "unit_or_chapter": chunk.unit_or_chapter,
        "section": chunk.section,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
    }
