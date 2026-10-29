"""Create "<book>.units.json" (unit names + the PDF page where each unit starts).

You rarely need this now: `python -m ingestion.textbook_ingest` builds the file
itself when a book has none (and writes it next to the PDF for you to review).
Use this script to look at the result first, or to retry a different method.

    python make_units_json.py "<book>.pdf"                      # try every method automatically
    python make_units_json.py "<book>.pdf" --mode contents --page-offset 12
    python make_units_json.py "<book>.pdf" --mode headers       # "TITLE / UNIT TWO / 37" headers
    python make_units_json.py "<book>.pdf" --mode openers       # "Learning Outcomes ... end of this unit" pages

Run it from backend/. Check the printed list against the book's Contents and
edit the JSON by hand if a title or page is wrong.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingestion import book_tools  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--mode", choices=["auto", "contents", "headers", "openers"], default="auto")
    ap.add_argument("--page-offset", type=int, default=None,
                    help="front-matter pages before printed page 1 (detected automatically if left out)")
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    pages = book_tools.read_pages(pdf_path)
    if not book_tools.has_text_layer(pages):
        sys.exit("This PDF has no text layer (scanned). Run ocrmypdf on it first.")

    offset = args.page_offset
    if offset is None:
        d = book_tools.detect_page_offset(pages)
        offset = d["offset"] if d["confident"] else None
        print(f"page offset: {offset}" + (f" (detected, {d['votes']}/{d['pages_with_text']} pages agree)"
                                          if offset is not None else " (could not be detected)"))

    if args.mode == "auto":
        mode, entries = book_tools.auto_units(pages, offset)
        if mode == "running headers":
            print("This book's pages carry a 'Unit N: Title' header; ingestion reads units from it, "
                  "so no .units.json is needed.")
            return
    elif args.mode == "contents":
        if offset is None:
            sys.exit("--mode contents needs --page-offset (it could not be detected).")
        mode, entries = "contents", book_tools.units_from_contents(pages, offset)
    elif args.mode == "headers":
        mode, entries = "headers", book_tools.units_from_headers(pages)
    else:
        mode, entries = "openers", book_tools.units_from_openers(pages)

    if not entries:
        sys.exit(f"No units found (mode: {mode}). Write the JSON by hand: "
                 '[{"start_pdf_page": 8, "unit": "Unit 1: Title"}, ...]')
    out = pdf_path.with_suffix(".units.json")
    out.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"mode: {mode}; {len(entries)} units -> {out}")
    for e in entries:
        print(f"  pdf page {e['start_pdf_page']:>4}  {e['unit']}")
    print("\nCheck the list against the book's Contents; edit the JSON by hand if a title or page is wrong.")


if __name__ == "__main__":
    main()
