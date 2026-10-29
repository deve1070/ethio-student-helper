"""Audit what is actually in the database + Chroma for a grade (or all grades).

Run from backend/ (venv active):

    python audit_ingestion.py --grade 12                 # all checks, no embeddings needed
    python audit_ingestion.py --grade 12 --smoke         # + "does each unit title find its own unit?" search test
    python audit_ingestion.py --all-grades --matrix-only # subject x grade coverage table only
    python audit_ingestion.py --grade 12 --json audit_g12.json

What it checks, per book:
  * on disk vs ingested (missing books, duplicate copies)
  * database rows vs Chroma vectors (both directions)
  * units: every unit in <book>.units.json has chunks; no fallback/odd labels; chunks per printed page
  * text quality: control characters / U+FFFD (damaged font), private-use glyphs (unmapped bullets),
    garbled digits, very short chunks, exact-duplicate chunks
  * page numbers: missing / reversed, and runs of printed pages with no chunk at all
  * running headers/footers that survived cleaning (a line repeated on many chunks)
Verdict per book: ok / WARN / FAIL. Nothing is modified.
"""

import argparse
import collections
import json
import re
from pathlib import Path

DAMAGE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufffd]")
GARBLE = re.compile(r"[\u01e0-\u01ff\u0370-\u0390]")
PUA = re.compile(r"[\ue000-\uf8ff]")
# lines that legitimately repeat in every unit of a textbook
MARKERS = re.compile(
    r"(?i)^(activity|exercise|example|solution|brainstorming|key (concepts?|terms)|unit summary|"
    r"review (exercise|questions)|learning (outcomes|competencies)|unit outcomes|note|keywords|"
    r"introduction|summary|self.?questioning|inquiry activity|discussion|reflect|start-up activity|"
    r"at the end of this|after completing this|in a small group|answer the following|please answer)"
)


# ----------------------------------------------------------------------------- analysis (pure)
def runs(numbers: list[int]) -> list[tuple[int, int]]:
    out, start, prev = [], None, None
    for n in sorted(numbers):
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append((start, prev))
            start = prev = n
    if start is not None:
        out.append((start, prev))
    return out


def analyze_book(chunks: list[dict], expected_units: list[str] | None = None) -> dict:
    """chunks: dicts with unit, section, page_start, page_end, text (full chunk text)."""
    n = len(chunks)
    rep = {"chunks": n, "issues": []}
    add = lambda level, msg: rep["issues"].append((level, msg))
    if n == 0:
        add("FAIL", "no chunks")
        return rep

    texts = [c["text"] or "" for c in chunks]
    damaged = sum(
        1 for t in texts if len(DAMAGE.findall(t)) >= 3 or len(GARBLE.findall(t)) >= 3
    )
    pua = sum(1 for t in texts if PUA.search(t))
    short = sum(1 for t in texts if len(t.strip()) < 60)
    longc = sum(1 for t in texts if len(t) > 1500)
    dupes = n - len({t.strip() for t in texts})
    rep.update(damaged=damaged, pua=pua, short=short, long=longc, duplicates=dupes)

    share = damaged / n
    if share > 0.10:
        add(
            "FAIL",
            f"{damaged}/{n} chunks ({share:.0%}) have damaged text - OCR this book",
        )
    elif damaged:
        add(
            "WARN",
            f"{damaged}/{n} chunks have damaged text (control characters / garbled digits)",
        )
    if pua:
        add(
            "WARN",
            f"{pua} chunks contain private-use glyphs (an unmapped bullet/symbol font)",
        )
    if short / n > 0.05:
        add("WARN", f"{short}/{n} chunks are under 60 characters")
    if dupes / n > 0.30:
        add(
            "FAIL",
            f"{dupes}/{n} chunks are exact duplicates - the book is probably in the index twice",
        )
    elif dupes / n > 0.03:
        add("WARN", f"{dupes}/{n} chunks are exact duplicates of another chunk")

    # ---- units
    by_unit = collections.OrderedDict()
    for c in chunks:
        by_unit.setdefault(c["unit"] or "", []).append(c)
    units = []
    for label, cs in by_unit.items():
        p0 = min((c["page_start"] for c in cs if c["page_start"]), default=0)
        p1 = max((c["page_end"] for c in cs if c["page_end"]), default=0)
        pages = max(p1 - p0 + 1, 1)
        units.append(
            {
                "unit": label,
                "chunks": len(cs),
                "p0": p0,
                "p1": p1,
                "per_page": round(len(cs) / pages, 2),
            }
        )
    units.sort(key=lambda u: (u["p0"], u["unit"]))
    rep["units"] = units

    unlabeled = len(by_unit.get("", []))
    if unlabeled:
        add(
            "FAIL" if unlabeled / n > 0.05 else "WARN",
            f"{unlabeled} chunks have no unit label",
        )
    if expected_units:
        expected = set(expected_units)
        missing = [u for u in expected_units if u not in by_unit]
        if missing:
            add("FAIL", f"units in units.json with NO chunks: {missing}")
        odd = {k: len(v) for k, v in by_unit.items() if k and k not in expected}
        odd_n = sum(odd.values())
        if odd:
            top = sorted(odd.items(), key=lambda kv: -kv[1])[:4]
            add(
                "FAIL" if odd_n / n > 0.05 else "WARN",
                f"{odd_n} chunks carry labels that are not in units.json (fallback headings?): {top}",
            )
    for u in units:
        if u["unit"] and u["p1"] - u["p0"] >= 5 and u["per_page"] < 0.8:
            add(
                "WARN",
                f"{u['unit'][:50]}: only {u['per_page']} chunks per page (text may be missing)",
            )

    # ---- pages
    bad_pages = sum(
        1
        for c in chunks
        if not c["page_start"] or not c["page_end"] or c["page_end"] < c["page_start"]
    )
    if bad_pages:
        add("WARN", f"{bad_pages} chunks have missing or reversed page numbers")
    covered = set()
    for c in chunks:
        if c["page_start"] and c["page_end"] and c["page_end"] >= c["page_start"]:
            covered.update(range(c["page_start"], c["page_end"] + 1))
    if covered:
        top_page = max(covered)
        gaps = [
            (a, b)
            for a, b in runs([p for p in range(1, top_page + 1) if p not in covered])
            if b - a + 1 >= 4
        ]
        rep["page_gaps"] = gaps
        rep["last_page"] = top_page
        if gaps:
            add(
                "WARN",
                f"runs of 4+ printed pages with no chunk: {gaps[:5]} (blank/figure pages, or lost text)",
            )

    # ---- surviving running headers
    seen = collections.Counter()
    for t in texts:
        lines = {re.sub(r"\d+", "#", ln.strip()) for ln in t.split("\n")}
        seen.update(
            ln
            for ln in lines
            if 6 <= len(ln) <= 120 and ln != "\u2022" and not MARKERS.match(ln)
        )
    threshold = max(8, n // 30)
    left = [(ln, k) for ln, k in seen.most_common(6) if k >= threshold]
    rep["repeated_lines"] = left
    if left:
        add(
            "WARN",
            f"lines repeated on many chunks (running header/footer left in?): {left[:3]}",
        )
    return rep


def verdict(rep: dict) -> str:
    levels = {lvl for lvl, _ in rep.get("issues", [])}
    return "FAIL" if "FAIL" in levels else "WARN" if "WARN" in levels else "ok"


def matrix_text(rows: list[tuple[int, str, int]], grades=(9, 10, 11, 12)) -> str:
    subjects = sorted({s for _, s, _ in rows})
    cell = {(g, s): n for g, s, n in rows}
    out = [f"{'subject':26}" + "".join(f"{('G' + str(g)):>9}" for g in grades)]
    for s in subjects:
        out.append(
            f"{s:26}"
            + "".join(
                f"{(str(cell[(g, s)]) if (g, s) in cell else '-'):>9}" for g in grades
            )
        )
    holes = [f"{s} G{g}" for s in subjects for g in grades if (g, s) not in cell]
    out.append("")
    out.append("missing: " + (", ".join(holes) if holes else "none"))
    return "\n".join(out)


# ----------------------------------------------------------------------------- project access
def load(grade_filter):
    import chromadb
    from config import constants
    from config.settings import settings
    from db.models import Chunk, Textbook
    from db.session import SessionLocal

    client = chromadb.PersistentClient(path=settings.CHROMA_DB_PATH)
    coll = client.get_collection(constants.TEXTBOOK_COLLECTION_NAME)
    db = SessionLocal()
    try:
        q = db.query(Textbook)
        if grade_filter:
            q = q.filter(Textbook.grade == grade_filter)
        books = []
        for tb in q.order_by(Textbook.grade, Textbook.subject).all():
            rows = db.query(Chunk).filter(Chunk.textbook_id == tb.id).all()
            ids = [r.vector_id for r in rows]
            docs = {}
            for i in range(0, len(ids), 500):
                got = coll.get(ids=ids[i : i + 500], include=["documents"])
                docs.update(dict(zip(got["ids"], got["documents"])))
            in_chroma = set(
                coll.get(where={"textbook_id": str(tb.id)}, include=[])["ids"]
            )
            books.append(
                {
                    "tb": {
                        "id": tb.id,
                        "grade": tb.grade,
                        "subject": tb.subject,
                        "title": tb.title,
                        "path": tb.source_file_path,
                    },
                    "chunks": [
                        {
                            "unit": r.unit_or_chapter or "",
                            "section": r.section or "",
                            "page_start": r.page_start or 0,
                            "page_end": r.page_end or 0,
                            "text": docs.get(r.vector_id, ""),
                        }
                        for r in rows
                    ],
                    "no_vector": [r.vector_id for r in rows if r.vector_id not in docs],
                    "orphans": sorted(in_chroma - set(ids)),
                }
            )
        all_counts = [
            (
                tb.grade,
                tb.subject,
                db.query(Chunk).filter(Chunk.textbook_id == tb.id).count(),
            )
            for tb in db.query(Textbook).all()
        ]
    finally:
        db.close()
    return constants, settings, coll, books, all_counts


def expected_units_for(path: str):
    side = Path(path).with_suffix(".units.json")
    if not side.exists():
        return None
    try:
        data = json.loads(side.read_text(encoding="utf-8"))
        return [e["unit"] for e in sorted(data, key=lambda e: e["start_pdf_page"])]
    except Exception:
        return None


def disk_books(constants, grade_filter):
    root = Path(constants.TEXTBOOK_CONTENT_ROOT)
    out = []
    for gd in sorted(root.glob("grade_*")):
        try:
            g = int(gd.name.split("_")[1])
        except (IndexError, ValueError):
            continue
        if grade_filter and g != grade_filter:
            continue
        for sd in sorted(p for p in gd.iterdir() if p.is_dir()):
            for pdf in sorted(sd.glob("*.pdf")):
                out.append((g, sd.name.strip().lower(), pdf))
    return out


def smoke(constants, settings, books):
    from langchain_community.vectorstores import Chroma
    from retriever.builder import RetrieverBuilder

    store = Chroma(
        collection_name=constants.TEXTBOOK_COLLECTION_NAME,
        embedding_function=RetrieverBuilder().embeddings,
        persist_directory=settings.CHROMA_DB_PATH,
    )
    results = {}
    for b in books:
        tb = b["tb"]
        units = expected_units_for(tb["path"]) or []
        misses = []
        for label in units:
            title = re.sub(r"^Unit\s*\d+\s*:\s*", "", label)
            hits = store.similarity_search(
                title,
                k=5,
                filter={"$and": [{"subject": tb["subject"]}, {"grade": tb["grade"]}]},
            )
            if not any((h.metadata or {}).get("unit") == label for h in hits):
                misses.append(label)
        results[tb["title"]] = (len(units), misses)
    return results


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--grade", type=int)
    ap.add_argument("--all-grades", action="store_true")
    ap.add_argument("--matrix-only", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    if not args.grade and not args.all_grades:
        ap.error("give --grade N or --all-grades")
    g = None if args.all_grades else args.grade

    constants, settings, coll, books, all_counts = load(g)
    print("SUBJECT x GRADE COVERAGE (chunks, all grades in the database)\n")
    print(matrix_text(all_counts))
    if args.matrix_only:
        return

    print("\n\nON DISK vs INGESTED")
    ingested = collections.Counter(
        (b["tb"]["grade"], b["tb"]["subject"]) for b in books
    )
    for gr, subj, pdf in disk_books(constants, g):
        n = ingested.get((gr, subj), 0)
        flag = "ok" if n == 1 else ("MISSING" if n == 0 else f"DUPLICATE x{n}")
        print(f"  grade {gr:>2} {subj:26} {flag:12} {pdf.name}")
    for (gr, subj), n in ingested.items():
        if n > 1:
            print(
                f"  !! grade {gr} {subj} is in the database {n} times -> --only-subject {subj} --remove, then ingest once"
            )

    report = {}
    print("\n\nPER BOOK")
    for b in books:
        tb = b["tb"]
        rep = analyze_book(b["chunks"], expected_units_for(tb["path"]))
        if b["no_vector"]:
            rep["issues"].append(
                (
                    "FAIL",
                    f"{len(b['no_vector'])} database rows have no vector in Chroma",
                )
            )
        if b["orphans"]:
            rep["issues"].append(
                ("FAIL", f"{len(b['orphans'])} Chroma vectors have no database row")
            )
        report[tb["title"]] = rep
        print(
            f"\n[{verdict(rep):4}] grade {tb['grade']} {tb['subject']}: {rep['chunks']} chunks"
            + (f", printed pages 1-{rep['last_page']}" if rep.get("last_page") else "")
        )
        for u in rep.get("units", []):
            print(
                f"        {u['chunks']:4d} chunks  pp.{u['p0']:>3}-{u['p1']:<3} {u['per_page']:>4}/page  {u['unit'][:60] or '(no label)'}"
            )
        for lvl, msg in rep["issues"]:
            print(f"      {lvl}: {msg}")

    if args.smoke:
        print(
            "\n\nSMOKE TEST: searching each unit title should return a chunk of that unit"
        )
        for title, (n, misses) in smoke(constants, settings, books).items():
            print(
                f"  {title}: {n - len(misses)}/{n} units found"
                + (f"   MISSED: {misses}" if misses else "")
            )

    print("\n\nSUMMARY")
    for title, rep in report.items():
        print(f"  {verdict(rep):4}  {title}")
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"\nfull report -> {args.json}")


if __name__ == "__main__":
    main()
