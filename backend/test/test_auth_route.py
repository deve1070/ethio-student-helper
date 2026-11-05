"""Test of the auth endpoints (/v1/auth/*): signup/login/telegram-link, email validation, and the
slowapi rate limit on credential-checking routes. Real (SQLite) database, no stubs needed - nothing in
this path calls an LLM or external service. Run from backend/:   python test/test_auth_route.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db.models as M
from sqlalchemy import ARRAY, JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

for t in M.Base.metadata.tables.values():
    for c in t.columns:
        if isinstance(c.type, (JSONB, ARRAY)):
            c.type = JSON()
engine = create_engine(
    "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
)
M.Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autoflush=False)

import api.routes_auth as R
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _db():
    s = Session()
    try:
        yield s
    finally:
        s.close()


app = FastAPI()
app.include_router(R.router)
app.dependency_overrides[R.get_db] = _db
c = TestClient(app)

# ---- 1. signup: happy path, duplicate rejected, bad email rejected, weak password rejected --------------------
r = c.post(
    "/v1/auth/signup",
    json={"email": "alice@example.com", "password": "correcthorsebattery"},
)
assert r.status_code == 200 and r.json()["access_token"], r.text
token = r.json()["access_token"]

r = c.post(
    "/v1/auth/signup",
    json={"email": "alice@example.com", "password": "anotherlongpassword"},
)
assert r.status_code == 409, r.text  # same email twice

r = c.post("/v1/auth/signup", json={"email": "not-an-email", "password": "longenough123"})
assert r.status_code == 422 and "email" in str(r.json()["detail"]), r.text

r = c.post("/v1/auth/signup", json={"email": "bob@example.com", "password": "short"})
assert r.status_code == 422, r.text  # under min_length=8

r = c.post("/v1/auth/signup", json={"password": "longenough123"})
assert r.status_code == 422, r.text  # neither phone nor email given

# ---- 2. login: happy path, wrong password rejected -------------------------------------------------------------
r = c.post(
    "/v1/auth/login", json={"identifier": "alice@example.com", "password": "correcthorsebattery"}
)
assert r.status_code == 200 and r.json()["access_token"], r.text

r = c.post("/v1/auth/login", json={"identifier": "alice@example.com", "password": "wrong"})
assert r.status_code == 401, r.text

# ---- 3. telegram-link: same credential check, links a telegram_user_id to the account --------------------------
r = c.post(
    "/v1/auth/telegram-link",
    json={"telegram_user_id": 999, "identifier": "alice@example.com", "password": "correcthorsebattery"},
)
assert r.status_code == 200, r.text

# ---- 3b. /streams: the static natural/social/common partition ---------------------------------------------------
r = c.get("/v1/auth/streams")
b = r.json()
assert set(b["natural_only"]) == {"biology", "chemistry", "physics"}
assert set(b["social_only"]) == {"economics", "geography", "history"}
assert set(b["common"]) == {"english", "scholastic_aptitude_test", "mathematics"}

# ---- 3c. /me (GET/PATCH): real bearer-token auth, no stub - onboarding profile fields ------------------------------
auth_headers = {"Authorization": f"Bearer {token}"}
r = c.get("/v1/auth/me", headers=auth_headers)
assert r.status_code == 200 and r.json()["onboarding_completed"] is False, r.text

r = c.get("/v1/auth/me")  # no header at all
assert r.status_code in (401, 403), r.text  # HTTPBearer itself rejects a missing credential

r = c.patch("/v1/auth/me", json={"grade_level": 12, "stream": "natural_science"}, headers=auth_headers)
b = r.json()
assert r.status_code == 200 and b["grade_level"] == 12 and b["stream"] == "natural_science"
assert b["onboarding_completed"] is True  # any call here marks it seen

# a social-only subject is rejected once a natural_science stream is set
r = c.patch("/v1/auth/me", json={"subjects_selected": ["physics", "history"]}, headers=auth_headers)
assert r.status_code == 400 and "history" in r.json()["detail"], r.text

r = c.patch("/v1/auth/me", json={"subjects_selected": ["physics", "mathematics"]}, headers=auth_headers)
b = r.json()
assert r.status_code == 200 and set(b["subjects_selected"]) == {"physics", "mathematics"}

r = c.patch("/v1/auth/me", json={"exam_date": "2026-11-30", "daily_goal_minutes": 60}, headers=auth_headers)
b = r.json()
assert r.status_code == 200 and b["exam_date"] == "2026-11-30" and b["daily_goal_minutes"] == 60

# ---- 3d. referral codes: every signup gets one; an optional code at signup links the two accounts ----
assert len(b["referral_code"]) == 8 and b["referral_code"].isupper() and b["referral_paid_count"] == 0

r = c.post("/v1/auth/signup", json={"email": "carol@example.com", "password": "longenough123"})
assert r.status_code == 200, r.text
carol_token, carol_id = r.json()["access_token"], r.json()["user_id"]
carol_code = c.get("/v1/auth/me", headers={"Authorization": f"Bearer {carol_token}"}).json()["referral_code"]

r = c.post(
    "/v1/auth/signup",
    json={"email": "dave@example.com", "password": "longenough123", "referral_code": carol_code},
)
assert r.status_code == 200, r.text

# an unknown code blocks signup outright - no account is created
r = c.post(
    "/v1/auth/signup",
    json={"email": "erin@example.com", "password": "longenough123", "referral_code": "NOTREAL1"},
)
assert r.status_code == 400 and "referral code" in r.json()["detail"].lower(), r.text

db2 = Session()
assert db2.query(M.User).filter(M.User.email == "erin@example.com").one_or_none() is None
dave = db2.query(M.User).filter(M.User.email == "dave@example.com").one()
assert str(dave.referred_by_user_id) == carol_id, (dave.referred_by_user_id, carol_id)

# ---- 3e. password reset via Telegram: only works for a student with a linked account (alice, from
# section 3) - the Telegram push itself is stubbed (no real network call), capturing whatever 6-digit
# code the real endpoint generated so this test uses the REAL code rather than a hardcoded one --------
import re as _re

sent_codes: dict[str, str] = {}


def _fake_send_text(db, user, text):
    # Mirrors auth/telegram_notify.py's own "no linked chat -> nothing sent" check (the real reason
    # to stub is only to avoid a live network call to Telegram, not to skip that check).
    if db.query(M.TelegramLink).filter(M.TelegramLink.user_id == user.id).first() is None:
        return False
    m = _re.search(r"\b(\d{6})\b", text)
    sent_codes[str(user.id)] = m.group(1) if m else None
    return True


R.send_text = _fake_send_text

r = c.post("/v1/auth/password-reset/request", json={"identifier": "alice@example.com"})
assert r.status_code == 200 and r.json()["status"] == "code_sent", r.text
alice = db2.query(M.User).filter(M.User.email == "alice@example.com").one()
code = sent_codes[str(alice.id)]
assert code and len(code) == 6, sent_codes

r = c.post(
    "/v1/auth/password-reset/confirm",
    json={"identifier": "alice@example.com", "code": "000000", "new_password": "newlongpassword1"},
)
assert r.status_code == 401, r.text  # wrong code

r = c.post(
    "/v1/auth/password-reset/confirm",
    json={"identifier": "alice@example.com", "code": code, "new_password": "newlongpassword1"},
)
assert r.status_code == 200 and r.json()["access_token"], r.text  # right code logs the student in

# confirm the password actually changed - checked directly (not via /login, which has its own
# separately-tracked rate limit the next section's exact counting depends on)
from auth.security import verify_password

db2.expire_all()
alice = db2.query(M.User).filter(M.User.email == "alice@example.com").one()
assert not verify_password("correcthorsebattery", alice.password_hash)  # old password no longer works
assert verify_password("newlongpassword1", alice.password_hash)  # new password does

r = c.post(
    "/v1/auth/password-reset/confirm",
    json={"identifier": "alice@example.com", "code": code, "new_password": "yetanotherpw2"},
)
assert r.status_code == 401, r.text  # single-use: the same code can't be replayed

# carol has no linked Telegram account - same response as "no account at all", on purpose
r = c.post("/v1/auth/password-reset/request", json={"identifier": "carol@example.com"})
assert r.status_code == 200 and r.json()["status"] == "no_telegram_link", r.text
assert carol_id not in sent_codes

r = c.post("/v1/auth/password-reset/request", json={"identifier": "nosuchuser@example.com"})
assert r.status_code == 200 and r.json()["status"] == "no_telegram_link", r.text

# ---- 4. rate limiting: /login allows 5 attempts per minute per IP, then 429 (burns remaining capacity, do last) -
# section 2 already spent 2 of the 5 (one success, one failure) - 3 more get through before 429 kicks in
codes = []
for _ in range(7):
    r = c.post("/v1/auth/login", json={"identifier": "alice@example.com", "password": "wrong"})
    codes.append(r.status_code)
assert codes == [401, 401, 401, 429, 429, 429, 429], codes

print("AUTH ROUTE TESTS PASSED")
