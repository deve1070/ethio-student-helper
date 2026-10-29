"""One-time: copy every vector from the local Chroma DB into the pgvector-backed Postgres
VECTOR_DATABASE_URL points at (Supabase, once that project exists). Reuses each document's
EXISTING embedding (PGVector.add_embeddings) rather than re-embedding the text, so the migrated
vectors are byte-identical to the originals, not a fresh (possibly slightly different) encoding.

This is the one place in the project that's still allowed to import Chroma directly - its whole
job is reading the old format being retired, not serving requests.

Idempotent: each id is the same one already used in Chroma (e.g. "exam-123"), and PGVector upserts
on conflict, so re-running after a partial failure is safe.

Run from backend/ (venv active), once CHROMA_DB_PATH below points at your real local chroma_db/
and VECTOR_DATABASE_URL (in .env) points at the target Postgres:

    python -m scripts.migrate_vectors_to_pgvector
    python -m scripts.migrate_vectors_to_pgvector --collection esslce_exams
    python -m scripts.migrate_vectors_to_pgvector --dry-run
"""

import argparse

CHROMA_DB_PATH = "./chroma_db"
BATCH_SIZE = 500


def migrate_collection(name: str, dry_run: bool) -> int:
    import chromadb

    from retriever import vectorstore

    source = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    try:
        coll = source.get_collection(name)
    except Exception as e:
        print(f"  {name}: not found in local Chroma ({e}) - skipped")
        return 0
    total = coll.count()
    print(f"{name}: {total} vectors to migrate")
    if total == 0 or dry_run:
        return total

    target = vectorstore.get_vector_store(collection_name=name, embedding_function=None)
    moved = 0
    offset = 0
    while offset < total:
        batch = coll.get(
            limit=BATCH_SIZE, offset=offset, include=["embeddings", "documents", "metadatas"]
        )
        target.add_embeddings(
            texts=batch["documents"],
            embeddings=[list(e) for e in batch["embeddings"]],
            metadatas=batch["metadatas"],
            ids=batch["ids"],
        )
        moved += len(batch["ids"])
        offset += BATCH_SIZE
        print(f"  {name}: {moved}/{total}")
    return moved


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--collection",
        choices=["textbooks", "esslce_exams", "exam_questions"],
        default=None,
        help="just this one collection (default: all three)",
    )
    ap.add_argument("--dry-run", action="store_true", help="print counts only, write nothing")
    args = ap.parse_args()

    collections = [args.collection] if args.collection else ["textbooks", "esslce_exams", "exam_questions"]
    for name in collections:
        migrate_collection(name, args.dry_run)
