"""
Smoke test for the /v1/explain endpoint.

    python smoke_test.py                      # all cases, server at 127.0.0.1:8000
    python smoke_test.py --url http://127.0.0.1:8000 --pause 20
    python smoke_test.py --only fungi,trends  # run cases whose name contains these words
    python smoke_test.py --cases physics_g12.json   # add cases for a new book (see below)

Extra cases file (JSON list; every key except name/grade/subject/question is optional):
    [{"name": "newton2", "grade": 12, "subject": "physics",
      "question": "State Newton's second law of motion.",
      "any_of": ["acceleration"], "pages": [41, 42], "must_not": ["invented phrase"]},
     {"name": "no-data-phys", "grade": 12, "subject": "physics",
      "question": "Who wrote Hamlet?", "expect": "no_data"}]
"pages" are PRINTED page numbers; "expect" may be "no_data" or "http400".

Each case checks (as far as it applies):
  - the answer contains the expected key words,
  - none of the "must NOT contain" phrases appear (these are things the model
    once invented that are NOT in the textbook),
  - at least one citation points at a page where the answer really is
    (printed page numbers),
  - questions the books don't cover return the "no data" message,
  - a mistyped subject returns HTTP 400 with a suggestion.

--pause waits between requests so the free Groq tier (8,000 tokens/minute) is
not exceeded. Lower it if you are on a paid tier. Needs only the standard library.
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request

NO_DATA = "isn't related"

CASES = [
    # name, grade, subject, question, any_of (keywords), must_not (phrases), pages (any of), expect
    dict(name="fungi", grade=9, subject="biology", question="What are fungi?",
         any_of=["hyphae"], pages={33, 34}),
    dict(name="repro-compare", grade=9, subject="biology",
         question="What is the difference between asexual and sexual reproduction?",
         any_of=["gamete"], pages={75, 81},
         must_not=["requires a mate", "energy cost", "dependence on fertilization"]),
    dict(name="photosynthesis-bio", grade=9, subject="biology", question="How does photosynthesis work?",
         any_of=["chlorophyll"], pages={34, 51, 52}),
    dict(name="subset", grade=9, subject="mathematics",
         question="What is the difference between a proper subset and a subset?",
         any_of=["proper subset"], pages={9, 10, 11}),
    dict(name="polygon-angles", grade=9, subject="mathematics",
         question="What is the formula for the sum of interior angles of a polygon?",
         any_of=["180"], pages={219}),
    dict(name="adverbs", grade=9, subject="english", question="What are adverbs of frequency?",
         any_of=["always", "never"], pages={44, 45, 46},
         must_not=["every time", "hardly ever", "now and then"]),
    dict(name="chem-definition", grade=9, subject="chemistry", question="What is the definition of chemistry?",
         any_of=["properties"], pages={2, 3, 15}),
    dict(name="trends", grade=9, subject="chemistry", question="What are the trends in the periodic table?",
         any_of=["electronegativity", "electron affinity"], pages={133, 134, 136}),
    dict(name="soil-erosion", grade=9, subject="geography",
         question="What are the causes of soil erosion in Ethiopia?",
         any_of=["steep slopes", "rainstorm"], pages={60, 174}),
    dict(name="no-data-chem", grade=9, subject="chemistry", question="What is photosynthesis?", expect="no_data"),
    dict(name="no-data-maths", grade=9, subject="mathematics", question="Who won the 2022 World Cup?", expect="no_data"),
    dict(name="typo-subject", grade=9, subject="chemisty", question="What is chemistry?",
         expect="http400", any_of=["chemistry"]),
]


def load_cases(path):
    cases = json.load(open(path, encoding="utf-8"))
    for c in cases:
        for key in ("name", "grade", "subject", "question"):
            if key not in c:
                sys.exit(f"{path}: every case needs '{key}' (problem in {c.get('name', c)})")
        if "pages" in c:
            c["pages"] = set(c["pages"])
    return cases


def pages_of(citations):
    out = set()
    for c in citations:
        nums = [int(n) for n in re.findall(r"\d+", str(c.get("page", "")))]
        if len(nums) == 2 and nums[0] <= nums[1] <= nums[0] + 30:
            out.update(range(nums[0], nums[1] + 1))
        else:
            out.update(nums)
    return out


def call(url, case, timeout):
    body = json.dumps({"grade": case["grade"], "subject": case["subject"], "question": case["question"]}).encode()
    req = urllib.request.Request(url + "/v1/explain", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def evaluate(case, status, data):
    """Returns a list of problems (empty list = PASS)."""
    problems = []
    expect = case.get("expect", "answer")
    if expect == "http400":
        if status != 400:
            return [f"expected HTTP 400, got {status}"]
        detail = json.dumps(data).lower()
        return [] if all(k in detail for k in case.get("any_of", [])) else ["400 message has no suggestion"]
    if status != 200:
        return [f"HTTP {status}: {str(data)[:120]}"]
    answer = data.get("answer", "")
    low = answer.lower()
    if expect == "no_data":
        if NO_DATA not in low:
            problems.append("expected the 'no data' message but got an answer")
        if data.get("citations"):
            problems.append("no-data reply should have no citations")
        return problems
    if NO_DATA in low:
        return ["got the 'no data' message for a question the book covers"]
    if case.get("any_of") and not any(k.lower() in low for k in case["any_of"]):
        problems.append(f"none of the key words {case['any_of']} in the answer")
    for bad in case.get("must_not", []):
        if bad.lower() in low:
            problems.append(f"contains invented phrase: '{bad}'")
    if case.get("pages") and not (pages_of(data.get("citations", [])) & case["pages"]):
        problems.append(f"no citation on expected pages {sorted(case['pages'])} "
                        f"(cited: {sorted(pages_of(data.get('citations', [])))})")
    if "could not be checked" in low:
        problems.append("answer was returned UNVERIFIED (verifier unavailable)")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--pause", type=float, default=15.0, help="seconds between requests")
    ap.add_argument("--timeout", type=float, default=240.0)
    ap.add_argument("--only", default="", help="comma-separated words; run cases whose name contains one")
    ap.add_argument("--cases", action="append", default=[], help="JSON file with extra cases (repeatable)")
    ap.add_argument("--skip-builtin", action="store_true", help="run only the cases from --cases files")
    args = ap.parse_args()
    wanted = [w.strip() for w in args.only.split(",") if w.strip()]
    all_cases = ([] if args.skip_builtin else list(CASES))
    for path in args.cases:
        all_cases += load_cases(path)
    cases = [c for c in all_cases if not wanted or any(w in c["name"] for w in wanted)]

    failed = 0
    for i, case in enumerate(cases, 1):
        t0 = time.time()
        try:
            status, data = call(args.url, case, args.timeout)
            if status == 503:  # service busy: wait and try once more
                time.sleep(30)
                status, data = call(args.url, case, args.timeout)
            problems = evaluate(case, status, data)
        except Exception as e:  # server down, timeout...
            problems = [f"request failed: {e}"]
        mark = "PASS" if not problems else "FAIL"
        failed += bool(problems)
        print(f"[{i:>2}/{len(cases)}] {mark}  {case['name']:<20} ({time.time() - t0:4.0f}s)")
        for p in problems:
            print(f"        - {p}")
        if i < len(cases):
            time.sleep(args.pause)
    print(f"\n{len(cases) - failed}/{len(cases)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
