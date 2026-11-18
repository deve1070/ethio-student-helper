"""Referral payouts: a student asks to be paid their referral earnings to a Telebirr or CBE account,
and an admin sends the money by hand and marks the request paid (or rejects it). The bot's
/pending_payouts command and the push in payments/admin_notify.py are the admin's side of this."""

import re
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user, require_admin
from auth.identifiers import normalize_phone
from auth.telegram_notify import send_text
from config.settings import settings
from db.models import ReferralPayout, User
from db.session import get_db
from payments.admin_notify import notify_admins_payout_request, payout_request_text
from payments.referral import referral_balance
from utils.logging import logger

router = APIRouter(prefix="/v1/referrals", tags=["referrals"])

# CBE account numbers are 13 digits; spaces and dashes typed between groups are dropped first.
_CBE_ACCOUNT = re.compile(r"\d{13}")


class PayoutOut(BaseModel):
    payout_id: uuid.UUID
    amount_etb: float
    method: str
    account_number: str
    account_name: str
    status: str
    admin_note: str | None
    created_at: datetime
    reviewed_at: datetime | None


def _payout_out(p: ReferralPayout) -> PayoutOut:
    return PayoutOut(
        payout_id=p.id,
        amount_etb=float(p.amount_etb),
        method=p.method,
        account_number=p.account_number,
        account_name=p.account_name,
        status=p.status,
        admin_note=p.admin_note,
        created_at=p.created_at,
        reviewed_at=p.reviewed_at,
    )


class PayoutSummary(BaseModel):
    reward_per_referral_etb: float
    paid_referrals: int
    earned_etb: float
    paid_etb: float
    pending_etb: float
    available_etb: float
    requests: list[PayoutOut]


def _summary(db: Session, user: User) -> PayoutSummary:
    balance = referral_balance(db, user)
    rows = (
        db.query(ReferralPayout)
        .filter(ReferralPayout.user_id == user.id)
        .order_by(ReferralPayout.created_at.desc())
        .all()
    )
    return PayoutSummary(
        reward_per_referral_etb=settings.REFERRAL_REWARD_ETB,
        paid_referrals=user.referral_paid_count,
        earned_etb=balance["earned"],
        paid_etb=balance["paid"],
        pending_etb=balance["pending"],
        available_etb=balance["available"],
        requests=[_payout_out(p) for p in rows],
    )


@router.get("/payouts", response_model=PayoutSummary)
def my_payouts(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> PayoutSummary:
    return _summary(db, user)


class PayoutRequest(BaseModel):
    method: Literal["telebirr", "cbe"]
    account_number: str = Field(..., max_length=32)
    account_name: str = Field(..., max_length=128)


@router.post("/payouts", response_model=PayoutSummary)
def request_payout(
    body: PayoutRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> PayoutSummary:
    account_name = " ".join(body.account_name.split())
    if len(account_name) < 3:
        raise HTTPException(status_code=400, detail="Enter the full name on the account.")
    if body.method == "telebirr":
        try:
            account_number = normalize_phone(body.account_number)
        except ValueError:
            raise HTTPException(status_code=400, detail="Enter your Telebirr phone number like 0912345678.")
    else:
        account_number = re.sub(r"[\s-]", "", body.account_number)
        if not _CBE_ACCOUNT.fullmatch(account_number):
            raise HTTPException(status_code=400, detail="A CBE account number has 13 digits.")

    # Lock the student's row so two requests sent at once can't both claim the same balance.
    db.query(User).filter(User.id == user.id).with_for_update().one()
    if db.query(ReferralPayout).filter(ReferralPayout.user_id == user.id, ReferralPayout.status == "pending").first():
        raise HTTPException(status_code=409, detail="You already have a payout waiting. You can request again once it's paid.")
    available = referral_balance(db, user)["available"]
    if available <= 0:
        raise HTTPException(status_code=400, detail="You have no referral earnings to withdraw yet.")

    payout = ReferralPayout(
        user_id=user.id,
        amount_etb=available,
        method=body.method,
        account_number=account_number,
        account_name=account_name,
        status="pending",
    )
    db.add(payout)
    db.commit()
    db.refresh(payout)
    logger.info(f"Referral payout {payout.id} requested by {user.id}: {available} ETB via {body.method}")

    notify_admins_payout_request(
        db,
        payout.id,
        payout_request_text(
            _student_name(user), user.phone_number or user.email, available, body.method, account_number, account_name
        ),
    )
    return _summary(db, user)


def _student_name(user: User) -> str:
    return user.full_name or user.phone_number or user.email or str(user.id)


class PendingPayoutOut(PayoutOut):
    student_name: str
    student_contact: str | None
    text: str  # the same summary the admin push shows, for the bot to print as it is


@router.get("/payouts/pending", response_model=list[PendingPayoutOut])
def pending_payouts(db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> list[PendingPayoutOut]:
    rows = (
        db.query(ReferralPayout)
        .filter(ReferralPayout.status == "pending")
        .order_by(ReferralPayout.created_at.asc())
        .all()
    )
    return [
        PendingPayoutOut(
            **_payout_out(p).model_dump(),
            student_name=_student_name(p.user),
            student_contact=p.user.phone_number or p.user.email,
            text=payout_request_text(
                _student_name(p.user),
                p.user.phone_number or p.user.email,
                float(p.amount_etb),
                p.method,
                p.account_number,
                p.account_name,
            ),
        )
        for p in rows
    ]


class ReviewBody(BaseModel):
    note: str | None = Field(None, max_length=500)


def _review(db: Session, admin: User, payout_id: uuid.UUID, status: Literal["paid", "rejected"], note: str | None) -> PayoutOut:
    payout = db.query(ReferralPayout).filter(ReferralPayout.id == payout_id).with_for_update().one_or_none()
    if payout is None:
        raise HTTPException(status_code=404, detail="Payout not found")
    if payout.status == status:
        return _payout_out(payout)  # a repeated tap on the same button
    if payout.status != "pending":
        raise HTTPException(status_code=409, detail=f"Payout is already '{payout.status}'")

    payout.status = status
    payout.admin_note = note
    payout.reviewed_by = admin.id
    payout.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    logger.info(f"Referral payout {payout.id} marked {status} by admin {admin.id}")

    amount = f"{float(payout.amount_etb):.2f} ETB"
    if status == "paid":
        message = f"Your referral payout of {amount} has been sent to your {payout.method.upper()} account {payout.account_number}."
    else:
        message = f"Your referral payout request of {amount} was not processed, and the amount is back in your balance."
    if note:
        message += f"\nNote: {note}"
    send_text(db, payout.user, message)
    return _payout_out(payout)


@router.post("/payouts/{payout_id}/paid", response_model=PayoutOut)
def mark_paid(
    payout_id: uuid.UUID, body: ReviewBody | None = None, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> PayoutOut:
    return _review(db, admin, payout_id, "paid", body.note if body else None)


@router.post("/payouts/{payout_id}/reject", response_model=PayoutOut)
def reject(
    payout_id: uuid.UUID, body: ReviewBody | None = None, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> PayoutOut:
    return _review(db, admin, payout_id, "rejected", body.note if body else None)
