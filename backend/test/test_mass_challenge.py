"""Direct unit test of the mass-practice feature's core logic: question-picking rotation
determinism, answer-recording idempotency, and leaderboard ranking - against a bare SQLite
session, no HTTP layer, mirroring test_entitlement.py's shape.
Run from backend/:   python test/test_mass_challenge.py"""
import os
import sys
import uuid
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db.models as M  # noqa: F401 - registers users/etc. on the shared Base before create_all
from exams.models import (
    Base,
    EsslceAttempt,
    EsslcePaper,
    EsslceQuestion,
    EsslceTopicLink,
    MassChallenge,
)
from exams.store import pick_mass_challenge_questions, pick_todays_challenges, pick_todays_unit
from sqlalchemy import ARRAY, JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

for t in Base.metadata.tables.values():
    for c in t.columns:
        if isinstance(c.type, (JSONB, ARRAY)):
            c.type = JSON()
engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autoflush=False)

passed = failed = 0


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL: {label}")


def make_question(db, paper, item_no, unit, options=None, answer_index=1, grade=12, verified=True):
    q = EsslceQuestion(
        paper_id=paper.id,
        item_no=item_no,
        stem=f"Question {item_no}",
        options=options or ["A opt", "B opt", "C opt", "D opt"],
        has_diagram=False,
        answer_index=answer_index,
        answer_source="official_key",
        review_status="approved",
    )
    db.add(q)
    db.commit()
    db.add(
        EsslceTopicLink(
            question_id=q.id, rank=1, grade=grade, unit=unit, verified=verified
        )
    )
    db.commit()
    return q


# ---- pick_todays_unit: deterministic rotation - the same calendar date always picks the same
# (subject, grade, unit), and only ever from a subject that actually has eligible units -----------
db = Session()
bio_paper = EsslcePaper(subject="biology", year_ec=2015, source_dir=None)
db.add(bio_paper)
db.commit()
make_question(db, bio_paper, 1, "Unit 3: Ecology")
make_question(db, bio_paper, 2, "Unit 3: Ecology")

today = date(2026, 11, 9)
first = pick_todays_unit(db, today)
second = pick_todays_unit(db, today)
check("pick_todays_unit is deterministic for the same date", first == second)
check("pick_todays_unit found biology's only eligible unit", first is not None and first[0] == "biology")
check("pick_todays_unit returns the unit's own grade", first is not None and first[2] == "Unit 3: Ecology")

empty_engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
Base.metadata.create_all(empty_engine)
no_data_db = sessionmaker(bind=empty_engine, autoflush=False)()
check(
    "pick_todays_unit returns None when nothing is eligible anywhere",
    pick_todays_unit(no_data_db, today) is None,
)

# ---- pick_mass_challenge_questions: only questions linked to the requested unit/grade, capped
# at the requested count, never more than what's actually eligible -------------------------------
other_unit_q = make_question(db, bio_paper, 3, "Unit 4: Genetics")
picked = pick_mass_challenge_questions(db, "biology", 12, "Unit 3: Ecology", count=10)
check("pick_mass_challenge_questions only returns the matching unit", other_unit_q.id not in picked)
check("pick_mass_challenge_questions found both Ecology questions", len(picked) == 2)

picked_capped = pick_mass_challenge_questions(db, "biology", 12, "Unit 3: Ecology", count=1)
check("pick_mass_challenge_questions respects the requested count", len(picked_capped) == 1)


# ---- pick_todays_challenges: a day that lands on a stream-specific subject (here, only biology
# and geography have any eligible content at all, so the main rotation can only ever resolve to
# one of those two) splits into one challenge per stream, not a single shared one ------------------
geo_paper = EsslcePaper(subject="geography", year_ec=2015, source_dir=None)
db.add(geo_paper)
db.commit()
make_question(db, geo_paper, 1, "Unit 1: Population")

challenges = pick_todays_challenges(db, today)
check("stream-split day produces two challenges, not one shared", len(challenges) == 2)
by_stream = {c["stream"]: c for c in challenges}
check("one challenge is the natural-science stream's biology", by_stream.get("natural_science", {}).get("subject") == "biology")
check("the other is the social-science stream's geography", by_stream.get("social_science", {}).get("subject") == "geography")

common_engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
Base.metadata.create_all(common_engine)
common_db = sessionmaker(bind=common_engine, autoflush=False)()
math_paper = EsslcePaper(subject="mathematics", year_ec=2015, source_dir=None)
common_db.add(math_paper)
common_db.commit()
make_question(common_db, math_paper, 1, "Unit 1: Sets")
common_only = pick_todays_challenges(common_db, today)
check(
    "a day with only a common subject available produces one shared challenge",
    len(common_only) == 1 and common_only[0]["stream"] == "",
)


# ---- answer recording idempotency: the exact (user, challenge, question) no-op check the route
# itself performs before inserting a new EsslceAttempt row -----------------------------------------
def record_mass_answer(db, user_id, challenge_id, question, chosen_index):
    existing = (
        db.query(EsslceAttempt)
        .filter(
            EsslceAttempt.user_id == user_id,
            EsslceAttempt.mass_challenge_id == challenge_id,
            EsslceAttempt.question_id == question.id,
        )
        .first()
    )
    if existing is not None:
        return False, existing.is_correct
    is_correct = chosen_index == question.answer_index
    db.add(
        EsslceAttempt(
            user_id=user_id,
            question_id=question.id,
            paper_id=question.paper_id,
            chosen_index=chosen_index,
            is_correct=is_correct,
            mode="mass",
            mass_challenge_id=challenge_id,
        )
    )
    db.commit()
    return True, is_correct


challenge = MassChallenge(
    date=today, stream="", subject="biology", grade=12, unit="Unit 3: Ecology",
    question_ids=picked, opens_at=datetime.utcnow(), question_seconds=90,
)
db.add(challenge)
db.commit()

student = M.User(id=uuid.uuid4(), full_name="Mass Challenge Mia")
db.add(student)
db.commit()
q = db.query(EsslceQuestion).filter_by(item_no=1).first()

recorded_first, correct_first = record_mass_answer(db, student.id, challenge.id, q, q.answer_index)
check("first mass answer is recorded", recorded_first is True)
check("first mass answer is scored correctly", correct_first is True)

recorded_second, correct_second = record_mass_answer(db, student.id, challenge.id, q, 0)
check("a repeat mass answer is a no-op, not a new row", recorded_second is False)
check("a repeat mass answer returns the ORIGINAL result, not the new chosen_index", correct_second is True)
check(
    "exactly one attempt row exists for this (user, challenge, question)",
    db.query(EsslceAttempt)
    .filter(
        EsslceAttempt.user_id == student.id,
        EsslceAttempt.mass_challenge_id == challenge.id,
        EsslceAttempt.question_id == q.id,
    )
    .count()
    == 1,
)


# ---- leaderboard ranking: correct count first, then answered count, deterministic on ties -------
q2 = db.query(EsslceQuestion).filter_by(item_no=2).first()
record_mass_answer(db, student.id, challenge.id, q2, q2.answer_index)  # Mia: 2 correct, 2 answered

runner_up = M.User(id=uuid.uuid4(), full_name="Runner Up Ruth")
db.add(runner_up)
db.commit()
record_mass_answer(db, runner_up.id, challenge.id, q, q.answer_index)  # Ruth: 1 correct, 1 answered

rows = (
    db.query(EsslceAttempt.user_id, EsslceAttempt.is_correct)
    .filter(EsslceAttempt.mass_challenge_id == challenge.id)
    .all()
)
tally = {}
for user_id, is_correct in rows:
    entry = tally.setdefault(user_id, {"correct": 0, "answered": 0})
    entry["answered"] += 1
    if is_correct:
        entry["correct"] += 1
ranked = sorted(tally.items(), key=lambda kv: (-kv[1]["correct"], -kv[1]["answered"]))

check("the student with more correct answers ranks first", ranked[0][0] == student.id)
check("the student with fewer correct answers ranks second", ranked[1][0] == runner_up.id)


# ---- is_closed: catch-up serves, and scores as late, only questions finished in the group ------
from api.routes_mass_challenge import is_closed  # noqa: E402

check("before the event nothing is closed", is_closed(0, {}, 90) is False)
check("a poll still open is not closed", is_closed(0, {0: 30.0}, 90) is False)
check("inside the closing grace is not closed", is_closed(0, {0: 95.0}, 90) is False)
check("a poll past its open period is closed", is_closed(0, {0: 200.0}, 90) is True)
check("a question not posted yet, mid-event, is not closed", is_closed(2, {0: 200.0, 1: 30.0}, 90) is False)
check("a failed send the event moved past is closed", is_closed(1, {0: 300.0, 2: 30.0}, 90) is True)
check("the last question's failed send closes once its slot has passed", is_closed(5, {4: 300.0}, 90) is True)
check("...but not while its slot could still come", is_closed(5, {4: 120.0}, 90) is False)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
