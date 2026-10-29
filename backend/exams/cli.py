"""Command line for the national exam (ESSLCE) bank. Run from backend/ with the venv active.

  python -m exams.cli create-tables
  python -m exams.cli extract "English 2016 ESSLCE.pdf" --subject english --year-ec 2016 \\
        --first-printed-page 2 --expected 4-100 --vision-model <a Groq vision model id> --out exams_out
  python -m exams.cli load exams_out/english_2016                       # into the exam tables (separate from practice)
  python -m exams.cli key english 2016 english_2016_key.txt             # a REAL official key, when one exists
  python -m exams.cli solve english 2016                                # AI proposes answers for the rest (grounded + quote-verified);
                                                                         # also suggests Grade 9-12 textbook links for every question (link rides along)
  python -m exams.cli approve english 2016 --all-clean                  # keyed/solved questions with no flags
  python -m exams.cli approve english 2016 --items 33,34,59             # after you checked them against the photos
  python -m exams.cli link english 2016                                 # re-run just the textbook links (e.g. after re-ingesting a textbook) - solve already does this once
  python -m exams.cli index english 2016                                # approved questions -> exam collection
  python -m exams.cli unit english 2016 --items 5,6 --grade 11 --unit "Unit 3: Grammar"   # a person sets the textbook unit
  python -m exams.cli minutes english 2016 150                          # time allowed in a mock exam
  python -m exams.cli stats --subject english                           # how many questions per unit, across every loaded year
  python -m exams.cli status

Papers with a stream (Mathematics) need --stream natural_science|social_science on every command that names a paper.
A paper with a regional sitting or an online-delivery variant (both occasional, not every year) needs
--region tigray / --delivery-mode online the same way.
"""
import argparse
import sys
from pathlib import Path

import re as _re


def _subject(raw: str) -> str:
    """"Information Technology" -> information_technology; "maths" -> mathematics (the names the textbooks use)."""
    name = _re.sub(r"[\s\-]+", "_", raw.strip().lower())
    try:
        from utils.subjects import _ALIASES
        return _ALIASES.get(name, name)
    except ImportError:
        return name


def _paper_args(p):
    p.add_argument("subject")
    p.add_argument("year_ec", type=int)
    p.add_argument("--stream", default="")
    p.add_argument("--round", default="")
    p.add_argument("--region", default="", help="e.g. tigray - only when EAES gave this region its own sitting")
    p.add_argument("--delivery-mode", default="", help="'online' - only for years with an online-delivery variant")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create-tables")
    sub.add_parser("status")

    e = sub.add_parser("extract")
    e.add_argument("source")
    e.add_argument("--subject", required=True)
    e.add_argument("--year-ec", type=int, required=True)
    e.add_argument("--year-gc", type=int)
    e.add_argument("--stream", default="")
    e.add_argument("--round", default="")
    e.add_argument("--region", default="", help="e.g. tigray - only when EAES gave this region its own sitting")
    e.add_argument("--delivery-mode", default="", help="'online' - only for years with an online-delivery variant")
    e.add_argument("--booklet-code")
    e.add_argument("--first-printed-page", type=int, default=1)
    e.add_argument("--expected", default="1-100", help="question numbers the paper should have, e.g. 4-100")
    e.add_argument("--provider", choices=("groq", "gemini"), default="groq")
    e.add_argument("--vision-model", required=True,
                   help="a model id that accepts images - a Groq id (console.groq.com) for --provider groq, "
                        "a Gemini id (ai.google.dev/gemini-api/docs/models) for --provider gemini")
    e.add_argument("--no-ocr", action="store_true")
    e.add_argument("--pause", type=float, default=10.0, help="seconds between page calls, to stay under the vision model's rate limit")
    e.add_argument("--out", default="exams_out")

    l = sub.add_parser("load"); l.add_argument("folder"); l.add_argument("--replace", action="store_true"); l.add_argument("--allow-incomplete", action="store_true")
    kv = sub.add_parser("keyvision", help="build a key.txt from a checkmarked 'completed exam' answer document (no hand-typed key)")
    kv.add_argument("source")
    kv.add_argument("--provider", choices=("groq", "gemini"), default="gemini")
    kv.add_argument("--vision-model", required=True)
    kv.add_argument("--pause", type=float, default=10.0)
    kv.add_argument("--out", required=True)
    k = sub.add_parser("key"); _paper_args(k); k.add_argument("keyfile")
    a = sub.add_parser("approve"); _paper_args(a)
    a.add_argument("--items", help="comma separated item numbers"); a.add_argument("--all-clean", action="store_true")
    a.add_argument("--by", default="")
    u = sub.add_parser("unit"); _paper_args(u)
    u.add_argument("--items", required=True, help="comma separated item numbers"); u.add_argument("--grade", type=int, required=True)
    u.add_argument("--unit", required=True); u.add_argument("--section", default=None)
    m = sub.add_parser("minutes"); _paper_args(m); m.add_argument("minutes", type=int)
    t = sub.add_parser("link"); _paper_args(t)
    i = sub.add_parser("index"); _paper_args(i); i.add_argument("--include-unreviewed", action="store_true")
    sv = sub.add_parser("solve"); _paper_args(sv)
    sv.add_argument("--grades", default="9,10,11,12", help="grounding search scope, comma separated")
    st = sub.add_parser("stats"); st.add_argument("--subject", default=None)
    args = ap.parse_args(argv)

    if args.cmd == "extract":
        from .extract import SUBJECTS_WITH_SECTIONS, make_gemini_call, make_groq_call, run_extract
        lo, hi = (int(x) for x in args.expected.split("-"))
        subject = _subject(args.subject)
        meta = {"subject": subject, "exam": "ESSLCE", "year_ec": args.year_ec,
                "year_gc": args.year_gc or args.year_ec + 8,       # ESSLCE sits in Hamle (July): E.C. + 8
                "stream": args.stream, "round": args.round, "region": args.region,
                "delivery_mode": args.delivery_mode, "booklet_code": args.booklet_code}
        make_call = make_gemini_call if args.provider == "gemini" else make_groq_call
        call = make_call(args.vision_model, has_sections=subject in SUBJECTS_WITH_SECTIONS)
        run_extract(Path(args.source), Path(args.out), meta, call,
                    args.first_printed_page, (lo, hi), use_ocr=not args.no_ocr, pause_seconds=args.pause)
        return 0

    if args.cmd == "keyvision":
        from .extract import make_gemini_keyvision_call, run_keyvision
        call = make_gemini_keyvision_call(args.vision_model)  # Gemini only - no Groq vision model (see extract.py)
        result = run_keyvision(Path(args.source), call, pause_seconds=args.pause)
        lines = [f"{n}: {letter}" for n, letter in sorted(result["key"].items())]
        Path(args.out).write_text("\n".join(lines), encoding="utf-8")
        print(f"wrote {len(result['key'])} answers to {args.out}")
        if result["unresolved"]:
            print(f"  unresolved (no checkmark read): {result['unresolved']}")
        if result["problems"]:
            print("  problems:")
            for p in result["problems"]:
                print(f"    {p}")
        return 0

    from db.session import SessionLocal
    from . import store
    from .models import Base

    db = SessionLocal()
    try:
        if args.cmd == "create-tables":
            from .models import (
                EsslceAttempt, EsslceElaboration, EsslcePaper, EsslcePassage, EsslceQuestion, EsslceTopicLink,
            )
            Base.metadata.create_all(db.get_bind(), tables=[EsslcePaper.__table__, EsslcePassage.__table__,
                                                           EsslceQuestion.__table__, EsslceTopicLink.__table__,
                                                           EsslceAttempt.__table__, EsslceElaboration.__table__])
            print("national exam tables ready (esslce_papers, esslce_passages, esslce_questions, esslce_topic_links, "
                  "esslce_attempts, esslce_elaborations)")
        elif args.cmd == "status":
            for r in store.status_rows(db):
                print(r)
        elif args.cmd == "stats":
            for r in store.unit_stats(db, _subject(args.subject) if args.subject else None):
                print(r)
        elif args.cmd == "load":
            store.load_paper(db, Path(args.folder), replace=args.replace, allow_incomplete=args.allow_incomplete)
        else:
            paper = store.find_paper(db, _subject(args.subject), args.year_ec, args.stream, args.round,
                                      args.region, args.delivery_mode)
            if args.cmd == "key":
                res = store.attach_key(db, paper, store.read_key_file(Path(args.keyfile)))
                for pmsg in res["problems"]:
                    print("  PROBLEM:", pmsg)
                if res["missing"]:
                    print("  no key for:", res["missing"])
            elif args.cmd == "approve":
                items = {int(x) for x in args.items.split(",")} if args.items else None
                print("approved", store.approve(db, paper, items, args.all_clean, args.by), "questions")
            elif args.cmd == "unit":
                items = {int(x) for x in args.items.split(",")}
                print("unit set on", store.set_unit(db, paper, items, args.grade, args.unit, args.section), "questions")
            elif args.cmd == "minutes":
                store.set_duration(db, paper, args.minutes)
                print(f"mock exam time for {paper.subject} {paper.year_ec}: {args.minutes} minutes")
            elif args.cmd in ("link", "index", "solve"):
                from config import constants
                from retriever.builder import RetrieverBuilder
                from retriever import vectorstore
                emb = RetrieverBuilder().embeddings
                tb = vectorstore.get_vector_store(
                    collection_name=constants.TEXTBOOK_COLLECTION_NAME, embedding_function=emb
                )
                if args.cmd == "link":
                    store.link_topics(db, paper, tb)
                elif args.cmd == "solve":
                    from llm.client import LLMClient
                    grades = [int(g) for g in args.grades.split(",")]
                    store.solve_paper(db, paper, LLMClient(temperature=0, max_tokens=600), tb, grades)
                    # link always rides along with solve now (same tb connection already open, same
                    # grades) - a paper can no longer end up solved-but-unlinked just because a second,
                    # separate CLI command was forgotten (confirmed: happened to chemistry_2016 and SAT_2018)
                    store.link_topics(db, paper, tb, grades)
                else:
                    ex = vectorstore.get_vector_store(
                        collection_name=constants.EXAM_COLLECTION_NAME, embedding_function=emb
                    )
                    store.index_questions(db, paper, ex, args.include_unreviewed)
    except (LookupError, FileExistsError, ValueError) as e:
        print("ERROR:", e)
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())