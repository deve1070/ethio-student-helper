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

import psycopg
from langchain_postgres import PGVector

from config.settings import settings


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
