"""
Read, approve or reject the generated questions, one at a time, in the terminal.
Only APPROVED questions are shown to students.

    python scripts/review_questions.py --grade 9 --subject chemistry
    python scripts/review_questions.py --grade 9 --subject chemistry --unit "Unit 4" --limit 30

For each question you see the options, the marked answer, the explanation and the
book sentence the question is based on. Keys:
    a  approve (the question goes live)
    r  reject  (kept in the database as 'retired', never shown)
    k  the marked answer is WRONG: type the right letter; the question is fixed and approved
    s  skip (stays in the review queue)
    q  quit
Check the answer against your textbook, not against your memory.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LETTERS = (
    "A",
    "B",
    "C",
    "D",
)  # a tuple: with a string, "" in "ABCD" is True and an empty answer would pick A


def show(i: int, total: int, q, out=print) -> None:
    pages = (
        f"{q.page_start}"
        if q.page_end in (None, q.page_start)
        else f"{q.page_start}-{q.page_end}"
    )
    out(
        f"\n[{i}/{total}]  {q.unit_or_chapter}  |  printed page {pages}  |  {q.difficulty}"
    )
    out(f"Q: {q.question}")
    for letter, option in zip(LETTERS, q.options):
        out(
            f"   {letter}) {option}"
            + (
                "    <== marked correct"
                if LETTERS.index(letter) == q.answer_index
                else ""
            )
        )
    out(f"Why: {q.explanation}")
    out(f'Book: "{q.supporting_quote}"')


def review_loop(db, questions, ask=input, out=print) -> dict:
    """Interactive review; returns counts. `ask` and `out` can be replaced in tests."""
    counts = {"approved": 0, "rejected": 0, "fixed": 0, "skipped": 0}
    total = len(questions)
    for i, q in enumerate(questions, start=1):
        show(i, total, q, out)
        while True:
            choice = (
                ask("(a)pprove  (r)eject  (k)ey is wrong  (s)kip  (q)uit > ")
                .strip()
                .lower()
            )
            if choice == "a":
                q.status = "active"
                counts["approved"] += 1
            elif choice == "r":
                q.status = "retired"
                counts["rejected"] += 1
            elif choice == "k":
                letter = ""
                while letter not in LETTERS and letter != "X":
                    letter = (
                        ask("Which option is actually correct (A-D, or X to cancel)? ")
                        .strip()
                        .upper()
                    )
                    if letter not in LETTERS and letter != "X":
                        out("Please type A, B, C or D.")
                if letter == "X":
                    continue
                q.answer_index = LETTERS.index(letter)
                q.status = "active"
                counts["fixed"] += 1
            elif choice == "s":
                counts["skipped"] += 1
            elif choice == "q":
                db.commit()
                return counts
            else:
                out("Please type a, r, k, s or q.")
                continue
            db.commit()
            break
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grade", type=int, required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--unit", default=None)
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    from db.models_practice import QuizQuestion
    from db.session import SessionLocal
    from utils.subjects import resolve_subject

    db = SessionLocal()
    available = sorted(
        {
            s
            for (s,) in db.query(QuizQuestion.subject)
            .filter(QuizQuestion.grade == args.grade)
            .distinct()
        }
    )
    subject, suggestion = resolve_subject(args.subject, available)
    if subject is None:
        sys.exit(
            f"No questions for '{args.subject}' in grade {args.grade}. "
            + (f"Did you mean '{suggestion}'? " if suggestion else "")
            + f"Available: {', '.join(available) or 'none'}"
        )
    q = db.query(QuizQuestion).filter(
        QuizQuestion.grade == args.grade,
        QuizQuestion.subject == subject,
        QuizQuestion.status == "needs_review",
    )
    if args.unit:
        q = q.filter(QuizQuestion.unit_or_chapter.ilike(f"%{args.unit}%"))
    waiting = q.count()
    rows = (
        q.order_by(
            QuizQuestion.unit_or_chapter, QuizQuestion.page_start, QuizQuestion.question
        )
        .limit(args.limit)
        .all()
    )
    print(f"{waiting} question(s) waiting for review; showing {len(rows)}.")
    if not rows:
        return
    counts = review_loop(db, rows)
    print(
        f"\nDone: {counts['approved']} approved, {counts['fixed']} fixed and approved, "
        f"{counts['rejected']} rejected, {counts['skipped']} skipped."
    )
    db.close()


if __name__ == "__main__":
    main()
