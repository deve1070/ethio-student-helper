"""Integration test for /v1/progress/streak - the one endpoint that legitimately spans the
QuizQuestion-practice and ESSLCE systems (combining their attempt DATES, never their schemas).
Run from backend/:   python test/test_progress_route.py"""
import sys
import types
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, ".")

auth_pkg = types.ModuleType("auth")
auth_dep = types.ModuleType("auth.dependencies")
auth_dep.get_current_user = lambda: (_ for _ in ()).throw(RuntimeError("overridden in test"))
sys.modules["auth"] = auth_pkg
sys.modules["auth.dependencies"] = auth_dep
dbs = types.ModuleType("db.session")
dbs.get_db = lambda: (_ for _ in ()).throw(RuntimeError("overridden in test"))
sys.modules["db.session"] = dbs

from sqlalchemy import ARRAY, JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db.models as M
import db.models_practice as P
import exams.models as EM  # registers esslce_* tables onto the same shared Base

for t in M.Base.metadata.tables.values():
    for c in t.columns:
        if isinstance(c.type, (JSONB, ARRAY)):
            c.type = JSON()
engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
M.Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autoflush=False)

import api.routes_progress as R
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(R.router)

db = Session()
alice = M.User(id=uuid.uuid4(), full_name="Alice")
bob = M.User(id=uuid.uuid4(), full_name="Bob")
book = M.Textbook(id=uuid.uuid4(), grade=9, subject="chemistry", title="Chemistry Grade 9")
db.add_all([alice, bob, book])
db.commit()

q = P.QuizQuestion(
    textbook_id=book.id, grade=9, subject="chemistry", question="Q", options=["a", "b", "c", "d"],
    answer_index=0, explanation="x", supporting_quote="x", source_vector_ids=["v"],
    content_hash=uuid.uuid4().hex,
)
db.add(q)
db.commit()

paper = EM.EsslcePaper(subject="mathematics", year_ec=2018, year_gc=2026)
db.add(paper)
db.commit()
eq = EM.EsslceQuestion(
    paper_id=paper.id, item_no=1, stem="2+2=?", options=["3", "4", "5", "6"], answer_index=1,
    answer_source="ai_derived", explanation="because", review_status="approved",
)
db.add(eq)
db.commit()


def _db():
    s = Session()
    try:
        yield s
    finally:
        s.close()


def client_for(user):
    app.dependency_overrides[R.get_db] = _db
    app.dependency_overrides[R.get_current_user] = lambda: user
    return TestClient(app)


def attempt_on(day_offset, practice=True):
    ts = datetime.now() - timedelta(days=day_offset)
    if practice:
        db.add(P.QuizAttempt(user_id=alice.id, question_id=q.id, chosen_index=0, is_correct=True, created_at=ts))
    else:
        db.add(EM.EsslceAttempt(user_id=alice.id, question_id=eq.id, paper_id=paper.id, chosen_index=1,
                                 is_correct=True, mode="practice", created_at=ts))
    db.commit()


# ---- no attempts at all: streak is 0 -------------------------------------------------------------
c = client_for(bob)
r = c.get("/v1/progress/streak")
assert r.status_code == 200, r.text
assert r.json() == {"streak_days": 0}, r.json()

# ---- 3-day streak built from BOTH systems: today (practice) + yesterday (esslce) + 2 days ago (practice)
attempt_on(0, practice=True)
attempt_on(1, practice=False)
attempt_on(2, practice=True)
c = client_for(alice)
r = c.get("/v1/progress/streak")
assert r.json() == {"streak_days": 3}, r.json()

# ---- a gap breaks the streak: 4 days ago doesn't extend it past the 3-day run ending today --------
attempt_on(4, practice=True)
r = c.get("/v1/progress/streak")
assert r.json() == {"streak_days": 3}, r.json()

print("PROGRESS ROUTE TESTS PASSED")
