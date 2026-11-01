"""Student-facing Study Notes & Formula Sheets: GET subjects/units (from the real textbook corpus, not
from practice-question or ESSLCE content, since Study Notes exist independent of either), GET a note
(generated once per (grade, subject, unit), cached after - notes.store.get_or_create_note). The one
net-new content TYPE in this feature set, but reuses the same retrieval + LLM + LaTeX-rendering
infrastructure every other grounded feature already has."""

import base64
import queue
import threading

from auth.dependencies import get_current_user
from config import constants
from db.models import User
from db.session import get_db
from exams.latex_render import render_latex_png, wrap_as_math
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from llm.client import LLMClient
from notes.store import available_subjects, available_units, get_or_create_note
from pydantic import BaseModel
from retriever.builder import RetrieverBuilder
from retriever import vectorstore
from sqlalchemy.orm import Session
from utils.sse import format_sse_event

router = APIRouter(prefix="/v1/notes", tags=["notes"])

# Same "cache the expensive embeddings model, build a fresh short-lived store per request"
# pattern as api/routes_esslce.py.
_embeddings = RetrieverBuilder().embeddings


def _fresh_textbook_store():
    return vectorstore.get_vector_store(
        collection_name=constants.TEXTBOOK_COLLECTION_NAME,
        embedding_function=_embeddings,
    )


@router.get("/subjects")
def subjects(grade: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return {"grade": grade, "subjects": available_subjects(db, grade)}


@router.get("/units")
def units(
    grade: int, subject: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    return {"grade": grade, "subject": subject, "units": available_units(db, grade, subject)}


class NoteSection(BaseModel):
    number: str
    heading: str
    summary: str
    citation: dict | None


class NoteResponse(BaseModel):
    subject: str
    unit: str
    overview: str
    sections: list[NoteSection]
    key_formulas: list[str] | None
    formulas_image_base64: str | None = None
    worked_example: str | None
    worked_example_image_base64: str | None = None
    is_calculation: bool


def _note_events(grade: int, subject: str, unit: str, db: Session):
    """Generator of SSE-formatted strings for the /note stream below. get_or_create_note
    reports its progress through a plain callback (notes/store.py keeps that convention
    rather than becoming a generator itself, since test/test_notes.py and any other
    caller call it expecting a plain dict/StudyNote back) - so a background thread runs
    the blocking call while this generator drains a queue the callback feeds, turning a
    push-style callback into the pull-style stream StreamingResponse needs. The thread
    is joined before `db`/`row` are touched again from this (the main) thread, so the
    SQLAlchemy session is never used from both threads at once."""
    events: queue.Queue = queue.Queue()
    result: dict = {}

    def worker():
        try:
            result["row"] = get_or_create_note(
                db, LLMClient(temperature=0, max_tokens=2800), _fresh_textbook_store(),
                grade, subject, unit, on_stage=lambda label: events.put(label),
            )
        except Exception as e:  # noqa: BLE001 - surfaced as a done/error SSE event below
            result["error"] = e
        finally:
            events.put(None)  # sentinel: no more stages

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    while (label := events.get()) is not None:
        yield format_sse_event({"stage": label})
    thread.join()

    if "error" in result:
        yield format_sse_event({"done": True, "error": "Could not generate study notes right now. Please try again shortly."})
        return

    row = result["row"]
    if row is None:
        yield format_sse_event({"done": True, "error": "Could not generate grounded study notes for this topic yet."})
        return

    formulas_image = None
    if row.is_calculation and row.key_formulas:
        yield format_sse_event({"stage": "Formatting formulas..."})
        # each entry is a standalone formula fragment, often with no delimiter of its own at all (unlike
        # worked_example, where narration forces the model to mark where the math starts/ends) - wrap each
        # one explicitly rather than trusting it already has (or needs) one.
        png = render_latex_png("\n".join(wrap_as_math(f) for f in row.key_formulas))
        if png:
            formulas_image = base64.b64encode(png).decode()

    example_image = None
    if row.is_calculation and row.worked_example:
        png = render_latex_png(row.worked_example)
        if png:
            example_image = base64.b64encode(png).decode()

    yield format_sse_event({
        "done": True,
        **NoteResponse(
            subject=row.subject,
            unit=row.unit,
            overview=row.overview,
            sections=row.sections,
            key_formulas=row.key_formulas,
            formulas_image_base64=formulas_image,
            worked_example=row.worked_example,
            worked_example_image_base64=example_image,
            is_calculation=row.is_calculation,
        ).model_dump(),
    })


@router.get("/note")
def note(
    grade: int,
    subject: str,
    unit: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    # A whole-unit breakdown can propose many sections in one reply (see notes.store.UNIT_PROMPT), so
    # this needs more than a single-question elaboration's budget - but this account's Groq tier hard-caps
    # a whole request (input + this reservation) at 8000 tokens, so it can't just be pushed arbitrarily
    # higher; notes.store.MAX_CONTEXT_CHARS caps the input side to leave this room safely under that.
    return StreamingResponse(_note_events(grade, subject, unit, db), media_type="text/event-stream")
