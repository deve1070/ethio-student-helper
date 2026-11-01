"""Student-facing serving endpoint for the ESSLCE (Grade-12 national exam) past-paper bank.

Stateless and mode-agnostic by design: /answer always grades immediately and returns the full result.
"Practice, one question at a time" vs "whole exam, see results at the end" is a client-side UX choice
(the Telegram bot decides when to SHOW a result it already has) - not something this router branches on,
except to record which mode an attempt was made in (`EsslceAttempt.mode`, informational only).

eligible() (backend/exams/store.py) is the ONLY gate for what a student can ever be served - reused here,
never reimplemented, so there is exactly one definition of "safe to show a student."
"""

import base64

from auth.dependencies import get_current_user
from config import constants
from config.constants import CALCULATION_SUBJECTS
from db.models import User
from db.session import get_db
from exams.latex_render import render_latex_png
from exams.models import EsslceAttempt, EsslcePaper, EsslcePassage, EsslceQuestion
from exams.store import (
    MIN_ATTEMPTS_FOR_SIGNAL,
    ask_about_question,
    best_unit,
    diagnostic_questions,
    eligible,
    eligible_filter,
    eligible_skill_strands,
    eligible_units,
    get_or_create_elaboration,
    question_page_image,
    recommend_focus,
    skill_strand,
    student_progress,
)
from fastapi import APIRouter, Depends, HTTPException
from llm.client import LLMClient
from practice.selection import classify_level, daily_trend, pick_questions
from pydantic import BaseModel, Field
from retriever.builder import RetrieverBuilder
from retriever import vectorstore
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Literal

router = APIRouter(prefix="/v1/esslce", tags=["esslce"])

# The embeddings model (HuggingFace, loaded once - the expensive part) is cached for the process, matching
# retriever/builder.py's own RetrieverBuilder. Built fresh per request, matching
# retriever/builder.py's build_textbook_retriever - cheap (a pgvector connection, not an embeddings load).
_embeddings = RetrieverBuilder().embeddings


def _fresh_textbook_store():
    return vectorstore.get_vector_store(
        collection_name=constants.TEXTBOOK_COLLECTION_NAME,
        embedding_function=_embeddings,
    )


# ---- request / response models ------------------------------------------
class EsslceQuestionOut(BaseModel):
    id: int
    item_no: int
    year_ec: int  # which exam this question is from, alongside item_no - needed once
    # questions from several years are pooled together (e.g. "practice by unit")
    booklet_code: str | None = None  # which printed/shuffled copy, when the source paper has one
    stem: str
    options: list[str]
    passage_text: str | None = None
    passage_title: str | None = None  # the exam's own title for the passage ("Passage I", ...); often unset
    unit: str | None = None
    skill: str | None = None  # the skill-strand axis (English/SAT); unit and skill are never both set
    diagram_image_base64: str | None = None  # the real source page photo, only set for a has_diagram item


class NextRequest(BaseModel):
    subject: str = Field(..., min_length=1)
    paper_id: int | None = None  # set -> "whole exam" mode: every eligible question of this paper, in order
    stream: str | None = None
    unit: str | None = None  # pool across every year's questions linked to this one textbook unit
    grade: int | None = None  # disambiguates a unit name that recurs across grades; ignored if unit is unset
    skill: str | None = None  # pool across every year's questions in this one skill strand (English, SAT)
    incorrect_only: bool = False  # pool across every year's questions this student's LATEST attempt got wrong
    count: int = Field(5, ge=1, le=50)  # ignored when paper_id is set


class NextResponse(BaseModel):
    paper_id: int | None
    questions: list[EsslceQuestionOut]


class AnswerRequest(BaseModel):
    question_id: int
    chosen_index: int = Field(..., ge=0, le=3)
    mode: Literal["practice", "exam", "diagnostic"] = "practice"


class AnswerResponse(BaseModel):
    is_correct: bool
    correct_index: int
    explanation: str | None
    supporting_quote: str | None
    explanation_image_base64: str | None = None  # set only for a calculation-subject explanation that rendered


class ElaborateRequest(BaseModel):
    question_id: int


class Citation(BaseModel):
    textbook: str
    grade: int
    subject: str
    unit_or_chapter: str | None = None
    section: str | None = None
    page_start: int | None = None
    page_end: int | None = None


class ElaborateResponse(BaseModel):
    content: str
    is_calculation: bool
    content_image_base64: str | None = None
    citation: Citation | None = None  # None for a calculation subject, or a reading-comprehension question


class UnitProgress(BaseModel):
    grade: int
    unit: str
    attempted: int
    correct: int
    accuracy: float
    level: str


class SkillProgress(BaseModel):
    skill: str
    attempted: int
    correct: int
    accuracy: float
    level: str


class Recommendation(BaseModel):
    kind: Literal["unit", "skill"]
    grade: int | None
    unit: str | None
    skill: str | None
    attempted: int
    correct: int
    accuracy: float


class TrendPoint(BaseModel):
    date: str
    attempts: int
    accuracy: float | None


class ProgressResponse(BaseModel):
    subject: str
    attempted: int
    correct: int
    units: list[UnitProgress]
    skills: list[SkillProgress]
    recommendation: Recommendation | None
    trend: list[TrendPoint]


class MistakeItem(BaseModel):
    question_id: int
    item_no: int
    year_ec: int
    booklet_code: str | None = None
    stem: str
    options: list[str]
    passage_text: str | None = None  # a Reading Comprehension item's passage - must always precede the stem
    passage_title: str | None = None
    chosen_index: int
    correct_index: int
    explanation: str | None
    explanation_image_base64: str | None = None  # set only for a calculation-subject explanation that rendered
    unit: str | None
    skill: str | None


@router.get("/mistakes", response_model=list[MistakeItem])
def mistakes(
    subject: str, count: int = 20, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[MistakeItem]:
    """This student's most recently wrong answers in this subject (latest attempt per question only),
    newest first. Only questions still eligible() are shown - the same gate /next and /answer use, so a
    question withdrawn since being attempted never resurfaces here."""
    is_calculation = subject in CALCULATION_SUBJECTS
    paper_ids = [p.id for p in db.query(EsslcePaper.id).filter(EsslcePaper.subject == subject).all()]
    if not paper_ids:
        return []
    rows = (
        db.query(
            EsslceAttempt.question_id, EsslceAttempt.is_correct, EsslceAttempt.chosen_index,
            EsslceAttempt.created_at,
        )
        .filter(EsslceAttempt.user_id == user.id, EsslceAttempt.paper_id.in_(paper_ids))
        .order_by(EsslceAttempt.created_at)
        .all()
    )
    latest: dict[int, tuple[bool, int, object]] = {}
    for qid, ok, idx, ts in rows:
        latest[qid] = (ok, idx, ts)  # ordered by time, so the latest attempt wins
    wrong_ids = sorted(
        (qid for qid, (ok, _idx, _ts) in latest.items() if not ok),
        key=lambda qid: latest[qid][2],
        reverse=True,
    )
    if not wrong_ids:
        return []
    questions = {
        q.id: q for q in db.query(EsslceQuestion).filter(EsslceQuestion.id.in_(wrong_ids)).all()
    }
    passage_ids = {q.passage_id for q in questions.values() if q.passage_id}
    passages = {
        p.id: p
        for p in (db.query(EsslcePassage).filter(EsslcePassage.id.in_(passage_ids)).all() if passage_ids else [])
    }
    out = []
    for qid in wrong_ids:
        q = questions.get(qid)
        if q is None or not eligible(q):
            continue
        unit_info = best_unit(q)
        passage = passages.get(q.passage_id) if q.passage_id else None
        image_b64 = None
        if is_calculation and q.explanation:
            png = render_latex_png(q.explanation)
            if png:
                image_b64 = base64.b64encode(png).decode()
        out.append(
            MistakeItem(
                question_id=q.id,
                item_no=q.item_no,
                year_ec=q.paper.year_ec,
                booklet_code=q.paper.booklet_code,
                stem=q.stem,
                options=list(q.options or []),
                passage_text=passage.text if passage else None,
                passage_title=passage.title if passage else None,
                chosen_index=latest[qid][1],
                correct_index=q.answer_index,
                explanation=q.explanation,
                explanation_image_base64=image_b64,
                unit=unit_info[1] if unit_info else None,
                skill=skill_strand(q) if unit_info is None else None,
            )
        )
        if len(out) >= min(count, 50):
            break
    return out


class ExamSummaryRequest(BaseModel):
    paper_id: int


class ExamSummaryItem(BaseModel):
    item_no: int
    question_id: int
    chosen_index: int
    is_correct: bool
    correct_index: int


class ExamSummaryResponse(BaseModel):
    paper_id: int
    attempted: int
    correct: int
    total_eligible: int
    results: list[ExamSummaryItem]


# ---- helpers --------------------------------------------------------------
def _build_outputs(db: Session, questions: list[EsslceQuestion]) -> list[EsslceQuestionOut]:
    passage_ids = {q.passage_id for q in questions if q.passage_id}
    passages = {}
    if passage_ids:
        passages = {
            p.id: p
            for p in db.query(EsslcePassage).filter(EsslcePassage.id.in_(passage_ids)).all()
        }
    out = []
    for q in questions:
        unit_info = best_unit(q)
        passage = passages.get(q.passage_id) if q.passage_id else None
        image_b64 = None
        if q.has_diagram:
            png = question_page_image(q)
            if png:
                image_b64 = base64.b64encode(png).decode()
        out.append(
            EsslceQuestionOut(
                id=q.id,
                item_no=q.item_no,
                year_ec=q.paper.year_ec,
                booklet_code=q.paper.booklet_code,
                stem=q.stem,
                options=list(q.options or []),
                passage_text=passage.text if passage else None,
                passage_title=passage.title if passage else None,
                unit=unit_info[1] if unit_info else None,
                skill=skill_strand(q) if unit_info is None else None,
                diagram_image_base64=image_b64,
            )
        )
    return out


# ---- routes -----------------------------------------------------------------
@router.get("/subjects")
def subjects(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """ESSLCE subjects with at least one eligible (approved, keyed, no-diagram) question.

    Counts via a SQL aggregate (JOIN + GROUP BY), not by loading every paper's every question as
    a Python ORM object and checking eligible() on each one in a loop - confirmed live in
    production that doing it that way, across the whole bank (65 papers, 5,050+ questions),
    materialized enough objects to OOM-kill the single worker process. eligible_filter()
    (exams/store.py) is the exact same eligibility rule as eligible(), expressed as a filter
    instead of a per-object check, so this still has exactly one definition of "eligible" - it's
    just evaluated by the database instead of by Python."""
    rows = (
        db.query(EsslcePaper.subject, func.count(EsslceQuestion.id))
        .join(EsslceQuestion, EsslceQuestion.paper_id == EsslcePaper.id)
        .filter(eligible_filter())
        .group_by(EsslcePaper.subject)
        .all()
    )
    return {"subjects": [{"subject": s, "questions": n} for s, n in sorted(rows)]}


@router.get("/papers")
def papers(
    subject: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """Papers of this subject ready for a 'whole exam' attempt (>=1 eligible question) - same SQL-
    aggregate approach as /subjects above, for the same reason (avoids materializing every
    question of every paper in this subject just to count them)."""
    rows_q = (
        db.query(
            EsslcePaper.id,
            EsslcePaper.subject,
            EsslcePaper.stream,
            EsslcePaper.year_ec,
            EsslcePaper.round,
            EsslcePaper.region,
            EsslcePaper.delivery_mode,
            EsslcePaper.duration_minutes,
            func.count(EsslceQuestion.id).label("ready_for_students"),
        )
        .join(EsslceQuestion, EsslceQuestion.paper_id == EsslcePaper.id)
        .filter(EsslcePaper.subject == subject, eligible_filter())
        .group_by(EsslcePaper.id)
        .order_by(EsslcePaper.year_ec)
        .all()
    )
    rows = [
        {
            "id": r.id,
            "subject": r.subject,
            "stream": r.stream,
            "year_ec": r.year_ec,
            "round": r.round,
            "region": r.region,
            "delivery_mode": r.delivery_mode,
            "duration_minutes": r.duration_minutes,
            "ready_for_students": r.ready_for_students,
        }
        for r in rows_q
    ]
    if not rows:
        raise HTTPException(
            status_code=404, detail=f"No ESSLCE papers ready for students in '{subject}' yet."
        )
    return {"subject": subject, "papers": rows}


@router.get("/units")
def units(
    subject: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """Units with >=1 eligible question, for a 'practice by unit' picker (pools across every year)."""
    return {"subject": subject, "units": eligible_units(db, subject)}


@router.get("/skills")
def skills(
    subject: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """Skill strands (Grammar, Vocabulary, Reading Comprehension, ...) with >=1 eligible question, for
    subjects not organized by textbook topic (English, SAT) - empty for every other subject."""
    return {"subject": subject, "skills": eligible_skill_strands(db, subject)}


@router.get("/progress", response_model=ProgressResponse)
def progress(
    subject: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ProgressResponse:
    """Per-unit/per-skill accuracy from this student's OWN attempt history, plus the single weakest area
    with enough attempts to be a real signal (not a guess from one lucky or unlucky question)."""
    data = student_progress(db, user.id, subject)
    for row in data["units"] + data["skills"]:
        row["level"] = classify_level(row["accuracy"], row["attempted"], MIN_ATTEMPTS_FOR_SIGNAL)
    paper_ids = [p.id for p in db.query(EsslcePaper.id).filter(EsslcePaper.subject == subject).all()]
    rows = (
        db.query(EsslceAttempt.created_at, EsslceAttempt.is_correct)
        .filter(EsslceAttempt.user_id == user.id, EsslceAttempt.paper_id.in_(paper_ids))
        .all()
        if paper_ids
        else []
    )
    return ProgressResponse(
        subject=subject, recommendation=recommend_focus(data), trend=daily_trend(rows), **data
    )


class DiagnosticRequest(BaseModel):
    subject: str = Field(..., min_length=1)
    stream: str | None = None
    count: int = Field(15, ge=5, le=30)


@router.post("/diagnostic", response_model=NextResponse)
def diagnostic(
    request: DiagnosticRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> NextResponse:
    """A fixed, one-shot baseline set - deliberately spread across units/skills (diagnostic_questions),
    not the mastery-ordered mixed pool /next uses for ongoing practice. Graded the same stateless way as
    every other question (mode='diagnostic' on /answer); the bot defers results to the end, same as exam
    mode, but spans every year's paper rather than one specific one."""
    rows = diagnostic_questions(db, request.subject, request.count, request.stream)
    if not rows:
        raise HTTPException(
            status_code=404, detail=f"No {request.subject} questions are ready for a diagnostic yet."
        )
    return NextResponse(paper_id=None, questions=_build_outputs(db, rows))


@router.post("/next", response_model=NextResponse)
def next_questions(
    request: NextRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> NextResponse:
    if request.paper_id is not None:
        paper = db.get(EsslcePaper, request.paper_id)
        if paper is None or paper.subject != request.subject:
            raise HTTPException(status_code=404, detail="Paper not found for that subject.")
        rows = sorted((q for q in paper.questions if eligible(q)), key=lambda q: q.item_no)
        if not rows:
            raise HTTPException(
                status_code=404, detail="This paper has no questions ready for students yet."
            )
        return NextResponse(paper_id=paper.id, questions=_build_outputs(db, rows))

    papers_q = db.query(EsslcePaper).filter(EsslcePaper.subject == request.subject)
    if request.stream:
        papers_q = papers_q.filter(EsslcePaper.stream == request.stream)
    candidates: list[EsslceQuestion] = []
    for paper in papers_q.all():
        candidates.extend(q for q in paper.questions if eligible(q))
    if not candidates:
        return NextResponse(paper_id=None, questions=[])

    # computed once, before any filter below, so incorrect_only can use it alongside unit/skill
    ids = [q.id for q in candidates]
    last = {}
    for qid, ok, ts in (
        db.query(EsslceAttempt.question_id, EsslceAttempt.is_correct, EsslceAttempt.created_at)
        .filter(EsslceAttempt.user_id == user.id, EsslceAttempt.question_id.in_(ids))
        .order_by(EsslceAttempt.created_at)
    ):
        last[qid] = (ok, ts)  # ordered by time, so the latest attempt wins

    if request.unit is not None:
        candidates = [
            q
            for q in candidates
            if (bu := best_unit(q))
            and bu[1] == request.unit
            and (request.grade is None or bu[0] == request.grade)
        ]
    if request.skill is not None:
        candidates = [q for q in candidates if skill_strand(q) == request.skill]
    if request.incorrect_only:
        candidates = [q for q in candidates if q.id in last and not last[q.id][0]]
    if not candidates:
        return NextResponse(paper_id=None, questions=[])

    by_id = {q.id: q for q in candidates}
    picked = pick_questions([{"id": q.id} for q in candidates], last, request.count)
    return NextResponse(
        paper_id=None, questions=_build_outputs(db, [by_id[c["id"]] for c in picked])
    )


@router.post("/answer", response_model=AnswerResponse)
def answer(
    request: AnswerRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> AnswerResponse:
    question = db.get(EsslceQuestion, request.question_id)
    if question is None or not eligible(question):
        raise HTTPException(status_code=404, detail="Question not found or no longer available.")

    is_correct = request.chosen_index == question.answer_index
    db.add(
        EsslceAttempt(
            user_id=user.id,
            question_id=question.id,
            paper_id=question.paper_id,
            chosen_index=request.chosen_index,
            is_correct=is_correct,
            mode=request.mode,
        )
    )
    db.commit()

    image_b64 = None
    paper = db.get(EsslcePaper, question.paper_id)
    if paper.subject in CALCULATION_SUBJECTS and question.explanation:
        png = render_latex_png(question.explanation)
        if png:
            image_b64 = base64.b64encode(png).decode()

    return AnswerResponse(
        is_correct=is_correct,
        correct_index=question.answer_index,
        explanation=question.explanation,
        supporting_quote=question.supporting_quote,
        explanation_image_base64=image_b64,
    )


@router.post("/elaborate", response_model=ElaborateResponse)
def elaborate(
    request: ElaborateRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ElaborateResponse:
    """"I still don't get it, explain more" - cached per question (exams/store.get_or_create_elaboration),
    so only the first request for a given question ever makes a live LLM call."""
    question = db.get(EsslceQuestion, request.question_id)
    if question is None or not eligible(question):
        raise HTTPException(status_code=404, detail="Question not found or no longer available.")
    paper = db.get(EsslcePaper, question.paper_id)

    row = get_or_create_elaboration(
        db, LLMClient(temperature=0, max_tokens=1500), _fresh_textbook_store(), paper, question
    )
    if row is None:
        raise HTTPException(
            status_code=422,
            detail="Could not generate a grounded explanation for this question. Try again later.",
        )

    image_b64 = None
    if row.is_calculation:
        png = render_latex_png(row.content)
        if png:
            image_b64 = base64.b64encode(png).decode()

    return ElaborateResponse(
        content=row.content,
        is_calculation=row.is_calculation,
        content_image_base64=image_b64,
        citation=row.citation,
    )


class AskRequest(BaseModel):
    question_id: int
    message: str = Field(..., min_length=1, max_length=1000)
    history: list[dict] = Field(default_factory=list, max_length=20)  # [{"role": "user"|"assistant", "content": str}]


class AskResponse(BaseModel):
    reply: str
    reply_image_base64: str | None = None  # set only for a calculation-subject reply that rendered


@router.post("/ask", response_model=AskResponse)
def ask(
    request: AskRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> AskResponse:
    """Free-form follow-up chat about one specific question. Unlike /elaborate, this is NEVER cached - every
    call is a fresh LLM call, and grounding is prompt-level only (see ask_about_question), not independently
    quote-verified the way /answer and /elaborate's core claims are. Always ensures the same cached
    elaboration /elaborate would return exists first, so there is always at least that much real grounding
    context before the open-ended part of the conversation starts."""
    question = db.get(EsslceQuestion, request.question_id)
    if question is None or not eligible(question):
        raise HTTPException(status_code=404, detail="Question not found or no longer available.")
    paper = db.get(EsslcePaper, question.paper_id)

    llm = LLMClient(temperature=0, max_tokens=1500)
    elaboration = get_or_create_elaboration(db, llm, _fresh_textbook_store(), paper, question)
    history = [
        {"role": h["role"], "content": h["content"]}
        for h in request.history
        if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str)
    ]
    reply = ask_about_question(llm, question, elaboration, history, request.message)
    if not reply:
        raise HTTPException(status_code=422, detail="Could not generate a reply. Try again.")

    image_b64 = None
    if paper.subject in CALCULATION_SUBJECTS:
        png = render_latex_png(reply)
        if png:
            image_b64 = base64.b64encode(png).decode()

    return AskResponse(reply=reply, reply_image_base64=image_b64)


@router.post("/exam-summary", response_model=ExamSummaryResponse)
def exam_summary(
    request: ExamSummaryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExamSummaryResponse:
    """Reconstructed from EsslceAttempt alone, so a lost/restarted bot session doesn't lose the
    final score - the student's answers are already durably recorded by /answer as they go."""
    paper = db.get(EsslcePaper, request.paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    eligible_qs = {q.id: q for q in paper.questions if eligible(q)}
    if not eligible_qs:
        raise HTTPException(
            status_code=404, detail="This paper has no questions ready for students yet."
        )

    latest: dict[int, EsslceAttempt] = {}
    for a in (
        db.query(EsslceAttempt)
        .filter(EsslceAttempt.user_id == user.id, EsslceAttempt.paper_id == paper.id)
        .order_by(EsslceAttempt.created_at)
    ):
        latest[a.question_id] = a  # ordered by time, so the latest attempt wins

    results = []
    correct = 0
    for qid, q in sorted(eligible_qs.items(), key=lambda kv: kv[1].item_no):
        a = latest.get(qid)
        if a is None:
            continue
        correct += int(a.is_correct)
        results.append(
            ExamSummaryItem(
                item_no=q.item_no,
                question_id=qid,
                chosen_index=a.chosen_index,
                is_correct=a.is_correct,
                correct_index=q.answer_index,
            )
        )
    return ExamSummaryResponse(
        paper_id=paper.id,
        attempted=len(results),
        correct=correct,
        total_eligible=len(eligible_qs),
        results=results,
    )
