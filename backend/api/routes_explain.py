from agents.workflow import AgentWorkflow
from config import constants
from db.models import Textbook
from db.session import SessionLocal
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from llm.client import LLMClient
from llm.retry import LLMUnavailableError
from pydantic import BaseModel, Field
from retriever.builder import RetrieverBuilder
from retriever.decompose import DecomposingRetriever
from utils.sse import format_sse_event
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


def _explain_events(question: str, retriever):
    """Generator of SSE-formatted strings for the /explain stream below. Validation
    (grade/subject) already happened in explain() before this starts, since those are
    plain HTTP 400s - once streaming starts, the response is already HTTP 200, so any
    error from here on (LLM unavailable, no answer) has to travel as a final
    {"done": true, "error": ...} event instead of an HTTP error status."""
    try:
        for item in _workflow.stream_full_pipeline(question=question, retriever=retriever):
            if isinstance(item, str):
                yield format_sse_event({"stage": item})
                continue
            result = item
            if not result.get("draft_answer"):
                yield format_sse_event({"done": True, "error": "Could not generate an answer for this question."})
                return
            yield format_sse_event({
                "done": True,
                "answer": result["draft_answer"],
                "citations": [Citation(**c).model_dump() for c in result.get("citations", [])],
                "credits_charged": 0,
            })
    except LLMUnavailableError:
        yield format_sse_event({
            "done": True,
            "error": "The AI service is busy or unreachable right now. Please try again in a minute.",
        })


@router.post("/explain")
def explain(request: ExplainRequest) -> StreamingResponse:
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
    return StreamingResponse(
        _explain_events(request.question, retriever), media_type="text/event-stream"
    )
