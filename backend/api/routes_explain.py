from agents.workflow import AgentWorkflow
from config import constants
from db.models import Textbook
from db.session import SessionLocal
from fastapi import APIRouter, HTTPException
from llm.client import LLMClient
from llm.retry import LLMUnavailableError
from pydantic import BaseModel, Field
from retriever.builder import RetrieverBuilder
from retriever.decompose import DecomposingRetriever
from utils.subjects import resolve_subject

router = APIRouter(prefix="/v1", tags=["explain"])

# Built once at import time — RetrieverBuilder and AgentWorkflow hold
# model/client connections that are expensive to recreate per request.
_retriever_builder = RetrieverBuilder()
_workflow = AgentWorkflow()
# Splits broad questions ("what are the trends in...") into separate searches.
_planner_llm = LLMClient(temperature=0, max_tokens=600)


def _available_subjects(grade: int) -> list[str]:
    db = SessionLocal()
    try:
        return sorted(
            {s for (s,) in db.query(Textbook.subject).filter(Textbook.grade == grade)}
        )
    finally:
        db.close()


class ExplainRequest(BaseModel):
    grade: int = Field(..., ge=9, le=12)
    subject: str = Field(..., min_length=1)
    question: str = Field(..., min_length=3)


class Citation(BaseModel):
    textbook: str
    unit: str
    page: str | None = None


class ExplainResponse(BaseModel):
    answer: str
    citations: list[Citation]
    credits_charged: int = 0


@router.post("/explain", response_model=ExplainResponse)
def explain(request: ExplainRequest) -> ExplainResponse:
    if request.grade not in constants.SUPPORTED_GRADES:
        raise HTTPException(
            status_code=400, detail=f"Unsupported grade: {request.grade}"
        )

    available = _available_subjects(request.grade)
    subject, suggestion = resolve_subject(request.subject, available)
    if subject is None:
        hint = f" Did you mean '{suggestion}'?" if suggestion else ""
        raise HTTPException(
            status_code=400,
            detail=(
                f"No textbook for subject '{request.subject}' in grade {request.grade}."
                f"{hint} Available: {', '.join(available) or 'none yet'}."
            ),
        )

    retriever = _retriever_builder.build_textbook_retriever(
        grade=request.grade, subject=subject
    )
    retriever = DecomposingRetriever(
        retriever, _planner_llm
    )  # broad questions -> several searches
    try:
        result = _workflow.full_pipeline(question=request.question, retriever=retriever)
    except LLMUnavailableError as e:
        # Not a "no match": the AI service was busy or unreachable. No credits charged.
        raise HTTPException(
            status_code=503,
            detail="The AI service is busy or unreachable right now. Please try again in a minute.",
        ) from e

    if not result.get("draft_answer"):
        raise HTTPException(
            status_code=422, detail="Could not generate an answer for this question."
        )

    return ExplainResponse(
        answer=result["draft_answer"],
        citations=[Citation(**c) for c in result.get("citations", [])],
        credits_charged=0,  # explain mode is free in the initial pricing model
    )
