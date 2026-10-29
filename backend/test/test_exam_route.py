"""Test of POST /v1/exam/solve: the real route with fakes for the model, OCR and similarity cache,
and a real (SQLite) database. Run from backend/:   python test/test_exam_route.py
Checks the money-and-correctness rules: no caching or charging of 'no match' / unverified answers,
503 when the AI service is down, canonical subject names, credits only for fresh verified answers."""

import os
import sys
import types
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---- fakes for everything that needs keys, models or Postgres -------------------------------------------------
def stub(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


state = {"balance": 5, "pipeline_calls": 0, "next": None}


class Unavailable(RuntimeError):
    pass


class FakeWorkflow:
    citation_agent = types.SimpleNamespace(resolve_chunk_ids=lambda ids: [])

    def full_pipeline(self, question, retriever):
        state["pipeline_calls"] += 1
        nxt = state["next"]
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


stub("agents")
stub("agents.workflow", AgentWorkflow=FakeWorkflow)
stub("auth")
stub("auth.dependencies", get_current_user=lambda: None)
stub("db.session", get_db=lambda: None)
stub("exam")
stub("exam.ocr", extract_text_from_base64_image=lambda b: "text from image")


class FakeCache:
    store = {}

    def find_cached_answer(self, db, text, grade, subject):
        return FakeCache.store.get((text, grade, subject))

    def bump_times_asked(self, db, q):
        pass

    def store_new_answer(
        self,
        db,
        question_text,
        grade,
        subject,
        exam_year,
        answer_text,
        citation_chunk_ids,
    ):
        q = types.SimpleNamespace(id=uuid.uuid4())
        a = types.SimpleNamespace(answer_text=answer_text, citation_chunk_ids=[])
        FakeCache.store[(question_text, grade, subject)] = (q, a)
        return q, a


stub("exam.cache", ExamCache=FakeCache)

from fastapi import HTTPException


def require_credits(db, user_id, cost):
    if state["balance"] < cost:
        raise HTTPException(status_code=402, detail="Out of credits")


stub("payments")
stub("payments.entitlement", require_credits=require_credits)


class FakeBuilder:
    def build_textbook_retriever(self, grade, subject):
        return types.SimpleNamespace(invoke=lambda q: [], grade=grade, subject=subject)


stub("retriever.builder", RetrieverBuilder=FakeBuilder)
stub("llm.client", LLMClient=lambda **k: None)
import logging

stub("utils.logging", logger=logging.getLogger("t"))
import db.models as M
from llm.retry import LLMUnavailableError  # the real one the route catches
from sqlalchemy import ARRAY, JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

for t in M.Base.metadata.tables.values():
    for c in t.columns:
        if isinstance(c.type, (JSONB, ARRAY)):
            c.type = JSON()
engine = create_engine(
    "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
)
M.Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autoflush=False)

import api.routes_exam as R
from fastapi import FastAPI
from fastapi.testclient import TestClient

db = Session()
user = M.User(id=uuid.uuid4(), full_name="Alice")
db.add_all(
    [
        user,
        M.Textbook(
            id=uuid.uuid4(), grade=9, subject="chemistry", title="Chemistry Grade 9"
        ),
        M.Textbook(
            id=uuid.uuid4(),
            grade=9,
            subject="information_technology",
            title="IT Grade 9",
        ),
    ]
)
db.commit()


def _db():
    s = Session()
    try:
        yield s
    finally:
        s.close()


app = FastAPI()
app.include_router(R.router)
app.dependency_overrides[R.get_db] = _db
app.dependency_overrides[R.get_current_user] = lambda: user
c = TestClient(app)


def solve(subject="chemistry", q="What is an ion?", grade=9):
    return c.post(
        "/v1/exam/solve", json={"grade": grade, "subject": subject, "question_text": q}
    )


def ledger():
    s = Session()
    n = s.query(M.CreditLedgerEntry).count()
    s.close()
    return n


def submissions():
    s = Session()
    n = s.query(M.ExamQuestionSubmission).count()
    s.close()
    return n


GOOD = {
    "draft_answer": "An ion is a charged atom.",
    "citations": [],
    "is_relevant": True,
    "verification_status": "PASS",
    "verification_report": "",
}

# 1) unknown / mistyped subject -> 400 with a suggestion; nothing recorded or charged
r = solve("chemisty")
assert r.status_code == 400 and "Did you mean 'chemistry'" in r.json()["detail"], r.text
assert state["pipeline_calls"] == 0 and ledger() == 0 and submissions() == 0
# 2) a fresh verified answer: generated, cached, one credit charged
state["next"] = GOOD
r = solve()
b = r.json()
assert (
    r.status_code == 200
    and b["source"] == "generated"
    and b["credits_charged"] == 1
    and b["exam_question_id"]
), b
assert ledger() == 1 and state["pipeline_calls"] == 1
# 3) the same question again, written with a different subject spelling: served from the cache, free, no model call
r = solve("  Chemistry ")
b = r.json()
assert (
    b["source"] == "cache"
    and b["credits_charged"] == 0
    and state["pipeline_calls"] == 1
    and ledger() == 1
), b
# 4) the textbooks have nothing on it: not cached, not charged, no id; the submission is still recorded
state["next"] = {
    "draft_answer": "This question isn't related (or there's no data) for your query.",
    "citations": [],
    "is_relevant": False,
    "verification_status": "",
    "verification_report": "",
}
before = submissions()
r = solve(q="Who won the world cup?")
b = r.json()
assert (
    r.status_code == 200
    and b["source"] == "no_match"
    and b["exam_question_id"] is None
    and b["credits_charged"] == 0
    and ledger() == 1
), b
assert submissions() == before + 1
solve(q="Who won the world cup?")
assert (
    state["pipeline_calls"] == 3
)  # asked the model again: the 'no data' reply was NOT cached
# 5) the checker could not run: answer shown but not cached and not charged
state["next"] = dict(
    GOOD,
    draft_answer="An atom with a charge.\n\n> Note: this answer could not be checked...",
    verification_status="ERROR",
)
r = solve(q="Define ion?")
b = r.json()
assert (
    b["source"] == "unverified"
    and b["exam_question_id"] is None
    and b["credits_charged"] == 0
    and ledger() == 1
), b
calls = state["pipeline_calls"]
solve(q="Define ion?")
assert state["pipeline_calls"] == calls + 1  # not cached
# 6) AI service down -> 503, nothing charged or cached
state["next"] = LLMUnavailableError("rate limit")
r = solve(q="Another question about atoms?")
assert r.status_code == 503 and "try again" in r.json()["detail"] and ledger() == 1
# 7) out of credits: fresh questions are refused (402) but cached ones are still free
state["balance"] = 0
state["next"] = GOOD
assert solve(q="A brand new question?").status_code == 402
assert solve().json()["source"] == "cache"
# 8) the IT subject works with spaces and capitals, and a grade with no books lists nothing
assert solve("Information Technology", q="What is a file?").status_code != 400
r = solve("chemistry", grade=11)
assert r.status_code == 400 and "none yet" in r.json()["detail"]
print(
    "EXAM ROUTE TESTS PASSED (400 typo, cache, no_match, unverified, 503, 402, spelling-insensitive cache)"
)
