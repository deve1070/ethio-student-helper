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


def select_questions(
    db,
    grade,
    subject=None,
    unit=None,
    flagged_only=False,
    limit=20,
    min_answers=None,
    max_accuracy=None,
):
    """Returns (questions to show, {question_id: [reasons]}, how many are waiting in total)."""
    from db.models_practice import QuizQuestion
    from practice import health

    min_answers = health.MIN_ANSWERS if min_answers is None else min_answers
    max_accuracy = health.MAX_ACCURACY if max_accuracy is None else max_accuracy
    if flagged_only:
        found = health.find_flagged(db, grade, subject, unit, min_answers, max_accuracy)
        return [q for q, _ in found[:limit]], {q.id: r for q, r in found}, len(found)

    q = db.query(QuizQuestion).filter(
        QuizQuestion.grade == grade, QuizQuestion.status == "needs_review"
    )
    if subject:
        q = q.filter(QuizQuestion.subject == subject)
    if unit:
        q = q.filter(QuizQuestion.unit_or_chapter.ilike(f"%{unit}%"))
    waiting = q.count()
    rows = (
        q.order_by(
            QuizQuestion.unit_or_chapter, QuizQuestion.page_start, QuizQuestion.question
        )
        .limit(limit)
        .all()
    )
    info = health.report_info(db, [r.id for r in rows])
    flags = {
        r.id: health.flag_reasons("needs_review", 0, 0, *info[r.id][:1], info[r.id][1])
        for r in rows
        if r.id in info
    }
    return rows, flags, waiting


def show(i: int, total: int, q, out=print, reasons=None) -> None:
    pages = (
        f"{q.page_start}"
        if q.page_end in (None, q.page_start)
        else f"{q.page_start}-{q.page_end}"
    )
    out(
        f"\n[{i}/{total}]  {q.unit_or_chapter}  |  printed page {pages}  |  {q.difficulty}"
    )
    for r in reasons or []:
        out(f"   !! {r}")
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
    if q.times_answered:
        out(
            f"Students: answered {q.times_answered} times, {round(100 * q.times_correct / q.times_answered)}% correct"
        )


def apply_key_fix(db, q, new_index: int) -> int:
    """Set the correct option and re-score every earlier student answer against it (so their
    accuracy and weak-unit lists stop being wrong). Returns how many answers were re-scored."""
    from db.models_practice import QuizAttempt

    attempts = db.query(QuizAttempt).filter(QuizAttempt.question_id == q.id).all()
    for a in attempts:
        a.is_correct = a.chosen_index == new_index
    q.answer_index = new_index
    q.times_answered = len(attempts)
    q.times_correct = sum(1 for a in attempts if a.is_correct)
    return len(attempts)


def review_loop(db, questions, ask=input, out=print, flags=None) -> dict:
    """Interactive review; returns counts. `ask` and `out` can be replaced in tests."""
    flags = flags or {}
    counts = {"approved": 0, "rejected": 0, "fixed": 0, "skipped": 0}
    total = len(questions)
    for i, q in enumerate(questions, start=1):
        show(i, total, q, out, flags.get(q.id))
        while True:
            choice = (
                ask("(a)pprove  (r)eject  (k)ey is wrong  (s)kip  (q)uit > ")
                .strip()
                .lower()
            )
            if choice == "a":
                q.status = "active"
                q.times_answered = q.times_correct = (
                    0  # a human checked it: statistics start again
                )
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
                n = apply_key_fix(db, q, LETTERS.index(letter))
                q.status = "active"
                counts["fixed"] += 1
                if n:
                    out(
                        f"   (re-scored {n} earlier student answer(s) against the corrected key)"
                    )
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
    ap.add_argument(
        "--flagged", action="store_true", help="only reported or low-accuracy questions"
    )
    ap.add_argument("--min-answers", type=int, default=None)
    ap.add_argument("--max-accuracy", type=float, default=None)
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
    rows, flags, waiting = select_questions(
        db,
        args.grade,
        subject,
        args.unit,
        args.flagged,
        args.limit,
        args.min_answers,
        args.max_accuracy,
    )
    what = "flagged" if args.flagged else "waiting for review"
    print(f"{waiting} question(s) {what}; showing {len(rows)}.")
    if not rows:
        return
    counts = review_loop(db, rows, flags=flags)
    print(
        f"\nDone: {counts['approved']} approved, {counts['fixed']} fixed and approved, "
        f"{counts['rejected']} rejected, {counts['skipped']} skipped."
    )
    db.close()


if __name__ == "__main__":
    main()
