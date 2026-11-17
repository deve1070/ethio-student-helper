"""Referral payouts (/v1/referrals/*) against a real SQLite database, plus the phone/email
normalization that signup and login share. Run from backend/:   python test/test_referral_payouts.py"""

import os
import sys
import types
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth.identifiers import normalize_identifier, normalize_phone  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("PASS " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


# ---- identifiers -------------------------------------------------------------------------------
for typed in ["0912345678", "0912 345 678", "0912-345-678", "+251912345678", "251 912 345 678", "912345678", "(0912) 34 56 78"]:
    check(f"phone {typed!r} -> 0912345678", normalize_phone(typed) == "0912345678")
check("Safaricom 07 number kept", normalize_phone("+251 712 345 678") == "0712345678")
for bad in ["0812345678", "091234567", "09123456789", "abc", "+1 555 123 4567"]:
    try:
        normalize_phone(bad)
        check(f"phone {bad!r} rejected", False)
    except ValueError:
        check(f"phone {bad!r} rejected", True)
check("email lowercased", normalize_identifier("  Name@Gmail.COM ") == "name@gmail.com")
check("phone identifier normalized", normalize_identifier("+251 953 392 118") == "0953392118")
check("unknown text left alone", normalize_identifier(" hello ") == "hello")


# ---- payouts -----------------------------------------------------------------------------------
def stub(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


sent: list = []
admin_pushes: list = []
stub("auth.dependencies", get_current_user=lambda: None, require_admin=lambda: None)
stub("db.session", get_db=lambda: None)
stub("auth.telegram_notify", send_text=lambda db, user, text: sent.append((user.id, text)) or True)

import payments.admin_notify as AN  # noqa: E402

AN.notify_admins_payout_request = lambda db, payout_id, text: admin_pushes.append((payout_id, text))

import db.models as M  # noqa: E402
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
db = sessionmaker(bind=engine, autoflush=False)()

import api.routes_referrals as R  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

R.notify_admins_payout_request = AN.notify_admins_payout_request

student = M.User(id=uuid.uuid4(), full_name="Sara", phone_number="0911000000", referral_paid_count=3, is_admin=False)
admin = M.User(id=uuid.uuid4(), full_name="Admin", is_admin=True)
db.add_all([student, admin])
db.commit()

current = {"user": student}
app = FastAPI()
app.include_router(R.router)
app.dependency_overrides[R.get_db] = lambda: db
app.dependency_overrides[R.get_current_user] = lambda: current["user"]


def _admin_only():
    if not current["user"].is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current["user"]


app.dependency_overrides[R.require_admin] = _admin_only
client = TestClient(app)

s = client.get("/v1/referrals/payouts").json()
check("3 paid referrals earn 150", s["earned_etb"] == 150 and s["available_etb"] == 150)

r = client.post("/v1/referrals/payouts", json={"method": "telebirr", "account_number": "0812", "account_name": "Sara A"})
check("bad Telebirr number rejected", r.status_code == 400 and "0912345678" in r.json()["detail"])
r = client.post("/v1/referrals/payouts", json={"method": "cbe", "account_number": "1000 123", "account_name": "Sara A"})
check("short CBE account rejected", r.status_code == 400 and "13 digits" in r.json()["detail"])
r = client.post("/v1/referrals/payouts", json={"method": "cbe", "account_number": "1000123456789", "account_name": "S"})
check("missing account name rejected", r.status_code == 400)

r = client.post("/v1/referrals/payouts", json={"method": "telebirr", "account_number": "+251 911 22 33 44", "account_name": " Sara  Abebe "})
s = r.json()
check("request accepted for the full balance", r.status_code == 200 and s["pending_etb"] == 150 and s["available_etb"] == 0)
req = s["requests"][0]
check("Telebirr number stored normalized", req["account_number"] == "0911223344" and req["account_name"] == "Sara Abebe")
check("admins notified with amount and account", admin_pushes and "150.00 ETB" in admin_pushes[-1][1] and "0911223344" in admin_pushes[-1][1])

r = client.post("/v1/referrals/payouts", json={"method": "telebirr", "account_number": "0911223344", "account_name": "Sara Abebe"})
check("second request while one is pending refused", r.status_code == 409)

check("student can't list pending payouts", client.get("/v1/referrals/payouts/pending").status_code == 403)
check("student can't mark paid", client.post(f"/v1/referrals/payouts/{req['payout_id']}/paid").status_code == 403)

current["user"] = admin
pending = client.get("/v1/referrals/payouts/pending").json()
check("admin sees the pending payout with account", len(pending) == 1 and pending[0]["account_number"] == "0911223344" and pending[0]["amount_etb"] == 150)
check("admin list carries the student contact", pending[0]["student_contact"] == "0911000000")

r = client.post(f"/v1/referrals/payouts/{req['payout_id']}/reject", json={"note": "Name doesn't match"})
check("admin rejects", r.status_code == 200 and r.json()["status"] == "rejected")
check("student told about the rejection", sent and "back in your balance" in sent[-1][1] and "Name doesn't match" in sent[-1][1])
check("paid after reject refused", client.post(f"/v1/referrals/payouts/{req['payout_id']}/paid").status_code == 409)

current["user"] = student
s = client.get("/v1/referrals/payouts").json()
check("rejected amount available again", s["available_etb"] == 150 and s["pending_etb"] == 0)
s = client.post("/v1/referrals/payouts", json={"method": "cbe", "account_number": "1000-1234-56789", "account_name": "Sara Abebe"}).json()
second = next(r for r in s["requests"] if r["status"] == "pending")
check("CBE account stored as digits", second["account_number"] == "1000123456789")

current["user"] = admin
check("admin marks paid", client.post(f"/v1/referrals/payouts/{second['payout_id']}/paid").json()["status"] == "paid")
check("repeated tap is harmless", client.post(f"/v1/referrals/payouts/{second['payout_id']}/paid").status_code == 200)
check("student told it was sent", "has been sent to your CBE account 1000123456789" in sent[-1][1])

current["user"] = student
s = client.get("/v1/referrals/payouts").json()
check("paid amount counted as withdrawn", s["paid_etb"] == 150 and s["available_etb"] == 0)
r = client.post("/v1/referrals/payouts", json={"method": "telebirr", "account_number": "0911223344", "account_name": "Sara Abebe"})
check("nothing left to withdraw", r.status_code == 400)

student.referral_paid_count = 4
db.commit()
check("a new referral makes 50 available", client.get("/v1/referrals/payouts").json()["available_etb"] == 50)

print(f"\n{failures} failure(s)")
sys.exit(1 if failures else 0)
