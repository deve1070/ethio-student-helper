"""Referral count crediting: called from api/routes_payments.py at the two places a Payment is ever
marked 'completed' (the auto-approve path in submit_receipt, and the manual approve_payment) - not a
separate third code path, so the "did this referral count yet" logic never has to be kept in sync by
hand across both."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from auth.telegram_notify import send_text
from config.settings import settings
from db.models import Payment, ReferralPayout, User


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
    referrer.referral_earned_etb = float(referrer.referral_earned_etb or 0) + settings.REFERRAL_REWARD_ETB
    send_text(
        db,
        referrer,
        "Good news - a student you referred just became a paying student! "
        f"You've now referred {referrer.referral_paid_count} paying student(s).",
    )


def referral_balance(db: Session, user: User) -> dict[str, float]:
    """earned: every referral reward so far. paid and pending: payout requests already sent or still
    waiting for an admin. available: what the student can request now. A rejected request is in none
    of these, so its amount counts as available again."""
    totals = dict(
        db.query(ReferralPayout.status, func.coalesce(func.sum(ReferralPayout.amount_etb), 0))
        .filter(ReferralPayout.user_id == user.id, ReferralPayout.status.in_(("pending", "paid")))
        .group_by(ReferralPayout.status)
        .all()
    )
    earned = float(user.referral_earned_etb or 0)
    paid = float(totals.get("paid", 0))
    pending = float(totals.get("pending", 0))
    return {"earned": earned, "paid": paid, "pending": pending, "available": max(earned - paid - pending, 0.0)}
