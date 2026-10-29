

import uuid
from typing import Literal

from auth.dependencies import get_current_user
from db.models import Textbook, User
from db.models_practice import QuizAttempt, QuizQuestion, QuizReport
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException
from practice.progress import attempt_rows, attempt_timestamps
from practice.selection import daily_trend, pick_questions, unit_progress
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from utils.subjects import resolve_subject
from utils.units import unit_sort_key

router = APIRouter(prefix="/v1/practice", tags=["practice"])

CANDIDATE_POOL = 2000  # questions considered per request
# Credits: practice is served from the bank (no model call), so it is free for now.
# To meter it later:  from payments.entitlement import require_credits
#                     require_credits(db, user.id, COST)   # in /next
CREDIT_COST_PER_REQUEST = 0


# ---- request / response models ------------------------------------------
class NextRequest(BaseModel):
    grade: int = Field(..., ge=9, le=12)
    subject: str = Field(..., min_length=1)
    unit: str | None = None  # substring match, e.g. "Unit 4"
    units: list[str] | None = Field(
        None, max_length=12
    )  # exact unit names (e.g. a student's weak units)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    count: int = Field(5, ge=1, le=20)


class PracticeQuestion(BaseModel):
    id: uuid.UUID
    question: str
    options: list[str]
    unit: str | None
    difficulty: str


class NextResponse(BaseModel):
    questions: list[PracticeQuestion]


class AnswerRequest(BaseModel):
    question_id: uuid.UUID
    chosen_index: int = Field(..., ge=0, le=3)


class AnswerCitation(BaseModel):
    textbook: str
    unit: str | None
    page: str | None


class AnswerResponse(BaseModel):
    is_correct: bool
    correct_index: int
    explanation: str
    supporting_quote: str
    citation: AnswerCitation


class MistakeItem(BaseModel):
    question_id: uuid.UUID
    question: str
    options: list[str]
    chosen_index: int
    correct_index: int
    explanation: str
    unit: str | None


# ---- helpers --------------------------------------------------------------
def _format_page(start: int | None, end: int | None) -> str | None:
    if start is None:
        return None
    return str(start) if end is None or end == start else f"{start}-{end}"


def _resolve_subject_or_400(db: Session, grade: int, raw: str) -> str:
    available = sorted(
        {
            s
            for (s,) in db.query(QuizQuestion.subject)
            .filter(QuizQuestion.grade == grade, QuizQuestion.status == "active")
            .distinct()
        }
    )
    subject, suggestion = resolve_subject(raw, available)
    if subject is None:
        hint = f" Did you mean '{suggestion}'?" if suggestion else ""
        raise HTTPException(
            status_code=400,
            detail=(
                f"No practice questions for subject '{raw}' in grade {grade}.{hint} "
                f"Available: {', '.join(available) or 'none yet'}."
            ),
        )
    return subject


class ReportRequest(BaseModel):
    question_id: uuid.UUID
    reason: str | None = Field(None, max_length=300)


# ---- routes -----------------------------------------------------------------
@router.get("/subjects")
def subjects(
    grade: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """Subjects that have approved practice questions for this grade."""
    rows = (
        db.query(QuizQuestion.subject, func.count(QuizQuestion.id))
        .filter(QuizQuestion.grade == grade, QuizQuestion.status == "active")
        .group_by(QuizQuestion.subject)
        .order_by(QuizQuestion.subject)
        .all()
    )
    return {
        "grade": grade,
        "subjects": [{"subject": s, "questions": int(n)} for s, n in rows],
    }


@router.post("/report")
def report(
    request: ReportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """A student says this question is wrong or confusing. It is hidden at once
    (status 'needs_review') and stays hidden until it is re-approved with
    scripts/review_questions.py."""
    question = db.get(QuizQuestion, request.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found.")
    db.add(QuizReport(question_id=question.id, user_id=user.id, reason=request.reason))
    if question.status == "active":
        question.status = "needs_review"
    db.commit()
    return {"ok": True}


@router.get("/units")
def units(
    grade: int,
    subject: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    subject = _resolve_subject_or_400(db, grade, subject)
    counts = (
        db.query(QuizQuestion.unit_or_chapter, func.count(QuizQuestion.id))
        .filter(
            QuizQuestion.grade == grade,
            QuizQuestion.subject == subject,
            QuizQuestion.status == "active",
        )
        .group_by(QuizQuestion.unit_or_chapter)
        .all()
    )
    mine = {
        r["unit"]: r for r in unit_progress(attempt_rows(db, user.id, grade, subject))
    }
    out = []
    for unit, n in counts:
        name = unit or "(no unit)"
        p = mine.get(name)
        out.append(
            {
                "unit": name,
                "questions": int(n),
                "attempts": p["attempts"] if p else 0,
                "accuracy": p["accuracy"] if p else None,
                "level": p["level"] if p else "not enough data",
            }
        )
    out.sort(key=lambda r: unit_sort_key(r["unit"]))
    return {"grade": grade, "subject": subject, "units": out}


@router.post("/next", response_model=NextResponse)
def next_questions(
    request: NextRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NextResponse:
    subject = _resolve_subject_or_400(db, request.grade, request.subject)
    q = db.query(QuizQuestion).filter(
        QuizQuestion.grade == request.grade,
        QuizQuestion.subject == subject,
        QuizQuestion.status == "active",
    )
    if request.units:
        q = q.filter(QuizQuestion.unit_or_chapter.in_(request.units))
    elif request.unit:
        q = q.filter(QuizQuestion.unit_or_chapter.ilike(f"%{request.unit}%"))
    if request.difficulty:
        q = q.filter(QuizQuestion.difficulty == request.difficulty)
    rows = q.limit(CANDIDATE_POOL).all()
    if not rows:
        return NextResponse(questions=[])

    ids = [r.id for r in rows]
    last = {}
    for qid, ok, ts in (
        db.query(
            QuizAttempt.question_id, QuizAttempt.is_correct, QuizAttempt.created_at
        )
        .filter(QuizAttempt.user_id == user.id, QuizAttempt.question_id.in_(ids))
        .order_by(QuizAttempt.created_at)
    ):
        last[qid] = (ok, ts)  # ordered by time, so the latest attempt wins

    by_id = {r.id: r for r in rows}
    picked = pick_questions([{"id": r.id} for r in rows], last, request.count)
    return NextResponse(
        questions=[
            PracticeQuestion(
                id=c["id"],
                question=by_id[c["id"]].question,
                options=list(by_id[c["id"]].options),
                unit=by_id[c["id"]].unit_or_chapter,
                difficulty=by_id[c["id"]].difficulty,
            )
            for c in picked
        ]
    )


@router.post("/answer", response_model=AnswerResponse)
def answer(
    request: AnswerRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnswerResponse:
    question = db.get(QuizQuestion, request.question_id)
    if question is None or question.status != "active":
        raise HTTPException(status_code=404, detail="Question not found.")

    is_correct = request.chosen_index == question.answer_index
    db.add(
        QuizAttempt(
            user_id=user.id,
            question_id=question.id,
            chosen_index=request.chosen_index,
            is_correct=is_correct,
        )
    )
    db.query(QuizQuestion).filter(QuizQuestion.id == question.id).update(
        {
            QuizQuestion.times_answered: QuizQuestion.times_answered + 1,
            QuizQuestion.times_correct: QuizQuestion.times_correct
            + (1 if is_correct else 0),
        }
    )
    db.commit()

    book = db.get(Textbook, question.textbook_id)
    return AnswerResponse(
        is_correct=is_correct,
        correct_index=question.answer_index,
        explanation=question.explanation,
        supporting_quote=question.supporting_quote,
        citation=AnswerCitation(
            textbook=book.title if book else "Unknown",
            unit=question.unit_or_chapter,
            page=_format_page(question.page_start, question.page_end),
        ),
    )


@router.get("/mistakes", response_model=list[MistakeItem])
def mistakes(
    grade: int,
    subject: str,
    count: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[MistakeItem]:
    """This student's most recently wrong answers (latest attempt per question only - a question they
    got wrong then later got right no longer counts as a live mistake), newest first."""
    subject = _resolve_subject_or_400(db, grade, subject)
    rows = (
        db.query(
            QuizAttempt.question_id, QuizAttempt.is_correct, QuizAttempt.chosen_index, QuizAttempt.created_at
        )
        .join(QuizQuestion, QuizAttempt.question_id == QuizQuestion.id)
        .filter(QuizAttempt.user_id == user.id, QuizQuestion.grade == grade, QuizQuestion.subject == subject)
        .order_by(QuizAttempt.created_at)
        .all()
    )
    latest: dict[uuid.UUID, tuple[bool, int, object]] = {}
    for qid, ok, idx, ts in rows:
        latest[qid] = (ok, idx, ts)  # ordered by time, so the latest attempt wins
    wrong_ids = sorted(
        (qid for qid, (ok, _idx, _ts) in latest.items() if not ok),
        key=lambda qid: latest[qid][2],
        reverse=True,
    )[: min(count, 50)]
    if not wrong_ids:
        return []
    questions = {q.id: q for q in db.query(QuizQuestion).filter(QuizQuestion.id.in_(wrong_ids)).all()}
    return [
        MistakeItem(
            question_id=qid,
            question=questions[qid].question,
            options=list(questions[qid].options),
            chosen_index=latest[qid][1],
            correct_index=questions[qid].answer_index,
            explanation=questions[qid].explanation,
            unit=questions[qid].unit_or_chapter,
        )
        for qid in wrong_ids
        if qid in questions
    ]


@router.get("/progress")
def progress(
    grade: int,
    subject: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    subject = _resolve_subject_or_400(db, grade, subject)
    rows = attempt_rows(db, user.id, grade, subject)
    units_summary = unit_progress(rows)
    attempts = sum(r[1] for r in rows)
    correct = sum(r[2] for r in rows)
    return {
        "grade": grade,
        "subject": subject,
        "attempts": attempts,
        "accuracy": round(correct / attempts, 2) if attempts else None,
        "weakest_units": [u["unit"] for u in units_summary if u["level"] == "weak"][:3],
        "units": units_summary,
        "trend": daily_trend(attempt_timestamps(db, user.id, grade, subject)),
    }
