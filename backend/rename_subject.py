"""
Rename a subject in place, without re-ingesting the book.

    python rename_subject.py geograpy geography            # dry run: shows what would change
    python rename_subject.py geograpy geography --apply    # does it

Why this works: the subject name is NOT part of the text that was embedded, so
the vectors are fine. It only lives in two places, and this script fixes both:
  1. the metadata stored next to each vector in Chroma (the search filter uses it)
  2. the `textbooks` table in Postgres (subject, and the folder name inside
     source_file_path, which the ingestion script uses to skip books it has
     already done)

Afterwards rename the folder on disk too, so a future ingestion run does not
treat the book as new:
    mv content/moe_textbooks/grade_9/geograpy content/moe_textbooks/grade_9/geography

Safe to run twice: vectors are found through the database rows, not through
their current subject, so a run that stopped halfway can simply be repeated.
Stop the API server first (Chroma should not be written by two processes).
"""
import argparse
import re
import warnings

warnings.filterwarnings("ignore")


def fix_path(path: str, old: str, new: str) -> str:
    """Replace the folder segment `old` with `new` inside a stored path."""
    return re.sub(rf"(?<=[\\/]){re.escape(old)}(?=[\\/])", new, path or "")


def rename_in_collection(collection, vector_ids, new_subject, batch=200):
    """Set metadata['subject'] = new_subject for the given vectors. Returns how many changed."""
    changed = 0
    for i in range(0, len(vector_ids), batch):
        ids = vector_ids[i : i + batch]
        got = collection.get(ids=ids, include=["metadatas"])
        keep_ids, metas = [], []
        for vid, meta in zip(got["ids"], got["metadatas"]):
            if meta is not None and meta.get("subject") != new_subject:
                meta = dict(meta)
                meta["subject"] = new_subject
                keep_ids.append(vid)
                metas.append(meta)
        if keep_ids:
            collection.update(ids=keep_ids, metadatas=metas)
            changed += len(keep_ids)
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--grade", type=int, default=None)
    ap.add_argument("--apply", action="store_true", help="write the changes (default is a dry run)")
    args = ap.parse_args()
    old, new = args.old.strip().lower(), args.new.strip().lower()

    from langchain_community.vectorstores import Chroma

    from config import constants
    from config.settings import settings
    from db.models import Chunk, Textbook
    from db.session import SessionLocal
    from retriever.builder import RetrieverBuilder

    db = SessionLocal()
    q = db.query(Textbook).filter(Textbook.subject == old)
    if args.grade is not None:
        q = q.filter(Textbook.grade == args.grade)
    books = q.all()
    if not books:
        print(f"No textbook with subject '{old}'. Nothing to do.")
        return

    vs = Chroma(collection_name=constants.TEXTBOOK_COLLECTION_NAME,
                embedding_function=RetrieverBuilder().embeddings,
                persist_directory=settings.CHROMA_DB_PATH)
    collection = vs._collection

    try:
        for tb in books:
            ids = [v for (v,) in db.query(Chunk.vector_id).filter(Chunk.textbook_id == tb.id)]
            new_path = fix_path(tb.source_file_path, old, new)
            print(f"{tb.title} (grade {tb.grade}): {len(ids)} chunks")
            print(f"   subject  : {old!r} -> {new!r}")
            print(f"   file path: {tb.source_file_path}\n          ->  {new_path}")
            if not args.apply:
                continue
            n = rename_in_collection(collection, ids, new)   # Chroma first
            print(f"   updated {n} vectors in Chroma")
            tb.subject = new
            tb.source_file_path = new_path
        if args.apply:
            db.commit()
            print("\nDone. Now rename the folder on disk (see the top of this file) and restart the server.")
        else:
            print("\nDry run only. Add --apply to make the change.")
    except Exception:
        db.rollback()
        print("\nFAILED before the database commit. Fix the problem and run it again; it is safe to repeat.")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
