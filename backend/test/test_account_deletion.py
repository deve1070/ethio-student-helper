"""Account deletion (POST /v1/auth/me/delete, accounts/deletion.py) against a real SQLite database with
foreign keys switched on, so the ON DELETE rules run as they do in Postgres.
Run from backend/:   python test/test_account_deletion.py"""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db.models as M  # noqa: E402
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

import accounts.deletion as D  # noqa: E402
import api.routes_auth as R  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# nothing in a test run may touch real storage or the real Telegram group
removed_receipts: list = []
removed_from_group: list = []
D.storage.delete = lambda bucket, path: removed_receipts.append(path)
D._remove_from_private_group = lambda ids: removed_from_group.extend(ids)
R.limiter.enabled = False

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
app.include_router(R.router)
app.dependency_overrides[R.get_db] = _db
c = TestClient(app)

PASSWORD = "correcthorsebattery"
token = c.post("/v1/auth/signup", json={"phone_number": "0911223344", "password": PASSWORD, "full_name": "Sara"}).json()["access_token"]
auth = {"Authorization": f"Bearer {token}"}
db = Session()
sara = db.query(M.User).filter(M.User.phone_number == "0911223344").one()
sara_id = sara.id  # read before deletion: the object cannot be refreshed once its row is gone
friend = M.User(id=uuid.uuid4(), phone_number="0911000001", referred_by_user_id=sara.id, is_admin=False)
admin = M.User(id=uuid.uuid4(), phone_number="0911000002", is_admin=True)
db.add_all([friend, admin])
db.flush()
now = datetime.now(timezone.utc)
db.add_all([
    M.TelegramLink(telegram_user_id=555, user_id=sara.id),
    M.Subscription(user_id=sara.id, plan="yearly", status="active", current_period_end=now + timedelta(days=100)),
    M.Payment(user_id=sara.id, gateway="manual", gateway_tx_ref="tx-done", amount_etb=300, status="completed",
              receipt_photo_path="receipts/done.jpg", submitted_transaction_id="ABC"),
    M.Payment(user_id=sara.id, gateway="manual", gateway_tx_ref="tx-wait", amount_etb=300, status="pending",
              receipt_photo_path="receipts/wait.jpg"),
    M.PasswordResetCode(user_id=sara.id, code_hash="x", expires_at=now + timedelta(minutes=5)),
    M.ExamQuestionSubmission(submitted_by=sara.id, grade=12, subject="physics", raw_text="a question she sent"),
])
db.commit()

# ---- refused while referral money is waiting --------------------------------------------------
sara.referral_earned_etb = 50
db.commit()
r = c.post("/v1/auth/me/delete", json={"password": PASSWORD}, headers=auth)
check("refused with an available referral balance", r.status_code == 409 and "Withdraw" in r.json()["detail"])
db.add(M.ReferralPayout(user_id=sara.id, amount_etb=50, method="telebirr", account_number="0911223344", account_name="Sara", status="pending"))
db.commit()
r = c.post("/v1/auth/me/delete", json={"password": PASSWORD}, headers=auth)
check("refused while a payout is being sent", r.status_code == 409 and "still being sent" in r.json()["detail"])
db.query(M.ReferralPayout).update({"status": "paid"})
db.commit()

# ---- wrong password: refused, and not with 401 (which logs the web app out) -------------------
r = c.post("/v1/auth/me/delete", json={"password": "wrong-password"}, headers=auth)
check("wrong password refused with 403", r.status_code == 403)
check("account still there after refusals", db.get(M.User, sara.id) is not None)

# ---- deleted ----------------------------------------------------------------------------------
r = c.post("/v1/auth/me/delete", json={"password": PASSWORD}, headers=auth)
check("deletion accepted", r.status_code == 200 and r.json() == {"deleted": True})
db.expire_all()
check("user row gone", db.get(M.User, sara_id) is None)
check("telegram link gone", db.query(M.TelegramLink).filter(M.TelegramLink.user_id == sara_id).count() == 0)
check("subscription gone", db.query(M.Subscription).filter(M.Subscription.user_id == sara_id).count() == 0)
check("reset codes gone", db.query(M.PasswordResetCode).filter(M.PasswordResetCode.user_id == sara_id).count() == 0)
payments = db.query(M.Payment).order_by(M.Payment.gateway_tx_ref).all()
check("payments kept, without the person", len(payments) == 2 and all(p.user_id is None for p in payments))
check("payment amount and transaction id kept", {p.gateway_tx_ref for p in payments} == {"tx-done", "tx-wait"} and payments[0].submitted_transaction_id == "ABC")
check("waiting payment closed", next(p for p in payments if p.gateway_tx_ref == "tx-wait").status == "failed")
check("receipt photos removed", sorted(removed_receipts) == ["receipts/done.jpg", "receipts/wait.jpg"] and all(p.receipt_photo_path is None for p in payments))
payout = db.query(M.ReferralPayout).one()
check("paid payout record kept, without the person", payout.user_id is None and payout.status == "paid")
check("submitted exam question kept, without the person", db.query(M.ExamQuestionSubmission).one().submitted_by is None)
check("referred friend kept, link cleared", db.get(M.User, friend.id) is not None and db.get(M.User, friend.id).referred_by_user_id is None)
check("removed from the private group", 555 in removed_from_group)
check("old login token no longer works", c.get("/v1/auth/me", headers=auth).status_code == 401)

# ---- the admin views cope with a payment whose account is gone ---------------------------------
import api.routes_payments as P  # noqa: E402

papp = FastAPI()
papp.include_router(P.router)
papp.dependency_overrides[P.get_db] = _db
papp.dependency_overrides[P.require_admin] = lambda: admin
pc = TestClient(papp)
waiting = M.Payment(user_id=None, gateway="manual", gateway_tx_ref="tx-orphan", amount_etb=300, status="pending")
db.add(waiting)
db.commit()
pending = pc.get("/v1/payments/pending").json()
check("pending list shows a deleted account", any(p["student_name"] == "(deleted account)" for p in pending))
check("approving a deleted account's payment refused", pc.post(f"/v1/payments/{waiting.id}/approve").status_code == 409)

print(f"\n{failures} failure(s)")
sys.exit(1 if failures else 0)
