"""Test of the payments endpoints (/v1/payments/*): the real route with a real (SQLite) database,
a fake vision call standing in for the receipt-reading Gemini call (same stubbing convention as
test_esslce_route.py). Run from backend/:   python test/test_payments_route.py"""

import json
import os
import sys
import types
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def stub(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


stub("auth")
stub("auth.dependencies", get_current_user=lambda: None, require_admin=lambda: None)
stub("db.session", get_db=lambda: None)

# routes_payments.py builds a Gemini vision call at request time and pushes an admin notification
# over httpx - stub both so the test suite never touches a real API key or the network.
vision_state = {"response": json.dumps({"readable": False, "amount_etb": None, "transaction_id": None})}


def fake_make_gemini_vision_call(model_id, prompt):
    def call(jpg, note):
        return vision_state["response"]
    return call


stub("llm.vision", make_gemini_vision_call=fake_make_gemini_vision_call)
stub("payments.admin_notify", notify_admins_pending_payment=lambda *a, **kw: None)

import db.models as M
from sqlalchemy import ARRAY, JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

for t in M.Base.metadata.tables.values():
    for c in t.columns:
        if isinstance(c.type, (JSONB, ARRAY)):
            c.type = JSON()
engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
M.Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autoflush=False)

import api.routes_payments as R
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

db = Session()
student = M.User(id=uuid.uuid4(), full_name="Alice", is_admin=False)
admin = M.User(id=uuid.uuid4(), full_name="Admin Bob", is_admin=True)
db.add_all([student, admin])
db.commit()

app = FastAPI()
app.include_router(R.router)
app.dependency_overrides[R.get_db] = lambda: db
app.dependency_overrides[R.get_current_user] = lambda: student


def _forbidden():
    raise HTTPException(status_code=403, detail="Admin access required")


c = TestClient(app)
passed = failed = 0


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL: {label}")


# ---- submit-receipt: auto-approved when the receipt matches what was typed -------------------
vision_state["response"] = json.dumps(
    {"readable": True, "amount_etb": 25.0, "transaction_id": "ABC123"}
)
r = c.post(
    "/v1/payments/submit-receipt",
    data={"bundle": "bundle_5", "transaction_id": "abc-123"},  # dashes/case shouldn't matter
    files={"receipt": ("r.jpg", b"fake jpeg bytes", "image/jpeg")},
)
check("auto-approve status 200", r.status_code == 200)
body = r.json()
check("auto-approve completed", body["status"] == "completed")
payment_id_auto = body["payment_id"]
db.expire_all()
balance = sum(e.delta for e in db.query(M.CreditLedgerEntry).filter_by(user_id=student.id))
check("auto-approve credited 5", balance == 5)
p = db.get(M.Payment, uuid.UUID(payment_id_auto))
check("auto-approve verification_method", p.verification_method == "auto")

# ---- submit-receipt: amount mismatch falls to pending, no credits granted --------------------
vision_state["response"] = json.dumps(
    {"readable": True, "amount_etb": 10.0, "transaction_id": "XYZ999"}
)
r = c.post(
    "/v1/payments/submit-receipt",
    data={"bundle": "bundle_20", "transaction_id": "XYZ999"},
    files={"receipt": ("r.jpg", b"fake jpeg bytes", "image/jpeg")},
)
check("mismatch status 200", r.status_code == 200)
body = r.json()
check("mismatch pending", body["status"] == "pending")
payment_id_pending = body["payment_id"]
db.expire_all()
balance = sum(e.delta for e in db.query(M.CreditLedgerEntry).filter_by(user_id=student.id))
check("mismatch did not grant credits", balance == 5)  # unchanged from before

# ---- submit-receipt: unreadable receipt also falls to pending ---------------------------------
vision_state["response"] = json.dumps({"readable": False, "amount_etb": None, "transaction_id": None})
r = c.post(
    "/v1/payments/submit-receipt",
    data={"bundle": "bundle_5", "transaction_id": "WHATEVER"},
    files={"receipt": ("r.jpg", b"fake jpeg bytes", "image/jpeg")},
)
check("unreadable pending", r.json()["status"] == "pending")

# ---- unknown bundle rejected ------------------------------------------------------------------
r = c.post(
    "/v1/payments/submit-receipt",
    data={"bundle": "not_a_real_bundle", "transaction_id": "X"},
    files={"receipt": ("r.jpg", b"fake", "image/jpeg")},
)
check("unknown bundle 400", r.status_code == 400)

# ---- pending list + approve/reject: admin-only -------------------------------------------------
app.dependency_overrides[R.require_admin] = _forbidden
r = c.get("/v1/payments/pending")
check("pending list forbidden for non-admin", r.status_code == 403)
r = c.post(f"/v1/payments/{payment_id_pending}/approve")
check("approve forbidden for non-admin", r.status_code == 403)

app.dependency_overrides[R.require_admin] = lambda: admin
r = c.get("/v1/payments/pending")
check("pending list OK for admin", r.status_code == 200)
pending_ids = {row["payment_id"] for row in r.json()}
check("pending list has both pending payments", pending_ids == {payment_id_pending} | (pending_ids - {payment_id_pending}))
check("pending list count is 2", len(r.json()) == 2)

r = c.post(f"/v1/payments/{payment_id_pending}/approve")
check("manual approve OK", r.status_code == 200 and r.json()["status"] == "completed")
db.expire_all()
balance = sum(e.delta for e in db.query(M.CreditLedgerEntry).filter_by(user_id=student.id))
check("manual approve credited 20 more", balance == 25)
p = db.get(M.Payment, uuid.UUID(payment_id_pending))
check("manual approve reviewed_by set", p.reviewed_by == admin.id)

r = c.post(f"/v1/payments/{payment_id_pending}/approve")  # already completed - idempotent, not a 409
check("re-approve already-completed is idempotent", r.status_code == 200 and r.json()["status"] == "completed")

r = c.get("/v1/payments/pending")
check("one payment still pending after approving the other", len(r.json()) == 1)
remaining_id = r.json()[0]["payment_id"]
r = c.post(f"/v1/payments/{remaining_id}/reject")
check("reject OK", r.status_code == 200 and r.json()["status"] == "failed")
r = c.get("/v1/payments/pending")
check("none pending after rejecting the last one", len(r.json()) == 0)

# ---- /v1/me/credits still works, gateway-agnostic ----------------------------------------------
r = c.get("/v1/me/credits")
check("me/credits 200", r.status_code == 200)
check("me/credits balance 25", r.json()["balance"] == 25)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
