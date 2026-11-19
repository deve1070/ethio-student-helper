"""The channel quiz picker (api/routes_channel.py) and signup-source tracking (api/routes_auth.py)
against SQLite.   Run from backend/:   python test/test_channel_posts.py"""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db.models as M  # noqa: E402
import exams.models as EM  # noqa: E402
from sqlalchemy import ARRAY, JSON, create_engine  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

for t in M.Base.metadata.tables.values():
    for c in t.columns:
        if isinstance(c.type, (JSONB, ARRAY)):
            c.type = JSON()
engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
M.Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autoflush=False)

import api.routes_auth as A  # noqa: E402
import api.routes_channel as C  # noqa: E402
from config.settings import settings  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

A.limiter.enabled = False
failures = 0


def check(name, cond):
    global failures
    print(("PASS " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


def _db():
    s = Session()
    try:
        yield s
    finally:
        s.close()


app = FastAPI()
app.include_router(A.router)
app.include_router(C.router)
app.dependency_overrides[A.get_db] = _db
app.dependency_overrides[C.get_db] = _db
c = TestClient(app)
BOT = {"Authorization": f"Bearer {settings.BOT_INTERNAL_TOKEN}"}

db = Session()
paper = EM.EsslcePaper(subject="biology", year_ec=2016, year_gc=2024)
db.add(paper)
db.commit()
passage = EM.EsslcePassage(paper_id=paper.id, passage_key="P1", text="A story.")
db.add(passage)
db.commit()


def mk(item_no, stem, options=("a", "b", "c", "d"), **kw):
    q = EM.EsslceQuestion(paper_id=paper.id, item_no=item_no, stem=stem, options=list(options), answer_index=1,
                          answer_source="manual", review_status=kw.pop("review_status", "approved"), **kw)
    db.add(q)
    db.commit()
    return q


good = mk(1, "Which organelle makes ATP?", ["Ribosome", "Mitochondrion", "Nucleus", "Vacuole"], explanation="It is the site of respiration.")
mk(2, "Not approved yet", review_status="needs_review")
mk(3, "Has a figure", has_diagram=True)
mk(4, "About the story", passage_id=passage.id)
mk(5, "Which word is closest in meaning to the underlined word?", underlined=["swift"])
mk(6, "Solve $x^2 = 4$")
mk(7, "Too long " * 40)
mk(8, "Options too long", ["x" * 101, "b", "c", "d"])
recent = mk(9, "Posted last week", channel_posted_at=datetime.now(timezone.utc) - timedelta(days=7))

# ---- only the one question that fits a poll is picked, and it is marked posted
check("needs the bot token", c.post("/v1/channel/question-of-the-day").status_code in (401, 403))
r = c.post("/v1/channel/question-of-the-day", headers=BOT)
b = r.json()
check("picks the question that fits a poll", r.status_code == 200 and b["question_id"] == good.id, )
check("sends what the poll needs", b["options"][1] == "Mitochondrion" and b["correct_index"] == 1 and b["subject"] == "biology" and b["year_ec"] == 2016)
check("plain explanation included", b["explanation"] == "It is the site of respiration.")
db.expire_all()
check("marked posted", db.get(EM.EsslceQuestion, good.id).channel_posted_at is not None)
r = c.post("/v1/channel/question-of-the-day", headers=BOT)
check("not posted again soon: nothing left", r.status_code == 404)
q = db.get(EM.EsslceQuestion, recent.id)
q.channel_posted_at = datetime.now(timezone.utc) - timedelta(days=200)
q.explanation = "Because \\( x = 2 \\)"
db.commit()
r = c.post("/v1/channel/question-of-the-day", headers=BOT)
check("posted long ago: can be picked again; maths explanation left out", r.status_code == 200 and r.json()["question_id"] == recent.id and r.json()["explanation"] is None)

# ---- signup source: stored from the link tag, a malformed one dropped
def signup(phone, source):
    body = {"phone_number": phone, "password": "longenoughpassword", "full_name": "S"}
    if source is not None:
        body["signup_source"] = source
    return c.post("/v1/auth/signup", json=body)


check("signup with a tag", signup("0911000011", "Channel").status_code in (200, 201))
signup("0911000012", "channel")
signup("0911000013", None)
check("malformed tag does not block signup", signup("0911000014", "<script>").status_code in (200, 201))
db.expire_all()
by_phone = {u.phone_number: u.signup_source for u in db.query(M.User).all()}
check("tag stored lowercased", by_phone["0911000011"] == "channel" and by_phone["0911000012"] == "channel")
check("no tag and malformed tag stored as nothing", by_phone["0911000013"] is None and by_phone["0911000014"] is None)

admin = M.User(id=uuid.uuid4(), phone_number="0911000099", is_admin=True)
db.add(admin)
paid = db.query(M.User).filter(M.User.phone_number == "0911000011").one()
db.add(M.Subscription(user_id=paid.id, plan="yearly", status="active", current_period_end=datetime.now(timezone.utc) + timedelta(days=30)))
db.commit()
app.dependency_overrides[A.require_admin] = lambda: admin
r = c.get("/v1/auth/signup-sources", params={"days": 30})
sources = {s["source"]: (s["signups"], s["subscribed"]) for s in r.json()["sources"]}
check("counts per source with subscribers", sources["channel"] == (2, 1) and sources["(none)"] == (3, 0), )
check("public config carries the web app address", c.get("/v1/auth/public-config").json()["web_app_url"].startswith("https://"))

print(f"\n{failures} failure(s)")
sys.exit(1 if failures else 0)
