"""Referral count crediting: called from api/routes_payments.py at the two places a Payment is ever
marked 'completed' (the auto-approve path in submit_receipt, and the manual approve_payment) - not a
separate third code path, so the "did this referral count yet" logic never has to be kept in sync by
hand across both."""

from sqlalchemy.orm import Session

from auth.telegram_notify import send_text
from db.models import Payment, User


def credit_referral_if_first_payment(db: Session, payment: Payment) -> None:
    """Increments the referrer's referral_paid_count by exactly one, the moment the user they referred
    completes their FIRST payment ever - never on a later purchase by the same student, and never at
    signup (entering a code alone earns nothing). A plain counter, not a credit/cash reward - see
    docs/dev_plans/referrals_password_reset_help.md."""
    user = payment.user if payment.user is not None else db.get(User, payment.user_id)
    if user is None or user.referred_by_user_id is None:
        return

    earlier_completed = (
        db.query(Payment)
        .filter(
            Payment.user_id == user.id,
            Payment.status == "completed",
            Payment.id != payment.id,
        )
        .count()
    )
    if earlier_completed > 0:
        return  # not their first completed payment - already counted (or never will be)

    referrer = db.get(User, user.referred_by_user_id)
    if referrer is None:
        return
    referrer.referral_paid_count += 1
    send_text(
        db,
        referrer,
        "Good news - a student you referred just became a paying student! "
        f"You've now referred {referrer.referral_paid_count} paying student(s).",
    )
