"""Single choke point for constructing the project's vector store. Was local Chroma
(persist_directory on disk); now Postgres + pgvector via langchain_postgres.PGVector, since
Chroma's on-disk files don't survive a Render redeploy and the project can't afford Render's
paid persistent disk - Supabase's free-tier Postgres holds this instead (same database as
DATABASE_URL, just on the psycopg3 driver langchain-postgres requires).

Every caller that used to construct Chroma(collection_name=..., embedding_function=...,
persist_directory=...) directly now calls get_vector_store(collection_name, embedding_function)
instead. Same similarity_search_with_score(query, k, filter) / .as_retriever() surface, and the
same Mongo-style filter dicts already used throughout this codebase keep working unchanged -
confirmed directly against a local pgvector instance: PGVector supports the exact bare-equality
{"$and": [{"grade": g}, {"subject": s}]} shorthand already in use, not just the more verbose
{"$eq": ...} form - so no caller's query logic needs to change, only its construction line.
"""

import json
import time

import psycopg
from langchain_postgres import PGVector

from config.settings import settings
from utils.logging import logger


def get_vector_store(collection_name: str, embedding_function):
    return PGVector(
        embeddings=embedding_function,
        collection_name=collection_name,
        connection=settings.VECTOR_DATABASE_URL,
        use_jsonb=True,
    )


def from_documents(documents, embedding, collection_name: str):
    """Build-and-populate in one call - mirrors Chroma.from_documents's call shape, for the
    ad-hoc upload flow (retriever/builder.py's build_hybrid_retriever)."""
    return PGVector.from_documents(
        documents=documents,
        embedding=embedding,
        collection_name=collection_name,
        connection=settings.VECTOR_DATABASE_URL,
        use_jsonb=True,
    )


def collection_count(collection_name: str) -> int:
    """Row count for one collection. PGVector has no public .count() - Chroma's own
    `_collection.count()` (Chroma-internal API) doesn't carry over - so this queries
    langchain_postgres's own tables directly. Used by ingestion/textbook_ingest.py's --status."""
    dsn = settings.VECTOR_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM langchain_pg_embedding e "
            "JOIN langchain_pg_collection c ON c.uuid = e.collection_id "
            "WHERE c.name = %s",
            (collection_name,),
        )
        row = cur.fetchone()
        return row[0] if row else 0


def fetch_collection_rows(collection_name: str, batch_size: int = 500):
    """Yield (id, document, metadata) for every row of one collection, straight from
    langchain_postgres's own tables. Used by scripts/reembed_vectors.py to re-embed a
    collection's existing text with a new embedding model/input shape, without needing
    the original source (PDFs, exam extraction) again."""
    dsn = settings.VECTOR_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT e.id, e.document, e.cmetadata FROM langchain_pg_embedding e "
            "JOIN langchain_pg_collection c ON c.uuid = e.collection_id "
            "WHERE c.name = %s ORDER BY e.id",
            (collection_name,),
        )
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            for row_id, document, cmetadata in rows:
                if isinstance(cmetadata, str):  # defensive: psycopg normally loads jsonb as dict already
                    cmetadata = json.loads(cmetadata)
                yield row_id, document, cmetadata or {}


def add_in_batches(vector_store, texts, metadatas, ids, batch_size=50, retries=4, pace_seconds=0.0):
    """Embed + store in small batches, retrying on rate-limit/transient errors (a whole
    book, or a whole collection, in one call can exceed free-tier embedding quotas).
    pace_seconds, if set, sleeps that long after each successful batch - a fixed-rate
    throttle on top of the reactive per-batch retry below, for a provider whose free-tier
    RPM is low enough that firing batches back-to-back trips it on nearly every call
    (confirmed against Gemini's embedding free tier: reactive backoff alone spent most of
    its time retrying rather than progressing). Shared by ingestion/textbook_ingest.py and
    scripts/reembed_vectors.py."""
    for i in range(0, len(texts), batch_size):
        sl = slice(i, i + batch_size)
        for attempt in range(1, retries + 1):
            try:
                vector_store.add_texts(texts=texts[sl], metadatas=metadatas[sl], ids=ids[sl])
                break
            except Exception as e:
                if attempt == retries:
                    raise
                wait = 10 * attempt
                logger.warning(f"Batch {i}-{i + batch_size} failed ({e}); retrying in {wait}s")
                time.sleep(wait)
        logger.info(f"  embedded {min(i + batch_size, len(texts))}/{len(texts)} items")
        if pace_seconds:
            time.sleep(pace_seconds)
