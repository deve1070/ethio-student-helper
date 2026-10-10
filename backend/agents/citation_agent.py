"""
Turns retrieved chunks into structured citations the API can return
alongside an answer, e.g.
    {"textbook": "Biology Grade 11", "unit": "Unit 4", "page": "110-113"}

Two entry points:
  - extract(documents): from freshly retrieved LangChain Documents
    (explain mode, and a freshly generated exam answer)
  - resolve_chunk_ids(chunk_ids): from stored Chunk ids on a cached
    ExamAnswer, so a cache hit can redisplay the same citations without
    re-running retrieval

Both depend on ingestion/textbook_ingest.py having written a matching
Chunk row (keyed by vector_id) for every vector in the textbook
collection.
"""
import re
import uuid

from langchain.schema import Document

from db.models import Chunk, Textbook
from db.session import SessionLocal


def _format_page(chunk: Chunk) -> str | None:
    if chunk.page_start and chunk.page_end and chunk.page_start != chunk.page_end:
        return f"{chunk.page_start}-{chunk.page_end}"
    return str(chunk.page_start) if chunk.page_start else None


_STOPWORDS = frozenset(
    "about above after again also because been before being between both cannot "
    "could does doing each from have having into more most other over same such "
    "than that their them then there these they this those through under very "
    "were what when where which while will with would your only some many made "
    "make used uses using provided context textbook excerpt excerpts according".split()
)


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in _STOPWORDS}


# Chunks like these repeat a lot of topic words (they list or recap them) but
# aren't where a student learns the idea, so they should rarely be the cited
# source when a real explanation was retrieved too.
_NON_INSTRUCTIONAL = re.compile(
    r"Unit Outcomes|Unit Contents|Unit Summary|Key Terms|Review Exercise|Self Assessment|Summary and Review",
    re.I,
)


def select_cited_documents(
    answer: str, documents: list[Document], max_citations: int = 4, min_shared: int = 3
) -> list[Document]:
    """Keep only the retrieved chunks the answer actually draws on.

    Retrieval returns ~10 chunks, but most are only loosely related. Score each
    by how many distinctive words it shares with the answer, keep the best few,
    and drop chunks that share almost nothing. Cheap and deterministic (no LLM
    call); ordered best-first.
    """
    answer_words = _content_words(answer)
    scored = []
    for doc in documents:
        shared = len(answer_words & _content_words(doc.page_content))
        label = doc.page_content[:400] + " " + str(doc.metadata.get("section", ""))
        if _NON_INSTRUCTIONAL.search(label):
            shared *= 0.4  # demote outlines, key-term lists and recaps
        scored.append((shared, doc))
    scored.sort(key=lambda t: t[0], reverse=True)
    if not scored or scored[0][0] < min_shared:
        return []
    top = scored[0][0]
    keep = [d for shared, d in scored if shared >= max(min_shared, top * 0.4)]
    return keep[:max_citations]


class CitationAgent:
    def extract(
        self,
        documents: list[Document],
        answer: str | None = None,
        max_citations: int = 4,
    ) -> list[dict]:
        """Resolve retrieved chunks into human-readable citations.

        Falls back to raw vector metadata (subject/unit, no page, no
        chunk_id) if a chunk's vector_id can't be found in Postgres —
        e.g. the vector index and the relational DB have drifted out of
        sync — rather than silently dropping the citation.
        """
        citations = []
        seen_vector_ids = set()
        seen_labels = set()
        if answer is not None:
            documents = select_cited_documents(answer, documents, max_citations)
        db = SessionLocal()
        try:
            for doc in documents:
                vector_id = doc.metadata.get("vector_id")
                if vector_id in seen_vector_ids:
                    continue
                seen_vector_ids.add(vector_id)

                chunk = (
                    db.query(Chunk).filter(Chunk.vector_id == vector_id).one_or_none()
                    if vector_id
                    else None
                )
                if chunk is None:
                    citations.append(
                        {
                            "textbook": doc.metadata.get("subject", "Unknown"),
                            "unit": doc.metadata.get("unit", ""),
                            "page": None,
                            "chunk_id": None,
                        }
                    )
                    continue

                textbook = db.get(Textbook, chunk.textbook_id)
                entry = {
                    "textbook": textbook.title if textbook else "Unknown",
                    "unit": chunk.unit_or_chapter or "",
                    "page": _format_page(chunk),
                    "chunk_id": str(chunk.id),
                }
                label = (entry["textbook"], entry["unit"], entry["page"])
                if label in seen_labels:
                    continue  # same place in the book, cited once
                seen_labels.add(label)
                citations.append(entry)
            return citations
        finally:
            db.close()

    def resolve_chunk_ids(self, chunk_ids: list[uuid.UUID]) -> list[dict]:
        """Same citation shape as extract(), but starting from stored
        Chunk ids — used to redisplay a cached exam answer's citations
        without re-running retrieval.
        """
        if not chunk_ids:
            return []
        db = SessionLocal()
        try:
            citations = []
            for chunk_id in chunk_ids:
                chunk = db.get(Chunk, chunk_id)
                if chunk is None:
                    continue
                textbook = db.get(Textbook, chunk.textbook_id)
                citations.append(
                    {
                        "textbook": textbook.title if textbook else "Unknown",
                        "unit": chunk.unit_or_chapter or "",
                        "page": _format_page(chunk),
                        "chunk_id": str(chunk.id),
                    }
                )
            return citations
        finally:
            db.close()
