import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user, require_admin
from config.settings import settings
from db.models import CreditLedgerEntry, Payment, User
from db.session import get_db
from llm.vision import make_gemini_vision_call
from payments.admin_notify import notify_admins_pending_payment
from payments.entitlement import get_credit_balance, has_active_subscription
from payments.receipt_verification import (
    RECEIPT_MODEL_ID,
    RECEIPT_PROMPT,
    extract_receipt_data,
    verify_receipt,
)
from utils.logging import logger

router = APIRouter(prefix="/v1", tags=["payments"])

# Placeholder credit bundle pricing — settle alongside the Chapa vs SantimPay vs ArifPay comparison
# in docs/data-model-api.md (moot now that Chapa itself was dropped, but the pricing question
# itself is still open).
CREDIT_BUNDLES = {
    "bundle_5": {"credits": 5, "amount_etb": 25.0},
    "bundle_20": {"credits": 20, "amount_etb": 90.0},
}


class SubmitReceiptResponse(BaseModel):
    payment_id: uuid.UUID
    status: str  # 'completed' (auto-approved) | 'pending' (needs an admin)
    message: str


@router.post("/payments/submit-receipt", response_model=SubmitReceiptResponse)
def submit_receipt(
    bundle: str = Form(...),
    transaction_id: str = Form(..., description="The transaction/reference id the student read off their own receipt"),
    receipt: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SubmitReceiptResponse:
    bundle_info = CREDIT_BUNDLES.get(bundle)
    if bundle_info is None:
        raise HTTPException(status_code=400, detail=f"Unknown bundle: {bundle}")
    transaction_id = transaction_id.strip()
    if not transaction_id:
        raise HTTPException(status_code=400, detail="transaction_id is required")

    photo_bytes = receipt.file.read()
    payment = Payment(
        user_id=user.id,
        gateway="manual",
        gateway_tx_ref=f"esh_{uuid.uuid4().hex[:16]}",
        amount_etb=bundle_info["amount_etb"],
        status="pending",
        credits_granted=bundle_info["credits"],
        submitted_transaction_id=transaction_id,
    )
    db.add(payment)
    db.flush()  # need payment.id for the receipt's filename before the first commit

    receipts_dir = Path(settings.RECEIPTS_DIR)
    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipts_dir / f"{payment.id}.jpg"
    receipt_path.write_bytes(photo_bytes)
    payment.receipt_photo_path = str(receipt_path)
    db.commit()

    # Automatic check first; never guessed past what the photo actually shows (see
    # payments/receipt_verification.py) - anything it isn't confident about goes to an admin.
    try:
        vision_call = make_gemini_vision_call(RECEIPT_MODEL_ID, RECEIPT_PROMPT)
        extracted = extract_receipt_data(vision_call, photo_bytes)
        auto_approved, note = verify_receipt(extracted, transaction_id, bundle_info["amount_etb"])
    except Exception as e:  # noqa: BLE001 - a broken vision call is exactly as inconclusive as a bad read
        logger.warning(f"Receipt verification call failed for payment {payment.id}: {e}")
        auto_approved, note = False, "automatic verification could not run"

    if auto_approved:
        payment.status = "completed"
        payment.verification_method = "auto"
        payment.verification_note = note
        payment.completed_at = datetime.now(timezone.utc)
        db.add(CreditLedgerEntry(user_id=user.id, delta=payment.credits_granted, reason="purchase"))
        db.commit()
        logger.info(f"Payment {payment.id} auto-approved: {note}")
        return SubmitReceiptResponse(
            payment_id=payment.id,
            status="completed",
            message=f"Verified automatically — {bundle_info['credits']} credits added.",
        )

    payment.verification_method = "manual"
    payment.verification_note = note
    db.commit()
    notify_admins_pending_payment(
        db,
        payment_id=payment.id,
        receipt_photo_path=payment.receipt_photo_path,
        student_name=user.full_name or user.phone_number or user.email or str(user.id),
        bundle=bundle,
        amount_etb=bundle_info["amount_etb"],
        submitted_transaction_id=transaction_id,
        note=note,
    )
    return SubmitReceiptResponse(
        payment_id=payment.id,
        status="pending",
        message="Your receipt needs a quick manual check — you'll be credited once an admin confirms it.",
    )


class PendingPaymentOut(BaseModel):
    payment_id: uuid.UUID
    student_name: str
    amount_etb: float
    credits_granted: int
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
            credits_granted=p.credits_granted or 0,
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
    db.add(CreditLedgerEntry(user_id=payment.user_id, delta=payment.credits_granted, reason="purchase"))
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


class CreditsResponse(BaseModel):
    balance: int
    has_active_subscription: bool


@router.get("/me/credits", response_model=CreditsResponse)
def my_credits(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CreditsResponse:
    return CreditsResponse(
        balance=get_credit_balance(db, user.id),
        has_active_subscription=has_active_subscription(db, user.id),
    )
