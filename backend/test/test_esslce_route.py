"""Test of the ESSLCE student-serving endpoints (/v1/esslce/*): the real route with a real (SQLite)
database. No LLM/vision call exists anywhere in this path - nothing to stub there.
Run from backend/:   python test/test_esslce_route.py"""

import base64
import datetime
import os
import sys
import tempfile
import types
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def stub(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


stub("auth")
stub("auth.dependencies", get_current_user=lambda: None)
stub("db.session", get_db=lambda: None)

# routes_esslce.py builds a textbook-store connection and (per /elaborate call) an LLM client at import/
# call time - stub both so the test suite never touches a real embedding model, Chroma DB, or Groq key.
import json


class Doc:
    def __init__(self, text, **md):
        self.page_content, self.metadata = text, md


FAKE_EXCERPT = "Neon is a noble gas found in group 18 of the periodic table."
FAKE_VECTOR_ID = "chunk-vec-1"


class FakeTextbookStore:
    def similarity_search_with_score(self, query, k, filter):
        return [(Doc(FAKE_EXCERPT, subject="mathematics", grade=9, vector_id=FAKE_VECTOR_ID), 0.1)]


llm_state = {"response": json.dumps({"explanation": None})}


class FakeLLM:
    def chat(self, messages):
        return {"choices": [{"message": {"content": llm_state["response"]}}]}


stub("config")
stub(
    "config.constants",
    TEXTBOOK_COLLECTION_NAME="textbooks",
    EXAM_COLLECTION_NAME="esslce_exams",
    CALCULATION_SUBJECTS={"mathematics", "physics", "chemistry", "scholastic_aptitude_test"},
    ESSLCE_SKILL_STRAND_SUBJECTS={"english", "scholastic_aptitude_test"},
)
stub("config.settings", settings=types.SimpleNamespace(VECTOR_DATABASE_URL="x", SUPABASE_URL="", SUPABASE_SERVICE_KEY=""))
sys.modules["config"].constants = sys.modules["config.constants"]
sys.modules["config"].settings = sys.modules["config.settings"]
stub("retriever.vectorstore", get_vector_store=lambda **kw: FakeTextbookStore())
stub("retriever.builder", RetrieverBuilder=lambda: types.SimpleNamespace(embeddings=None))
def _parse_json_object(raw):
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


stub("llm.client", LLMClient=lambda **kw: FakeLLM(), parse_json_object=_parse_json_object)

import db.models as M
import exams.models as EM  # registers esslce_* tables onto M.Base.metadata (same shared declarative Base)
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

import api.routes_esslce as R
from fastapi import FastAPI
from fastapi.testclient import TestClient

db = Session()
user = M.User(id=uuid.uuid4(), full_name="Alice")

math_paper = EM.EsslcePaper(subject="mathematics", year_ec=2018, year_gc=2026)
english_paper = EM.EsslcePaper(subject="english", year_ec=2017, year_gc=2025)
db.add_all([user, math_paper, english_paper])
db.commit()

passage = EM.EsslcePassage(
    paper_id=english_paper.id, passage_key="P1", title="A reading passage", text="Once upon a time..."
)
db.add(passage)
db.commit()

textbook = M.Textbook(grade=9, subject="chemistry", title="Chemistry Grade 9", source_file_path="x.pdf")
db.add(textbook)
db.commit()
db.add(M.Chunk(
    textbook_id=textbook.id, unit_or_chapter="Unit 4: Periodic Classification", section="Noble gases",
    page_start=56, page_end=57, text_excerpt=FAKE_EXCERPT, vector_id=FAKE_VECTOR_ID,
))
db.commit()


def mk(paper, item_no, stem, options, answer_index, review_status="approved", has_diagram=False,
       passage_id=None, explanation="because", supporting_quote=None, part=None, section=None,
       printed_page=None):
    q = EM.EsslceQuestion(
        paper_id=paper.id, item_no=item_no, stem=stem, options=options, answer_index=answer_index,
        answer_source="ai_derived" if answer_index is not None else None, explanation=explanation,
        supporting_quote=supporting_quote, review_status=review_status, has_diagram=has_diagram,
        passage_id=passage_id, part=part, section=section, printed_page=printed_page,
    )
    db.add(q)
    db.commit()
    return q


m1 = mk(math_paper, 1, "2+2=?", ["3", "4", "5", "6"], 1, explanation="\\[ 2+2=4 \\]")
m2 = mk(math_paper, 2, "3+3=?", ["5", "6", "7", "8"], 1, explanation="\\[ 3+3=6 \\]")
m_no_key = mk(math_paper, 3, "unresolved", ["a", "b", "c", "d"], None, review_status="needs_key")
m_diagram = mk(math_paper, 4, "has a diagram", ["a", "b", "c", "d"], 0, has_diagram=True)  # no printed_page/source_dir - stays ineligible, no broken reference
m_pending = mk(math_paper, 5, "pending review", ["a", "b", "c", "d"], 0, review_status="needs_review")

# a diagram question whose real source page photo genuinely exists on disk - eligible, served with it
FAKE_PAGE_DIR = Path(tempfile.mkdtemp())
FAKE_PAGE_BYTES = b"\xff\xd8\xff fake jpeg bytes for p09.jpg"
(FAKE_PAGE_DIR / "p09.jpg").write_bytes(FAKE_PAGE_BYTES)
math_paper.source_dir = str(FAKE_PAGE_DIR)
db.commit()
m_diagram_ok = mk(math_paper, 6, "has a diagram with its real photo available", ["a", "b", "c", "d"], 0,
                   has_diagram=True, printed_page=9)
e1 = mk(
    english_paper, 1, "What happened?", ["x", "y", "z", "w"], 0, passage_id=passage.id,
    explanation="The passage says so.", supporting_quote="Once upon a time",
)
e2 = mk(
    english_paper, 2, "She ___ to school.", ["go", "goes", "went", "going"], 2,
    part="II. LANGUAGE FOCUS", section="Choose the correct answer.",
)

MATH_ELIGIBLE_IDS = {m1.id, m2.id, m_diagram_ok.id}


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

# ---- 1. /subjects, /papers: only eligible questions count -----------------------------------------------------
r = c.get("/v1/esslce/subjects")
by_subject = {s["subject"]: s["questions"] for s in r.json()["subjects"]}
assert by_subject == {"mathematics": 3, "english": 2}, r.json()

r = c.get("/v1/esslce/papers", params={"subject": "mathematics"})
assert r.json()["papers"][0]["ready_for_students"] == 3, r.json()

r = c.get("/v1/esslce/papers", params={"subject": "chemistry"})
assert r.status_code == 404, r.text  # no chemistry paper at all

# ---- 2. /next without paper_id: practice pool, only eligible questions -----------------------------------------
r = c.post("/v1/esslce/next", json={"subject": "mathematics", "count": 10})
ids = {q["id"] for q in r.json()["questions"]}
assert ids == MATH_ELIGIBLE_IDS, r.json()  # m_no_key/m_diagram/m_pending never served

# ---- 3. /next WITH paper_id: ALL eligible items of that one paper, ascending item_no ----------------------------
r = c.post("/v1/esslce/next", json={"subject": "mathematics", "paper_id": math_paper.id})
items = {q["item_no"]: q for q in r.json()["questions"]}
assert list(items) == [1, 2, 6], r.json()
# the diagram item's real source page photo rides along, base64-encoded; the other two never carry one
assert items[6]["diagram_image_base64"] == base64.b64encode(FAKE_PAGE_BYTES).decode()
assert items[1]["diagram_image_base64"] is None and items[2]["diagram_image_base64"] is None

r = c.post("/v1/esslce/next", json={"subject": "english", "paper_id": english_paper.id})
q = r.json()["questions"][0]
assert q["passage_text"] == "Once upon a time..."  # reading-comprehension item carries its passage
assert q["passage_title"] == "A reading passage"

# ---- 3b. /units + /next with unit filter: pool scoped to one (grade, unit), across every year -----------------
db.add_all([
    EM.EsslceTopicLink(question_id=m1.id, rank=1, grade=11, unit="Unit 2: Algebra", verified=True),
    EM.EsslceTopicLink(question_id=m2.id, rank=1, grade=12, unit="Unit 5: Calculus", verified=True),
])
db.commit()

r = c.get("/v1/esslce/units", params={"subject": "mathematics"})
by_unit = {(u["grade"], u["unit"]): u["questions"] for u in r.json()["units"]}
assert by_unit == {(11, "Unit 2: Algebra"): 1, (12, "Unit 5: Calculus"): 1}, r.json()

r = c.post(
    "/v1/esslce/next",
    json={"subject": "mathematics", "unit": "Unit 2: Algebra", "grade": 11, "count": 10},
)
ids = {q["id"] for q in r.json()["questions"]}
assert ids == {m1.id}, r.json()  # m2 is a different unit, never pooled in

r = c.post(
    "/v1/esslce/next", json={"subject": "mathematics", "unit": "no such unit", "count": 10}
)
assert r.json()["questions"] == [], r.json()

# ---- 3b2. /diagnostic: stratified across unit/skill groups, not the mastery-ordered mixed pool -----------------
r = c.post("/v1/esslce/diagnostic", json={"subject": "mathematics", "count": 15})
ids = {q["id"] for q in r.json()["questions"]}
assert ids == {m1.id, m2.id, m_diagram_ok.id}, r.json()  # 3 distinct groups (Algebra, Calculus, uncategorized)

r = c.post("/v1/esslce/diagnostic", json={"subject": "chemistry", "count": 15})
assert r.status_code == 404, r.text  # no chemistry paper at all

# ---- 3c. /skills + /next with skill filter: English/SAT's own section structure, not a textbook topic ----------
r = c.get("/v1/esslce/skills", params={"subject": "english"})
by_skill = {s["skill"]: s["questions"] for s in r.json()["skills"]}
assert by_skill == {"Reading Comprehension": 1, "Grammar": 1}, r.json()  # e1 via passage_id, e2 via part/section

r = c.get("/v1/esslce/skills", params={"subject": "mathematics"})
assert r.json()["skills"] == [], r.json()  # mathematics isn't organized by skill strand at all

r = c.post("/v1/esslce/next", json={"subject": "english", "skill": "Grammar", "count": 10})
ids = {q["id"] for q in r.json()["questions"]}
assert ids == {e2.id}, r.json()  # e1 is Reading Comprehension, never pooled into a Grammar-scoped request

# ---- 4. /answer: a calculation-subject explanation renders an image; grounded one does not ---------------------
r = c.post("/v1/esslce/answer", json={"question_id": m1.id, "chosen_index": 1, "mode": "practice"})
b = r.json()
assert b["is_correct"] and b["correct_index"] == 1 and b["explanation_image_base64"], b

r = c.post("/v1/esslce/answer", json={"question_id": e1.id, "chosen_index": 2, "mode": "practice"})
b = r.json()
assert not b["is_correct"] and b["correct_index"] == 0 and b["explanation_image_base64"] is None
assert b["supporting_quote"] == "Once upon a time"

# a never-eligible question (missing key, has a diagram, not approved) can never be answered
for bad in (m_no_key, m_diagram, m_pending):
    r = c.post("/v1/esslce/answer", json={"question_id": bad.id, "chosen_index": 0})
    assert r.status_code == 404, (bad.item_no, r.text)

db2 = Session()
assert db2.query(EM.EsslceAttempt).count() == 2  # m1 and e1 only - the three bad ones were rejected before insert

# ---- 5. /exam-summary: reconstructed from EsslceAttempt, aggregate + per-item -----------------------------------
c.post("/v1/esslce/answer", json={"question_id": m2.id, "chosen_index": 0, "mode": "exam"})  # wrong on purpose
r = c.post("/v1/esslce/exam-summary", json={"paper_id": math_paper.id})
b = r.json()
assert b["attempted"] == 2 and b["correct"] == 1 and b["total_eligible"] == 3, b  # m1, m2, and m_diagram_ok
by_item = {row["item_no"]: row["is_correct"] for row in b["results"]}
assert by_item == {1: True, 2: False}, b

# ---- 5b. /progress: this student's own attempt history, aggregated per unit/skill, with a recommendation -------
r = c.get("/v1/esslce/progress", params={"subject": "mathematics"})
b = r.json()
assert b["attempted"] == 2 and b["correct"] == 1 and b["skills"] == []
by_unit = {u["unit"]: u for u in b["units"]}
assert by_unit["Unit 2: Algebra"]["accuracy"] == 1.0 and by_unit["Unit 5: Calculus"]["accuracy"] == 0.0  # m1 (section 3b link) correct, m2 wrong
assert b["recommendation"] is None  # only 1 distinct question attempted per unit - below MIN_ATTEMPTS_FOR_SIGNAL, never a confident guess
assert len(b["trend"]) == 7 and b["trend"][-1]["attempts"] == 2 and b["trend"][-1]["accuracy"] == 0.5  # both m1/m2 attempts just made, today

r = c.get("/v1/esslce/progress", params={"subject": "english"})
b = r.json()
assert b["attempted"] == 1 and b["correct"] == 0
assert b["skills"] == [{"skill": "Reading Comprehension", "attempted": 1, "correct": 0, "accuracy": 0.0, "level": "not enough data"}]  # e1, via its passage_id; 1 attempt < MIN_ATTEMPTS_FOR_SIGNAL
assert b["recommendation"] is None  # below MIN_ATTEMPTS_FOR_SIGNAL - never a confident guess from 1 question

r = c.get("/v1/esslce/progress", params={"subject": "history"})
b = r.json()
assert b["attempted"] == 0 and b["correct"] == 0 and b["units"] == [] and b["skills"] == [] and b["recommendation"] is None
assert b["trend"] == [{"date": d["date"], "attempts": 0, "accuracy": None} for d in b["trend"]]  # no history attempts at all

# ---- 5c. /next with incorrect_only: pool scoped to questions this student's LATEST attempt got wrong -----------
r = c.post("/v1/esslce/next", json={"subject": "mathematics", "incorrect_only": True, "count": 10})
ids = {q["id"] for q in r.json()["questions"]}
assert ids == {m2.id}, r.json()  # m1 was answered correctly, m_diagram_ok was never attempted - neither counts

r = c.post("/v1/esslce/next", json={"subject": "english", "incorrect_only": True, "count": 10})
ids = {q["id"] for q in r.json()["questions"]}
assert ids == {e1.id}, r.json()  # e1 was answered wrong; e2 was never attempted

r = c.post("/v1/esslce/next", json={"subject": "history", "incorrect_only": True, "count": 10})
assert r.json()["questions"] == [], r.json()  # no attempts at all in this subject

# ---- 6. /elaborate: grounded path, cached per-question (not re-generated on a second call) ---------------------
llm_state["response"] = json.dumps({
    "explanation": "The passage opens with 'Once upon a time', a classic storytelling opener.",
    "source_index": 0,
    "supporting_quote": "Once upon a time",  # e1 has a passage, so its OWN text is the excerpt, not FAKE_EXCERPT
})
r = c.post("/v1/esslce/elaborate", json={"question_id": e1.id})
b = r.json()
assert r.status_code == 200 and not b["is_calculation"] and b["content_image_base64"] is None
assert "storytelling" in b["content"]

llm_state["response"] = json.dumps({"explanation": None})  # if this were called again, it would fail
r2 = c.post("/v1/esslce/elaborate", json={"question_id": e1.id})
assert r2.json()["content"] == b["content"]  # served from EsslceElaboration, no new LLM call made

db3 = Session()
assert db3.query(EM.EsslceElaboration).filter(EM.EsslceElaboration.question_id == e1.id).count() == 1

# ---- 7. /elaborate: calculation path, renders an image, verified against an executed code sample ---------------
llm_state["response"] = json.dumps({
    "example_problem": "What is 2+5?",
    "latex_solution": "\\[ 2+5=7 \\]",
    "final_answer": "7",
    "verification_code": "print(2+5)",
})
r = c.post("/v1/esslce/elaborate", json={"question_id": m1.id})
b = r.json()
assert r.status_code == 200 and b["is_calculation"] and b["content_image_base64"], b

# ---- 8. /elaborate: an ungroundable response (or one that fails code verification) is rejected, not shown -------
llm_state["response"] = json.dumps({
    "example_problem": "What is 2+5?", "latex_solution": "x", "final_answer": "999",
    "verification_code": "print(2+5)",  # computes 7, claims 999 - doesn't match
})
r = c.post("/v1/esslce/elaborate", json={"question_id": m2.id})
assert r.status_code == 422, r.text

# a never-eligible question can't be elaborated on either
r = c.post("/v1/esslce/elaborate", json={"question_id": m_diagram.id})
assert r.status_code == 404, r.text

# ---- 8b. /elaborate: structured citation resolved from Chunk/Textbook - deterministic, never from the LLM -------
llm_state["response"] = json.dumps({
    "explanation": "Noble gases, like neon, have a full outer electron shell.",
    "source_index": 0,
    "supporting_quote": "Neon is a noble gas",
})
r = c.post("/v1/esslce/elaborate", json={"question_id": e2.id})
b = r.json()
assert r.status_code == 200 and b["citation"] == {
    "textbook": "Chemistry Grade 9", "grade": 9, "subject": "chemistry",
    "unit_or_chapter": "Unit 4: Periodic Classification", "section": "Noble gases",
    "page_start": 56, "page_end": 57,
}, b

# a passage-grounded question has no textbook citation at all - it's grounded in the exam's own passage
r = c.post("/v1/esslce/elaborate", json={"question_id": e1.id})
assert r.json()["citation"] is None

# ---- 8c. /ask: free-form follow-up, grounded by the question + its (auto-created) elaboration -------------------
llm_state["response"] = "Sure - a noble gas like neon has a full outer shell, so it rarely reacts with anything."
r = c.post(
    "/v1/esslce/ask",
    json={"question_id": e2.id, "message": "why is it a noble gas?", "history": []},
)
assert r.status_code == 200 and "noble gas" in r.json()["reply"], r.text

r = c.post("/v1/esslce/ask", json={"question_id": m_diagram.id, "message": "hi", "history": []})
assert r.status_code == 404, r.text  # never-eligible question, same gate as /elaborate

# ---- 9. /mistakes: latest-wrong-per-question only, newest first, ineligible questions never resurface ----------
c.post("/v1/esslce/answer", json={"question_id": m_diagram_ok.id, "chosen_index": 1, "mode": "practice"})  # wrong (key is 0)
# backdate m2's wrong attempt (made in section 5 above) relative to utcnow() - SQLite's CURRENT_TIMESTAMP
# (what the API's own inserts use) is UTC, not local time, and only second-precision, so attempts made in
# the same test tick need forcing apart to get a real, deterministic newest-first order.
db.query(EM.EsslceAttempt).filter(EM.EsslceAttempt.question_id == m2.id).update(
    {EM.EsslceAttempt.created_at: datetime.datetime.utcnow() - datetime.timedelta(seconds=100)}
)
db.commit()
r = c.get("/v1/esslce/mistakes", params={"subject": "mathematics"})
b = r.json()
assert [m["question_id"] for m in b] == [m_diagram_ok.id, m2.id], b  # newest wrong first
assert b[0]["chosen_index"] == 1 and b[0]["correct_index"] == 0 and b[0]["unit"] is None  # no topic link for m_diagram_ok
assert b[1]["chosen_index"] == 0 and b[1]["correct_index"] == 1 and b[1]["unit"] == "Unit 5: Calculus"
assert b[1]["explanation_image_base64"], b[1]  # mathematics is a calculation subject - m2's LaTeX explanation renders
r = c.get("/v1/esslce/mistakes", params={"subject": "english"})
b = r.json()
assert [m["question_id"] for m in b] == [e1.id] and b[0]["skill"] == "Reading Comprehension" and b[0]["unit"] is None, b
assert b[0]["explanation_image_base64"] is None  # english is not a calculation subject - plain text only
assert b[0]["passage_text"] == "Once upon a time...", b  # a Reading Comprehension mistake must carry its passage too, not just /next
assert b[0]["passage_title"] == "A reading passage"
r = c.get("/v1/esslce/mistakes", params={"subject": "mathematics"})
assert all(m["passage_text"] is None for m in r.json())  # no passage for these - must not be given one from somewhere else
# re-answering correctly retires a mistake (latest attempt wins), same as /progress and /next
c.post("/v1/esslce/answer", json={"question_id": m2.id, "chosen_index": 1, "mode": "practice"})
r = c.get("/v1/esslce/mistakes", params={"subject": "mathematics"})
assert [m["question_id"] for m in r.json()] == [m_diagram_ok.id], r.json()

print("ESSLCE ROUTE TESTS PASSED")
