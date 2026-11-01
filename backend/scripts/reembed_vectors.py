"""One-time: re-embed every vector in the project's pgvector collections with the
embedding model retriever/builder.py's RetrieverBuilder now uses (local, via fastembed
and the EMBEDDING_MODEL setting - see config/settings.py's comment for why this moved
back from the Gemini embedding API: that free tier's daily quota proved unworkable for
a corpus this size, and fastembed removes torch's RAM overhead that ruled out a local
model the first time around). Switching embedding models changes the vector space, so
every existing vector has to be recomputed - there is no way to keep old vectors and mix
in new ones.

Reads each row's existing (document, metadata) straight from the pgvector tables via
retriever.vectorstore.fetch_collection_rows - no PDF re-parsing, no re-running exam
extraction. For the "textbooks" collection, the embedded text is rebuilt through
ingestion.textbook_ingest._embed_text() using the row's own unit/section metadata, so
textbook chunks pick up the hierarchical unit/section prefix on this same pass. The two
exam collections ("exam_questions", "esslce_exams") keep their stored text unchanged -
see ingestion.textbook_ingest._embed_text's docstring for why hierarchy is deliberately
NOT added there.

Ids are preserved exactly (same vector_id strings): add_texts/add_embeddings upserts by
id (INSERT ... ON CONFLICT (id) DO UPDATE, confirmed from langchain_postgres's source),
so each row is overwritten in place rather than deleted-then-reinserted. This matters
beyond tidiness - deleting a collection before the new rows are fully written leaves a
window where an interruption (process kill, free-tier rate limit exhausting the retry
budget, a crash) permanently loses whatever hadn't been re-added yet, since the full
chunk text for "textbooks" only ever lives in the vector store's document column, not
in the Chunk DB row (which only keeps a 280-char excerpt). Upserting removes that window
entirely: at every point during the run, every id still resolves to either its old or
its new vector, never nothing.

Run from backend/ (venv active):

    python -m scripts.reembed_vectors
    python -m scripts.reembed_vectors --collection textbooks
    python -m scripts.reembed_vectors --dry-run
"""

import argparse

from config import constants
from ingestion.textbook_ingest import _embed_text
from retriever import vectorstore
from retriever.builder import RetrieverBuilder
from utils.logging import logger

COLLECTIONS = {
    "textbooks": constants.TEXTBOOK_COLLECTION_NAME,
    "exam_questions": constants.EXAM_CACHE_COLLECTION_NAME,
    "esslce_exams": constants.EXAM_COLLECTION_NAME,
}


def _rebuild_textbook_text(document: str, metadata: dict) -> str:
    return _embed_text(
        grade=metadata.get("grade"),
        subject=metadata.get("subject") or "",
        unit=metadata.get("unit") or None,
        section=metadata.get("section") or None,
        text=document,
    )


def reembed_collection(name: str, dry_run: bool, batch_size: int = 100, pace_seconds: float = 5.0) -> int:
    rows = list(vectorstore.fetch_collection_rows(name))
    logger.info(f"{name}: {len(rows)} vectors to re-embed")
    if not rows or dry_run:
        return len(rows)

    is_textbooks = name == constants.TEXTBOOK_COLLECTION_NAME
    ids = [row_id for row_id, _document, _metadata in rows]
    metadatas = [metadata for _row_id, _document, metadata in rows]
    texts = [
        _rebuild_textbook_text(document, metadata) if is_textbooks else document
        for _row_id, document, metadata in rows
    ]

    embeddings = RetrieverBuilder().embeddings
    target = vectorstore.get_vector_store(collection_name=name, embedding_function=embeddings)
    vectorstore.add_in_batches(
        target, texts, metadatas, ids, batch_size=batch_size, pace_seconds=pace_seconds
    )
    logger.info(f"{name}: re-embedded {len(rows)} vectors")
    return len(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--collection",
        choices=list(COLLECTIONS),
        default=None,
        help="just this one collection (default: all three)",
    )
    ap.add_argument("--dry-run", action="store_true", help="print counts only, write nothing")
    ap.add_argument(
        "--batch-size",
        type=int,
        default=256,
        help="texts per embed_documents() call - local embedding has no request-rate "
             "limit to economize on, so this is just a memory/throughput tradeoff "
             "(matches FastEmbedEmbeddings' own default batch size)",
    )
    ap.add_argument(
        "--pace-seconds",
        type=float,
        default=0.0,
        help="fixed pause after each successful batch, on top of the reactive retry "
             "below - local embedding has no rate limit to pace around, so this "
             "defaults to 0; only useful again if this ever points at an API-backed "
             "embedding provider",
    )
    args = ap.parse_args()

    names = [COLLECTIONS[args.collection]] if args.collection else list(COLLECTIONS.values())
    for name in names:
        reembed_collection(name, args.dry_run, args.batch_size, args.pace_seconds)
