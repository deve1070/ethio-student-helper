import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import storage
from auth.dependencies import get_current_user, require_admin
from config.settings import settings
from db.models import FreeActionUsage, Payment, Subscription, User
from db.session import get_db
from llm.vision import make_gemini_vision_call
from payments.admin_notify import notify_admins_pending_payment
from payments.entitlement import FREE_ACTION_QUOTA, has_active_subscription
from payments.referral import credit_referral_if_first_payment
from payments.subscription import grant_or_extend_subscription
from payments.receipt_verification import (
    RECEIPT_MODEL_ID,
    RECEIPT_PROMPT,
    extract_receipt_data,
    verify_receipt,
)
from utils.logging import logger

router = APIRouter(prefix="/v1", tags=["payments"])

# The one plan this app sells: a full year of unlimited AI access for a single payment. Kept as
# an explicit id/amount pair (not a bare constant) so a second plan could be added later without
# submit_receipt's `plan` field becoming a magic implicit default.
SUBSCRIPTION_PLAN = {"id": "yearly", "amount_etb": 300.0}


class SubmitReceiptResponse(BaseModel):
    payment_id: uuid.UUID
    status: str  # 'completed' (auto-approved) | 'pending' (needs an admin)
    message: str


@router.post("/payments/submit-receipt", response_model=SubmitReceiptResponse)
def submit_receipt(
    plan: str = Form(SUBSCRIPTION_PLAN["id"]),
    transaction_id: str = Form(..., description="The transaction/reference id the student read off their own receipt"),
    receipt: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SubmitReceiptResponse:
    if plan != SUBSCRIPTION_PLAN["id"]:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {plan}")
    amount_etb = SUBSCRIPTION_PLAN["amount_etb"]
    transaction_id = transaction_id.strip()
    if not transaction_id:
        raise HTTPException(status_code=400, detail="transaction_id is required")

    photo_bytes = receipt.file.read()
    payment = Payment(
        user_id=user.id,
        gateway="manual",
        gateway_tx_ref=f"esh_{uuid.uuid4().hex[:16]}",
        amount_etb=amount_etb,
        status="pending",
        submitted_transaction_id=transaction_id,
    )
    db.add(payment)
    db.flush()  # need payment.id for the receipt's filename before the first commit

    receipt_path = f"{settings.RECEIPTS_DIR}/{payment.id}.jpg"
    storage.upload("receipts", receipt_path, photo_bytes)
    payment.receipt_photo_path = receipt_path
    db.commit()

    # Automatic check first; never guessed past what the photo actually shows (see
    # payments/receipt_verification.py) - anything it isn't confident about goes to an admin.
    try:
        vision_call = make_gemini_vision_call(RECEIPT_MODEL_ID, RECEIPT_PROMPT)
        extracted = extract_receipt_data(vision_call, photo_bytes)
        auto_approved, note = verify_receipt(extracted, transaction_id, amount_etb)
    except Exception as e:  # noqa: BLE001 - a broken vision call is exactly as inconclusive as a bad read
        logger.warning(f"Receipt verification call failed for payment {payment.id}: {e}")
        auto_approved, note = False, "automatic verification could not run"

    if auto_approved:
        payment.status = "completed"
        payment.verification_method = "auto"
        payment.verification_note = note
        payment.completed_at = datetime.now(timezone.utc)
        grant_or_extend_subscription(db, user.id)
        credit_referral_if_first_payment(db, payment)
        db.commit()
        logger.info(f"Payment {payment.id} auto-approved: {note}")
        return SubmitReceiptResponse(
            payment_id=payment.id,
            status="completed",
            message="Verified automatically — your year of unlimited access is active.",
        )

    payment.verification_method = "manual"
    payment.verification_note = note
    db.commit()
    notify_admins_pending_payment(
        db,
        payment_id=payment.id,
        receipt_photo_bytes=photo_bytes,
        student_name=user.full_name or user.phone_number or user.email or str(user.id),
        plan=plan,
        amount_etb=amount_etb,
        submitted_transaction_id=transaction_id,
        note=note,
    )
    return SubmitReceiptResponse(
        payment_id=payment.id,
        status="pending",
        message="Your receipt needs a quick manual check — your subscription starts once an admin confirms it.",
    )


class PendingPaymentOut(BaseModel):
    payment_id: uuid.UUID
    student_name: str
    amount_etb: float
    submitted_transaction_id: str | None
    verification_note: str | None
    created_at: datetime


@router.get("/payments/pending", response_model=list[PendingPaymentOut])
def list_pending_payments(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[PendingPaymentOut]:
    rows = (
        db.query(Payment)
        .filter(Payment.status == "pending")
        .order_by(Payment.created_at.asc())
        .all()
    )
    return [
        PendingPaymentOut(
            payment_id=p.id,
            student_name=p.user.full_name or p.user.phone_number or p.user.email or str(p.user_id),
            amount_etb=float(p.amount_etb or 0),
            submitted_transaction_id=p.submitted_transaction_id,
            verification_note=p.verification_note,
            created_at=p.created_at,
        )
        for p in rows
    ]


class ReviewResponse(BaseModel):
    payment_id: uuid.UUID
    status: str


@router.post("/payments/{payment_id}/approve", response_model=ReviewResponse)
def approve_payment(
    payment_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ReviewResponse:
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.status == "completed":
        return ReviewResponse(payment_id=payment.id, status="completed")  # already done, retried callback
    if payment.status != "pending":
        raise HTTPException(status_code=409, detail=f"Payment is '{payment.status}', not pending")

    payment.status = "completed"
    payment.reviewed_by = admin.id
    payment.completed_at = datetime.now(timezone.utc)
    grant_or_extend_subscription(db, payment.user_id)
    credit_referral_if_first_payment(db, payment)
    db.commit()
    logger.info(f"Payment {payment.id} manually approved by admin {admin.id}")
    return ReviewResponse(payment_id=payment.id, status="completed")


@router.post("/payments/{payment_id}/reject", response_model=ReviewResponse)
def reject_payment(
    payment_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ReviewResponse:
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.status == "failed":
        return ReviewResponse(payment_id=payment.id, status="failed")
    if payment.status != "pending":
        raise HTTPException(status_code=409, detail=f"Payment is '{payment.status}', not pending")

    payment.status = "failed"
    payment.reviewed_by = admin.id
    db.commit()
    logger.info(f"Payment {payment.id} manually rejected by admin {admin.id}")
    return ReviewResponse(payment_id=payment.id, status="failed")


class EntitlementResponse(BaseModel):
    has_active_subscription: bool
    subscription_expires_at: datetime | None
    free_actions_used: int
    free_actions_quota: int


@router.get("/me/entitlement", response_model=EntitlementResponse)
def my_entitlement(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EntitlementResponse:
    active = has_active_subscription(db, user.id)
    sub = (
        db.query(Subscription)
        .filter(Subscription.user_id == user.id, Subscription.status == "active")
        .order_by(Subscription.current_period_end.desc())
        .first()
    )
    used = db.scalar(
        select(func.count(FreeActionUsage.id)).where(FreeActionUsage.user_id == user.id)
    )
    return EntitlementResponse(
        has_active_subscription=active,
        subscription_expires_at=sub.current_period_end if (active and sub) else None,
        free_actions_used=used or 0,
        free_actions_quota=FREE_ACTION_QUOTA,
    )
