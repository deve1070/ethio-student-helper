"""Write the "why your choice looked right" notes ahead of time, so students see them at once instead of
waiting for the first request (explanations/wrong_choice.py). Questions that already have valid notes are
skipped, so it can be stopped and run again.

Run from backend/:
    venv/bin/python scripts/prefill_wrong_option_notes.py esslce --limit 50
    venv/bin/python scripts/prefill_wrong_option_notes.py practice --subject chemistry --limit 50

--wrong-first starts with the questions students have actually got wrong, most often first."""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models_practice import QuizAttempt, QuizQuestion  # noqa: E402
from db.session import SessionLocal  # noqa: E402
from exams.models import EsslceAttempt, EsslcePaper, EsslceQuestion  # noqa: E402
from exams.store import eligible  # noqa: E402
from explanations.wrong_choice import esslce_context, generate_notes, practice_context, store_notes, stored_notes  # noqa: E402
from llm.client import LLMClient  # noqa: E402
from sqlalchemy import func  # noqa: E402


def candidates(db, system: str, subject: str | None, wrong_first: bool):
    if system == "esslce":
        q = db.query(EsslceQuestion).join(EsslcePaper)
        if subject:
            q = q.filter(EsslcePaper.subject == subject)
        attempt, stem_of, context_of = EsslceAttempt, (lambda r: r.stem), esslce_context
        rows = [r for r in q.all() if eligible(r)]
    else:
        q = db.query(QuizQuestion).filter(QuizQuestion.status == "active")
        if subject:
            q = q.filter(QuizQuestion.subject == subject)
        attempt, stem_of, context_of = QuizAttempt, (lambda r: r.question), practice_context
        rows = q.all()
    if wrong_first:
        misses = dict(
            db.query(attempt.question_id, func.count())
            .filter(attempt.is_correct.is_(False))
            .group_by(attempt.question_id)
            .all()
        )
        rows.sort(key=lambda r: misses.get(r.id, 0), reverse=True)
    return [(r, stem_of, context_of) for r in rows if stored_notes(r, stem_of(r)) is None]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("system", choices=["esslce", "practice"])
    ap.add_argument("--subject")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--wrong-first", action="store_true")
    ap.add_argument("--pause", type=float, default=2.0, help="seconds between calls, to stay under the provider's rate limit")
    args = ap.parse_args()

    llm = LLMClient(temperature=0, max_tokens=1500)
    db = SessionLocal()
    todo = candidates(db, args.system, args.subject, args.wrong_first)
    print(f"{len(todo)} question(s) without notes; writing up to {args.limit}")
    written = failed = 0
    for row, stem_of, context_of in todo[: args.limit]:
        stem = stem_of(row)
        try:
            notes = generate_notes(llm, stem, list(row.options), row.answer_index, context_of(row))
        except Exception as e:  # noqa: BLE001  (one provider failure should not stop the run)
            print(f"  {row.id}: {type(e).__name__}: {e}")
            notes = None
        if notes is None:
            failed += 1
        else:
            store_notes(row, stem, notes)
            db.commit()
            written += 1
        time.sleep(args.pause)
    print(f"wrote {written}, could not write {failed}")


if __name__ == "__main__":
    main()
