"""Direct unit test of payments/entitlement.py's check_entitlement/record_free_action, against a
bare SQLite session - no HTTP layer, no router. Run from backend/:   python test/test_entitlement.py
Covers: subscription bypass, resource_key dedup vs. the None-never-collides "always counts" shape,
the exact quota boundary, and the check-then-charge contract (a check that's never followed by a
record - standing in for a failed generation - never consumes a slot)."""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db.models as M
from fastapi import HTTPException
from payments.entitlement import FREE_ACTION_QUOTA, check_entitlement, record_free_action
from payments.subscription import grant_or_extend_subscription
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

passed = failed = 0


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL: {label}")


def usage_count(db, user_id):
    return db.query(M.FreeActionUsage).filter_by(user_id=user_id).count()


# ---- subscription bypass: check_entitlement returns False (nothing to record) and never touches
# the quota, no matter how many free actions a subscribed user has already notionally used ---------
db = Session()
subscribed = M.User(id=uuid.uuid4(), full_name="Subscribed Sam")
db.add(subscribed)
db.commit()
grant_or_extend_subscription(db, subscribed.id)
db.commit()

needs_charge = check_entitlement(db, subscribed, "explain", None)
check("subscribed user is not charged", needs_charge is False)
check("subscribed user's check never writes a row", usage_count(db, subscribed.id) == 0)

# ---- dedup: a resource_key that's already unlocked returns False without inserting a new row -----
free_user = M.User(id=uuid.uuid4(), full_name="Free Fay")
db.add(free_user)
db.commit()

needs_charge = check_entitlement(db, free_user, "notes", "10:mathematics:Unit 1")
check("first view of a resource needs a charge", needs_charge is True)
record_free_action(db, free_user, "notes", "10:mathematics:Unit 1")
check("one row recorded", usage_count(db, free_user.id) == 1)

needs_charge = check_entitlement(db, free_user, "notes", "10:mathematics:Unit 1")
check("repeat view of the SAME resource needs no charge", needs_charge is False)
check("no second row for the same resource", usage_count(db, free_user.id) == 1)

# ---- None resource_key never dedups - Postgres (and SQLite, used here) never treats two NULLs as
# equal in a unique constraint, so every call with resource_key=None is always a fresh charge -----
for i in range(3):
    needs_charge = check_entitlement(db, free_user, "ask", None)
    check(f"ask call {i} always needs a charge (no dedup)", needs_charge is True)
    record_free_action(db, free_user, "ask", None)
check("three separate None-keyed rows recorded, none deduped", usage_count(db, free_user.id) == 4)

# ---- the exact quota boundary: 7 used -> 8th allowed -> 9th blocked, and the pool is shared
# across features (not per-feature) ------------------------------------------------------------------
boundary_user = M.User(id=uuid.uuid4(), full_name="Boundary Bo")
db.add(boundary_user)
db.commit()
for i in range(FREE_ACTION_QUOTA - 1):  # 7 of 8
    needs_charge = check_entitlement(db, boundary_user, "explain", None)
    check(f"action {i+1}/{FREE_ACTION_QUOTA} allowed", needs_charge is True)
    record_free_action(db, boundary_user, "explain", None)
check("7 used so far", usage_count(db, boundary_user.id) == FREE_ACTION_QUOTA - 1)

needs_charge = check_entitlement(db, boundary_user, "exam_solve", None)  # a DIFFERENT feature - still the 8th overall
check("8th action (a different feature) is still allowed - the pool is shared", needs_charge is True)
record_free_action(db, boundary_user, "exam_solve", None)
check("8 used", usage_count(db, boundary_user.id) == FREE_ACTION_QUOTA)

raised = None
try:
    check_entitlement(db, boundary_user, "elaborate", "some-question-id")
except HTTPException as e:
    raised = e
check("9th action raises HTTPException", raised is not None)
check("9th action is a 402", raised is not None and raised.status_code == 402)
check(
    "402 detail reports used/quota",
    raised is not None and raised.detail["used"] == FREE_ACTION_QUOTA and raised.detail["quota"] == FREE_ACTION_QUOTA,
)
check("the blocked 9th check never wrote a row", usage_count(db, boundary_user.id) == FREE_ACTION_QUOTA)

# ---- check-then-charge contract: a check that's never followed by record_free_action (standing
# in for a failed generation downstream) never consumes a slot - the caller is responsible for
# only calling record_free_action after a real success, and this must not happen automatically ----
contract_user = M.User(id=uuid.uuid4(), full_name="Contract Cal")
db.add(contract_user)
db.commit()
needs_charge = check_entitlement(db, contract_user, "exam_solve", None)
check("a checked-but-never-recorded action needs a charge per the check", needs_charge is True)
check("but nothing was actually written until record_free_action is called", usage_count(db, contract_user.id) == 0)
# simulating the real generation failing here and the caller simply never calling record_free_action
needs_charge_again = check_entitlement(db, contract_user, "exam_solve", None)
check("a second attempt after the simulated failure is still allowed - the first never counted", needs_charge_again is True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
