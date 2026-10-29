"""Tests for automatic page-offset and unit detection, using made-up pages (no PDFs needed).
Run from backend/:   python test/test_book_tools.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ingestion import book_tools as B  # noqa: E402

random.seed(3)
FRONT = 9                                   # 9 front-matter pages, so printed page 1 = PDF page 10
body = lambda n: " ".join(random.choice(["force", "mass", "energy", "cell", "atom", "river", "market"]) for _ in range(60))

def make_book(footer, n_body=80):
    pages = [f"Cover or credits page {i}\nSome text" for i in range(FRONT)]
    for printed in range(1, n_body + 1):
        pages.append(footer(printed) + "\n" + body(printed) + f"\nFigure {random.randint(1,30)} caption")
    return pages

# --- offset detected from different header/footer styles
styles = {
    "number in header line": lambda n: f"Grade 9 English Textbook {n}",
    "number on both sides": lambda n: f"{n} Chemistry Grade 9 {n + 1}",
    "lone page number": lambda n: str(n),
}
for name, footer in styles.items():
    d = B.detect_page_offset(make_book(footer))
    assert d["offset"] == FRONT and d["confident"], (name, d)
# no page numbers at all, or random numbers -> not confident (the ingestion then asks for a book.json)
assert not B.detect_page_offset([body(i) for i in range(100)])["confident"]
noisy = [f"{random.randint(1,400)} {body(i)}\nFig {random.randint(1,60)}" for i in range(100)]
assert not B.detect_page_offset(noisy)["confident"]
assert not B.detect_page_offset([""] * 50)["confident"]

# --- scanned vs text
assert B.has_text_layer(make_book(styles["lone page number"])) and not B.has_text_layer([""] * 40)

# --- units: running header, contents, TITLE/UNIT WORD headers, openers
running = [f"Unit {1 + p // 20}: Topic {1 + p // 20}\ntext {p}" for p in range(100)]
mode, entries = B.auto_units(running, 0)          # complete "Unit N: Title" headers -> an explicit list
assert mode == "numbered headers" and [e["unit"] for e in entries] == [f"Unit {k}: Topic" for k in range(1, 6)]   # a trailing number in a header is treated as a page number and dropped
assert [e["start_pdf_page"] for e in entries] == [1, 21, 41, 61, 81]
# the older mode is kept only as a last resort: headers exist but a unit is missing from them (gap), nothing else works
gappy = [f"Unit {[1, 2, 4][p // 20]}: Topic\ntext {p}" for p in range(60)]
assert B.auto_units(gappy, 0) == ("running headers", [])

contents = ["Table of Contents\nUnit1: CHEMISTRY AND ITS IMPORTANCE 1\nUnit2: MEASUREMENTS AND SCIENTIFIC METHODS 18\nUnit3: STRUCTURE OF THE ATOM 51"] \
    + ["filler"] * 5 + [f"body {i}" for i in range(80)]
mode, entries = B.auto_units(contents, 6)
assert mode == "contents" and [e["unit"] for e in entries] == [
    "Unit 1: Chemistry and its Importance", "Unit 2: Measurements and Scientific Methods", "Unit 3: Structure of the Atom"]
assert [e["start_pdf_page"] for e in entries] == [7, 24, 57]

geo = []
for p in range(90):
    unit = ["ONE", "TWO", "THREE"][p // 30]
    title = {"ONE": "GEOLOGICAL HISTORY OF ETHIOPIA", "TWO": "CLIMATE OF ETHIOPIA", "THREE": "NATURAL RESOURCES"}[unit]
    geo.append(f"{title}\nUNIT {unit}\n{p}\n" + body(p) if p % 2 == 0 else f"{p}\nGrade 9| Geography\n" + body(p))
mode, entries = B.auto_units(geo, None)
assert mode == "headers" and [e["unit"] for e in entries] == [
    "Unit 1: Geological History of Ethiopia", "Unit 2: Climate of Ethiopia", "Unit 3: Natural Resources"]

openers = [f"filler {i}" for i in range(10)]
for k, title in enumerate(["Cells", "Genetics", "Ecology"]):
    openers += [f"{title}\nLearning Outcomes\nAt the end of this unit you will be able to explain things"] + [f"body {k} {i}" for i in range(15)]
mode, entries = B.auto_units(openers, None)
assert mode == "openers" and [e["unit"] for e in entries] == ["Unit 1: Cells", "Unit 2: Genetics", "Unit 3: Ecology"]

# nothing usable -> "none", never a made-up answer
assert B.auto_units(["plain text"] * 60, 5) == ("none", [])
assert B.auto_units([], 0) == ("none", [])
assert not B.plausible([{"start_pdf_page": 5, "unit": "Unit 1: A"}, {"start_pdf_page": 3, "unit": "Unit 2: B"}, {"start_pdf_page": 9, "unit": "Unit 3: C"}], 50)  # not increasing

# --- Physics-style layout: Contents lines "1 Title 1" (no dots, no word "Unit"), headers "2 Unit 1 Title",
#     openers "Unit 1 / Title / Introduction", odd pages carry a section header instead of the unit
units_p = [("Physics and Human Society", 1), ("Motion in a Straight Line", 21), ("Force and Newton's Laws", 47), ("Work, Energy and Power", 83)]
FR = 7
phys = ["Physics | Student Textbook | Grade 9", "", "", "Physics | Student Textbook | Grade 9", "iv\nFirst Published by the Ministry of Education"]
toc = ["Contents"] + [f"{k + 1} {t} {pg}\n{k + 1}.1 First section . . . . . . . . . . . . . . {pg + 1}" for k, (t, pg) in enumerate(units_p)]
phys += ["\n".join(toc[:3]), "vi CONTENTS\n" + "\n".join(toc[3:])]
for printed in range(1, 110):
    k = max(i for i, (t, pg) in enumerate(units_p) if pg <= printed); t = units_p[k][0]
    if printed in [pg for _, pg in units_p]:
        head = f"Unit {k + 1}\n{t}\nIntroduction"
    elif printed % 2 == 0:
        head = f"{printed} Unit {k + 1} {t}"
    else:
        head = f"{k + 1}.{1 + printed % 3} Some section name {printed}"
    phys.append(head + "\n" + body(printed))
mode, entries = B.auto_units(phys, FR)
want = [f"Unit {k + 1}: {t}" for k, (t, pg) in enumerate(units_p)]
assert mode == "numbered headers" and [e["unit"] for e in entries] == want and [e["start_pdf_page"] for e in entries] == [pg + FR for _, pg in units_p], (mode, entries)
assert B.units_from_contents(phys, FR) == entries                  # the Contents method gives the very same answer
no_headers = phys[:7] + [body(p) for p in range(109)]              # headers gone: the Contents alone must still work
mode_c, entries_c = B.auto_units(no_headers, FR)
assert mode_c == "contents" and entries_c == entries, (mode_c, entries_c)
no_toc = ["x"] * 5 + ["nothing", "nothing"] + phys[7:]
mode, entries2 = B.auto_units(no_toc, FR)
assert mode == "numbered headers" and entries2 == entries, (mode, entries2)
noisy = list(no_toc); noisy[20] = "Unit 4 will discuss work and energy\n" + body(0); noisy[30] = "Unit 9 Something else entirely\n" + body(0)
assert B.auto_units(noisy, FR)[1] == entries                       # stray sentences ignored

# --- Economics-like book: mixed header spellings, Unit 6 has no colon ("Unit 6 Money"), no contents page.
#     The old reader lost Unit 6 and merged it into Unit 5; every unit must now be found.
FRE = 8
econ = [(1, "Unit 1: Introducing Economics", 1), (2, "Unit 2:The Basic Economic Problems", 14), (3, "Unit 3: Economic Resources and Markets", 30),
        (4, "Unit 4: Introduction to Demand and Supply", 44), (5, "Unit 5: Introduction to Production and Cost", 56), (6, "Unit 6 Money", 72),
        (7, "Unit 7: Introduction to Macroeconomics", 83), (8, "Unit 8: Basic Entrepreneurship", 95)]
pg_e = ["Cover"] + ["credits"] * (FRE - 1) + [[u for u in econ if u[2] <= p][-1][1] + "\n" + body(p) for p in range(1, 112)]
mode, entries = B.auto_units(pg_e, FRE)
assert mode == "numbered headers" and len(entries) == 8
assert entries[5] == {"start_pdf_page": 72 + FRE, "unit": "Unit 6: Money"} and entries[1]["unit"] == "Unit 2: The Basic Economic Problems", entries

# --- IT-like book: "Unit 1 : Title" (space before the colon) and a stray UPPERCASE "UNIT 5" header on the first 2 pages
FRI = 6
itu = [(1, "Organization of Files", 1), (2, "Computer Network", 37), (3, "Application Software", 73), (4, "Image Processing", 145),
       (5, "Information and Computer Security", 193), (6, "Fundamentals of Programming", 217)]
pg_i = ["Cover"] * FRI
for p in range(1, 244):
    n, t, _ = [u for u in itu if u[2] <= p][-1]
    pg_i.append(("UNIT 5 : INFORMATION AND COMPUTER SECURITY" if p in (1, 2) else f"Unit {n} : {t}") + "\n" + body(p))
mode, entries = B.auto_units(pg_i, FRI)
assert mode == "numbered headers" and [e["unit"] for e in entries] == [f"Unit {n}: {t}" for n, t, _ in itu]
assert [e["start_pdf_page"] for e in entries] == [pg + FRI for _, _, pg in itu]      # unit 5 is NOT dragged back to page 1
# a book with a missing unit number is not accepted as complete
assert not B.plausible([e for e in entries if not e["unit"].startswith("Unit 3")], 400)
print("BOOK TOOLS TESTS PASSED (3 header styles, no-number books, scanned, 5 unit methods incl. Physics layout)")
