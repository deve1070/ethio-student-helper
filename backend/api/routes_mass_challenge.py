"""The daily subscriber-only mass ESSLCE practice: one or two shared challenges per day (one per
stream, when that day's subject isn't common to both - see exams/store.py's
pick_todays_challenges), each a sequence of native Telegram polls posted to the private group,
everyone answering the same question at the same time, ranked on a leaderboard once that
challenge's questions are all done. See docs/dev_plans/mass_esslce_practice.md for the full design.
Most endpoints serve the bot's own scheduled job and aren't on behalf of any one student (behind
require_bot_internal_token); /answer is behind get_current_user (a real student's own vote,
recorded when their PollAnswer update arrives); the two leaderboard reads are intentionally open
(no auth) since they're non-sensitive and also used by the web app's own /leaderboard page."""

import base64
from datetime import date, datetime, timedelta

from auth.dependencies import get_current_user, require_bot_internal_token, require_student_or_bot
from config.settings import settings
from db.models import TelegramLink, User
from db.session import get_db
from exams.latex_render import contains_latex_math, render_latex_png
from exams.models import (
    EsslceAttempt,
    EsslceQuestion,
    MassChallenge,
    MassChallengePoll,
    PrivateGroupMembership,
)
from exams.store import pick_mass_challenge_questions, pick_todays_challenges, question_page_image
from fastapi import APIRouter, Depends, HTTPException
from payments.entitlement import has_active_subscription
from practice.selection import local_date, study_streak, today_local
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1/mass-challenge", tags=["mass-challenge"])

MASS_MODES = ("mass", "mass_late")  # EsslceAttempt.mode values that count as mass-practice participation
POLL_CLOSE_GRACE_SECONDS = 10  # a vote Telegram accepted just before closing can arrive slightly after


class TodayChallengeResponse(BaseModel):
    id: int
    stream: str
    subject: str
    grade: int | None
    unit: str
    question_ids: list[int]
    opens_at: datetime
    question_seconds: int


class TodayChallengesResponse(BaseModel):
    challenges: list[TodayChallengeResponse]


class QuestionContentResponse(BaseModel):
    item_no: int
    stem: str
    options: list[str]
    answer_index: int
    explanation: str | None
    diagram_image_base64: str | None
    stem_image_base64: str | None  # set when the stem/options contain LaTeX - raw text would be broken


class MassAnswerRequest(BaseModel):
    challenge_id: int
    question_id: int
    chosen_index: int = Field(ge=0, le=3)


class MassAnswerResponse(BaseModel):
    recorded: bool  # False when this (user, challenge, question) was already answered - a no-op
    is_correct: bool  # the bot shows this only for a late answer (below) - an on-time vote on the
    # group poll gets no feedback until the group's reveal message
    late: bool  # answered after that question's group poll had closed (the private catch-up
    # flow). Stored as mode="mass_late": it counts toward the student's participation days and
    # question totals, but not toward the day's or week's score ranking, since the correct
    # answers have already been posted in the group by then.


class RemainingResponse(BaseModel):
    challenge_id: int
    subject: str
    unit: str
    total: int
    remaining_question_ids: list[int]


class AtRiskStudent(BaseModel):
    telegram_user_id: int
    streak_days: int
    challenge_id: int


class AtRiskResponse(BaseModel):
    students: list[AtRiskStudent]


class WeeklyLeaderboardEntry(BaseModel):
    user_id: str
    display_name: str
    correct: int
    answered: int
    days_participated: int


class WeeklyLeaderboardResponse(BaseModel):
    entries: list[WeeklyLeaderboardEntry]


class ChallengeLeaderboardEntry(BaseModel):
    user_id: str
    display_name: str
    correct: int
    answered: int


class ChallengeLeaderboardResponse(BaseModel):
    challenge_id: int
    subject: str
    unit: str
    total_questions: int
    entries: list[ChallengeLeaderboardEntry]


class ConsistencyLeaderboardEntry(BaseModel):
    user_id: str
    display_name: str
    questions_answered: int
    days_participated: int


class ConsistencyLeaderboardResponse(BaseModel):
    entries: list[ConsistencyLeaderboardEntry]


class GroupEligibilityResponse(BaseModel):
    eligible: bool


class LapsedMembership(BaseModel):
    telegram_user_id: int


class LapsedMembershipsResponse(BaseModel):
    lapsed: list[LapsedMembership]


class LatestChallengeEntry(BaseModel):
    id: int
    stream: str
    subject: str
    unit: str


class LatestChallengesResponse(BaseModel):
    date: date
    challenges: list[LatestChallengeEntry]


def _display_name(user: User) -> str:
    """First name and last initial ("Dawit K."). Leaderboards are seen by every other student and
    posted in the Telegram group, so they never carry a full name."""
    parts = (user.full_name or "").split()
    if not parts:
        return f"Student {str(user.id)[:4]}"
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][0]}."


def _to_response(challenge: MassChallenge) -> TodayChallengeResponse:
    return TodayChallengeResponse(
        id=challenge.id,
        stream=challenge.stream,
        subject=challenge.subject,
        grade=challenge.grade,
        unit=challenge.unit,
        question_ids=challenge.question_ids,
        opens_at=challenge.opens_at,
        question_seconds=challenge.question_seconds,
    )


@router.get("/latest", response_model=LatestChallengesResponse | None)
def latest_challenges(db: Session = Depends(get_db)) -> LatestChallengesResponse | None:
    """Every challenge sharing the most recent date (1 or 2, one per stream) - for the web app's
    leaderboard page to discover which challenge_id(s) to ask /leaderboard about.
    Unauthenticated, same as the leaderboard endpoints themselves, and read-only (never creates
    one, unlike /today)."""
    latest_date = db.query(MassChallenge.date).order_by(MassChallenge.date.desc()).limit(1).scalar()
    if latest_date is None:
        return None
    rows = db.query(MassChallenge).filter(MassChallenge.date == latest_date).all()
    return LatestChallengesResponse(
        date=latest_date,
        challenges=[
            LatestChallengeEntry(id=c.id, stream=c.stream, subject=c.subject, unit=c.unit) for c in rows
        ],
    )


@router.post(
    "/today", response_model=TodayChallengesResponse, dependencies=[Depends(require_bot_internal_token)]
)
def today(db: Session = Depends(get_db)) -> TodayChallengesResponse:
    today_date = today_local()
    existing = db.query(MassChallenge).filter(MassChallenge.date == today_date).all()
    if existing:
        return TodayChallengesResponse(challenges=[_to_response(c) for c in existing])

    picked = pick_todays_challenges(db, today_date)
    if not picked:
        raise HTTPException(status_code=503, detail="No eligible unit available for today's challenge.")

    question_count = settings.MASS_CHALLENGE_QUESTION_COUNT
    created = []
    for entry in picked:
        question_ids = pick_mass_challenge_questions(
            db, entry["subject"], entry["grade"], entry["unit"], question_count
        )
        if not question_ids:
            continue
        challenge = MassChallenge(
            date=today_date,
            stream=entry["stream"],
            subject=entry["subject"],
            grade=entry["grade"],
            unit=entry["unit"],
            question_ids=question_ids,
            opens_at=datetime.utcnow(),
            question_seconds=settings.MASS_CHALLENGE_QUESTION_SECONDS,
        )
        db.add(challenge)
        created.append(challenge)

    if not created:
        raise HTTPException(status_code=503, detail="No eligible questions for today's chosen unit(s).")
    db.commit()
    for c in created:
        db.refresh(c)

    return TodayChallengesResponse(challenges=[_to_response(c) for c in created])


class ChallengeStateResponse(TodayChallengeResponse):
    posted_question_ids: list[int]
    seconds_since_last_poll: float | None  # None when no poll has been posted yet


class TodayStateResponse(BaseModel):
    challenges: list[ChallengeStateResponse]


@router.get(
    "/today-state",
    response_model=TodayStateResponse,
    dependencies=[Depends(require_bot_internal_token)],
)
def today_state(db: Session = Depends(get_db)) -> TodayStateResponse:
    """Today's challenge(s) plus which questions already have a poll posted - read-only (never
    creates a challenge, unlike /today). For the bot's resume_after_restart: its question/reveal
    jobs live only in process memory, so after a restart mid-event this is how it learns what is
    still owed. seconds_since_last_poll is measured against the database's own clock (the same
    clock that stamped MassChallengePoll.sent_at), not this server's."""
    out = []
    for challenge in db.query(MassChallenge).filter(MassChallenge.date == today_local()).all():
        polls = db.query(MassChallengePoll).filter(MassChallengePoll.challenge_id == challenge.id).all()
        since_last = None
        if polls:
            since_last = db.query(
                func.extract("epoch", func.now() - func.max(MassChallengePoll.sent_at))
            ).filter(MassChallengePoll.challenge_id == challenge.id).scalar()
        out.append(
            ChallengeStateResponse(
                **_to_response(challenge).model_dump(),
                posted_question_ids=[p.question_id for p in polls],
                seconds_since_last_poll=float(since_last) if since_last is not None else None,
            )
        )
    return TodayStateResponse(challenges=out)


@router.get(
    "/question/{question_id}",
    response_model=QuestionContentResponse,
    dependencies=[Depends(require_bot_internal_token)],
)
def question_content(question_id: int, db: Session = Depends(get_db)) -> QuestionContentResponse:
    """Full content for one mass-challenge question, for the bot to post as a pre-poll message
    (same stem+diagram+LaTeX-image handling api/routes_esslce.py's _build_outputs already uses) -
    kept separate from the poll itself because Telegram quiz polls cap the question at 300
    characters and each option at 100, far below a typical ESSLCE stem."""
    question = db.get(EsslceQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found.")

    options = list(question.options or [])
    diagram_b64 = None
    if question.has_diagram:
        png = question_page_image(question)
        if png:
            diagram_b64 = base64.b64encode(png).decode()

    stem_b64 = None
    if contains_latex_math(question.stem) or any(contains_latex_math(o) for o in options):
        lettered = "\n".join(f"{L}) {opt}" for L, opt in zip("ABCD", options))
        png = render_latex_png(f"{question.stem}\n\n{lettered}")
        if png:
            stem_b64 = base64.b64encode(png).decode()

    return QuestionContentResponse(
        item_no=question.item_no,
        stem=question.stem,
        options=options,
        answer_index=question.answer_index,
        explanation=question.explanation,
        diagram_image_base64=diagram_b64,
        stem_image_base64=stem_b64,
    )


class RecordPollRequest(BaseModel):
    question_id: int
    telegram_poll_id: str


class PollLookupResponse(BaseModel):
    challenge_id: int
    question_id: int


@router.post("/{challenge_id}/poll", dependencies=[Depends(require_bot_internal_token)])
def record_poll(challenge_id: int, request: RecordPollRequest, db: Session = Depends(get_db)) -> dict:
    challenge = db.get(MassChallenge, challenge_id)
    if challenge is None:
        raise HTTPException(status_code=404, detail="Challenge not found.")
    db.add(
        MassChallengePoll(
            challenge_id=challenge_id,
            question_id=request.question_id,
            telegram_poll_id=request.telegram_poll_id,
        )
    )
    db.commit()
    return {"ok": True}


@router.get(
    "/poll/{telegram_poll_id}",
    response_model=PollLookupResponse,
    dependencies=[Depends(require_bot_internal_token)],
)
def lookup_poll(telegram_poll_id: str, db: Session = Depends(get_db)) -> PollLookupResponse:
    poll = (
        db.query(MassChallengePoll).filter(MassChallengePoll.telegram_poll_id == telegram_poll_id).first()
    )
    if poll is None:
        raise HTTPException(status_code=404, detail="Unknown poll.")
    return PollLookupResponse(challenge_id=poll.challenge_id, question_id=poll.question_id)


@router.post("/answer", response_model=MassAnswerResponse)
def answer(
    request: MassAnswerRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MassAnswerResponse:
    challenge = db.get(MassChallenge, request.challenge_id)
    if challenge is None or request.question_id not in challenge.question_ids:
        raise HTTPException(status_code=404, detail="Question is not part of this challenge.")

    existing = (
        db.query(EsslceAttempt)
        .filter(
            EsslceAttempt.user_id == user.id,
            EsslceAttempt.mass_challenge_id == request.challenge_id,
            EsslceAttempt.question_id == request.question_id,
        )
        .first()
    )
    if existing is not None:
        return MassAnswerResponse(
            recorded=False, is_correct=existing.is_correct, late=existing.mode == "mass_late"
        )

    question = db.get(EsslceQuestion, request.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found.")

    is_correct = request.chosen_index == question.answer_index
    late = _poll_closed(db, challenge, question.id)
    db.add(
        EsslceAttempt(
            user_id=user.id,
            question_id=question.id,
            paper_id=question.paper_id,
            chosen_index=request.chosen_index,
            is_correct=is_correct,
            mode="mass_late" if late else "mass",
            mass_challenge_id=request.challenge_id,
        )
    )
    db.commit()
    return MassAnswerResponse(recorded=True, is_correct=is_correct, late=late)


def is_late_answer(seconds_since_poll: float | None, question_seconds: int, challenge_has_polls: bool) -> bool:
    """Whether an answer arriving now is after that question's group poll closed.
    seconds_since_poll is None when this question has no poll row: before the event starts that
    means "not late"; once the challenge has posted any poll it means this question's own poll
    was never recorded (a failed send), and the event has moved on without it."""
    if seconds_since_poll is None:
        return challenge_has_polls
    return seconds_since_poll > question_seconds + POLL_CLOSE_GRACE_SECONDS


def _poll_closed(db: Session, challenge: MassChallenge, question_id: int) -> bool:
    since = (
        db.query(func.extract("epoch", func.now() - func.max(MassChallengePoll.sent_at)))
        .filter(MassChallengePoll.challenge_id == challenge.id, MassChallengePoll.question_id == question_id)
        .scalar()
    )
    has_polls = (
        db.query(MassChallengePoll.id).filter(MassChallengePoll.challenge_id == challenge.id).first()
        is not None
    )
    return is_late_answer(float(since) if since is not None else None, challenge.question_seconds, has_polls)


@router.get("/{challenge_id}/remaining", response_model=RemainingResponse)
def remaining(
    challenge_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> RemainingResponse:
    """The questions of one challenge this student has not answered yet, in the day's order -
    what the bot's private catch-up flow serves next."""
    challenge = db.get(MassChallenge, challenge_id)
    if challenge is None:
        raise HTTPException(status_code=404, detail="Challenge not found.")
    answered = {
        row[0]
        for row in db.query(EsslceAttempt.question_id).filter(
            EsslceAttempt.user_id == user.id, EsslceAttempt.mass_challenge_id == challenge_id
        )
    }
    return RemainingResponse(
        challenge_id=challenge.id,
        subject=challenge.subject,
        unit=challenge.unit,
        total=len(challenge.question_ids),
        remaining_question_ids=[q for q in challenge.question_ids if q not in answered],
    )


@router.get("/at-risk", response_model=AtRiskResponse, dependencies=[Depends(require_bot_internal_token)])
def at_risk(db: Session = Depends(get_db)) -> AtRiskResponse:
    """Students whose mass-practice streak ends tonight: they took part yesterday, have not
    answered anything today, and today's challenge exists. Each comes with the challenge to catch
    up on - their own stream's on a stream-split day, the shared one otherwise. For the bot's
    evening reminder, which messages only these students, not the whole group."""
    challenges = db.query(MassChallenge).filter(MassChallenge.date == today_local()).all()
    if not challenges:
        return AtRiskResponse(students=[])
    by_stream = {c.stream: c for c in challenges}

    days_by_user: dict = {}
    for user_id, created_at in db.query(EsslceAttempt.user_id, EsslceAttempt.created_at).filter(
        EsslceAttempt.mode.in_(MASS_MODES)
    ):
        days_by_user.setdefault(user_id, set()).add(local_date(created_at))

    today = today_local()
    at_risk_ids = [u for u, days in days_by_user.items() if today not in days and study_streak(days) > 0]
    if not at_risk_ids:
        return AtRiskResponse(students=[])

    users = {u.id: u for u in db.query(User).filter(User.id.in_(at_risk_ids))}
    students = []
    for link in db.query(TelegramLink).filter(TelegramLink.user_id.in_(at_risk_ids)):
        user = users.get(link.user_id)
        challenge = by_stream.get(user.stream or "") or by_stream.get("") if user else None
        if challenge is None:
            continue
        students.append(
            AtRiskStudent(
                telegram_user_id=link.telegram_user_id,
                streak_days=study_streak(days_by_user[link.user_id]),
                challenge_id=challenge.id,
            )
        )
    return AtRiskResponse(students=students)


@router.get("/weekly-leaderboard", response_model=WeeklyLeaderboardResponse, dependencies=[Depends(require_student_or_bot)])
def weekly_leaderboard(db: Session = Depends(get_db)) -> WeeklyLeaderboardResponse:
    """Score ranking over the last 7 local days (today included). On-time answers only
    (mode="mass") - a catch-up answer is given after the correct answers were posted."""
    first_day = today_local() - timedelta(days=6)
    tally: dict = {}
    for user_id, is_correct, created_at in db.query(
        EsslceAttempt.user_id, EsslceAttempt.is_correct, EsslceAttempt.created_at
    ).filter(EsslceAttempt.mode == "mass", EsslceAttempt.created_at >= datetime.utcnow() - timedelta(days=8)):
        day = local_date(created_at)
        if day < first_day:
            continue
        entry = tally.setdefault(user_id, {"correct": 0, "answered": 0, "days": set()})
        entry["answered"] += 1
        entry["correct"] += bool(is_correct)
        entry["days"].add(day)

    users_by_id = {u.id: u for u in db.query(User).filter(User.id.in_(tally.keys())).all()}
    entries = [
        WeeklyLeaderboardEntry(
            user_id=str(user_id),
            display_name=_display_name(users_by_id[user_id]),
            correct=t["correct"],
            answered=t["answered"],
            days_participated=len(t["days"]),
        )
        for user_id, t in tally.items()
        if user_id in users_by_id
    ]
    entries.sort(key=lambda e: (-e.correct, -e.days_participated, -e.answered, e.display_name))
    return WeeklyLeaderboardResponse(entries=entries)


@router.get("/{challenge_id}/leaderboard", response_model=ChallengeLeaderboardResponse, dependencies=[Depends(require_student_or_bot)])
def challenge_leaderboard(challenge_id: int, db: Session = Depends(get_db)) -> ChallengeLeaderboardResponse:
    challenge = db.get(MassChallenge, challenge_id)
    if challenge is None:
        raise HTTPException(status_code=404, detail="Challenge not found.")

    rows = (
        db.query(EsslceAttempt.user_id, EsslceAttempt.is_correct)
        .filter(EsslceAttempt.mass_challenge_id == challenge_id, EsslceAttempt.mode == "mass")
        .all()
    )
    tally: dict = {}
    for user_id, is_correct in rows:
        entry = tally.setdefault(user_id, {"correct": 0, "answered": 0})
        entry["answered"] += 1
        if is_correct:
            entry["correct"] += 1

    users_by_id = {u.id: u for u in db.query(User).filter(User.id.in_(tally.keys())).all()}
    entries = [
        ChallengeLeaderboardEntry(
            user_id=str(user_id),
            display_name=_display_name(users_by_id[user_id]),
            correct=counts["correct"],
            answered=counts["answered"],
        )
        for user_id, counts in tally.items()
        if user_id in users_by_id
    ]
    entries.sort(key=lambda e: (-e.correct, -e.answered, e.display_name))

    return ChallengeLeaderboardResponse(
        challenge_id=challenge.id,
        subject=challenge.subject,
        unit=challenge.unit,
        total_questions=len(challenge.question_ids),
        entries=entries,
    )


@router.get("/consistency-leaderboard", response_model=ConsistencyLeaderboardResponse, dependencies=[Depends(require_student_or_bot)])
def consistency_leaderboard(db: Session = Depends(get_db)) -> ConsistencyLeaderboardResponse:
    rows = (
        db.query(EsslceAttempt.user_id, EsslceAttempt.created_at)
        .filter(EsslceAttempt.mode.in_(MASS_MODES))
        .all()
    )
    days_by_user: dict = {}
    counts: dict = {}
    for user_id, created_at in rows:
        days_by_user.setdefault(user_id, set()).add(local_date(created_at))
        counts[user_id] = counts.get(user_id, 0) + 1

    users_by_id = {u.id: u for u in db.query(User).filter(User.id.in_(days_by_user.keys())).all()}
    entries = [
        ConsistencyLeaderboardEntry(
            user_id=str(user_id),
            display_name=_display_name(users_by_id[user_id]),
            questions_answered=counts[user_id],
            days_participated=len(days),
        )
        for user_id, days in days_by_user.items()
        if user_id in users_by_id
    ]
    entries.sort(key=lambda e: (-e.days_participated, -e.questions_answered, e.display_name))

    return ConsistencyLeaderboardResponse(entries=entries)


@router.get(
    "/group-eligibility/{telegram_user_id}",
    response_model=GroupEligibilityResponse,
    dependencies=[Depends(require_bot_internal_token)],
)
def group_eligibility(telegram_user_id: int, db: Session = Depends(get_db)) -> GroupEligibilityResponse:
    """Checked when a student requests to join the private group. An eligible request also
    records the membership row immediately (rather than waiting for a second call), since
    approval is about to follow - sweep_expired_memberships later needs this row to know who to
    re-check."""
    link = db.get(TelegramLink, telegram_user_id)
    if link is None or not has_active_subscription(db, link.user_id):
        return GroupEligibilityResponse(eligible=False)

    existing = db.get(PrivateGroupMembership, link.user_id)
    if existing is None:
        db.add(PrivateGroupMembership(user_id=link.user_id))
        db.commit()
    return GroupEligibilityResponse(eligible=True)


@router.get(
    "/lapsed-memberships",
    response_model=LapsedMembershipsResponse,
    dependencies=[Depends(require_bot_internal_token)],
)
def lapsed_memberships(db: Session = Depends(get_db)) -> LapsedMembershipsResponse:
    """Daily sweep: every private-group member whose subscription is no longer active. Clears
    their membership row here (the backend owns subscription truth) - the bot's job is only to
    perform the Telegram-side kick, which this endpoint cannot do itself."""
    memberships = db.query(PrivateGroupMembership).all()
    lapsed_user_ids = [m.user_id for m in memberships if not has_active_subscription(db, m.user_id)]
    if not lapsed_user_ids:
        return LapsedMembershipsResponse(lapsed=[])

    links = (
        db.query(TelegramLink).filter(TelegramLink.user_id.in_(lapsed_user_ids)).all()
    )
    telegram_ids = [link.telegram_user_id for link in links]

    db.query(PrivateGroupMembership).filter(
        PrivateGroupMembership.user_id.in_(lapsed_user_ids)
    ).delete(synchronize_session=False)
    db.commit()

    return LapsedMembershipsResponse(lapsed=[LapsedMembership(telegram_user_id=t) for t in telegram_ids])
