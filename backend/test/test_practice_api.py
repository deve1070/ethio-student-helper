"""Integration test: the real routes + real SQLAlchemy queries on an in-memory SQLite database."""
import sys, types, uuid, datetime
sys.path.insert(0, ".")

# --- stub only what needs secrets / a live Postgres: auth dependency and db.session
auth_pkg = types.ModuleType("auth"); auth_dep = types.ModuleType("auth.dependencies")
def get_current_user(): raise RuntimeError("overridden in test")
auth_dep.get_current_user = get_current_user
sys.modules["auth"] = auth_pkg; sys.modules["auth.dependencies"] = auth_dep
dbs = types.ModuleType("db.session")
def get_db(): raise RuntimeError("overridden in test")
dbs.get_db = get_db; sys.modules["db.session"] = dbs

from sqlalchemy import create_engine, JSON
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import db.models as M
import db.models_practice as P

# SQLite (used only by this test) cannot store Postgres JSONB/ARRAY columns, and older SQLAlchemy
# versions cannot even compile them. Store those columns as JSON for the test; production uses Postgres.
from sqlalchemy import ARRAY
from sqlalchemy.dialects.postgresql import JSONB
for _table in M.Base.metadata.tables.values():
    for _col in _table.columns:
        if isinstance(_col.type, (JSONB, ARRAY)):
            _col.type = JSON()
engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
M.Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autoflush=False)

from fastapi import FastAPI
from fastapi.testclient import TestClient
import api.routes_practice as R

app = FastAPI(); app.include_router(R.router)
db = Session()
alice = M.User(id=uuid.uuid4(), full_name="Alice"); bob = M.User(id=uuid.uuid4(), full_name="Bob")
book = M.Textbook(id=uuid.uuid4(), grade=9, subject="chemistry", title="Chemistry Grade 9")
db.add_all([alice, bob, book]); db.commit()

def add_q(unit, text, key=1, diff="medium", status="active", p0=10, p1=11):
    q = P.QuizQuestion(textbook_id=book.id, grade=9, subject="chemistry", unit_or_chapter=unit, section="s",
                       page_start=p0, page_end=p1, question=text, options=["a","b","c","d"], answer_index=key,
                       explanation="because " + text, supporting_quote="quote " + text, difficulty=diff,
                       status=status, source_vector_ids=["v"], content_hash=uuid.uuid4().hex)
    db.add(q); db.commit(); return q
u1 = [add_q("Unit 1: Chemistry and its Importance", f"Q1-{i}") for i in range(3)]
u10 = [add_q("Unit 10: Later Topic", f"Q10-{i}", diff="hard") for i in range(2)]
u4 = [add_q("Unit 4: Periodic Classification of Elements", f"Q4-{i}", key=2) for i in range(6)]
hidden = add_q("Unit 4: Periodic Classification of Elements", "HIDDEN", status="needs_review")
retired = add_q("Unit 1: Chemistry and its Importance", "RETIRED", status="retired")

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
c = client_for(alice)

# ---- /next: only active questions, no answers leaked, respects count/unit/difficulty
r = c.post("/v1/practice/next", json={"grade": 9, "subject": "chemistry", "count": 20}); assert r.status_code == 200, r.text
qs = r.json()["questions"]; assert len(qs) == 11, len(qs)                      # 3 + 2 + 6, not hidden/retired
texts = {q["question"] for q in qs}; assert "HIDDEN" not in texts and "RETIRED" not in texts
assert all(set(q) == {"id","question","options","unit","difficulty"} for q in qs)   # no answer/explanation/quote
r = c.post("/v1/practice/next", json={"grade": 9, "subject": "Chemistry", "unit": "unit 4", "count": 3}); assert len(r.json()["questions"]) == 3
r = c.post("/v1/practice/next", json={"grade": 9, "subject": "chemistry", "difficulty": "hard"}); assert {q["difficulty"] for q in r.json()["questions"]} == {"hard"}
# ---- subject typo -> 400 with a suggestion; unknown grade has no subjects
r = c.post("/v1/practice/next", json={"grade": 9, "subject": "chemisty"}); assert r.status_code == 400 and "Did you mean 'chemistry'" in r.json()["detail"]
r = c.post("/v1/practice/next", json={"grade": 10, "subject": "chemistry"}); assert r.status_code == 400 and "none yet" in r.json()["detail"]
r = c.post("/v1/practice/next", json={"grade": 9, "subject": "chemistry", "unit": "unit 7"}); assert r.json() == {"questions": []}

# ---- /answer: correct and wrong, explanation + page citation, counters updated, validation
q4 = u4[0]
r = c.post("/v1/practice/answer", json={"question_id": str(q4.id), "chosen_index": 2}); body = r.json()
assert r.status_code == 200 and body["is_correct"] is True and body["correct_index"] == 2
assert body["citation"] == {"textbook": "Chemistry Grade 9", "unit": "Unit 4: Periodic Classification of Elements", "page": "10-11"}, body
assert body["explanation"].startswith("because") and body["supporting_quote"].startswith("quote")
r = c.post("/v1/practice/answer", json={"question_id": str(u4[1].id), "chosen_index": 0}); assert r.json()["is_correct"] is False
assert c.post("/v1/practice/answer", json={"question_id": str(hidden.id), "chosen_index": 0}).status_code == 404       # not active
assert c.post("/v1/practice/answer", json={"question_id": str(uuid.uuid4()), "chosen_index": 0}).status_code == 404
assert c.post("/v1/practice/answer", json={"question_id": str(q4.id), "chosen_index": 4}).status_code == 422             # out of range
db.expire_all(); assert db.get(P.QuizQuestion, q4.id).times_answered == 1 and db.get(P.QuizQuestion, q4.id).times_correct == 1
assert db.get(P.QuizQuestion, u4[1].id).times_correct == 0

# ---- /next now puts the question Alice got WRONG before the ones she got right, unseen first
r = c.post("/v1/practice/next", json={"grade": 9, "subject": "chemistry", "unit": "unit 4", "count": 6}); order = [q["question"] for q in r.json()["questions"]]
assert order[:4] and "Q4-0" == order[-1] and order[4] == "Q4-1", order     # 4 unseen, then wrong (Q4-1), then right (Q4-0)

# ---- progress needs >=5 attempts per unit before calling a unit weak: Alice answers unit 4 wrongly 5 more times
for q in u4[2:6]: c.post("/v1/practice/answer", json={"question_id": str(q.id), "chosen_index": 0})       # 4 wrong (total 1 right, 5 wrong = 6 attempts)
c.post("/v1/practice/answer", json={"question_id": str(u1[0].id), "chosen_index": 1})                      # unit 1: 1 right
p = c.get("/v1/practice/progress", params={"grade": 9, "subject": "chemistry"}).json()
by = {u["unit"]: u for u in p["units"]}
assert by["Unit 4: Periodic Classification of Elements"]["attempts"] == 6 and by["Unit 4: Periodic Classification of Elements"]["level"] == "weak"
assert by["Unit 1: Chemistry and its Importance"]["level"] == "not enough data"
assert p["weakest_units"] == ["Unit 4: Periodic Classification of Elements"] and p["attempts"] == 7 and p["accuracy"] == round(2/7, 2), p
# ---- /units: every unit with counts, natural order (Unit 10 after Unit 4), my progress merged
u = c.get("/v1/practice/units", params={"grade": 9, "subject": "chem"}).json()          # alias 'chem'
names = [x["unit"] for x in u["units"]]
assert names == ["Unit 1: Chemistry and its Importance", "Unit 4: Periodic Classification of Elements", "Unit 10: Later Topic"], names
assert {x["unit"]: x["questions"] for x in u["units"]}["Unit 4: Periodic Classification of Elements"] == 6    # hidden one not counted
# ---- a different student sees none of Alice's history
c2 = client_for(bob)
assert c2.get("/v1/practice/progress", params={"grade": 9, "subject": "chemistry"}).json()["attempts"] == 0
r = c2.post("/v1/practice/next", json={"grade": 9, "subject": "chemistry", "unit": "unit 4", "count": 6}); assert len(r.json()["questions"]) == 6
# ---- /mistakes: latest-wrong-per-question only, newest first, no leaked answer key for the right one
bob_qs = r.json()["questions"]
c2.post("/v1/practice/answer", json={"question_id": bob_qs[0]["id"], "chosen_index": 0})      # wrong (key is 2)
c2.post("/v1/practice/answer", json={"question_id": bob_qs[1]["id"], "chosen_index": 2})       # right - never a mistake
c2.post("/v1/practice/answer", json={"question_id": bob_qs[2]["id"], "chosen_index": 1})       # wrong, answered most recently
# SQLite's CURRENT_TIMESTAMP (what the API's own inserts use) is UTC and only second-precision, so
# attempts made in the same test tick can tie - force a real, distinct order (backdated relative to
# utcnow(), matching the DB's own clock, not local time, and with headroom below "now" for the
# re-answer made further down):
for qid, seconds_ago in ((bob_qs[0]["id"], 300), (bob_qs[1]["id"], 200), (bob_qs[2]["id"], 100)):
    db.query(P.QuizAttempt).filter(
        P.QuizAttempt.user_id == bob.id, P.QuizAttempt.question_id == uuid.UUID(qid)
    ).update({P.QuizAttempt.created_at: datetime.datetime.utcnow() - datetime.timedelta(seconds=seconds_ago)})
db.commit()
mist = c2.get("/v1/practice/mistakes", params={"grade": 9, "subject": "chemistry"}).json()
assert [m["question_id"] for m in mist] == [bob_qs[2]["id"], bob_qs[0]["id"]], mist             # newest wrong first
assert mist[0]["chosen_index"] == 1 and mist[0]["correct_index"] == 2 and mist[0]["unit"] == "Unit 4: Periodic Classification of Elements"
# re-answering the first mistake correctly retires it from the list (latest attempt wins)
c2.post("/v1/practice/answer", json={"question_id": bob_qs[2]["id"], "chosen_index": 2})
mist = c2.get("/v1/practice/mistakes", params={"grade": 9, "subject": "chemistry"}).json()
assert [m["question_id"] for m in mist] == [bob_qs[0]["id"]], mist

# ---- review tool: approve / reject / fix a wrong key / skip / quit, and only approved questions reach students
import importlib.util
_spec = importlib.util.spec_from_file_location("rq", "scripts/review_questions.py")
rq = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(rq)
rev = [add_q("Unit 9: Review Unit", f"R{i} question text here", key=1, status="needs_review") for i in range(1, 6)]
rows = db.query(P.QuizQuestion).filter(P.QuizQuestion.unit_or_chapter == "Unit 9: Review Unit").order_by(P.QuizQuestion.question).all()
assert rq.LETTERS.count("") == 0 and "" not in rq.LETTERS        # an empty answer must never count as 'A'
answers = iter(["x", "a",          # invalid key, then approve R1
                "r",               # reject R2
                "k", "", "Z", "C", # R3: wrong key -> empty and invalid letters are refused, then C
                "s",               # skip R4
                "q"])              # quit before R5
shown = []
counts = rq.review_loop(db, rows, ask=lambda prompt: next(answers), out=shown.append)
assert counts == {"approved": 1, "rejected": 1, "fixed": 1, "skipped": 1}, counts
db.expire_all()
st = {q.question[:2]: (q.status, q.answer_index) for q in db.query(P.QuizQuestion).filter(P.QuizQuestion.unit_or_chapter == "Unit 9: Review Unit")}
assert st == {"R1": ("active", 1), "R2": ("retired", 1), "R3": ("active", 2), "R4": ("needs_review", 1), "R5": ("needs_review", 1)}, st
assert any("<== marked correct" in line for line in shown) and any('Book: "quote R1' in line for line in shown)
c = client_for(alice)
got = {x["question"][:2] for x in c.post("/v1/practice/next", json={"grade": 9, "subject": "chemistry", "unit": "unit 9", "count": 20}).json()["questions"]}
assert got == {"R1", "R3"}, got                                   # approved + fixed only; retired/skipped/unreviewed are hidden

# ---- /subjects, the multi-unit filter and /report (used by the Telegram flow)
c = client_for(alice)
subj = c.get("/v1/practice/subjects", params={"grade": 9}).json()
assert subj["subjects"] == [{"subject": "chemistry", "questions": db.query(P.QuizQuestion).filter(P.QuizQuestion.status == "active").count()}], subj
assert c.get("/v1/practice/subjects", params={"grade": 12}).json()["subjects"] == []
only = c.post("/v1/practice/next", json={"grade": 9, "subject": "chemistry", "units": ["Unit 1: Chemistry and its Importance", "Unit 10: Later Topic"], "count": 20}).json()["questions"]
assert {q["unit"] for q in only} == {"Unit 1: Chemistry and its Importance", "Unit 10: Later Topic"} and len(only) == 5, [q["unit"] for q in only]
victim = only[0]
r = c.post("/v1/practice/report", json={"question_id": victim["id"], "reason": "the marked answer looks wrong"}); assert r.status_code == 200 and r.json() == {"ok": True}
db.expire_all()
assert db.get(P.QuizQuestion, uuid.UUID(victim["id"])).status == "needs_review"                   # pulled out of circulation at once
assert db.query(P.QuizReport).filter(P.QuizReport.question_id == uuid.UUID(victim["id"])).one().reason == "the marked answer looks wrong"
again = c.post("/v1/practice/next", json={"grade": 9, "subject": "chemistry", "units": ["Unit 1: Chemistry and its Importance", "Unit 10: Later Topic"], "count": 20}).json()["questions"]
assert victim["id"] not in {q["id"] for q in again} and len(again) == 4
assert c.post("/v1/practice/answer", json={"question_id": victim["id"], "chosen_index": 0}).status_code == 404   # hidden questions cannot be answered
assert c.post("/v1/practice/report", json={"question_id": str(uuid.uuid4())}).status_code == 404
assert c.post("/v1/practice/report", json={"question_id": victim["id"]}).status_code == 200                 # reporting twice is harmless

# ---- question health: flagged selection, reviewing flagged questions, and re-scoring when a key is fixed
from practice import health
def set_stats(q, answered, correct):
    q.times_answered, q.times_correct = answered, correct; db.commit(); return q
qa = set_stats(add_q("Unit 8: Health", "QA low accuracy question text", key=1), 12, 2)        # students keep choosing another option
qb = set_stats(add_q("Unit 8: Health", "QB fine question text", key=1), 12, 10)
qc = set_stats(add_q("Unit 8: Health", "QC few answers question text", key=1), 5, 0)
qd = add_q("Unit 8: Health", "QD reported question text", key=1, status="needs_review")
qe = add_q("Unit 8: Health", "QE brand new question text", key=1, status="needs_review")
for reason in ("the marked answer looks wrong", None):
    db.add(P.QuizReport(question_id=qd.id, user_id=alice.id, reason=reason))
for i in range(12):                                                   # 10 of 12 students chose C (index 2); the key said B (index 1)
    db.add(P.QuizAttempt(user_id=alice.id, question_id=qa.id, chosen_index=2 if i < 10 else 1, is_correct=(i >= 10)))
db.commit()
flagged = health.find_flagged(db, 9, "chemistry", "Unit 8")
assert [q.question[:2] for q, _ in flagged] == ["QD", "QA"], [q.question[:2] for q, _ in flagged]            # reported first, then low accuracy
assert flagged[0][1] == ["reported by 2 student(s): the marked answer looks wrong"] and "only 17% correct after 12 answers" in flagged[1][1][0]
assert health.find_flagged(db, 9, "chemistry", "Unit 8", min_answers=13) == [flagged[0]] or [q.question[:2] for q, _ in health.find_flagged(db, 9, "chemistry", "Unit 8", min_answers=13)] == ["QD"]
rows, flags, waiting = rq.select_questions(db, 9, "chemistry", "Unit 8", flagged_only=False)
assert {q.question[:2] for q in rows} == {"QD", "QE"} and waiting == 2 and flags[qd.id] == ["reported by 2 student(s): the marked answer looks wrong"] and qe.id not in flags
rows, flags, waiting = rq.select_questions(db, 9, "chemistry", "Unit 8", flagged_only=True)
assert [q.question[:2] for q in rows] == ["QD", "QA"] and waiting == 2
shown = []
answers = iter(["k", "C",     # QD is shown first: its key is wrong too, fix it -> C
                "k", "C"])    # QA: the students were right, the key is wrong -> C
qd_attempts = [P.QuizAttempt(user_id=alice.id, question_id=qd.id, chosen_index=2, is_correct=False)]; db.add_all(qd_attempts); db.commit()
counts = rq.review_loop(db, rows, ask=lambda p: next(answers), out=shown.append, flags=flags)
assert counts == {"approved": 0, "rejected": 0, "fixed": 2, "skipped": 0}, counts
text = "\n".join(shown)
assert "!! reported by 2 student(s)" in text and "Students: answered 12 times, 17% correct" in text and "re-scored 12 earlier student answer(s)" in text and "re-scored 1 earlier" in text
db.expire_all()
assert (qa.answer_index, qa.status, qa.times_answered, qa.times_correct) == (2, "active", 12, 10)         # 10 of 12 re-scored as correct
assert (qd.answer_index, qd.status, qd.times_answered, qd.times_correct) == (2, "active", 1, 1)
assert health.find_flagged(db, 9, "chemistry", "Unit 8") == []                                          # nothing flagged any more
c = client_for(alice); prog = c.get("/v1/practice/progress", params={"grade": 9, "subject": "chemistry"}).json()
u8 = {u["unit"]: u for u in prog["units"]}["Unit 8: Health"]
assert (u8["attempts"], u8["correct"]) == (13, 11), u8                                                    # the student's own accuracy was repaired too
# approving a flagged-but-correct question keeps it live and clears its statistics, so it is not flagged again
qf = set_stats(add_q("Unit 8: Health", "QF hard but correct question", key=0), 14, 1)
rows, flags, _ = rq.select_questions(db, 9, "chemistry", "Unit 8", flagged_only=True); assert [q.question[:2] for q in rows] == ["QF"]
rq.review_loop(db, rows, ask=lambda p: "a", out=lambda *a: None, flags=flags); db.expire_all()
assert (qf.status, qf.times_answered, qf.times_correct) == ("active", 0, 0) and health.find_flagged(db, 9, "chemistry", "Unit 8") == []
print("PRACTICE API INTEGRATION TEST PASSED (routes + SQL on SQLite)")