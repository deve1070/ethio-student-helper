MIN_ANSWERS = 10
MAX_ACCURACY = 0.25


def flag_reasons(
    status: str,
    answered: int,
    correct: int,
    reports: int = 0,
    report_reasons=(),
    min_answers: int = MIN_ANSWERS,
    max_accuracy: float = MAX_ACCURACY,
) -> list[str]:
    reasons = []
    if status == "needs_review" and reports:
        why = [r for r in report_reasons if r]
        reasons.append(
            f"reported by {reports} student(s)"
            + (f": {'; '.join(why[:3])}" if why else "")
        )
    if (
        status == "active"
        and answered >= min_answers
        and correct / answered < max_accuracy
    ):
        reasons.append(
            f"only {round(100 * correct / answered)}% correct after {answered} answers (the answer key may be wrong)"
        )
    return reasons


def summarize(rows) -> dict:
    """rows: [(subject, status, times_answered, times_correct)] -> per-subject counts and accuracy."""
    out: dict = {}
    for subject, status, answered, correct in rows:
        s = out.setdefault(
            subject,
            {"active": 0, "needs_review": 0, "retired": 0, "answered": 0, "correct": 0},
        )
        s[status] = s.get(status, 0) + 1
        s["answered"] += answered or 0
        s["correct"] += correct or 0
    for s in out.values():
        s["accuracy"] = (
            round(s["correct"] / s["answered"], 2) if s["answered"] else None
        )
    return out


def report_info(db, question_ids) -> dict:
    """{question_id: (number of reports, [reasons])}"""
    from db.models_practice import QuizReport

    info: dict = {}
    if not question_ids:
        return info
    for qid, reason in db.query(QuizReport.question_id, QuizReport.reason).filter(
        QuizReport.question_id.in_(list(question_ids))
    ):
        count, reasons = info.get(qid, (0, []))
        info[qid] = (count + 1, reasons + ([reason] if reason else []))
    return info


def find_flagged(
    db,
    grade=None,
    subject=None,
    unit=None,
    min_answers: int = MIN_ANSWERS,
    max_accuracy: float = MAX_ACCURACY,
):
    """[(question, [reasons])], most urgent first: reported questions, then the lowest accuracy."""
    from db.models_practice import QuizQuestion
    from sqlalchemy import and_, or_

    q = db.query(QuizQuestion).filter(
        or_(
            QuizQuestion.status == "needs_review",
            and_(
                QuizQuestion.status == "active",
                QuizQuestion.times_answered >= min_answers,
            ),
        )
    )
    if grade is not None:
        q = q.filter(QuizQuestion.grade == grade)
    if subject:
        q = q.filter(QuizQuestion.subject == subject)
    if unit:
        q = q.filter(QuizQuestion.unit_or_chapter.ilike(f"%{unit}%"))
    candidates = q.all()
    reports = report_info(db, [c.id for c in candidates])
    flagged = []
    for c in candidates:
        n, why = reports.get(c.id, (0, []))
        reasons = flag_reasons(
            c.status,
            c.times_answered or 0,
            c.times_correct or 0,
            n,
            why,
            min_answers,
            max_accuracy,
        )
        if reasons:
            flagged.append((c, reasons))
    flagged.sort(
        key=lambda t: (
            t[0].status != "needs_review",
            (t[0].times_correct or 0) / max(t[0].times_answered or 1, 1),
            t[0].unit_or_chapter or "",
            t[0].page_start or 0,
        )
    )
    return flagged
