"""Test of the Today's Study Plan feature: the pure build_plan allocator, plus the real route with a
real (SQLite) database. No LLM/vision call exists anywhere in this path - nothing to stub.
Run from backend/:   python test/test_study_plan.py"""
import sys
import types
import uuid

sys.path.insert(0, ".")

from studyplan.plan import TaskCandidate, build_plan

# ---- 1. build_plan: pure allocator - drops low-priority tasks first, "ask" always last/flexible --------
practice = TaskCandidate(kind="practice", label="Practice Unit 4", subject="chemistry", unit="Unit 4")
esslce = TaskCandidate(kind="esslce", label="ESSLCE chemistry", subject="chemistry")
mistakes = TaskCandidate(kind="mistakes", label="Review mistakes", subject="chemistry")
ask = TaskCandidate(kind="ask", label="Ask a question")

plan = build_plan(60, [practice, esslce, mistakes, ask])
assert [t["kind"] for t in plan] == ["practice", "esslce", "mistakes", "ask"]
assert all(t["minutes"] == 20 for t in plan[:3]) and plan[3]["minutes"] is None and plan[3]["done"] is False

plan = build_plan(30, [practice, esslce, mistakes, ask])  # only room for 2 required tasks at >=15 min each
assert [t["kind"] for t in plan] == ["practice", "esslce", "ask"], plan  # mistakes (lowest priority) dropped

plan = build_plan(10, [practice, esslce, ask])  # too small for even one 15-min task - still gives the top one everything
assert [t["kind"] for t in plan] == ["practice", "ask"] and plan[0]["minutes"] == 10, plan

plan = build_plan(100, [practice, esslce, mistakes])  # remainder minutes land on the last required task
assert [t["minutes"] for t in plan] == [33, 33, 34], plan

assert build_plan(60, [ask]) == [{"kind": "ask", "label": "Ask a question", "subject": None, "unit": None, "skill": None, "minutes": None, "done": False}]

print("STUDY PLAN PURE-FUNCTION TESTS PASSED")

# ---- 2. the real route + real SQL on SQLite -----------------------------------------------------------
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
import db.models_studyplan as SP
import exams.models as EM  # registers esslce_* tables onto the same shared Base

for t in M.Base.metadata.tables.values():
    for c in t.columns:
        if isinstance(c.type, (JSONB, ARRAY)):
            c.type = JSON()
engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
M.Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autoflush=False)

import api.routes_studyplan as R
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(R.router)

db = Session()
alice = M.User(id=uuid.uuid4(), full_name="Alice", grade_level=9, subjects_selected=["chemistry"], daily_goal_minutes=30)
db.add(alice)
db.commit()

book = M.Textbook(id=uuid.uuid4(), grade=9, subject="chemistry", title="Chemistry Grade 9")
db.add(book)
db.commit()


def add_q(unit, text, key=1):
    q = P.QuizQuestion(
        textbook_id=book.id, grade=9, subject="chemistry", unit_or_chapter=unit, question=text,
        options=["a", "b", "c", "d"], answer_index=key, explanation="because " + text,
        supporting_quote="quote " + text, source_vector_ids=["v"], content_hash=uuid.uuid4().hex,
    )
    db.add(q)
    db.commit()
    return q


weak_qs = [add_q("Unit 4: Periodic Classification of Elements", f"Q4-{i}", key=2) for i in range(6)]
for i, q in enumerate(weak_qs):
    db.add(P.QuizAttempt(user_id=alice.id, question_id=q.id, chosen_index=0, is_correct=(i == 0)))  # 1/6 right - weak
db.commit()


def _db():
    s = Session()
    try:
        yield s
    finally:
        s.close()


app.dependency_overrides[R.get_db] = _db
app.dependency_overrides[R.get_current_user] = lambda: alice
c = TestClient(app)

r = c.get("/v1/study-plan/today")
assert r.status_code == 200, r.text
b = r.json()
assert any(t["kind"] == "practice" and t["unit"] == "Unit 4: Periodic Classification of Elements" for t in b["tasks"]), b
assert any(t["kind"] == "ask" for t in b["tasks"]), b  # always present, always last/flexible

# ---- stability: a second request on the same day returns the SAME tasks, even after the weak-area
# signal would otherwise have changed (alice now gets everything right on that unit) -------------------
more_qs = [add_q("Unit 4: Periodic Classification of Elements", f"Q4-extra-{i}", key=2) for i in range(10)]
for q in more_qs:
    db.add(P.QuizAttempt(user_id=alice.id, question_id=q.id, chosen_index=2, is_correct=True))
db.commit()

r2 = c.get("/v1/study-plan/today")
assert r2.json() == b, (r2.json(), b)  # identical - generated once, served as-is for the rest of the day

# ---- marking a task done persists and is reflected on the next GET -------------------------------------
r = c.post("/v1/study-plan/today/tasks/0/done")
assert r.status_code == 200 and r.json()["tasks"][0]["done"] is True, r.text
r = c.get("/v1/study-plan/today")
assert r.json()["tasks"][0]["done"] is True, r.json()

r = c.post("/v1/study-plan/today/tasks/0/done", params={"done": "false"})
assert r.json()["tasks"][0]["done"] is False, r.json()

r = c.post("/v1/study-plan/today/tasks/99/done")
assert r.status_code == 404, r.text

print("STUDY PLAN ROUTE TESTS PASSED")
