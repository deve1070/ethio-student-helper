"""Test of POST /v1/exam/solve: the real route with fakes for the model, OCR and similarity cache,
a real (SQLite) database, and the REAL payments.entitlement module (not stubbed) so the free-action
quota/dedup logic itself gets exercised here too. Run from backend/:   python test/test_exam_route.py
Checks the money-and-correctness rules: no caching or charging of 'no match' / unverified answers,
503 when the AI service is down, canonical subject names, a free action only for fresh verified
answers, and that the shared 8-action quota (not a per-feature one) blocks a fresh solve once used up."""

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


state = {"pipeline_calls": 0, "next": None}


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
stub("exams")
stub("exams.ocr", extract_text_from_base64_image=lambda b: "text from image")


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


stub("exams.cache", ExamCache=FakeCache)


class FakeBuilder:
    embeddings = None

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

# payments.entitlement is NOT stubbed - the real check_entitlement/record_free_action run against
# the same SQLite database, so this test also covers the entitlement boundary itself for the one
# gated endpoint that was already metered before this feature existed.
import api.routes_exam as R
from fastapi import FastAPI
from fastapi.testclient import TestClient

db = Session()
user = M.User(id=uuid.uuid4(), full_name="Alice")
db.add_all(
    [
        user,
        # ExamSolveRequest.grade is pinned to exactly 12 (ESSLCE scope) - a pre-existing,
        # already-uncommitted change on this branch, unrelated to this feature; these fixtures
        # just need to match it for the route to accept any request at all.
        M.Textbook(
            id=uuid.uuid4(), grade=12, subject="chemistry", title="Chemistry Grade 12"
        ),
        M.Textbook(
            id=uuid.uuid4(),
            grade=12,
            subject="information_technology",
            title="IT Grade 12",
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


def solve(subject="chemistry", q="What is an ion?", grade=12):
    return c.post(
        "/v1/exam/solve", json={"grade": grade, "subject": subject, "question_text": q}
    )


def free_actions_used():
    s = Session()
    n = s.query(M.FreeActionUsage).filter_by(user_id=user.id).count()
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
assert state["pipeline_calls"] == 0 and free_actions_used() == 0 and submissions() == 0
# 2) a fresh verified answer: generated, cached, one free action consumed
state["next"] = GOOD
r = solve()
b = r.json()
assert (
    r.status_code == 200
    and b["source"] == "generated"
    and "credits_charged" not in b
    and b["exam_question_id"]
), b
assert free_actions_used() == 1 and state["pipeline_calls"] == 1
# 3) the same question again, written with a different subject spelling: served from the cache, free, no model call
r = solve("  Chemistry ")
b = r.json()
assert (
    b["source"] == "cache" and state["pipeline_calls"] == 1 and free_actions_used() == 1
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
    and free_actions_used() == 1
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
    b["source"] == "unverified" and b["exam_question_id"] is None and free_actions_used() == 1
), b
calls = state["pipeline_calls"]
solve(q="Define ion?")
assert state["pipeline_calls"] == calls + 1  # not cached
# 5b) the checker DID run and flagged the draft as unsupported (re-research already used up its
# retries) - must be treated the same as ERROR above, not silently cached/charged as a normal pass.
state["next"] = dict(
    GOOD,
    draft_answer="An atom with a charge.\n\n> Note: some details could not be confirmed...",
    verification_status="FAIL",
)
r = solve(q="Define cation?")
b = r.json()
assert (
    b["source"] == "unverified" and b["exam_question_id"] is None and free_actions_used() == 1
), b
calls = state["pipeline_calls"]
solve(q="Define cation?")
assert state["pipeline_calls"] == calls + 1  # not cached either
# 6) AI service down -> 503, nothing charged or cached
state["next"] = LLMUnavailableError("rate limit")
r = solve(q="Another question about atoms?")
assert r.status_code == 503 and "try again" in r.json()["detail"] and free_actions_used() == 1
# 7) quota exhaustion is a SHARED pool, not per-feature - drive it up with other features' usage
# (resource_key=None rows, matching how explain/ask always count) rather than more exam solves,
# then confirm a fresh solve 402s while a cached one stays free regardless.
s = Session()
s.add_all(
    [M.FreeActionUsage(user_id=user.id, feature="explain", resource_key=None) for _ in range(6)]
)
s.commit()
s.close()
assert free_actions_used() == 7  # 1 from exam_solve above + 6 just inserted
state["next"] = GOOD
assert solve(q="A brand new question?").status_code == 200  # 8th action: still allowed
assert free_actions_used() == 8
state["next"] = GOOD
r = solve(q="Yet another brand new question?")
assert r.status_code == 402, r.text  # 9th action: blocked
assert solve().json()["source"] == "cache"  # cached answers are never gated, even now
# 8) the IT subject works with spaces and capitals
assert solve("Information Technology", q="What is a file?").status_code != 400
print(
    "EXAM ROUTE TESTS PASSED (400 typo, cache, no_match, unverified, 503, shared-quota 402, spelling-insensitive cache)"
)
