"""
Health report for an ingested book. Run it right after ingestion: it finds the
problems we kept finding by hand (garbled text, noise on every page, missing
pages, wrong units) so you do not have to read hundreds of chunks.

    python scripts/book_report.py --grade 12 --subject physics
    python scripts/book_report.py            # every ingested book (leave both out)
    python scripts/book_report.py --subject chemistry   # one subject, all grades

Looks at every stored chunk of the book (text comes from Chroma, units and
pages from Postgres) and prints: chunks per unit, chunk sizes, and warnings
for the checks below. A clean report is not proof the book is good, but each
warning is something worth opening the PDF for.
"""
import argparse
import os
import re
import statistics
import sys
import warnings
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")

LIGATURE_GAP = re.compile(r"(?<=[A-Za-z])(?:ffi|ffl|fi|fl)[ \t]+(?=[a-z])|(?<![A-Za-z])(?:fi|fl)[ \t]+(?=[a-z]{2})")
GLYPH_CODES = re.compile(r"/gid\d+|\(cid:\d+\)")
ODD_CHARS = re.compile(r"[\ufffe\ufffd\ue000-\uf8ff]")
MATH_LETTERS = re.compile(r"[\U0001D400-\U0001D7FF]")
MARGIN_TABS = re.compile(r"\bu\s+n\s+i\s+t(?:\s+\d{1,2})?\b")


def analyze(rows):
    """rows: [(unit, page_start, page_end, vector_id, text)] -> report dict."""
    n = len(rows)
    sizes = [len(r[4]) for r in rows]
    per_unit = defaultdict(lambda: {"chunks": 0, "p0": None, "p1": None})
    pages_with_chunks = set()
    texts = Counter()
    line_docs = Counter()
    flags = Counter()

    for unit, p0, p1, _vid, text in rows:
        u = per_unit[unit or "(no unit)"]
        u["chunks"] += 1
        for p in (p0, p1):
            if p is not None:
                u["p0"] = p if u["p0"] is None else min(u["p0"], p)
                u["p1"] = p if u["p1"] is None else max(u["p1"], p)
        if p0 is not None:
            pages_with_chunks.update(range(p0, (p1 if p1 is not None else p0) + 1))
        texts[text.strip()] += 1
        for line in {re.sub(r"\s+", " ", ln).strip().lower() for ln in text.splitlines()}:
            if len(line) >= 12:
                line_docs[line] += 1
        if GLYPH_CODES.search(text):
            flags["garbled glyph codes (/gid, cid)"] += 1
        if LIGATURE_GAP.search(text):
            flags["split ligatures (\"Defi ne\")"] += 1
        if ODD_CHARS.search(text):
            flags["odd/private-use characters"] += 1
        if MATH_LETTERS.search(text):
            flags["math-italic letters not folded"] += 1
        if MARGIN_TABS.search(text):
            flags["vertical 'u n i t' margin tabs"] += 1
        if len(text.strip()) < 80:
            flags["very short chunks (<80 chars)"] += 1
        if not unit:
            flags["chunks with no unit"] += 1

    repeated = [(line, c) for line, c in line_docs.most_common(5) if c >= max(5, 0.03 * n)]
    dupes = sum(c - 1 for c in texts.values() if c > 1)
    gaps = []
    if pages_with_chunks:
        lo, hi = min(pages_with_chunks), max(pages_with_chunks)
        gaps = [p for p in range(lo, hi + 1) if p not in pages_with_chunks]

    warnings_out = []
    for name, c in flags.items():
        pct = 100 * c / max(n, 1)
        limit = 5 if name.startswith("very short") else 0.5
        if pct > limit:
            warnings_out.append(f"{name}: {c} chunks ({pct:.1f}%)")
    if repeated:
        warnings_out.append("lines repeated across many chunks (header/footer/watermark?): "
                            + "; ".join(f"{c}x {line[:50]!r}" for line, c in repeated))
    if dupes:
        warnings_out.append(f"exact duplicate chunks: {dupes} (was the book ingested twice?)")
    if len(gaps) > max(3, 0.05 * (max(pages_with_chunks) - min(pages_with_chunks) + 1)) if pages_with_chunks else False:
        warnings_out.append(f"{len(gaps)} pages have no chunks at all (e.g. {gaps[:8]}): figure pages, or text lost?")
    thin = [u for u, d in per_unit.items() if d["chunks"] < 5]
    if thin:
        warnings_out.append(f"units with fewer than 5 chunks (wrong unit mapping?): {thin}")

    return {
        "chunks": n,
        "chars_median": int(statistics.median(sizes)) if sizes else 0,
        "chars_mean": int(statistics.mean(sizes)) if sizes else 0,
        "units": {u: d for u, d in sorted(per_unit.items(), key=lambda kv: (kv[1]["p0"] is None, kv[1]["p0"] or 0))},
        "gaps": gaps,
        "warnings": warnings_out,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grade", type=int, default=None)
    ap.add_argument("--subject", default=None)
    args = ap.parse_args()

    from config import constants
    from db.models import Chunk, Textbook
    from db.session import SessionLocal
    from retriever.builder import RetrieverBuilder
    from retriever import vectorstore

    db = SessionLocal()
    q = db.query(Textbook)
    if args.grade is not None:
        q = q.filter(Textbook.grade == args.grade)
    if args.subject:
        q = q.filter(Textbook.subject == args.subject.strip().lower())
    books = q.order_by(Textbook.grade, Textbook.subject).all()
    if not books:
        sys.exit("No matching textbook.")
    vs = vectorstore.get_vector_store(
        collection_name=constants.TEXTBOOK_COLLECTION_NAME,
        embedding_function=RetrieverBuilder().embeddings,
    )
    for book in books:
        chunks = db.query(Chunk).filter(Chunk.textbook_id == book.id).all()
        by_vid = {c.vector_id: c for c in chunks}
        stored = {d.id: d.page_content for d in vs.get_by_ids(list(by_vid))}
        missing = [v for v in by_vid if not stored.get(v)]
        rows = [(c.unit_or_chapter, c.page_start, c.page_end, v, stored[v]) for v, c in by_vid.items() if stored.get(v)]
        rep = analyze(rows)
        print(f"\n=== {book.title}  (grade {book.grade}, {book.subject})")
        print(f"chunks: {rep['chunks']}   median {rep['chars_median']} chars, mean {rep['chars_mean']}")
        if missing:
            print(f"WARNING: {len(missing)} database chunks have no vector in the store (interrupted ingestion?)")
        print("\nunit".ljust(58), "chunks   pages")
        for unit, d in rep["units"].items():
            print(f"{str(unit)[:56]:<57}{d['chunks']:>6}   {d['p0']}-{d['p1']}")
        print("\n" + ("No warnings." if not rep["warnings"] else "WARNINGS:"))
        for w in rep["warnings"]:
            print(f"  - {w}")
    db.close()


if __name__ == "__main__":
    main()
