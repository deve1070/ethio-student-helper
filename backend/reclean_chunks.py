import argparse
import collections
import json
import re
import time
from pathlib import Path

BULLET = "\u2022"
BULLET_MAP = str.maketrans(
    {
        "\x83": BULLET,
        "\x84": BULLET,
        "\x8d": BULLET,
        "\x95": BULLET,
        "\uf0b7": BULLET,
        "\uf0d8": BULLET,
        "\uf0d1": BULLET,
        "\uf0a4": BULLET,
        "\uf0a7": BULLET,
        "\uf061": BULLET,
        "\uf040": BULLET,
        "\uf026": BULLET,
        "\uf09c": "",
        "\u0102": BULLET,  # OCR-mangled bullet in Economics G9 ("\u0102 Activity 6")
    }
)
PUA = re.compile(r"[\ue000-\uf8ff]")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
LINE_START_1F = re.compile(r"(?m)^\x1f[ \t]+(?=\S)")
LONE_BULLET = re.compile(r"(?m)^[ \t]*\u2022[ \t]*\n")

# ordinary repeating section lines: never learned as headers.
# "given/required/remember" are worked-example scaffolding in the Physics and
# Maths books ("Given:" / "Required:" above each solved problem); the skill
# words and a leading "§" are section headings in the English books. All of
# them repeat often enough to look like running headers, but they carry the
# structure of the lesson, so they must survive cleaning.
MARKERS = re.compile(
    r"(?i)^(activity|exercise|example|solution|brainstorming|key (concepts?|terms)|unit summary|"
    r"review (exercise|questions)|learning (outcomes|competencies)|unit outcomes|note|keywords|"
    r"introduction|summary|self.?questioning|inquiry activity|discussion|reflect|start-up activity|"
    r"at the end of this|after completing this|in a small group|answer the following|please answer|"
    r"lesson|table|figure|fig\.|question|answer|part [ivx0-9]|section|chapter|review|"
    r"given|required|remember|memor|objectives?|"
    r"grammar|writing|speaking|listening|reading|vocabulary|pronunciation|§|"
    r"unit \d+ (summary|review))"
)

W = r"(?:ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN)"
RULES: dict[str, list[tuple[re.Pattern, str]]] = {
    "agriculture": [(re.compile(r"(?m)^Agriculture Grade \d+[ \t]*\n?"), "")],
    "biology": [
        (re.compile(r"(?m)^BIOLOGY GRADE \d+\b[^\n]*\n?"), ""),  # Grade 11 caps header
        (re.compile(r"(?m)^[ \t]*Grade \d+[ \t]+Biology[ \t]*\n?"), ""),  # G9 "Grade 9 Biology"
        (
            re.compile(r"(?m)^[ \t]*\d{1,3}[ \t]*\|[ \t]*Page[ \t]*\n?"),
            "",
        ),  # Grade 12 "177|Page"
        (
            re.compile(
                r"(?m)^[ \t]*FDRE[ \t]*[-\u2013\u2014]+[ \t]*MoE\.?[ \t]*Ethiopia[ \t]*\n?"
            ),
            "",
        ),
    ],
    "chemistry": [
        (re.compile(r"(?m)^CHEMISTRY GRADE \d+[ \t]*\n?"), ""),
        (re.compile(r"(?m)^Chemistry Grade \d+[ \t]*\n?"), ""),  # G9 mixed-case header
        (
            re.compile(
                r"(?m)^(?:\d{1,3} UNIT \d{1,2}|UNIT \d{1,2} \d{1,3}|UNIT \d{1,2})[ \t]*\n?"
            ),
            "",
        ),
        (re.compile(r"(?m)^\)[ \t]*(?=\S)"), BULLET + " "),  # outcomes list bullet
        (re.compile(r"(?m)^[y~][ \t]+(?=[A-Z])"), BULLET + " "),
    ],
    "english": [
        (
            re.compile(
                r"(?m)^ENGLISH STUDENT TEXTBOOK GRADE \d+(?:[ \t]+\d{1,3})?[ \t]*\n?"
            ),
            "",
        ),
        (re.compile(r"(?m)^UNIT \d{1,2} [A-Z][^\n]{3,60}[ \t]*\n?"), ""),
        (
            re.compile(
                r"(?m)^[A-Z][A-Za-z ,&\-]{3,60}[ \t]+UNIT[ \t]+\d{1,2}[ \t]*\n?"
            ),
            "",
        ),
        (re.compile(r"(?m)^V[ \t]+(?=Activity)"), ""),
    ],
    "history": [
        (re.compile(r"(?m)^(?:TextBook|Text Book|Page|Grade \d+)[ \t]*\n?"), ""),
        # Bare lesson-number footers ("LESSON 2" alone on a line). Titled
        # lessons ("Lesson 3: ...") are real headings and survive.
        (re.compile(r"(?m)^[ \t]*LESSON[ \t]+\d+[ \t]*\n?", re.I), ""),
        (re.compile(r"(?m)^[ \t]*Student Textbook[ \t]*\n?"), ""),
        (re.compile(r"(?m)^[ \t]*Unit[ \t]*#[ \t]*\n?"), ""),
    ],
    "information_technology": [
        (
            re.compile(
                r"(?mi)^(?:\d{1,3}[ \t]+)?Informat\w*(?:[ \t]+[A-Za-z]+){1,3}(?:[ \t]+\d+[ \t]*~[ \t]*Student[ \t]+[A-Za-z]+)?(?:[ \t]+\d{1,3})?[ \t]*\n?"
            ),
            "",
        ),
        (
            re.compile(r"(?m)^(?:\d{1,3}[ \t]+)?rade \d+[ \t]*~[ \t]*Student[ \t]*\n?"),
            "",
        ),
        (re.compile(r"(?m)^[ \t]*extbook[ \t]*\n?"), ""),
        (re.compile(r"(?m)^UNIT-\d{1,2}(?:[ \t]+[A-Z][^\n]{3,80})?[ \t]*\n?"), ""),
    ],
    "economics": [
        (re.compile(r"(?m)^INTRODUCTION[ \t]+\d{1,3}[ \t]*\n?"), ""),
        (
            re.compile(r"(?m)^UNIT \d{1,2}:[ \t]*[A-Z][A-Z ,&'\u2019\-]{6,}[ \t]*\n?"),
            "",
        ),
        (
            re.compile(
                r"(?m)^[ \t]*(?:Unit Summary|Review Questions|Key Terms|Summary)[ \t]+\d{1,3}[ \t]*\n?"
            ),
            "",
        ),
    ],
    "geography": [
        (
            re.compile(
                rf"(?m)^[ \t]*UNIT(?:[ \t]+{W})?(?:[ \t]+UNIT(?:[ \t]+{W})?)+[ \t]*\n(?:{W}[ \t]*\n)?"
            ),
            "",
        ),
        (re.compile(r"(?m)^\u00bf[ \t]*"), BULLET + " "),
    ],
    "physics": [
        # Whole-line unit headers ("Unit # Simple Machines", "Unit # : ...").
        # Titled unit lines that carry page content on the SAME line survive;
        # only the bare header line is furniture.
        (re.compile(r"(?m)^[ \t]*Unit[ \t]*#[ \t]*(?::[ \t]*)?[A-Z][^\n]{2,80}\n?"), ""),
        (re.compile(r"(?m)^[ \t]*Unit[ \t]*#[ \t]*\n?"), ""),
        (re.compile(r"(?m)^[ \t]*Grade Ll[ \t]*\n?"), ""),  # G11 OCR-mangled footer
    ],
    "mathematics": [
        (re.compile(r"(?m)^[ \t]*Unit[ \t]*#:[ \t]*[A-Z][^\n]{2,80}\n?"), ""),
        (re.compile(r"(?m)^[ \t]*Unit[ \t]*#[ \t]*\n?"), ""),
    ],
    "citizenship_education": [
        (
            re.compile(
                r"(?m)^Citizenship Education (Grade \d+|Student Textbook)[^\n]*\n?"
            ),
            "",
        ),
    ],
}


def normalize(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip())


def title_rule(unit_titles: list[str]):
    """Whole-line headers made from a unit title of THIS book plus a page or unit number."""
    parts = []
    for u in unit_titles:
        m = re.match(r"^Unit\s*(\d+)\s*:\s*(.+)$", u.strip(), re.I)
        t = (m.group(2) if m else u).strip()
        if len(t) < 6:
            continue
        words = r"\s+".join(re.escape(w) for w in t.split())
        parts.append(words)
    if not parts:
        return None
    alt = "|".join(parts)
    # The three shapes of a running header built from a unit title:
    #   "Unit 3 Traffic Accident 45" / "45 Traffic Accident" / "Unit 3: Traffic Accident".
    # The page-number-first shape MUST be end-anchored: without the anchor, an
    # exercise number followed by sentence text that happens to contain the
    # title words ("4 Communicable diseases have killed...") matches and the
    # sentence loses its head. The bare-title shape is anchored for the same
    # reason: a sentence that opens with the official title is content.
    return re.compile(
        rf"(?mi)^[ \t]*(?:(?:Unit[ \t]*\d{{1,2}}[ \t]*[:|]?[ \t]*)?(?:{alt})[ \t]+\d{{1,3}}|\d{{1,3}}[ \t]+(?:{alt})[ \t]*$|Unit[ \t]*\d{{1,2}}[ \t]*[:|]?[ \t]*(?:{alt})[ \t]*$)[ \t]*\n?"
    )


SPACES = str.maketrans(
    {
        "\u00a0": " ",
        "\u2002": " ",
        "\u2003": " ",
        "\u2005": " ",
        "\u2007": " ",
        "\u2008": " ",
        "\u2009": " ",
        "\u200b": "",
    }
)


def chars_clean(text: str) -> str:
    text = text.translate(SPACES).translate(BULLET_MAP)
    text = re.sub(
        r"(?m)^[ \t]+|[ \t]+$", "", text
    )  # so the line-anchored rules below match
    text = LINE_START_1F.sub(BULLET + " ", text)
    text = PUA.sub("", text)
    return text.replace("\ufffe", "-")


def learn_headers(
    texts: list[str], min_share: float = 0.03, min_count: int = 8
) -> dict[str, int]:
    seen = collections.Counter()
    for t in texts:
        seen.update(
            {normalize(ln) for ln in t.split("\n") if 4 <= len(ln.strip()) <= 120}
        )
    thr = max(min_count, int(len(texts) * min_share))
    return {
        ln: k
        for ln, k in seen.items()
        if k >= thr
        and ln != BULLET
        and not MARKERS.match(ln)
        and re.search(r"[A-Za-z]", ln)
    }


def finish(text: str) -> str:
    text = CONTROL.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"(?m)^[ \t]+", "", text)
    text = LONE_BULLET.sub("", text + "\n").rstrip("\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def clean_book(
    texts: list[str],
    subject: str,
    unit_titles: list[str] | None = None,
    learn: bool = True,
):
    """Returns (cleaned texts, learned header lines)."""
    rules = list(RULES.get(subject, []))
    tr = title_rule(unit_titles or [])
    if tr:
        rules.append((tr, ""))
    stage1 = []
    for t in texts:
        t = chars_clean(t)
        for rx, repl in rules:
            t = rx.sub(repl, t)
        stage1.append(t)
    learned = learn_headers(stage1) if learn else {}
    out = []
    for t in stage1:
        if learned:
            t = "\n".join(ln for ln in t.split("\n") if normalize(ln) not in learned)
        out.append(finish(t))
    return out, learned


# ----------------------------------------------------------------------------- project access
def run(args):
    import chromadb
    from config import constants
    from config.settings import settings
    from db.models import Chunk, Textbook
    from db.session import SessionLocal

    client = chromadb.PersistentClient(path=settings.CHROMA_DB_PATH)
    coll = client.get_collection(constants.TEXTBOOK_COLLECTION_NAME)
    db = SessionLocal()
    emb = None
    stamp = time.strftime("%Y%m%d_%H%M")
    backup = Path(f"reclean_backup_{stamp}.jsonl")
    total_changed = 0
    try:
        q = db.query(Textbook)
        if args.grade:
            q = q.filter(Textbook.grade == args.grade)
        if args.subject:
            q = q.filter(Textbook.subject == args.subject)
        for tb in q.order_by(Textbook.grade, Textbook.subject).all():
            rows = db.query(Chunk).filter(Chunk.textbook_id == tb.id).all()
            ids = [r.vector_id for r in rows]
            docs = {}
            for i in range(0, len(ids), 500):
                got = coll.get(ids=ids[i : i + 500], include=["documents"])
                docs.update(dict(zip(got["ids"], got["documents"])))
            rows = [r for r in rows if docs.get(r.vector_id)]
            side = Path(tb.source_file_path).with_suffix(".units.json")
            titles = []
            if side.exists():
                try:
                    titles = [
                        e["unit"] for e in json.loads(side.read_text(encoding="utf-8"))
                    ]
                except Exception:
                    pass
            before = [docs[r.vector_id] for r in rows]
            after, learned = clean_book(
                before, tb.subject, titles, learn=not args.no_learned
            )
            changed = [(r, b, a) for r, b, a in zip(rows, before, after) if a != b]
            tiny = [r for r, b, a in zip(rows, before, after) if len(a) < 40]
            print(
                f"\ngrade {tb.grade} {tb.subject}: {len(changed)}/{len(rows)} chunks change; "
                f"{len(tiny)} would be under 40 characters"
            )
            for ln, k in sorted(learned.items(), key=lambda kv: -kv[1])[:8]:
                print(f"    learned header: {k:4d}x  {ln[:80]}")
            for r, b, a in changed[:2]:
                print("    --- before:", repr(b[:140]))
                print("    +++ after :", repr(a[:140]))
            total_changed += len(changed)
            if not args.apply or not changed:
                continue
            if emb is None:
                from retriever.builder import RetrieverBuilder

                emb = RetrieverBuilder().embeddings
            with backup.open("a", encoding="utf-8") as f:
                for r, b, a in changed:
                    f.write(
                        json.dumps({"id": r.vector_id, "text": b}, ensure_ascii=False)
                        + "\n"
                    )
            for i in range(0, len(changed), 64):
                part = changed[i : i + 64]
                vecs = emb.embed_documents([a for _, _, a in part])
                coll.update(
                    ids=[r.vector_id for r, _, _ in part],
                    documents=[a for _, _, a in part],
                    embeddings=vecs,
                )
                for r, _, a in part:
                    r.text_excerpt = a[:280]
                db.commit()
            print(f"    updated {len(changed)} chunks")
        print(
            f"\n{'applied' if args.apply else 'DRY RUN'}: {total_changed} chunks "
            + (
                "changed. backup: " + str(backup)
                if args.apply
                else "would change. Re-run with --apply."
            )
        )
    finally:
        db.close()


def restore(path):
    import chromadb
    from config import constants
    from config.settings import settings
    from db.models import Chunk
    from db.session import SessionLocal
    from retriever.builder import RetrieverBuilder

    coll = chromadb.PersistentClient(path=settings.CHROMA_DB_PATH).get_collection(
        constants.TEXTBOOK_COLLECTION_NAME
    )
    emb = RetrieverBuilder().embeddings
    db = SessionLocal()
    recs = [
        json.loads(l)
        for l in Path(path).read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    for i in range(0, len(recs), 64):
        part = recs[i : i + 64]
        coll.update(
            ids=[r["id"] for r in part],
            documents=[r["text"] for r in part],
            embeddings=emb.embed_documents([r["text"] for r in part]),
        )
        for r in part:
            ch = db.query(Chunk).filter(Chunk.vector_id == r["id"]).first()
            if ch:
                ch.text_excerpt = r["text"][:280]
        db.commit()
    db.close()
    print(f"restored {len(recs)} chunks")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--grade", type=int)
    ap.add_argument("--subject")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-learned", action="store_true")
    ap.add_argument("--restore")
    a = ap.parse_args()
    if a.restore:
        restore(a.restore)
    else:
        run(a)
