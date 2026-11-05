"""Test of the multi-day Study Plan feature: the pure build_week_plan allocator, the real
studyplan/profile.py aggregation against a real (SQLite) database, and the real route (with the one LLM
call - studyplan/coach.add_rationale - stubbed, same convention test_notes.py uses for its own LLM
calls: stub what must be stubbed, test everything else for real).
Run from backend/:   python test/test_study_plan.py"""
import datetime
import json
import sys
import types
import uuid

sys.path.insert(0, ".")

from studyplan.planner import build_week_plan

# ---- 1. build_week_plan: pure allocator -----------------------------------------------------------
def _profile(days_remaining=None, daily_goal_minutes=60, subjects=None, test_weight=None):
    return {
        "required_subjects": ["chemistry"],
        "missing_subjects": [],
        "days_remaining": days_remaining,
        "daily_goal_minutes": daily_goal_minutes,
        "subjects": subjects or [{
            "subject": "chemistry", "coverage_ratio": 1.0,
            "uncovered_units": [], "weak_esslce": [], "weak_practice": [],
        }],
        "test_weight": test_weight or {},
    }


# nothing weak or uncovered -> every day is just the flexible "ask" task
p = build_week_plan(_profile())
assert p["horizon_days"] == 7 and p["realistic"] is True and p["shortfall_minutes"] == 0
assert all(day == [{"kind": "ask", "label": "Ask a question about anything you're stuck on",
                     "subject": None, "unit": None, "skill": None, "minutes": None, "done": False}]
           for day in p["days"]), p["days"]

# one weak practice unit + one uncovered unit -> both land on day 1, nothing left for day 2+
p = build_week_plan(_profile(subjects=[{
    "subject": "chemistry", "coverage_ratio": 0.5,
    "uncovered_units": [{"grade": 12, "unit": "Unit 5: Thermodynamics"}],
    "weak_esslce": [],
    "weak_practice": [{"unit": "Unit 4: Periodic Classification of Elements", "accuracy": 0.2}],
}]))
day0 = p["days"][0]
assert len(day0) == 3, day0  # weak practice + uncovered "notes" task + always-present "ask"
assert {t["kind"] for t in day0} == {"practice", "notes", "ask"}, day0
assert [t["minutes"] for t in day0 if t["kind"] != "ask"] == [30, 30], day0  # 60 min / 2 required tasks
assert p["days"][1] == [{"kind": "ask", "label": "Ask a question about anything you're stuck on",
                          "subject": None, "unit": None, "skill": None, "minutes": None, "done": False}]

# days_remaining clamps the horizon: capped at 14, floored at 1, otherwise used as-is
assert build_week_plan(_profile(days_remaining=100))["horizon_days"] == 14
assert build_week_plan(_profile(days_remaining=3))["horizon_days"] == 3
assert build_week_plan(_profile(days_remaining=0))["horizon_days"] == 1

# more weak/uncovered items than the horizon can realistically fit -> explicit, honest shortfall flag
busy_subject = {
    "subject": "chemistry", "coverage_ratio": 0.0,
    "uncovered_units": [{"grade": 12, "unit": f"Unit {i}"} for i in range(10)],
    "weak_esslce": [], "weak_practice": [],
}
p = build_week_plan(_profile(days_remaining=2, daily_goal_minutes=15, subjects=[busy_subject]))
assert p["realistic"] is False and p["shortfall_minutes"] == 150 - 30, p  # 10*15 needed vs 2*15 available

print("STUDY PLAN PURE-FUNCTION TESTS PASSED")

# ---- 2. studyplan/profile.py against a real (SQLite) database --------------------------------------
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
import db.models_studyplan as SP  # noqa: F401 - registers study_plan_weeks onto the shared Base
import exams.models as EM
import notes.models as NM

for t in M.Base.metadata.tables.values():
    for c in t.columns:
        if isinstance(c.type, (JSONB, ARRAY)):
            c.type = JSON()
engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
M.Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autoflush=False)
db = Session()

from notes.store import record_note_view
from studyplan.profile import build_profile

alice = M.User(
    id=uuid.uuid4(), full_name="Alice", grade_level=12, stream="natural_science",
    subjects_selected=["chemistry"], daily_goal_minutes=30,
    exam_date=datetime.date.today() + datetime.timedelta(days=10),
)
bob = M.User(id=uuid.uuid4(), full_name="Bob", grade_level=12, subjects_selected=["chemistry"], daily_goal_minutes=45)
db.add_all([alice, bob])
db.commit()

book = M.Textbook(id=uuid.uuid4(), grade=12, subject="chemistry", title="Chemistry Grade 12")
db.add(book)
db.commit()
db.add_all([
    M.Chunk(id=uuid.uuid4(), textbook_id=book.id, unit_or_chapter="Unit 4: Periodic Classification of Elements", vector_id="v1"),
    M.Chunk(id=uuid.uuid4(), textbook_id=book.id, unit_or_chapter="Unit 5: Thermodynamics", vector_id="v2"),
])
db.commit()


def add_quiz_q(unit, text, key=1):
    q = P.QuizQuestion(
        textbook_id=book.id, grade=12, subject="chemistry", unit_or_chapter=unit, question=text,
        options=["a", "b", "c", "d"], answer_index=key, explanation="because " + text,
        supporting_quote="quote " + text, source_vector_ids=["v"], content_hash=uuid.uuid4().hex,
    )
    db.add(q)
    db.commit()
    return q


weak_qs = [add_quiz_q("Unit 4: Periodic Classification of Elements", f"Q4-{i}", key=2) for i in range(6)]
for i, q in enumerate(weak_qs):
    db.add(P.QuizAttempt(user_id=alice.id, question_id=q.id, chosen_index=0, is_correct=(i == 0)))  # 1/6 right
db.commit()

esslce_paper = EM.EsslcePaper(subject="chemistry", year_ec=2016)
db.add(esslce_paper)
db.commit()
esslce_q = EM.EsslceQuestion(paper_id=esslce_paper.id, item_no=1, stem="?", options=["A", "B", "C", "D"], answer_index=0, review_status="approved")
db.add(esslce_q)
db.commit()
db.add(EM.EsslceTopicLink(question_id=esslce_q.id, rank=1, score=0.1, grade=12, unit="Unit 5: Thermodynamics", verified=True))
db.commit()

profile = build_profile(db, alice)
assert profile["required_subjects"] == ["chemistry"]
assert set(profile["missing_subjects"]) == {"biology", "english", "mathematics", "physics", "scholastic_aptitude_test"}, profile["missing_subjects"]
assert profile["days_remaining"] == 10, profile["days_remaining"]
chem = profile["subjects"][0]
assert any(w["unit"] == "Unit 4: Periodic Classification of Elements" for w in chem["weak_practice"]), chem
assert any(u["unit"] == "Unit 5: Thermodynamics" for u in chem["uncovered_units"]), chem  # never opened yet
assert profile["test_weight"]["chemistry"]["Unit 5: Thermodynamics"] == 1, profile["test_weight"]

# opening the Study Note for the uncovered unit should move it out of "uncovered" on the next build
record_note_view(db, alice.id, 12, "chemistry", "Unit 5: Thermodynamics")
profile2 = build_profile(db, alice)
chem2 = profile2["subjects"][0]
assert not any(u["unit"] == "Unit 5: Thermodynamics" for u in chem2["uncovered_units"]), chem2

# a student with no exam_date set gets a profile with no countdown, not a crash
bob_profile = build_profile(db, bob)
assert bob_profile["days_remaining"] is None, bob_profile

print("STUDY PLAN PROFILE TESTS PASSED")

# ---- 3. the real route, with the one LLM call (studyplan/coach.py) stubbed -------------------------
class FakeCoachLLM:
    """Mirrors llm.client.LLMClient's .chat() contract - no network call, no API key needed. Returns a
    generic, ungrounded rationale on purpose, to also confirm add_rationale's own grounding check (never
    trust LLM wording blindly) quietly drops it rather than crashing."""

    def chat(self, messages):
        content = json.dumps({"day_rationales": ["Keep going!"] * 10, "weekly_note": "You're making progress - stay consistent."})
        return {"choices": [{"message": {"content": content}}]}


import api.routes_studyplan as R
from fastapi import FastAPI
from fastapi.testclient import TestClient

R.LLMClient = lambda **kwargs: FakeCoachLLM()  # test seam: avoid constructing a real ChatGroq client

app = FastAPI()
app.include_router(R.router)


def _db():
    s = Session()
    try:
        yield s
    finally:
        s.close()


app.dependency_overrides[R.get_db] = _db
app.dependency_overrides[R.get_current_user] = lambda: alice
c = TestClient(app)

r = c.get("/v1/study-plan/week")
assert r.status_code == 200, r.text
b = r.json()
assert b["days_remaining"] == 10 and len(b["days"]) == 10, b  # horizon == days_remaining (< 14)
assert any(
    t["kind"] == "practice" and t["unit"] == "Unit 4: Periodic Classification of Elements"
    for t in b["days"][0]["tasks"]
), b
assert any(t["kind"] == "ask" for t in b["days"][0]["tasks"]), b

# stability: a second request within the same week returns the SAME plan, even after the weak-area
# signal would otherwise have changed
more_qs = [add_quiz_q("Unit 4: Periodic Classification of Elements", f"Q4-extra-{i}", key=2) for i in range(10)]
for q in more_qs:
    db.add(P.QuizAttempt(user_id=alice.id, question_id=q.id, chosen_index=2, is_correct=True))
db.commit()

r2 = c.get("/v1/study-plan/week")
assert r2.json() == b, (r2.json(), b)

# marking a task done persists and is reflected on the next GET
r = c.post("/v1/study-plan/week/days/0/tasks/0/done")
assert r.status_code == 200 and r.json()["days"][0]["tasks"][0]["done"] is True, r.text
r = c.get("/v1/study-plan/week")
assert r.json()["days"][0]["tasks"][0]["done"] is True, r.json()

r = c.post("/v1/study-plan/week/days/0/tasks/0/done", params={"done": "false"})
assert r.json()["days"][0]["tasks"][0]["done"] is False, r.json()

r = c.post("/v1/study-plan/week/days/99/tasks/0/done")
assert r.status_code == 404, r.text
r = c.post("/v1/study-plan/week/days/0/tasks/99/done")
assert r.status_code == 404, r.text

print("STUDY PLAN ROUTE TESTS PASSED")
