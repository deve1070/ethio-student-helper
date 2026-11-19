"""Free trial, daily nudges, share cards, schools and inline-mode questions, against SQLite.
Run from backend/:   python test/test_growth.py"""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db.models as M  # noqa: E402
import db.models_practice as P  # noqa: E402
import exams.models as EM  # noqa: E402
from sqlalchemy import ARRAY, JSON, create_engine, event  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

for t in M.Base.metadata.tables.values():
    for c in t.columns:
        if isinstance(c.type, (JSONB, ARRAY)):
            c.type = JSON()
engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _foreign_keys_on(conn, _):
    conn.execute("PRAGMA foreign_keys=ON")  # SQLite ignores ON DELETE rules without this


M.Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autoflush=False)

import api.routes_auth as A  # noqa: E402
import api.routes_channel as C  # noqa: E402
import api.routes_growth as G  # noqa: E402
import api.routes_schools as S  # noqa: E402
import growth.nudges as N  # noqa: E402
from config.settings import settings  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from payments.entitlement import FREE_ACTION_QUOTA, has_active_subscription  # noqa: E402
from payments.subscription import grant_or_extend_subscription  # noqa: E402
from practice.selection import today_local  # noqa: E402

A.limiter.enabled = False
S.send_text = lambda *a, **k: True  # never message a real Telegram account from a test
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
for r in (A.router, C.router, G.router, S.router):
    app.include_router(r)
for mod in (A, C, G, S):
    app.dependency_overrides[mod.get_db] = _db
c = TestClient(app)
BOT = {"Authorization": f"Bearer {settings.BOT_INTERNAL_TOKEN}"}
db = Session()
now = datetime.now(timezone.utc)
today = today_local()


def signup(phone, name="Student", **extra):
    r = c.post("/v1/auth/signup", json={"phone_number": phone, "password": "longenoughpassword", "full_name": name, **extra})
    assert r.status_code in (200, 201), r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def link(phone, tg):
    return c.post("/v1/auth/telegram-link", json={"telegram_user_id": tg, "identifier": phone, "password": "longenoughpassword"}).json()


def user(phone):
    db.expire_all()
    return db.query(M.User).filter(M.User.phone_number == phone).one()


# ================================ 2. free trial ================================
signup("0911100001", "Abel Tesfaye")
r = link("0911100001", 1001)
abel = user("0911100001")
check("first link starts the trial", r["trial_ends_at"] is not None and has_active_subscription(db, abel.id))
sub = db.query(M.Subscription).filter(M.Subscription.user_id == abel.id).one()
check("trial is a 7-day subscription marked trial", sub.plan == "trial" and timedelta(days=6, hours=23) < (sub.current_period_end.replace(tzinfo=timezone.utc) - now) <= timedelta(days=7, minutes=1))
check("linking again gives no second trial", link("0911100001", 1001)["trial_ends_at"] is None and db.query(M.Subscription).filter(M.Subscription.user_id == abel.id).count() == 1)
signup("0911100002")
check("same Telegram account on another number: no trial", link("0911100002", 1001)["trial_ends_at"] is None)
signup("0911100003")
paid = user("0911100003")
grant_or_extend_subscription(db, paid.id, timedelta(days=365))
db.commit()
check("already subscribed: no trial", link("0911100003", 1003)["trial_ends_at"] is None)
# deleting the account and signing up again with the same number: no second trial
db.query(M.TelegramLink).filter(M.TelegramLink.user_id == abel.id).delete()
db.delete(user("0911100001"))
db.commit()
signup("0911100001")
check("deleted and signed up again: no second trial", link("0911100001", 1009)["trial_ends_at"] is None)
check("trial record outlives the account", db.query(M.FreeTrial).filter(M.FreeTrial.identifier == "0911100001").one().user_id is None)

# paying during a trial turns it into a paid year
signup("0911100004")
link("0911100004", 1004)
t4 = user("0911100004")
grant_or_extend_subscription(db, t4.id, timedelta(days=365))
db.commit()
sub = db.query(M.Subscription).filter(M.Subscription.user_id == t4.id).one()
check("paying during the trial: plan becomes yearly, trial days kept on top", sub.plan == "yearly" and (sub.current_period_end.replace(tzinfo=timezone.utc) - now).days >= 371)

# ================================ 5. nudges ================================
db.query(M.NudgeSent).delete()
db.commit()


def make_linked(phone, tg, **fields):
    signup(phone)
    link(phone, tg)
    u = user(phone)
    for k, v in fields.items():
        setattr(u, k, v)
    db.commit()
    return u


def set_trial(u, ends_in_days):
    trial = db.query(M.FreeTrial).filter(M.FreeTrial.user_id == u.id).one()
    trial.ends_at = now + timedelta(days=ends_in_days)
    trial.started_at = trial.ends_at - timedelta(days=7)
    sub = db.query(M.Subscription).filter(M.Subscription.user_id == u.id).one()
    sub.current_period_end = trial.ends_at
    db.commit()


ending = make_linked("0911200001", 2001)
set_trial(ending, 2)
ended = make_linked("0911200002", 2002)
set_trial(ended, -1)
exam = make_linked("0911200003", 2003, exam_date=today + timedelta(days=30))
db.query(M.Subscription).filter(M.Subscription.user_id == exam.id).delete()  # no trial in the way
db.commit()
previews = make_linked("0911200004", 2004)
db.query(M.Subscription).filter(M.Subscription.user_id == previews.id).delete()
for i in range(FREE_ACTION_QUOTA):
    db.add(M.FreeActionUsage(user_id=previews.id, feature="explain", created_at=now - timedelta(days=3)))
idle = make_linked("0911200005", 2005)
book = M.Textbook(grade=9, subject="chemistry", title="Chem 9", source_file_path="x")
db.add(book)
db.commit()
q = P.QuizQuestion(textbook_id=book.id, grade=9, subject="chemistry", question="q", options=["a", "b", "c", "d"], answer_index=0,
                   explanation="e", supporting_quote="s", content_hash=uuid.uuid4().hex)
db.add(q)
db.commit()
db.add(P.QuizAttempt(user_id=idle.id, question_id=q.id, chosen_index=0, is_correct=True, created_at=now - timedelta(days=3)))
quiet = make_linked("0911200006", 2006, nudges_off=True)
set_trial(quiet, 2)
db.commit()

r = c.post("/v1/growth/nudges", headers=BOT)
by_tg = {n["telegram_user_id"]: n for n in r.json()["nudges"]}
check("needs the bot token", c.post("/v1/growth/nudges").status_code in (401, 403))
check("trial ending in 2 days", by_tg.get(2001, {}).get("kind") == "trial_ending" and by_tg[2001]["days_left"] == 2)
check("trial ended yesterday", by_tg.get(2002, {}).get("kind") == "trial_ended")
check("exam in 30 days", by_tg.get(2003, {}).get("kind") == "countdown" and by_tg[2003]["days_left"] == 30)
check("free previews used up 3 days ago", by_tg.get(2004, {}).get("kind") == "previews_used")
check("no practice for 3 days", by_tg.get(2005, {}).get("kind") == "inactive" and by_tg[2005]["days_away"] == 3)
check("turned off: nothing", 2006 not in by_tg)
check("first name and price included", by_tg[2001]["first_name"] == "Student" and by_tg[2001]["price_etb"] == settings.SUBSCRIPTION_PRICE_ETB)
again = c.post("/v1/growth/nudges", headers=BOT).json()["nudges"]
check("one a day: nothing more the same day", again == [])
# the next day: each moment was sent once, so it is not sent again
db.query(M.NudgeSent).update({M.NudgeSent.sent_on: today - timedelta(days=1)})
db.commit()
later = {n["telegram_user_id"]: n["kind"] for n in N.due_nudges(Session(), today)}
check("each moment sent only once", all(later.get(tg) != kind for tg, kind in ((2001, "trial_ending"), (2003, "countdown"), (2005, "inactive"))))
h = signup("0911200007")
c.post("/v1/growth/nudges-setting", json={"off": True}, headers=h)
check("a student can turn nudges off", user("0911200007").nudges_off is True)

# ================================ 6. schools ================================
admin = M.User(id=uuid.uuid4(), phone_number="0911999999", is_admin=True)
db.add(admin)
db.commit()
app.dependency_overrides[S.require_admin] = lambda: admin
r = c.post("/v1/schools", json={"name": "  Menelik  II  School "})
check("admin adds a school, spaces tidied", r.status_code == 200 and r.json()["name"] == "Menelik II School")
check("same school twice refused", c.post("/v1/schools", json={"name": "menelik ii school"}).status_code == 409)
school_id = r.json()["id"]
signup("0911300001", "Amb")
r = c.post("/v1/schools/ambassador", json={"identifier": "+251911300001", "school": "Menelik II School"})
check("admin names an ambassador by phone in any format", r.status_code == 200 and user("0911300001").is_ambassador and user("0911300001").school_id == school_id)
code = r.json()["referral_code"]
h2 = signup("0911300002", referral_code=code)
check("signing up with an ambassador's code joins their school", user("0911300002").school_id == school_id)
other = c.post("/v1/schools", json={"name": "Lideta School"}).json()["id"]
h3 = signup("0911300003")
r = c.patch("/v1/auth/me", json={"school_id": other}, headers=h3)
check("student picks a school on Profile", r.status_code == 200 and r.json()["school_name"] == "Lideta School")
check("unknown school refused", c.patch("/v1/auth/me", json={"school_id": 999}, headers=h3).status_code == 400)
check("school kept when another field changes", c.patch("/v1/auth/me", json={"daily_goal_minutes": 60}, headers=h3).json()["school_id"] == other)
check("school cleared with null", c.patch("/v1/auth/me", json={"school_id": None}, headers=h3).json()["school_id"] is None)
c.patch("/v1/auth/me", json={"school_id": other}, headers=h3)
for u_phone, n in (("0911300002", 5), ("0911300001", 2), ("0911300003", 4)):
    for _ in range(n):
        db.add(P.QuizAttempt(user_id=user(u_phone).id, question_id=q.id, chosen_index=0, is_correct=True))
db.commit()
ranking = c.get("/v1/schools/weekly-ranking", headers=BOT).json()["schools"]
check("weekly ranking by questions answered", ranking == [
    {"school": "Menelik II School", "answered": 7, "active_students": 2},
    {"school": "Lideta School", "answered": 4, "active_students": 1},
])
ov = {s["name"]: s for s in c.get("/v1/schools/overview").json()["schools"]}
check("admin overview with ambassadors", ov["Menelik II School"]["students"] == 2 and ov["Menelik II School"]["ambassadors"] == ["Amb"])
check("schools listed for students", [s["name"] for s in c.get("/v1/schools", headers=h3).json()] == ["Lideta School", "Menelik II School"])

# ================================ 4. share cards ================================
r = c.get("/v1/growth/share", params={"kind": "week"}, headers=h2)
card = r.json()
check("week card with numbers and the student's referral link", r.status_code == 200 and "5 ESSLCE-style questions" in card["text"] and f"ref={user('0911300002').referral_code}" in card["link"] and "src=share" in card["link"])
check("Telegram share link carries both", card["share_url"].startswith("https://t.me/share/url?url=https%3A%2F%2F") and "&text=This%20week" in card["share_url"])
check("nothing to share without practice", c.get("/v1/growth/share", params={"kind": "week"}, headers=signup("0911300009")).status_code == 404)
paper = EM.EsslcePaper(subject="biology", year_ec=2016, year_gc=2024)
db.add(paper)
db.commit()
eq = [EM.EsslceQuestion(paper_id=paper.id, item_no=i, stem=f"Which is true {i}?", options=["a", "b", "c", "d"], answer_index=0,
                        answer_source="manual", review_status="approved") for i in range(1, 4)]
db.add_all(eq)
db.commit()
mc = EM.MassChallenge(date=datetime(today.year, today.month, today.day), subject="biology", unit="Cells", question_ids=[x.id for x in eq],
                      opens_at=datetime.utcnow(), question_seconds=60)
db.add(mc)
db.commit()
u2 = user("0911300002")
for x, ok in zip(eq, (True, True, False)):
    db.add(EM.EsslceAttempt(user_id=u2.id, question_id=x.id, paper_id=paper.id, chosen_index=0, is_correct=ok, mode="mass", mass_challenge_id=mc.id))
db.commit()
r = c.get("/v1/growth/share", params={"kind": "mass", "challenge_id": mc.id}, headers=h2)
check("evening result card", r.status_code == 200 and r.json()["text"].startswith("I got 2/3 in tonight's ESSLCE Biology practice"))
check("no card for a challenge they skipped", c.get("/v1/growth/share", params={"kind": "mass", "challenge_id": mc.id}, headers=h3).status_code == 404)

# ================================ 3. inline questions ================================
chem = EM.EsslcePaper(subject="chemistry", year_ec=2015, year_gc=2023)
db.add(chem)
db.commit()
db.add_all([
    EM.EsslceQuestion(paper_id=chem.id, item_no=1, stem="Which gas is a noble gas?", options=["Neon", "Oxygen", "Nitrogen", "Hydrogen"],
                      answer_index=0, answer_source="manual", review_status="approved", explanation="Neon is in group 18."),
    EM.EsslceQuestion(paper_id=chem.id, item_no=2, stem="Solve $x^2$", options=["a", "b", "c", "d"], answer_index=0, answer_source="manual", review_status="approved"),
])
db.commit()
res = c.get("/v1/channel/inline-questions", params={"q": "chem"}, headers=BOT).json()
check("subject words narrow the search; maths left out", [r["stem"] for r in res] == ["Which gas is a noble gas?"] and "answer_index" not in res[0] and "correct_index" not in res[0])
res = c.get("/v1/channel/inline-questions", params={"q": "bio true 2"}, headers=BOT).json()
check("other words must appear in the question", [r["stem"] for r in res] == [] or all("true" in r["stem"] for r in res))
check("empty search gives a mix", len(c.get("/v1/channel/inline-questions", headers=BOT).json()) == 4)
noble = db.query(EM.EsslceQuestion).filter(EM.EsslceQuestion.stem == "Which gas is a noble gas?").one()
key = c.get(f"/v1/channel/answer-key/{noble.id}", headers=BOT).json()
check("answer key for a tap", key == {"correct_index": 0, "explanation": "Neon is in group 18."})
check("config carries the group price", c.get("/v1/auth/public-config").json()["group_min_students"] == settings.GROUP_MIN_STUDENTS)

print(f"\n{failures} failure(s)")
sys.exit(1 if failures else 0)
