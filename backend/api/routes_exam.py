import uuid

from agents.workflow import AgentWorkflow
from auth.dependencies import get_current_user
from db.models import CreditLedgerEntry, ExamQuestionSubmission, Textbook, User
from db.session import get_db
from exams.cache import ExamCache
from exams.ocr import extract_text_from_base64_image
from fastapi import APIRouter, Depends, HTTPException
from llm.client import LLMClient
from llm.retry import LLMUnavailableError
from payments.entitlement import require_credits
from pydantic import BaseModel, Field, model_validator
from retriever.builder import RetrieverBuilder
from retriever.decompose import DecomposingRetriever
from sqlalchemy.orm import Session
from utils.logging import logger
from utils.subjects import resolve_subject

router = APIRouter(prefix="/v1/exam", tags=["exam"])

_retriever_builder = RetrieverBuilder()
_workflow = AgentWorkflow()
_cache = ExamCache()
# Splits broad questions ("what are the trends in...") into separate searches.
_planner_llm = LLMClient(temperature=0, max_tokens=800)


CREDIT_COST_CACHE_HIT = 0
CREDIT_COST_FRESH_ANSWER = 1


class ExamSolveRequest(BaseModel):
    grade: int = Field(12, ge=12, le=12)
    subject: str = Field(..., min_length=1)
    exam_year: int | None = None
    question_text: str | None = None
    image_base64: str | None = None

    @model_validator(mode="after")
    def _one_input_required(self):
        if not self.question_text and not self.image_base64:
            raise ValueError("Provide either question_text or image_base64.")
        return self


class Citation(BaseModel):
    textbook: str
    unit: str
    page: str | None = None


class ExamSolveResponse(BaseModel):
    exam_question_id: (
        uuid.UUID | None
    )  # None when the answer was not stored (no_match / unverified)
    answer: str
    citations: list[Citation]

    source: str
    credits_charged: int


@router.post("/solve", response_model=ExamSolveResponse)
def solve(
    request: ExamSolveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExamSolveResponse:
    available = sorted(
        {
            s
            for (s,) in db.query(Textbook.subject)
            .filter(Textbook.grade == request.grade)
            .distinct()
        }
    )
    subject, suggestion = resolve_subject(request.subject, available)
    if subject is None:
        hint = f" Did you mean '{suggestion}'?" if suggestion else ""
        raise HTTPException(
            status_code=400,
            detail=(
                f"No textbook for subject '{request.subject}' in grade {request.grade}.{hint} "
                f"Available: {', '.join(available) or 'none yet'}."
            ),
        )

    question_text = request.question_text or extract_text_from_base64_image(
        request.image_base64
    )

    submission = ExamQuestionSubmission(
        submitted_by=user.id,
        grade=request.grade,
        subject=subject,
        exam_year=request.exam_year,
        raw_text=question_text,
    )
    db.add(submission)
    db.flush()

    cached = _cache.find_cached_answer(db, question_text, request.grade, subject)
    if cached is not None:
        question, answer = cached
        _cache.bump_times_asked(db, question)
        submission.matched_question_id = question.id
        db.commit()
        _charge_credits(
            db, user.id, CREDIT_COST_CACHE_HIT, question.id, "exam_solve_cached"
        )

        return ExamSolveResponse(
            exam_question_id=question.id,
            answer=answer.answer_text,
            citations=[
                Citation(**c)
                for c in _workflow.citation_agent.resolve_chunk_ids(
                    answer.citation_chunk_ids or []
                )
            ],
            source="cache",
            credits_charged=CREDIT_COST_CACHE_HIT,
        )

    logger.info(
        f"Cache miss for exam question in grade={request.grade}, subject={subject}; generating"
    )

    require_credits(db, user.id, CREDIT_COST_FRESH_ANSWER)

    retriever = _retriever_builder.build_textbook_retriever(
        grade=request.grade, subject=subject
    )
    retriever = DecomposingRetriever(
        retriever, _planner_llm
    )  # broad questions -> several searches
    try:
        result = _workflow.full_pipeline(question=question_text, retriever=retriever)
    except LLMUnavailableError as e:
        # The AI service was busy or unreachable: nothing is cached, nothing is charged.
        raise HTTPException(
            status_code=503,
            detail="The AI service is busy or unreachable right now. Please try again in a minute.",
        ) from e
    if not result.get("draft_answer"):
        raise HTTPException(
            status_code=422, detail="Could not generate an answer for this question."
        )

    if result.get("is_relevant") is False:
        # The textbooks have nothing on this. The "not related" reply must not become the
        # cached canonical answer for this question, and the student must not pay for it.
        db.commit()  # keep the submission row: it shows which topics students ask about that we lack
        return ExamSolveResponse(
            exam_question_id=None,
            answer=result["draft_answer"],
            citations=[],
            source="no_match",
            credits_charged=0,
        )

    if result.get("verification_status") == "ERROR":
        # The checker could not run (rate limit / network). An unchecked answer is not cached
        # as the canonical one, and the student is not charged for it.
        db.commit()
        return ExamSolveResponse(
            exam_question_id=None,
            answer=result["draft_answer"],
            citations=[Citation(**c) for c in result.get("citations", [])],
            source="unverified",
            credits_charged=0,
        )

    citations = result.get("citations", [])
    chunk_ids = [uuid.UUID(c["chunk_id"]) for c in citations if c.get("chunk_id")]

    question, answer = _cache.store_new_answer(
        db,
        question_text=question_text,
        grade=request.grade,
        subject=subject,
        exam_year=request.exam_year,
        answer_text=result["draft_answer"],
        citation_chunk_ids=chunk_ids,
    )
    submission.matched_question_id = question.id
    db.commit()
    _charge_credits(
        db, user.id, CREDIT_COST_FRESH_ANSWER, question.id, "exam_solve_new"
    )

    return ExamSolveResponse(
        exam_question_id=question.id,
        answer=answer.answer_text,
        citations=[Citation(**c) for c in citations],
        source="generated",
        credits_charged=CREDIT_COST_FRESH_ANSWER,
    )


def _charge_credits(
    db: Session, user_id: uuid.UUID, cost: int, exam_question_id: uuid.UUID, reason: str
) -> None:
    if cost <= 0:
        return
    db.add(
        CreditLedgerEntry(
            user_id=user_id,
            delta=-cost,
            reason=reason,
            related_exam_question_id=exam_question_id,
        )
    )
    db.commit()
