"""The public channel's daily quiz (telegram_bot/channel_posts.py): one past-exam question that fits a
Telegram quiz poll, picked by the backend so the same question is not posted again for a long time.

A Telegram quiz poll holds plain text only - a question of at most 300 characters and four options
of at most 100 - so a question is skipped when it needs anything a poll cannot show: a diagram, a
reading passage, underlined words, or LaTeX maths."""

import random
from datetime import datetime, timedelta, timezone

from auth.dependencies import require_bot_internal_token
from db.session import get_db
from exams.latex_render import contains_latex_math
from exams.models import EsslcePaper, EsslceQuestion
from exams.store import eligible, eligible_filter
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1/channel", tags=["channel"])

POLL_QUESTION_CHARS = 300
POLL_OPTION_CHARS = 100
REPOST_AFTER_DAYS = 180
MAX_CHECKED = 200  # candidates loaded one by one until one fits; a cap so a bad bank never loops long


class QuizQuestion(BaseModel):
    question_id: int
    subject: str
    year_ec: int
    stem: str
    options: list[str]
    correct_index: int
    explanation: str | None  # plain text only; None when it has maths a poll cannot show


def fits_poll(q: EsslceQuestion) -> bool:
    options = q.options or []
    return (
        len(options) == 4
        and all(isinstance(o, str) and 0 < len(o.strip()) <= POLL_OPTION_CHARS for o in options)
        and 0 < len(q.stem.strip()) <= POLL_QUESTION_CHARS
        and not q.underlined
        and not contains_latex_math(q.stem)
        and not any(contains_latex_math(o) for o in options)
    )


@router.post("/question-of-the-day", response_model=QuizQuestion, dependencies=[Depends(require_bot_internal_token)])
def question_of_the_day(db: Session = Depends(get_db)) -> QuizQuestion:
    """Picks a question for today's channel quiz and marks it posted. Each call picks a new one."""
    now = datetime.now(timezone.utc)
    ids = [
        qid
        for (qid,) in db.query(EsslceQuestion.id)
        .join(EsslcePaper, EsslceQuestion.paper_id == EsslcePaper.id)
        .filter(
            eligible_filter(),
            EsslceQuestion.has_diagram.is_(False),
            EsslceQuestion.passage_id.is_(None),
            func.length(EsslceQuestion.stem) <= POLL_QUESTION_CHARS,
            or_(
                EsslceQuestion.channel_posted_at.is_(None),
                EsslceQuestion.channel_posted_at < now - timedelta(days=REPOST_AFTER_DAYS),
            ),
        )
        .all()
    ]
    random.shuffle(ids)
    for qid in ids[:MAX_CHECKED]:
        q = db.get(EsslceQuestion, qid)
        if not fits_poll(q):
            continue
        q.channel_posted_at = now
        db.commit()
        explanation = q.explanation if q.explanation and not contains_latex_math(q.explanation) else None
        return QuizQuestion(
            question_id=q.id,
            subject=q.paper.subject,
            year_ec=q.paper.year_ec,
            stem=q.stem.strip(),
            options=[o.strip() for o in q.options],
            correct_index=q.answer_index,
            explanation=explanation,
        )
    raise HTTPException(status_code=404, detail="No question fits a channel quiz right now.")


# ---- inline mode: students send a question into any chat (telegram_bot/inline_quiz.py) ------------------
INLINE_RESULTS = 10
INLINE_TEXT_CHARS = 1500  # stem plus options, so the message stays readable in a chat
INLINE_POOL = 60  # rows loaded per search at most: Telegram sends a search as the student types


class InlineQuestion(BaseModel):
    question_id: int
    subject: str
    year_ec: int
    stem: str
    options: list[str]


def fits_message(q: EsslceQuestion) -> bool:
    options = q.options or []
    return (
        len(options) == 4
        and all(isinstance(o, str) and o.strip() for o in options)
        and len(q.stem) + sum(len(o) for o in options) <= INLINE_TEXT_CHARS
        and not q.underlined
        and not contains_latex_math(q.stem)
        and not any(contains_latex_math(o) for o in options)
    )


@router.get("/inline-questions", response_model=list[InlineQuestion], dependencies=[Depends(require_bot_internal_token)])
def inline_questions(q: str = "", db: Session = Depends(get_db)) -> list[InlineQuestion]:
    """Up to 10 random past-exam questions that read well as a chat message. `q` is what the
    student typed after the bot's name: words matching a subject name (e.g. "bio", "physics")
    narrow to those subjects; other words must appear in the question."""
    words = [w for w in q.lower().split() if len(w) >= 3][:5]
    subjects = [s for (s,) in db.query(EsslcePaper.subject).distinct()]
    wanted = {s for s in subjects for w in words if s.replace("_", " ").startswith(w) or w in s}
    keywords = [w for w in words if not any(w in s or s.replace("_", " ").startswith(w) for s in subjects)]
    query = (
        db.query(EsslceQuestion.id)
        .join(EsslcePaper, EsslceQuestion.paper_id == EsslcePaper.id)
        .filter(eligible_filter(), EsslceQuestion.has_diagram.is_(False), EsslceQuestion.passage_id.is_(None))
    )
    if wanted:
        query = query.filter(EsslcePaper.subject.in_(wanted))
    for w in keywords:
        query = query.filter(EsslceQuestion.stem.ilike(f"%{w}%"))
    ids = [qid for (qid,) in query.all()]
    random.shuffle(ids)
    out = []
    for qid in ids[:INLINE_POOL]:
        row = db.get(EsslceQuestion, qid)
        if fits_message(row):
            out.append(InlineQuestion(question_id=row.id, subject=row.paper.subject, year_ec=row.paper.year_ec,
                                      stem=row.stem.strip(), options=[o.strip() for o in row.options]))
            if len(out) == INLINE_RESULTS:
                break
    return out


class AnswerKey(BaseModel):
    correct_index: int
    explanation: str | None  # plain text only


@router.get("/answer-key/{question_id}", response_model=AnswerKey, dependencies=[Depends(require_bot_internal_token)])
def answer_key(question_id: int, db: Session = Depends(get_db)) -> AnswerKey:
    """For a tap on a shared question's A-D button: the right option and a plain explanation."""
    q = db.get(EsslceQuestion, question_id)
    if q is None or not eligible(q):
        raise HTTPException(status_code=404, detail="That question is no longer available.")
    explanation = q.explanation if q.explanation and not contains_latex_math(q.explanation) else None
    return AnswerKey(correct_index=q.answer_index, explanation=explanation)
