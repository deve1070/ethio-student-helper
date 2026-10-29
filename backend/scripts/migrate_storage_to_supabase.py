"""One-time: upload every exam diagram photo (exams_out/*/p*.jpg) and payment receipt
(receipts/*.jpg) to their Supabase Storage buckets, so exams/store.py's question_page_image()
and api/routes_payments.py can read them back by the same relative path once local disk is gone.

Requires SUPABASE_URL and SUPABASE_SERVICE_KEY to already be set (storage.upload has no local
fallback once those are set - see storage.py). Create the two buckets ("exam-pages", "receipts")
in the Supabase dashboard first; this script only uploads into them.

Idempotent: storage.upload always upserts, so re-running after an interruption just re-uploads
whatever didn't finish, overwriting nothing differently.

Run from backend/ (venv active):
    python -m scripts.migrate_storage_to_supabase
    python -m scripts.migrate_storage_to_supabase --only exam-pages
    python -m scripts.migrate_storage_to_supabase --only receipts
"""

import argparse
from pathlib import Path

import storage
from config.settings import settings


def migrate_exam_pages(root: Path) -> int:
    n = 0
    for jpg in sorted(root.glob("*/p*.jpg")):
        # question_page_image() reads f"{paper.source_dir}/p{page:02d}.jpg", and paper.source_dir is
        # stored as the literal path passed to `load`, e.g. "exams_out/english_2005" - so the upload
        # key must be root/paper-folder/filename, not just paper-folder/filename.
        key = f"{root}/{jpg.parent.name}/{jpg.name}"
        storage.upload("exam-pages", key, jpg.read_bytes())
        n += 1
        if n % 100 == 0:
            print(f"  exam-pages: {n}")
    return n


def migrate_receipts(root: Path) -> int:
    n = 0
    for jpg in sorted(root.glob("*.jpg")):
        storage.upload("receipts", f"{settings.RECEIPTS_DIR}/{jpg.name}", jpg.read_bytes())
        n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", choices=["exam-pages", "receipts"], default=None)
    ap.add_argument("--exams-out", default="exams_out")
    ap.add_argument("--receipts-dir", default=None, help="default: settings.RECEIPTS_DIR")
    args = ap.parse_args()

    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not set - nothing to migrate to")

    if args.only in (None, "exam-pages"):
        root = Path(args.exams_out)
        if root.is_dir():
            n = migrate_exam_pages(root)
            print(f"exam-pages: {n} photos uploaded")
        else:
            print(f"exam-pages: {root} not found - skipped")

    if args.only in (None, "receipts"):
        root = Path(args.receipts_dir or settings.RECEIPTS_DIR)
        if root.is_dir():
            n = migrate_receipts(root)
            print(f"receipts: {n} photos uploaded")
        else:
            print(f"receipts: {root} not found - skipped")
