"""Test of the Study Notes feature (/v1/notes/*): the real route with a real (SQLite) database, a
stand-in textbook store and LLM (no real embeddings/Groq call - nothing in this path needs one to prove
the logic is right). Run from backend/:   python test/test_notes.py"""
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def stub(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


stub("auth")
stub("auth.dependencies", get_current_user=lambda: None)
stub("db.session", get_db=lambda: None)


class Doc:
    def __init__(self, text, **md):
        self.page_content, self.metadata = text, md


LIMIT_EXCERPT = (
    "A limit describes the value a function approaches as the input gets close to a certain point."
)
CONTINUITY_EXCERPT = (
    "A function is continuous at a point if the limit exists, the function is defined there, and the "
    "limit equals the function's value there."
)
ONE_SIDED_EXCERPT = (
    "A one-sided limit only considers values approaching from the left or from the right of the point."
)


class FakeTextbookStore:
    def similarity_search_with_score(self, query, k, filter):
        and_clauses = {list(c.keys())[0]: list(c.values())[0] for c in filter["$and"]}
        unit = and_clauses.get("unit")
        if unit == "Unit 2: Limits and Continuity":
            return [
                (Doc(LIMIT_EXCERPT, vector_id="chunk-vec-limit"), 0.1),
                (Doc(CONTINUITY_EXCERPT, vector_id="chunk-vec-continuity"), 0.15),
                (Doc(ONE_SIDED_EXCERPT, vector_id="chunk-vec-onesided"), 0.2),
            ]
        if unit == "Unit 9: Provider Error":
            return [(Doc("some real excerpt text", vector_id="chunk-vec-err"), 0.1)]
        return []


llm_state = {"unit": None, "calc": None, "raise_error": False}


class ProviderTooLarge(Exception):
    pass


class FakeLLM:
    def __init__(self, n=[0]):
        pass

    def chat(self, messages):
        if llm_state["raise_error"]:
            raise ProviderTooLarge("Request too large for model ... (simulated)")
        content = messages[0]["content"]
        key = "calc" if "key formulas" in content else "unit"
        return {"choices": [{"message": {"content": json.dumps(llm_state[key])}}]}


stub("config")
stub("config.constants", TEXTBOOK_COLLECTION_NAME="textbooks", CALCULATION_SUBJECTS={"mathematics"},
     LANGUAGE_SKILL_SUBJECTS={"english"})
stub("config.settings", settings=types.SimpleNamespace(VECTOR_DATABASE_URL="x"))
sys.modules["config"].constants = sys.modules["config.constants"]
sys.modules["config"].settings = sys.modules["config.settings"]
stub("retriever.vectorstore", get_vector_store=lambda **kw: FakeTextbookStore())
stub("retriever.builder", RetrieverBuilder=lambda: types.SimpleNamespace(embeddings=None))
stub("llm.client", LLMClient=lambda **kw: FakeLLM(), parse_json_object=lambda raw: json.loads(raw) if raw else None)

import db.models as M
from sqlalchemy import ARRAY, JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import notes.models as NM  # registers study_notes onto the shared Base

for t in M.Base.metadata.tables.values():
    for c in t.columns:
        if isinstance(c.type, (JSONB, ARRAY)):
            c.type = JSON()
engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
M.Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autoflush=False)

import api.routes_notes as R
from fastapi import FastAPI
from fastapi.testclient import TestClient

db = Session()

textbook = M.Textbook(grade=10, subject="mathematics", title="Mathematics Grade 10")
db.add(textbook)
db.commit()
db.add(
    M.Chunk(
        textbook_id=textbook.id, unit_or_chapter="Unit 2: Limits and Continuity", section="3.2",
        page_start=56, page_end=57, text_excerpt=LIMIT_EXCERPT, vector_id="chunk-vec-limit",
    )
)
db.add(
    M.Chunk(
        textbook_id=textbook.id, unit_or_chapter="Unit 10: Later Topic", section="1.1",
        page_start=1, page_end=2, text_excerpt="x", vector_id="chunk-vec-later",
    )
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
app.dependency_overrides[R.get_current_user] = lambda: None
c = TestClient(app)

# ---- 1. /subjects, /units: from the real textbook corpus, natural unit order -----------------------------
r = c.get("/v1/notes/subjects", params={"grade": 10})
assert r.json() == {"grade": 10, "subjects": ["mathematics"]}, r.json()

r = c.get("/v1/notes/units", params={"grade": 10, "subject": "mathematics"})
assert r.json()["units"] == ["Unit 2: Limits and Continuity", "Unit 10: Later Topic"], r.json()  # natural order, not alphabetical (10 after 2)

r = c.get("/v1/notes/subjects", params={"grade": 11})
assert r.json()["subjects"] == [], r.json()  # no grade-11 content at all

# ---- 2. /note: ungroundable topic (no chunks at all) -------------------------------------------------------
r = c.get("/v1/notes/note", params={"grade": 10, "subject": "mathematics", "unit": "No Such Unit"})
assert r.status_code == 422, r.text

# ---- 3. /note: hierarchical sections - a bad quote in one section is dropped, not fatal to the whole note --
llm_state["unit"] = {
    "overview": "This unit covers limits, continuity, and one-sided limits.",
    "sections": [
        {
            "heading": "Limits",
            "level": 1,
            "summary": "A limit is the value a function approaches near a point.",
            "source_index": 0,
            "supporting_quote": "A limit describes the value a function approaches as the input gets close to a certain point.",
        },
        {
            "heading": "One-Sided Limits",
            "level": 2,
            "summary": "This claims something the excerpt never actually says, so verification must drop it.",
            "source_index": 2,
            "supporting_quote": "this quote does not appear anywhere in the one-sided limit excerpt",
        },
        {
            "heading": "Continuity",
            "level": 1,
            "summary": "A function is continuous where its limit exists and equals its value there.",
            "source_index": 1,
            "supporting_quote": "A function is continuous at a point if the limit exists, the function is defined there, and the limit equals the function's value there.",
        },
    ],
}
r = c.get("/v1/notes/note", params={"grade": 10, "subject": "mathematics", "unit": "Unit 2: Limits and Continuity"})
assert r.status_code == 200, r.text
b = r.json()
assert b["overview"] == llm_state["unit"]["overview"]
assert b["is_calculation"] is True  # mathematics is in CALCULATION_SUBJECTS (stubbed to just {"mathematics"})
# only 2 of the 3 proposed sections survive verification - the unsupported "One-Sided Limits" one is dropped
assert [s["heading"] for s in b["sections"]] == ["Limits", "Continuity"], b["sections"]
# numbered from the unit's own leading number (2), sequentially - the dropped middle section never
# breaks the numbering of the one that follows it
assert [s["number"] for s in b["sections"]] == ["2.1", "2.2"], b["sections"]
assert b["sections"][0]["citation"]["page_start"] == 56
assert b["sections"][0]["citation"]["unit_or_chapter"] == "Unit 2: Limits and Continuity"

db2 = Session()
assert db2.query(NM.StudyNote).count() == 1

# ---- 4. cached after the first call (LLM never called again for the same topic) ----------------------------
llm_state["unit"] = {"overview": "DIFFERENT - should never be seen, this call must be served from cache", "sections": []}
r2 = c.get("/v1/notes/note", params={"grade": 10, "subject": "mathematics", "unit": "Unit 2: Limits and Continuity"})
assert r2.json()["overview"] == b["overview"], r2.json()  # unchanged - cached, not regenerated

# ---- 5. a provider failure (rate limit, request-too-large, network) degrades to a clean 422, never a 500 ---
llm_state["raise_error"] = True
r = c.get("/v1/notes/note", params={"grade": 10, "subject": "mathematics", "unit": "Unit 9: Provider Error"})
assert r.status_code == 422, r.text  # not 500 - api/routes_notes.py's normal "couldn't ground this" response
llm_state["raise_error"] = False
assert db.query(NM.StudyNote).filter(NM.StudyNote.unit == "Unit 9: Provider Error").count() == 0  # nothing cached

# ---- 6. English units get a different prompt: the unit's theme ("Sustainable Development", ...) is only a
# vehicle for a passage/vocabulary list, never the subject of the notes - the prompt must say so; no other
# subject's prompt should carry that framing ----------------------------------------------------------------
import notes.store as NS

captured_prompts = []


class RecordingLLM:
    def chat(self, messages):
        captured_prompts.append(messages[0]["content"])
        return {"choices": [{"message": {"content": json.dumps({"overview": None, "sections": []})}}]}


class OneDocStore:
    def similarity_search_with_score(self, query, k, filter):
        return [(Doc("A reading passage about renewable energy, with a vocabulary exercise.", vector_id="v"), 0.1)]


NS.generate_note(db, RecordingLLM(), OneDocStore(), 9, "english", "Unit 5: Sustainable Development")
assert "English LANGUAGE unit" in captured_prompts[-1], captured_prompts[-1]
assert "never make the theme itself the subject" in captured_prompts[-1]
# the requirement is baked into the "summary" field's own description (not appended after a generic
# "2-4 sentences" rule that would half-override it) - a dedicated prompt, not UNIT_PROMPT + an addendum
assert "there is no sentence limit and no fixed template here" in captured_prompts[-1]
# examples are required (for grammar AND vocabulary alike), but the count/template is deliberately left
# to the model's own judgement, not forced to a fixed number - confirmed directly by the user that an
# earlier, stricter "at least two, labeled Example 1/Example 2" version was over-constraining
assert "YOU decide how many" in captured_prompts[-1]
assert "not examples for one kind and not the other" in captured_prompts[-1]  # grammar AND vocabulary
assert "AT LEAST TWO" not in captured_prompts[-1]
# naming a grammatical category ("an auxiliary verb") isn't stating it - the real candidate words and how
# one is chosen must be spelled out; and a SET of related items (cohesive devices, modal verbs, confused
# tenses) must be taught item-by-item, each with its own differentiating meaning and own example, never
# one blurred description for the whole set - confirmed directly by the user as a real regression: relaxing
# the example-count requirement had also silently dropped this, and grammar notes went shallow again
assert "does not say what the real candidate words ARE" in captured_prompts[-1]
assert "teach EVERY item in that set on its own terms" in captured_prompts[-1]
assert "not a shared example for the whole set" in captured_prompts[-1]
assert "2-4 sentences" not in captured_prompts[-1]  # the generic UNIT_PROMPT cap must not appear at all

captured_prompts.clear()
NS.generate_note(db, RecordingLLM(), OneDocStore(), 10, "mathematics", "Unit 2: Limits and Continuity")
assert "English LANGUAGE unit" not in captured_prompts[-1]

# ---- 7. English's "Example" requirement isn't reliably followed on a single call (confirmed for real:
# the identical prompt produced a compliant reply once and a reply with zero examples the next time) - a
# call missing it must be retried rather than accepted, keeping whichever attempt actually complies -------
TAG_EXCERPT = "A tag question is added to the end of a statement, e.g. 'You like tea, don't you?'"


class TagQuestionStore:
    def similarity_search_with_score(self, query, k, filter):
        return [(Doc(TAG_EXCERPT, vector_id="chunk-vec-tag"), 0.1)]


class FlakyEnglishLLM:
    """1st main-gen call: describes the activity, no 'Example' at all (the real regression hit live). 2nd
    main-gen call: properly taught, with two labeled examples - generate_note must prefer the 2nd, not the
    1st. The judge call that always follows a successful main-gen reports nothing wrong (this section is
    already fine), so no repair call happens."""

    def __init__(self):
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        content = messages[0]["content"]
        if "failing_indices" in content:
            return {"choices": [{"message": {"content": json.dumps({"failing_indices": []})}}]}
        if self.calls == 1:
            sections = [{
                "heading": "Tag questions", "level": 1,
                "summary": "Tag questions are practiced in the grammar activity in this unit.",
                "source_index": 0, "supporting_quote": TAG_EXCERPT,
            }]
        else:
            sections = [{
                "heading": "Tag questions", "level": 1,
                "summary": (
                    "A tag question is a short question added to confirm a statement, with opposite "
                    "polarity. Example 1 (positive statement): 'You like tea, don't you?' Example 2 "
                    "(negative statement): 'You don't like tea, do you?'"
                ),
                "source_index": 0, "supporting_quote": TAG_EXCERPT,
            }]
        return {"choices": [{"message": {"content": json.dumps({"overview": "Tag questions unit.", "sections": sections})}}]}


flaky = FlakyEnglishLLM()
result = NS.generate_note(db, flaky, TagQuestionStore(), 9, "english", "Unit 9: Tag Question Retry")
assert flaky.calls == 3, flaky.calls  # 2 main-gen calls (stopped once compliant) + 1 judge call, no repair needed
assert result["resolved"] is True
assert "Example 1" in result["sections"][0]["summary"], result["sections"][0]["summary"]
assert "Example 2" in result["sections"][0]["summary"]

# ---- 8. A SET of related items (cohesive devices, modal verbs, ...) listed with only ONE shared example
# for the whole set is a separate real regression from #7 (every section HAS an example, so the cheap
# "has an example" check alone would accept it and never even retry). This needs real reading
# comprehension to catch reliably - a regex-based detector was tried first and kept finding new disguises
# it couldn't catch (quoted, then bolded, then a bare parenthesised list, then items simply starting
# consecutive sentences inside one shared example paragraph - four different real failure shapes from the
# SAME prompt) - so this is an LLM judge, not a pattern match. _judge_sections is tested directly first for
# its own parsing contract: a well-formed reply, a malformed one, and a failing call ------------------------
COHESIVE_EXCERPT = "Fill in the blank with a suitable cohesive device: moreover, however, or therefore."
UNDIFFERENTIATED_SECTIONS = [{
    "heading": "Cohesive devices",
    "summary": (
        'Cohesive devices such as "moreover", "however", and "therefore" link ideas smoothly. '
        'Example: "Living in a city is exciting; however, it can be stressful."'
    ),
}]


class JudgeRepliesWith:
    def __init__(self, content=None, raises=False):
        self.content, self.raises = content, raises

    def chat(self, messages):
        if self.raises:
            raise RuntimeError("provider error (simulated)")
        return {"choices": [{"message": {"content": self.content}}]}


assert NS._judge_sections(
    JudgeRepliesWith(json.dumps({"failing_indices": [0]})), UNDIFFERENTIATED_SECTIONS, 9
) == {0}
assert NS._judge_sections(JudgeRepliesWith(json.dumps({"failing_indices": []})), UNDIFFERENTIATED_SECTIONS, 9) == set()
assert NS._judge_sections(JudgeRepliesWith(json.dumps({"something_else": True})), UNDIFFERENTIATED_SECTIONS, 9) == set()
assert NS._judge_sections(JudgeRepliesWith(raises=True), UNDIFFERENTIATED_SECTIONS, 9) == set()
assert NS._judge_sections(JudgeRepliesWith(json.dumps({"failing_indices": [5]})), UNDIFFERENTIATED_SECTIONS, 9) == set()  # out of range, dropped

# ---- 9. The full generate_note flow: one main-gen call succeeds immediately (it has an example, so the
# cheap retry loop is satisfied), the judge flags it anyway as an undifferentiated list, and the repair
# pass fixes just that section - confirmed by exact call counts, not just the end result ---------------


class CohesiveStore:
    def similarity_search_with_score(self, query, k, filter):
        return [(Doc(COHESIVE_EXCERPT, vector_id="chunk-vec-cohesive"), 0.1)]


class JudgedAndRepairedLLM:
    """Main-gen call: always the same undifferentiated-list section (has an example, so the cheap
    main-loop check accepts it on the first try - no full regeneration should ever be needed or attempted
    for this kind of defect anymore). Judge call: flags it. Repair call: fixes it."""

    def __init__(self):
        self.main_calls, self.judge_calls, self.repair_calls = 0, 0, 0

    def chat(self, messages):
        content = messages[0]["content"]
        if "failing_indices" in content:
            self.judge_calls += 1
            return {"choices": [{"message": {"content": json.dumps({"failing_indices": [0]})}}]}
        if "Rewrite ONLY the summary" in content:
            self.repair_calls += 1
            return {"choices": [{"message": {"content": (
                'Moreover introduces a further point. Example: "The city has jobs; moreover, good schools." '
                'However contrasts. Example: "The city has jobs; however, it is stressful." '
                'Therefore shows a result. Example: "Rent is high; therefore, families share apartments."'
            )}}]}
        self.main_calls += 1
        sections = [{
            "heading": "Cohesive devices", "level": 1, "summary": UNDIFFERENTIATED_SECTIONS[0]["summary"],
            "source_index": 0, "supporting_quote": COHESIVE_EXCERPT,
        }]
        return {"choices": [{"message": {"content": json.dumps({"overview": "Cohesive devices unit.", "sections": sections})}}]}


judged = JudgedAndRepairedLLM()
result = NS.generate_note(db, judged, CohesiveStore(), 9, "english", "Unit 10: Judged And Repaired")
assert judged.main_calls == 1, judged.main_calls  # accepted on the first try - it DOES have an example
assert judged.judge_calls == 1, judged.judge_calls  # exactly one judge pass over the whole note
assert judged.repair_calls == 1, judged.repair_calls  # exactly one targeted rewrite for the flagged section
assert result["resolved"] is True
assert result["sections"][0]["summary"].count("Example") == 3, result["sections"][0]["summary"]

print("STUDY NOTES TESTS PASSED")
