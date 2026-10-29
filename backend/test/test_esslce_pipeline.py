"""Tests for the national exam (ESSLCE) bank in exams/: rendered page images -> stand-in vision model -> parse ->
load -> key -> approve -> link -> index, plus the command line. SQLite, no API, no real vision model.
Run from backend/:   python test/test_esslce_pipeline.py        (needs Pillow; OCR checks run only if tesseract is installed)"""
import io
import json
import os
import sys
import tempfile
import types
import uuid
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db.models as M                                                  # the project's own tables (incl. the exam-solver cache)
from exams import cli, store as ST, tools as T
from exams.extract import run_extract
from exams.models import Base, EsslceAttempt, EsslcePaper, EsslcePassage, EsslceQuestion, EsslceTopicLink

quiet = lambda *a, **k: None
TMP = Path(tempfile.mkdtemp())

# ---- 0. the draft's names used to collide with the exam-solver cache: both sets must live side by side
assert "exam_questions" in M.Base.metadata.tables and "esslce_questions" in M.Base.metadata.tables
assert M.ExamQuestion.__tablename__ == "exam_questions" and EsslceQuestion.__tablename__ == "esslce_questions"
assert Base is M.Base

# ---- three "photos" of a chemistry paper and what the (stand-in) vision model reads from each
PAGES = {
 1: ["I. CHEMISTRY", "Choose the best answer from the given alternatives.",
     "1. Which of the following is a noble gas?", "A. Oxygen", "B. Neon", "C. Chlorine", "D. Sodium",
     "2. The atomic number of carbon is", "A. 4", "B. 6", "C. 12", "D. 14",
     "3. Which particle carries a negative charge?", "A. Proton", "B. Neutron", "C. Electron", "D. Nucleus"],
 2: ["4. Water boils at ______ degrees Celsius at sea level.", "A. 50", "B. 100", "C. 150", "D. 200",
     "5. Study the diagram of an atom. Which label shows the nucleus?", "A. W", "B. X", "C. Y", "D. Z",
     "6. Which of these substances is an acid?", "A. Vinegar", "B. Soap"],
 3: ["C. Baking soda", "D. Ammonia solution",
     "7. Which gas do plants take in for photosynthesis?", "A. Oxygen", "B. Nitrogen", "C. Carbon dioxide", "D. Hydrogen"],
}
MARKUP = {
 1: "@part I. CHEMISTRY\n@section Choose the best answer from the given alternatives.\nQ1 | Which of the following is a noble gas?\nA. Oxygen\nB. Neon\nC. Chlorine\nD. Sodium\n"
    "Q2 | The atomic number of carbon is\nA. 4\nB. 6\nC. 12\nD. 14\nQ3 | Which particle carries a negative charge?\nA. Proton\nB. Neutron\nC. Electron\nD. Nucleus",
 2: "Q4 | Water boils at ______ degrees Celsius at sea level.\nA. 50\nB. 100\nC. 150\nD. 200\nQ5 | Study the diagram of an atom. Which label shows the nucleus?\nA. W\nB. X\nC. Y\nD. Z\n"
    "DIAGRAM: an atom with four labelled regions W X Y Z\nQ6 | Which of these substances is an acid?\nA. Vinegar\nB. Soap",
 3: "```\nHere is the page you asked for:\nC. Baking soda\nD. Ammonia solution\nQ7 | Which gas do plants take in for photosynthesis?\nA. Oxygen\nB. Nitrogen\nC. Carbon dioxide\nD. Hydrogen\n```",
}
try:
    FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
except OSError:
    FONT = ImageFont.load_default()
folder = TMP / "photos"; folder.mkdir()
for pg, lines in PAGES.items():
    img = Image.new("RGB", (1300, 1700), "white"); d = ImageDraw.Draw(img)
    for i, t in enumerate(lines): d.text((90, 120 + i * 80), t, fill="black", font=FONT)
    img.save(folder / f"p{pg}.jpg")
def fake_vision_for(markup):
    def call(jpg, note):
        return markup[int(note.split("printed page ")[1].split(" ")[0].rstrip("."))]
    return call
meta = {"subject": "chemistry", "exam": "ESSLCE", "year_ec": 2016, "year_gc": 2024, "stream": "natural_science", "round": ""}
try:
    import pytesseract; pytesseract.get_tesseract_version(); HAS_OCR = True
except Exception:
    HAS_OCR = False

# ---- 1. extraction
out = run_extract(folder, TMP / "out", meta, fake_vision_for(MARKUP), 1, (1, 7), use_ocr=HAS_OCR, log=quiet, pause_seconds=0)
recs = [json.loads(l) for l in (out["dir"] / "questions.jsonl").read_text().splitlines()]
assert [r["item_no"] for r in recs] == list(range(1, 8))
assert recs[5]["options"] == ["Vinegar", "Soap", "Baking soda", "Ammonia solution"]            # options continued on the next page
assert recs[4]["has_diagram"] and "needs_figure" in recs[4]["flags"] and recs[0]["flags"] == []
assert "Here is the page" not in (out["dir"] / "transcript.txt").read_text()
rv = (out["dir"] / "review.txt").read_text()
assert "commentary dropped (e.g. 'Here is the page you asked for:')" in rv            # the reviewer SEES what was dropped, not only how many
pj = json.loads((out["dir"] / "paper.json").read_text()); assert pj["issues"] == [] and pj["failed_pages"] == []
assert T.parse_transcript("@page 1\n@passage | Title only\nP1: text\n")["passages"]["P1"]["title"] == "Title only"      # a malformed @passage line no longer crashes

# a misclassified item (model wrote "@section 5. ..." instead of "Q5 | ...") is recovered as item 5, not a crash
recovered = T.parse_transcript("@page 1\n@section 5. What is 2+2?\nA. 3\nB. 4\nC. 5\nD. 6\n")["questions"][0]
assert recovered["n"] == 5 and recovered["stem"] == "What is 2+2?" and recovered["options"] == {"A": "3", "B": "4", "C": "5", "D": "6"}
# a REAL section heading (not a bare-number prefix) still works as before
still_real = T.parse_transcript("@page 1\n@section Choose the best answer.\nQ1 | Pick one\nA. x\nB. y\nC. z\nD. w\n")
assert still_real["questions"][0]["section"] == "Choose the best answer."

# a digit-prefixed @section that's actually a numbered bullet in the "GENERAL DIRECTIONS" cover-page
# boilerplate (never followed by real options, unlike a genuinely misclassified item) is dropped, not
# kept as a bogus empty-option question colliding with the real Q1 that follows on the next page
directions_bullet = T.parse_transcript(
    "@page 1\n@part GENERAL DIRECTIONS:\n@section 1. FOLLOW THE RULES:\n@section II. ATTENTION!\n"
    "@page 2\nQ1 | The real first question\nA. x\nB. y\nC. z\nD. w\n"
)
assert [q["n"] for q in directions_bullet["questions"]] == [1]
assert directions_bullet["questions"][0]["stem"] == "The real first question"
assert any("never got any options" in p for p in directions_bullet["problems"])

# an orphaned option line that ISN'T a recoverable digit-prefixed heading (e.g. a question misclassified
# as a passage paragraph) is dropped and reported, not a crash - the item then surfaces as "missing" below
dropped = T.parse_transcript("@page 1\n@passage P1 |\nP1: some passage text\nA. x\nB. y\nC. z\nD. w\n")
assert not dropped["questions"] and "not attached to any question" in dropped["problems"][0]

# a "Q4+" on an item number never opened before is a spurious "+" (the model mislabeled a fresh item as a
# continuation) - recovered as a real question 4, flagged for a human to double check it's complete
spurious_plus = T.parse_transcript("@page 1\nQ3 | Pick one\nA. x\nB. y\nC. z\nD. w\nQ4+ | A fresh item\nA. x\nB. y\nC. z\nD. w\n")
assert spurious_plus["questions"][1]["n"] == 4 and spurious_plus["questions"][1]["stem"] == "A fresh item"
assert any("Q4: recovered from an unmatched" in p for p in spurious_plus["problems"])

# the SAME passage id reused for a genuinely different passage (each page is transcribed in isolation, so
# the model has no memory that "P1" was already taken) is auto-renumbered, not silently overwritten
two_passages = T.parse_transcript(
    "@page 1\n@passage P1 | First passage\nP1: alpha\n@passage P1 | Second passage\nP1: beta\n"
)
assert set(two_passages["passages"].keys()) == {"P1", "P2"}
assert two_passages["passages"]["P1"]["title"] == "First passage" and two_passages["passages"]["P1"]["paragraphs"][0]["text"] == "alpha"
assert two_passages["passages"]["P2"]["title"] == "Second passage" and two_passages["passages"]["P2"]["paragraphs"][0]["text"] == "beta"

# a reading passage that spans a page break must still link EVERY one of its questions to it, even the
# ones on the LATER page - a passage's own continuation ("P1+: ...") and a question's own option lines
# carry no tag of their own, so only @passage (seen once, on the first page) ever names the passage
# explicitly. Confirmed for real against two different loaded papers before this fix: a 14-item English
# Reading Comprehension block and a 4-item SAT one both left every question on the later page(s) unlinked,
# even though the real passage text was transcribed correctly and sitting right there in the DB.
multi_page_passage = T.parse_transcript(
    "@page 1\n@section READING COMPREHENSION\n@passage P1 | Passage I\nP1: Once upon a time.\n"
    "Q1 | First question\nA. a\nB. b\nC. c\nD. d\n"
    "@page 2\nP1+: The end.\nQ2 | Second question, no @passage tag on this page\nA. a\nB. b\nC. c\nD. d\n"
    "@section VOCABULARY\nQ3 | Not part of the passage at all\nA. a\nB. b\nC. c\nD. d\n"
)
by_n = {q["n"]: q["passage"] for q in multi_page_passage["questions"]}
assert by_n == {1: "P1", 2: "P1", 3: None}, by_n  # q2 inherits the still-open passage; q3, after a real @section change, does not
assert multi_page_passage["passages"]["P1"]["paragraphs"][0]["text"] == "Once upon a time. The end."

# a SECOND passage introduced mid-section (a fresh @passage tag, no intervening @section) must take over
# cleanly for its own questions, without need of any explicit "close P1" marker
two_passages_one_section = T.parse_transcript(
    "@page 1\n@section READING COMPREHENSION\n@passage P1 | Passage I\nP1: alpha\nQ1 | q1\nA. a\nB. b\nC. c\nD. d\n"
    "@passage P2 | Passage II\nP1: beta\nQ2 | q2\nA. a\nB. b\nC. c\nD. d\n"
)
by_n2 = {q["n"]: q["passage"] for q in two_passages_one_section["questions"]}
assert by_n2 == {1: "P1", 2: "P2"}, by_n2

# a later question's options arriving with no opening Q line must NEVER silently overwrite the current
# question's real options (this corrupted a real stored answer once, completely undetected) - flagged instead
overwrite_guard = T.parse_transcript("@page 1\nQ1 | Pick one\nA. real1\nB. real2\nC. real3\nD. real4\nA. intruder1\nB. intruder2\nC. intruder3\nD. intruder4\n")
assert overwrite_guard["questions"][0]["options"] == {"A": "real1", "B": "real2", "C": "real3", "D": "real4"}
assert any("option A already set" in p for p in overwrite_guard["problems"])

# ---- 2. a paper with a missing question is refused (the draft loaded it and the problem was only in review.txt)
bad = dict(MARKUP); bad[2] = bad[2].replace("Q4 | Water boils at ______ degrees Celsius at sea level.\nA. 50\nB. 100\nC. 150\nD. 200\n", "")
bad_out = run_extract(folder, TMP / "out_bad", {**meta, "year_ec": 2015}, fake_vision_for(bad), 1, (1, 7), use_ocr=False, log=quiet, pause_seconds=0)
assert any("missing question numbers: [4]" in m for lvl, m in json.loads((bad_out["dir"] / "paper.json").read_text())["issues"])

engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
Base.metadata.create_all(engine, tables=[EsslcePaper.__table__, EsslcePassage.__table__, EsslceQuestion.__table__, EsslceTopicLink.__table__, EsslceAttempt.__table__])
Session = sessionmaker(bind=engine); db = Session()
try: ST.load_paper(db, bad_out["dir"], log=quiet); raise SystemExit("should refuse an incomplete paper")
except ValueError as e: assert "missing question numbers: [4]" in str(e) and "mock exam" in str(e)
incomplete = ST.load_paper(db, bad_out["dir"], allow_incomplete=True, log=quiet)
assert not ST.paper_complete(incomplete) and "missing question numbers" in incomplete.notes
db.delete(incomplete); db.commit()

# ---- 3. load, reload, key
paper = ST.load_paper(db, out["dir"], log=quiet)
assert len(paper.questions) == 7 and ST.paper_complete(paper) and all(q.review_status == "needs_key" for q in paper.questions)
try: ST.load_paper(db, out["dir"], log=quiet); raise SystemExit("second load must be refused")
except FileExistsError: pass
for text, want in [("1. B  2. B  3. C  4. B  5. B  6. A  7. C", {1: "B", 3: "C", 7: "C"}), ("1-B 2)B 3:C", {1: "B", 3: "C"}), ("Answer key\n1 B\n2 D", {1: "B", 2: "D"})]:
    p = TMP / "k.txt"; p.write_text(text); got = ST.read_key_file(p); assert all(got[k] == v for k, v in want.items()), (text, got)
(TMP / "k.json").write_text(json.dumps({"1": "b", "2": "d"})); assert ST.read_key_file(TMP / "k.json") == {1: "B", 2: "D"}
(TMP / "k2.json").write_text(json.dumps([{"item": 1, "answer": "C"}])); assert ST.read_key_file(TMP / "k2.json") == {1: "C"}
(TMP / "k3.txt").write_text("1. A\n1. B\n") 
try: ST.read_key_file(TMP / "k3.txt"); raise SystemExit("conflicting key must be refused")
except ValueError: pass
res = ST.attach_key(db, paper, {1: "B", 2: "B", 3: "C", 4: "B", 5: "B", 6: "Z", 99: "A"}, log=quiet)
assert res["missing"] == [6, 7] and any("99" in p for p in res["problems"]) and any("'Z'" in p for p in res["problems"])
res = ST.attach_key(db, paper, {6: "A", 7: "C"}, log=quiet); assert res["missing"] == []

# ---- 4. review: only clean + keyed questions are approved in bulk; a diagram question needs a person
assert ST.approve(db, paper, all_clean=True) == 6 and {q.item_no for q in paper.questions if q.review_status == "approved"} == {1, 2, 3, 4, 6, 7}
assert [q.item_no for q in paper.questions if ST.eligible(q)] == [1, 2, 3, 4, 6, 7]
diagram_q = paper.questions[4]
assert ST.approve(db, paper, items={5}, who="teacher") == 1
# a diagram question is eligible once approved IF its real source page photo is actually on disk
# (load_paper recorded source_dir = out["dir"], and run_extract really did save p0N.jpg there)
assert diagram_q.has_diagram and paper.source_dir == str(out["dir"])
real_image = ST.question_page_image(diagram_q)
assert real_image and ST.eligible(diagram_q)
# ...but NOT if the paper predates source_dir being recorded (an older row, source_dir still None)
paper.source_dir = None
assert ST.question_page_image(diagram_q) is None and not ST.eligible(diagram_q)
# ...nor if source_dir is set but the expected file is just missing from disk (never a broken reference)
paper.source_dir = str(TMP)  # a real dir that exists, but holds no p0N.jpg for this printed_page
assert ST.question_page_image(diagram_q) is None and not ST.eligible(diagram_q)
paper.source_dir = str(out["dir"])  # restored for the rest of the test
unkeyed = ST.load_paper(db, bad_out["dir"], allow_incomplete=True, log=quiet)
assert ST.approve(db, unkeyed, items={1}) == 0 and ST.approve(db, unkeyed, all_clean=True) == 0              # no key, no approval
db.delete(unkeyed); db.commit()
# the key is corrected later: the approval of that item is withdrawn, the others stay
res = ST.attach_key(db, paper, {1: "A"}, log=quiet)
assert paper.questions[0].review_status == "needs_review" and paper.questions[0].answer_index == 0 and any("approval withdrawn" in p for p in res["problems"])
assert paper.questions[1].review_status == "approved"
ST.attach_key(db, paper, {1: "B"}, log=quiet); ST.approve(db, paper, items={1}, who="teacher")

# ---- 5. links to the textbooks (suggestions) and a person's verified unit
class Doc:
    def __init__(self, text, **md): self.page_content, self.metadata = text, md
BOOKS = [Doc("noble gases neon argon helium oxygen chlorine sodium atoms", subject="chemistry", grade=9, unit="Unit 4: Periodic Classification", section="Noble gases", vector_id="v1", textbook_id=str(uuid.uuid4())),
         Doc("acid acids bases substances vinegar soap baking soda ammonia indicators", subject="chemistry", grade=11, unit="Unit 3: Acids and Bases", section="Common acids", vector_id="v2", textbook_id=str(uuid.uuid4())),
         Doc("atomic number carbon protons electrons neutrons nucleus particle charge", subject="chemistry", grade=9, unit="Unit 3: Structure of the Atom", section="Subatomic particles", vector_id="v3", textbook_id=str(uuid.uuid4())),
         Doc("photosynthesis carbon dioxide plants gas oxygen", subject="biology", grade=12, unit="Unit 2: Plant Physiology", section="Photosynthesis", vector_id="v4", textbook_id=str(uuid.uuid4()))]
class FakeTextbooks:
    def similarity_search_with_score(self, query, k, filter):
        want = {list(c.items())[0][0]: list(c.items())[0][1] for c in filter["$and"]}
        q = set(query.lower().replace("?", " ").split())
        scored = [(1 - len(q & set(d.page_content.split())) / max(len(q), 1), d) for d in BOOKS if d.metadata["subject"] == want["subject"] and d.metadata["grade"] == want["grade"]]
        return [(d, dist) for dist, d in sorted(scored, key=lambda t: t[0])][:k]
tb = FakeTextbooks()
ST.link_topics(db, paper, tb, log=quiet)
q1 = paper.questions[0]; q6 = paper.questions[5]
assert q1.links and q1.links[0].unit == "Unit 4: Periodic Classification" and q1.links[0].textbook_id == BOOKS[0].metadata["textbook_id"]   # the UUID is kept (the draft stored None)
assert ST.best_unit(q6)[1] == "Unit 3: Acids and Bases" and ST.best_unit(q6)[2] is False and ST.best_unit(q6)[0] == 11
assert all(l.vector_id and l.score is not None for l in q1.links)
assert [l.rank for l in q6.links] == sorted(l.rank for l in q6.links) and q6.links[0].grade <= q6.links[-1].grade     # review order: grade, then distance
assert ST.best_unit(q6)[0] == 11 and q6.links[0].grade == 9                                                         # ...but the BEST unit is the closest one, not the lowest grade
ST.set_unit(db, paper, {6}, 12, "Unit 7: Household Chemicals")
assert ST.best_unit(q6) == (12, "Unit 7: Household Chemicals", True)
ST.link_topics(db, paper, tb, log=quiet); assert ST.best_unit(q6) == (12, "Unit 7: Household Chemicals", True)              # re-running link keeps a person's decision

# ---- 6. index into the exam collection: question wording only, deterministic ids, approved only
class FakeIndex:
    def __init__(self): self.docs, self.deleted = {}, []
    def delete(self, ids):
        self.deleted += list(ids)
        for i in ids: self.docs.pop(i, None)
    def add_texts(self, texts, metadatas, ids): self.docs.update({i: (t, m) for i, t, m in zip(ids, texts, metadatas)})
ix = FakeIndex(); n = ST.index_questions(db, paper, ix, log=quiet)
assert n == 7 and all(i.startswith("exam-") for i in ix.docs)
text, md = ix.docs[f"exam-{paper.questions[0].id}"]
assert text == "Which of the following is a noble gas?\nA. Oxygen\nB. Neon\nC. Chlorine\nD. Sodium" and "ESSLCE" not in text and "2016" not in text
assert md["year_ec"] == 2016 and md["item_no"] == 1 and md["subject"] == "chemistry" and md["has_key"] is True and md["kind"] == "esslce_question"
ix2 = FakeIndex(); paper.questions[2].review_status = "needs_review"; db.commit()
assert ST.index_questions(db, paper, ix2, log=quiet) == 6 and ST.index_questions(db, paper, FakeIndex(), include_unreviewed=True, log=quiet) == 7
ST.index_questions(db, paper, ix, log=quiet)                                                                      # again, with item 3's approval withdrawn:
assert len(ix.docs) == 6 and f"exam-{paper.questions[2].id}" not in ix.docs                                       # it leaves the index (the draft kept it searchable)
paper.questions[2].review_status = "approved"; db.commit(); ST.index_questions(db, paper, ix, log=quiet); assert len(ix.docs) == 7   # replaced, not duplicated
rows = ST.status_rows(db); assert rows[0]["complete"] and rows[0]["ready_for_students"] == 7 and rows[0]["keyed"] == 7 and rows[0]["flagged"] == 1  # all 7 incl. the diagram item (its real photo is on disk)

# ---- 6b. AI-derived answers (solve) - grounded, quote-verified, never overwrites a real key; and unit_stats
class FakeLLM:
    def __init__(self, content): self.content = content
    def chat(self, messages): return {"choices": [{"message": {"content": self.content}}]}

PASSAGE = "Neon is a noble gas found in group 18 of the periodic table, used in lighting."
class StubTB:
    def __init__(self, text): self.text = text
    def similarity_search_with_score(self, query, k, filter):
        return [(Doc(self.text, subject="chemistry", grade=9), 0.1)]
tb1 = StubTB(PASSAGE)

confident = FakeLLM(json.dumps({"answer_index": 1, "source_index": 0,
    "explanation": "Neon is explicitly named as a noble gas.", "supporting_quote": "Neon is a noble gas"}))
r = ST.solve_question(confident, tb1, paper, paper.questions[0], grades=(9,))
assert r["resolved"] and r["answer_index"] == 1 and r["supporting_quote"] == "Neon is a noble gas"

unconfident = FakeLLM(json.dumps({"answer_index": -1}))
assert not ST.solve_question(unconfident, tb1, paper, paper.questions[0], grades=(9,))["resolved"]

fabricated = FakeLLM(json.dumps({"answer_index": 1, "source_index": 0, "explanation": "...",
    "supporting_quote": "this sentence does not appear anywhere in the passage"}))
assert not ST.solve_question(fabricated, tb1, paper, paper.questions[0], grades=(9,))["resolved"]

# a fresh, unkeyed paper (year_ec=2019 so it doesn't collide with the one loaded above)
solve_out = run_extract(folder, TMP / "out_solve", {**meta, "year_ec": 2019}, fake_vision_for(MARKUP), 1, (1, 7), use_ocr=False, log=quiet, pause_seconds=0)
sp = ST.load_paper(db, solve_out["dir"], log=quiet)
assert all(q.answer_source is None for q in sp.questions)
sp.questions[1].answer_source, sp.questions[1].answer_index = "manual", 3            # a human already answered this one
sp.questions[2].review_status, sp.questions[2].answer_index, sp.questions[2].answer_source = "approved", 1, "ai_derived"  # previously resolved+approved
db.commit()

always_two = FakeLLM(json.dumps({"answer_index": 2, "source_index": 0,
    "explanation": "matches the passage", "supporting_quote": "Neon is a noble gas"}))
res = ST.solve_paper(db, sp, always_two, tb1, grades=(9,), log=quiet)
assert res == {"solved": 6, "unresolved": 0, "withdrawn": 1}                          # 7 - 1 manual (never touched); item 3's approval withdrawn
assert sp.questions[1].answer_index == 3 and sp.questions[1].answer_source == "manual"  # untouched - never overwritten
assert sp.questions[2].answer_index == 2 and sp.questions[2].review_status == "needs_review" and sp.questions[2].reviewed_by is None
assert sp.questions[0].answer_index == 2 and sp.questions[0].answer_source == "ai_derived" and sp.questions[0].review_status == "needs_review"

# index_questions omits grade/unit metadata when a question has no resolved unit yet (sp was never `link`ed)
ST.approve(db, sp, all_clean=True)
ix_sp = FakeIndex(); ST.index_questions(db, sp, ix_sp, log=quiet)
assert ix_sp.docs and all("grade" not in md and "unit" not in md for _, md in ix_sp.docs.values())
# ...but it's present for paper's q6, which WAS unit-tagged earlier (section 5)
md6 = ix.docs[f"exam-{paper.questions[5].id}"][1]
assert md6["grade"] == 12 and md6["unit"] == "Unit 7: Household Chemicals" and md6["unit_verified"] is True

# ---- 6c. calculation subjects: the derivation's code is actually EXECUTED, never just trusted
calc_q = EsslceQuestion(stem="What is (2f-g)(-2)?", options=["20/3", "11/3", "7/3", "16/3"])
confident_calc = FakeLLM(json.dumps({
    "answer_index": 0,
    "latex_solution": "\\[ (2f-g)(-2) = 2f(-2) - g(-2) = 6 + \\tfrac{2}{3} = \\tfrac{20}{3} \\]",
    "verification_code": "from fractions import Fraction\nprint(2 * Fraction(-3, -1) - Fraction(-2, 3))",
}))
r = ST.solve_question_calculation(confident_calc, calc_q)
assert r["resolved"] and r["answer_index"] == 0 and r["verification_output"] == "20/3" and r["explanation"].startswith("\\[")

unconfident_calc = FakeLLM(json.dumps({"answer_index": -1}))
assert not ST.solve_question_calculation(unconfident_calc, calc_q)["resolved"]

unsafe_calc = FakeLLM(json.dumps({
    "answer_index": 0, "latex_solution": "x", "verification_code": "import os\nprint(os.listdir('.'))",
}))
assert not ST.solve_question_calculation(unsafe_calc, calc_q)["resolved"]           # rejected before execution

wrong_calc = FakeLLM(json.dumps({
    "answer_index": 0, "latex_solution": "x", "verification_code": "print(999)",
}))
assert not ST.solve_question_calculation(wrong_calc, calc_q)["resolved"]            # ran fine, but matches no option

assert ST.run_verification_code("print(2 + 2)") == "4"
assert ST.run_verification_code("import subprocess; subprocess.run(['ls'])") is None
assert ST.run_verification_code("while True: pass", timeout=1) is None             # a hang is killed, not left to hang the pipeline

stats = ST.unit_stats(db, subject="chemistry")
by_unit = {(r["grade"], r["unit"]): r for r in stats}
assert by_unit[(9, "Unit 4: Periodic Classification")]["all_count"] >= 1
assert by_unit[(9, "Unit 4: Periodic Classification")]["approved_count"] >= 1
assert by_unit[(12, "Unit 7: Household Chemicals")]["verified"] is True
assert stats == sorted(stats, key=lambda r: r["all_count"], reverse=True)

# ---- 6c. skill_strand: English/SAT aren't organized by textbook topic - read the skill straight off the
# exam's own real section/part headings (grounded in the real loaded English 2018 paper), no LLM call
sn = types.SimpleNamespace
assert ST.skill_strand(sn(passage_id=7, part=None, section=None)) == "Reading Comprehension"      # a passage always wins, no matter what else is set
assert ST.skill_strand(sn(passage_id=None, part="II. LANGUAGE FOCUS", section="Choose the correct answer.")) == "Grammar"
assert ST.skill_strand(sn(passage_id=None, part="III. COMPREHENSION", section="B. Analogy")) == "Analogy"
assert ST.skill_strand(sn(passage_id=None, part="IV. WRITING", section="Instructions: ... NOT in the right order ...")) == "Word Order"
assert ST.skill_strand(sn(passage_id=None, part=None, section="Section Three: Word Spelling")) == "Spelling"
assert ST.skill_strand(sn(passage_id=None, part=None, section="Some unrecognized heading")) is None      # never guessed

# ---- 6c-i. skill_strand must cover every section heading actually found in the loaded English/SAT papers -
# of 131 real eligible English questions and 19 real eligible SAT questions, 108 and 5 respectively were
# falling through to None before this fix (confirmed live, not hypothetical) because their own section
# heading was a bare label ("Substitution (47 - 57)"), a typo ("READING COMPREHNSION"), or shared
# boilerplate between two different skills (a grammar AND a vocabulary section use near-identical
# "...are incomplete sentences...choose the word that best completes the sentence" directions, told apart
# only by whether the heading itself says "VOCABULARY").
assert ST.skill_strand(sn(passage_id=None, part=None, section="SECTION FOUR: VOCABULARY (25-57) DIRECTIONS: Questions 27-46 are incomplete sentences. Choose that one that best completes each sentence.")) == "Vocabulary"
assert ST.skill_strand(sn(passage_id=None, part=None, section="DIRECTION: Questions 58 - 85 are incomplete sentences. Choose the word that best completes the sentence.")) == "Grammar"  # same boilerplate, no "VOCABULARY" heading -> falls to the generic Grammar bucket, not left unclassified
assert ST.skill_strand(sn(passage_id=None, part=None, section="SECTION THREE: - READING COMPREHNSION (13-26)")) == "Reading Comprehension"  # real typo, missing the E
assert ST.skill_strand(sn(passage_id=None, part=None, section="Substitution (47 - 57)")) == "Word Substitution"  # heading dropped "word"
assert ST.skill_strand(sn(passage_id=None, part=None, section="SECTION ONE: Word order (1-5)")) == "Word Order"
assert ST.skill_strand(sn(passage_id=None, part=None, section="SECTION SIX: Communicative Activities (86 - 105)")) == "Sentence Comprehension"  # bare heading, no "complete the dialogue" phrase this time
assert ST.skill_strand(sn(passage_id=None, part=None, section="SECTION SEVEN: Writing (106-120) Direction: different types of writing")) == "Writing"
assert ST.skill_strand(sn(passage_id=None, part=None, section="Instruction: For Questions 56 - 60 use the information given in the table and choose the correct answer from the given alternatives.")) == "Quantitative Reasoning"  # SAT items 56-60's own section never repeats "Quantitative Reasoning"
# the specific label must still win over the generic fallbacks it depends on being checked first
assert ST.skill_strand(sn(passage_id=None, part=None, section="Letter Writing (1-5)")) == "Letter Writing"
assert ST.skill_strand(sn(passage_id=None, part=None, section="Paragraph Writing (1-5)")) == "Paragraph Writing"

# ---- 6c-ii. best_unit must return None for English/SAT even when a chapter link exists for the question -
# these subjects are organized by skill_strand (above), never by textbook chapter, even though the generic
# embedding-based linker (link_topics) doesn't know that on its own and would otherwise still produce one
# (confirmed live against the real app: English had 37 such chapter links auto-suggested before this fix).
eng_paper = EsslcePaper(subject="english", year_ec=2018, stream=None, round=None, region=None, delivery_mode=None)
db.add(eng_paper); db.commit()
eng_q = EsslceQuestion(paper_id=eng_paper.id, item_no=1, stem="Choose the correct tense.", options=["A", "B", "C", "D"], answer_index=0, review_status="approved")
db.add(eng_q); db.commit()
db.add(EsslceTopicLink(question_id=eng_q.id, rank=1, score=0.1, grade=12, unit="Unit 1: Sustainable Development", verified=True))
db.commit()
assert ST.best_unit(eng_q) is None, "English/SAT must never be categorized by textbook chapter, even a verified one"
assert ST.eligible_units(db, "english") == []
# link_topics itself must skip these subjects outright, not just have its output ignored downstream -
# running retrieval and storing suggestions nobody ever reads would be pure waste
assert ST.link_topics(db, eng_paper, tb, log=quiet) == {"links": 0}
assert len(eng_q.links) == 1  # still just the one verified link added above - no suggestion rows added

# ---- 6d. student_progress: latest attempt per question wins, aggregated per unit from this student's OWN
# history (q1 unit "Unit 4: Periodic Classification"; q6 unit "Unit 7: Household Chemicals", from section 5
# above) - chemistry has no skill strand, so skills stays empty throughout.
uid = uuid.uuid4()
q1, q6b = paper.questions[0], paper.questions[5]
def stamp(q, ok, i):
    db.add(EsslceAttempt(user_id=uid, question_id=q.id, paper_id=paper.id, chosen_index=0,
                          is_correct=ok, created_at=datetime(2024, 1, 1, 0, 0, i)))
    db.commit()
stamp(q1, False, 1); stamp(q1, False, 2)                                      # q1: wrong, then wrong again

empty_prog = ST.student_progress(db, uuid.uuid4(), "chemistry")               # a student with no attempts at all
assert empty_prog == {"units": [], "skills": [], "attempted": 0, "correct": 0}
assert ST.recommend_focus(empty_prog) is None

prog = ST.student_progress(db, uid, "chemistry")
assert prog["attempted"] == 1 and prog["correct"] == 0 and prog["skills"] == []        # 1 DISTINCT question (q1), latest attempt counted once
by_unit = {r["unit"]: r for r in prog["units"]}
assert by_unit["Unit 4: Periodic Classification"] == {"grade": 9, "unit": "Unit 4: Periodic Classification", "attempted": 1, "correct": 0, "accuracy": 0.0}
assert ST.recommend_focus(prog) is None            # only 1 distinct question attempted in this unit so far - below MIN_ATTEMPTS_FOR_SIGNAL, never guessed

stamp(q1, True, 3)                                 # q1's LATEST attempt flips to correct - must overwrite the two old wrong ones, not accumulate alongside them
prog2 = ST.student_progress(db, uid, "chemistry")
by_unit2 = {r["unit"]: r for r in prog2["units"]}
assert by_unit2["Unit 4: Periodic Classification"] == {"grade": 9, "unit": "Unit 4: Periodic Classification", "attempted": 1, "correct": 1, "accuracy": 1.0}

stamp(q6b, True, 4)                                # a second, independent unit now has its own (perfect) record
prog3 = ST.student_progress(db, uid, "chemistry")
by_unit3 = {r["unit"]: r for r in prog3["units"]}
assert by_unit3["Unit 7: Household Chemicals"]["accuracy"] == 1.0 and prog3["attempted"] == 2

# recommend_focus's threshold logic, tested directly against hand-built data (not enough distinct real
# questions in this fixture's units to reach MIN_ATTEMPTS_FOR_SIGNAL through the DB alone)
below_floor = {"units": [{"grade": 9, "unit": "U1", "attempted": 2, "correct": 0, "accuracy": 0.0}], "skills": []}
assert ST.recommend_focus(below_floor) is None                                         # <3 attempts is never a confident signal
mixed = {
    "units": [{"grade": 9, "unit": "U1", "attempted": 3, "correct": 0, "accuracy": 0.0},
              {"grade": 10, "unit": "U2", "attempted": 5, "correct": 4, "accuracy": 0.8}],
    "skills": [{"skill": "Grammar", "attempted": 4, "correct": 1, "accuracy": 0.25}],
}
rec = ST.recommend_focus(mixed)
assert rec["kind"] == "unit" and rec["unit"] == "U1" and rec["accuracy"] == 0.0         # the weakest across BOTH axes, not just one

# ---- 6e. diagnostic_questions: stratified across topic groups, not just "first N" - by now there are TWO
# chemistry papers (`paper` from section 5, `sp` from section 6b), so this also confirms it pools across
# every paper of the subject, same as the mixed practice pool does, not just one
n_eligible_chem = sum(
    1 for p in db.query(EsslcePaper).filter_by(subject="chemistry").all() for q in p.questions if ST.eligible(q)
)
diag_all = ST.diagnostic_questions(db, "chemistry", count=100)
assert len(diag_all) == n_eligible_chem  # requesting more than exists returns everything, no duplicates
assert len({q.id for q in diag_all}) == n_eligible_chem  # every one a distinct question row
def _group_key(q):
    u = ST.best_unit(q)
    if u:
        return f"unit:{u[1]}"
    s = ST.skill_strand(q)
    return f"skill:{s}" if s else "uncategorized"
diag_two = ST.diagnostic_questions(db, "chemistry", count=2)
assert len(diag_two) == 2 and len({_group_key(q) for q in diag_two}) == 2  # one from each of 2 DIFFERENT groups
assert ST.diagnostic_questions(db, "no such subject") == []

# ---- 7. the command line, end to end (SQLite session and fake models stand in for the project's)
sys.modules["db.session"] = types.SimpleNamespace(SessionLocal=Session)
import exams.extract as EX
EX.make_groq_call = lambda model_id, has_sections=True: fake_vision_for(MARKUP)
stub = lambda name, **a: sys.modules.setdefault(name, types.SimpleNamespace(**a))
sys.modules["retriever.vectorstore"] = types.SimpleNamespace(get_vector_store=lambda collection_name, embedding_function: FakeTextbooks() if collection_name == "textbooks" else FakeIndex())
# exams/store.py's own real import of retriever.citation (above, never stubbed in this file) already
# really imported retriever/builder.py, which already really imported retriever.vectorstore - so the real
# "retriever" package object already carries a real .vectorstore attribute from that import. Overwriting
# sys.modules alone doesn't retroactively fix an attribute already resolved before this point.
import retriever as _retriever_pkg
_retriever_pkg.vectorstore = sys.modules["retriever.vectorstore"]
sys.modules["config"] = types.ModuleType("config")
sys.modules["config.constants"] = types.SimpleNamespace(
    TEXTBOOK_COLLECTION_NAME="textbooks", EXAM_COLLECTION_NAME="esslce_exams"
)
sys.modules["config.settings"] = types.SimpleNamespace(settings=types.SimpleNamespace(VECTOR_DATABASE_URL="x"))
sys.modules["config"].constants = sys.modules["config.constants"]; sys.modules["config"].settings = sys.modules["config.settings"]
sys.modules["retriever.builder"] = types.SimpleNamespace(RetrieverBuilder=lambda: types.SimpleNamespace(embeddings=None))
sys.modules["llm.client"] = types.SimpleNamespace(LLMClient=lambda **kw: FakeLLM(json.dumps({"answer_index": -1})))
def run(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf): code = cli.main(list(argv))
    return code, buf.getvalue()
db2e = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}); S2 = sessionmaker(bind=db2e)
sys.modules["db.session"] = types.SimpleNamespace(SessionLocal=S2)
class B(types.SimpleNamespace):
    def get_bind(self): return db2e
real_session = S2
sys.modules["db.session"].SessionLocal = lambda: real_session()
code, o = run("create-tables"); assert code == 0 and "esslce_papers" in o
code, o = run("extract", str(folder), "--subject", "Chemistry", "--year-ec", "2016", "--stream", "natural_science", "--expected", "1-7",
              "--vision-model", "x", "--no-ocr", "--pause", "0", "--out", str(TMP / "cli_out"))
assert code == 0 and (TMP / "cli_out" / "chemistry_2016_natural_science" / "questions.jsonl").exists()
code, o = run("load", str(TMP / "cli_out" / "chemistry_2016_natural_science")); assert code == 0
code, o = run("load", str(TMP / "cli_out" / "chemistry_2016_natural_science")); assert code == 1 and "already loaded" in o
(TMP / "cli_key.txt").write_text("1. B 2. B 3. C 4. B 5. B 6. A 7. C")
code, o = run("key", "chemistry", "2016", str(TMP / "cli_key.txt"), "--stream", "natural_science"); assert code == 0 and "key attached to 7" in o
code, o = run("approve", "CHEMISTRY", "2016", "--all-clean", "--stream", "natural_science"); assert code == 0 and "approved 6" in o
code, o = run("approve", "chemistry", "2016", "--items", "5", "--stream", "natural_science", "--by", "teacher"); assert "approved 1" in o
code, o = run("unit", "chemistry", "2016", "--items", "1,2", "--grade", "9", "--unit", "Unit 4: Periodic Classification", "--stream", "natural_science"); assert "unit set on 2" in o
code, o = run("minutes", "chemistry", "2016", "90", "--stream", "natural_science"); assert "90 minutes" in o
code, o = run("index", "chemistry", "2016", "--stream", "natural_science"); assert code == 0
# `solve` alone (no separate `link` call - deliberately not run above) must still populate topic links;
# a paper solved via the CLI can no longer end up unlinked just because a second command was forgotten
code, o = run("solve", "chemistry", "2016", "--stream", "natural_science"); assert code == 0 and "solved 0" in o  # all 7 already have an official_key
cli_paper = ST.find_paper(real_session(), "chemistry", 2016, "natural_science", "", "", "")
assert any(ST.best_unit(q) is not None for q in cli_paper.questions), "solve must link, not just solve"
code, o = run("stats", "--subject", "chemistry"); assert code == 0
code, o = run("status"); assert code == 0 and "'complete': True" in o and "'ready_for_students': 7" in o and "'minutes': 90" in o, o
code, o = run("approve", "chemistry", "1999"); assert code == 1 and "no exam paper" in o
print("ESSLCE PIPELINE TESTS PASSED" + ("" if HAS_OCR else "  (OCR cross-check skipped: tesseract not installed)"))