"""
Fill the question bank from an ingested textbook. Slow on purpose (model
calls, rate limits): run it once per book, ideally overnight, then review.

    python scripts/generate_questions.py --grade 9 --subject chemistry --limit 10
    python scripts/generate_questions.py --grade 9 --subject chemistry --unit "Unit 4"
    python scripts/generate_questions.py --grade 9 --subject biology --status needs_review

--limit N        stop after N passages (try 10 first and read the output)
--per-passage K  questions requested per passage (default 3)
--unit TEXT      only units whose name contains TEXT
--status         'active' (served to students) or 'needs_review' (hidden until you approve)
--pause SECONDS  wait between passages; the free Groq tier needs about 15 or more
It remembers finished passages in practice_progress.json, so you can stop and resume.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import warnings
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")

PROGRESS_FILE = "practice_progress.json"
REJECTED_FILE = "practice_rejected.jsonl"   # every rejected question + why, one JSON per line
SKIP_START = re.compile(
    r"^\s*(Exercise|Activity|Self[- ]?Assessment|Review|Unit Outcomes|Unit Summary|Key Terms|"
    r"Learning competencies|Part [IVX]+|PART [IVX]+|Glossary|Contents|Table of Contents)",
    re.I,
)
MIN_WORDS, MAX_CHARS = 40, 1600


def usable(text: str) -> bool:
    """Skip exercises, outlines, key-term lists and number-heavy table dumps."""
    if SKIP_START.match(text) or len(text.split()) < 20:
        return False
    letters = sum(c.isalpha() for c in text)
    return letters / max(len(text), 1) >= 0.6


def build_passages(rows):
    """rows: [(unit, section, page_start, page_end, vector_id, text)] -> passages.
    Chunks from the same unit and page are joined (up to MAX_CHARS)."""
    groups = defaultdict(list)
    for unit, section, p0, p1, vid, text in rows:
        if usable(text):
            groups[(unit, p0)].append((section, p0, p1, vid, text))
    passages = []
    for (unit, _), items in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1] or 0)):
        current, size = [], 0
        for item in items + [None]:
            if item is None or (current and size + len(item[4]) > MAX_CHARS):
                if current and sum(len(x[4].split()) for x in current) >= MIN_WORDS:
                    passages.append({
                        "unit": unit,
                        "section": current[0][0],
                        "page_start": min(x[1] for x in current if x[1] is not None) if any(x[1] is not None for x in current) else None,
                        "page_end": max(x[2] for x in current if x[2] is not None) if any(x[2] is not None for x in current) else None,
                        "vector_ids": [x[3] for x in current],
                        "text": "\n\n".join(x[4] for x in current),
                    })
                current, size = [], 0
            if item is not None:
                current.append(item)
                size += len(item[4])
    return passages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grade", type=int, required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--unit", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--per-passage", type=int, default=3)
    ap.add_argument("--status", choices=["active", "needs_review"], default="active")
    ap.add_argument("--pause", type=float, default=15.0)
    args = ap.parse_args()

    from sqlalchemy.exc import IntegrityError

    from config import constants
    from db.models import Chunk, Textbook
    from db.models_practice import QuizQuestion
    from db.session import SessionLocal
    from llm.client import LLMClient
    from llm.gemini_client import GeminiLLMClient
    from practice.generator import generate_for_passage
    from practice.validate import dup_key
    from retriever.builder import RetrieverBuilder
    from retriever import vectorstore

    subject = args.subject.strip().lower()
    db = SessionLocal()
    books = db.query(Textbook).filter(Textbook.grade == args.grade, Textbook.subject == subject).all()
    if not books:
        sys.exit(f"No textbook for grade {args.grade}, subject '{subject}'.")

    vs = vectorstore.get_vector_store(
        collection_name=constants.TEXTBOOK_COLLECTION_NAME,
        embedding_function=RetrieverBuilder().embeddings,
    )
    gen_llm = LLMClient(temperature=0.4, max_tokens=2500)
    # A genuinely different model than gen_llm for the blind second opinion
    # (practice/generator.py's blind_solve) - the same reasoning this project
    # now applies everywhere an AI checks another AI's answer with no human
    # backstop (see exams/store.py's solve_question_crosschecked).
    solve_llm = GeminiLLMClient(temperature=0, max_tokens=800)

    progress = json.load(open(PROGRESS_FILE)) if os.path.exists(PROGRESS_FILE) else {}
    totals, rejected_total, made = Counter(), Counter(), 0

    for book in books:
        chunks = db.query(Chunk).filter(Chunk.textbook_id == book.id).all()
        by_vid = {c.vector_id: c for c in chunks}
        docs = vs.get_by_ids(list(by_vid))
        rows = [(by_vid[d.id].unit_or_chapter, by_vid[d.id].section, by_vid[d.id].page_start,
                  by_vid[d.id].page_end, d.id, d.page_content) for d in docs if d.page_content]
        passages = build_passages(rows)
        if args.unit:
            passages = [p for p in passages if args.unit.lower() in (p["unit"] or "").lower()]
        print(f"{book.title}: {len(chunks)} chunks -> {len(passages)} usable passages")

        existing = [dup_key(q.question, q.options, q.answer_index)
                    for q in db.query(QuizQuestion).filter(QuizQuestion.textbook_id == book.id)]

        done_here = 0
        for p in passages:
            key = hashlib.sha1("|".join(sorted(p["vector_ids"])).encode()).hexdigest()
            if key in progress:
                continue
            if args.limit is not None and done_here >= args.limit:
                break
            done_here += 1
            try:
                rejected_log = []
                accepted, rejected = generate_for_passage(gen_llm, solve_llm, p["text"], args.per_passage, existing, rejected_log)
                with open(REJECTED_FILE, "a", encoding="utf-8") as fh:
                    for r in rejected_log:
                        fh.write(json.dumps({**r, "unit": p["unit"], "page": p["page_start"]}, ensure_ascii=False) + "\n")
            except Exception as e:  # model unreachable etc.: stop cleanly, progress is saved
                print(f"  stopped: {e}")
                json.dump(progress, open(PROGRESS_FILE, "w"))
                db.close()
                return
            rejected_total.update(rejected)
            saved = 0
            for q in accepted:
                db.add(QuizQuestion(
                    textbook_id=book.id, grade=book.grade, subject=book.subject,
                    unit_or_chapter=p["unit"], section=p["section"],
                    page_start=p["page_start"], page_end=p["page_end"],
                    question=q["question"], options=q["options"], answer_index=q["answer_index"],
                    explanation=q["explanation"], supporting_quote=q["supporting_quote"],
                    difficulty=q["difficulty"], status=args.status,
                    source_vector_ids=p["vector_ids"], content_hash=q["content_hash"],
                ))
                try:
                    db.commit()
                    existing.append(dup_key(q["question"], q["options"], q["answer_index"]))
                    saved += 1
                except IntegrityError:
                    db.rollback()  # same question already in the bank
            made += saved
            progress[key] = {"unit": p["unit"], "page": p["page_start"], "kept": saved}
            json.dump(progress, open(PROGRESS_FILE, "w"))
            print(f"  {done_here:>3}. {str(p['unit'])[:38]:<38} p{p['page_start']}: kept {saved}/{args.per_passage}")
            time.sleep(args.pause)

    print(f"\nSaved {made} new questions (status={args.status}).")
    if rejected_total:
        print("Rejected, by reason:")
        for reason, n in rejected_total.most_common():
            print(f"  {n:>4}  {reason}")
        print(f"The rejected questions are listed in {REJECTED_FILE}")
    db.close()


if __name__ == "__main__":
    main()