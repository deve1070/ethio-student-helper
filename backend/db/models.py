import secrets
import uuid
from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# Same unambiguous alphabet as auth/referral.py's generate_referral_code. This Python-side column
# default (not a DB-side one, same pattern as User.id below) only ever fires when a User is
# constructed WITHOUT an explicit referral_code - the real signup route (api/routes_auth.py) always
# passes generate_referral_code(db)'s own DB-collision-checked value instead, since that function (not
# this one) is the one source of truth that checks uniqueness before handing out a code. This default
# exists so the many test fixtures and scripts across this project that construct User(...) directly
# don't all need to learn about referral codes just to satisfy the NOT NULL constraint.
def _unchecked_referral_code() -> str:
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    return "".join(secrets.choice(alphabet) for _ in range(8))


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "stream IN ('natural_science','social_science')", name="ck_user_stream"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    phone_number: Mapped[str | None] = mapped_column(String, unique=True)
    email: Mapped[str | None] = mapped_column(String, unique=True)
    full_name: Mapped[str | None] = mapped_column(String)
    grade_level: Mapped[int | None] = mapped_column(SmallInteger)
    password_hash: Mapped[str | None] = mapped_column(String)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Onboarding profile (grades 11-12 only pick a stream - see config.constants stream sets; exam_date is
    # meaningful for grade 12 ESSLCE-takers only, left null for everyone else).
    stream: Mapped[str | None] = mapped_column(String)
    subjects_selected: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    exam_date: Mapped[date | None] = mapped_column(Date)
    daily_goal_minutes: Mapped[int | None] = mapped_column(Integer)
    # Set the first time the onboarding wizard is finished OR explicitly skipped - distinguishes "never
    # seen it" from "chose to skip", so the app never re-nags a student who opted out on purpose.
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Referrals (see auth/referral.py): every user gets their own code at signup, generated once and
    # never changed. referred_by_user_id is set only if a NEW user entered someone else's code at their
    # own signup - never retroactively, and never edited afterward. referral_paid_count is a plain
    # counter, not a derived/joined value - it only ever increments, from payments/referral.py, at the
    # moment a referred user's FIRST payment completes (never at signup, never on a second purchase).
    referral_code: Mapped[str] = mapped_column(
        String(16), unique=True, nullable=False, default=_unchecked_referral_code
    )
    referred_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    referral_paid_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Total referral rewards earned, each added at the reward in force when it was earned, so changing
    # settings.REFERRAL_REWARD_ETB later never rewrites what a student already earned.
    referral_earned_etb: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, server_default="0")
    # Where the student came from when they signed up, from the web app's ?src= link tag (e.g.
    # "channel" for the channel posts' buttons); NULL when they arrived without one.
    signup_source: Mapped[str | None] = mapped_column(String(32))
    # Bot messages at chosen moments (growth/nudges.py); a student can turn them off from the bot.
    nudges_off: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    # The student's school, for the weekly top-schools post (growth/schools.py). An ambassador is
    # a student an admin put in charge of bringing their school in; students who sign up with an
    # ambassador's referral code join the ambassador's school.
    school_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("schools.id", ondelete="SET NULL"))
    is_ambassador: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    telegram_link: Mapped["TelegramLink | None"] = relationship(
        back_populates="user", uselist=False
    )
    devices: Mapped[list["Device"]] = relationship(back_populates="user")
    credit_entries: Mapped[list["CreditLedgerEntry"]] = relationship(
        back_populates="user"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="user", foreign_keys="Payment.user_id"
    )


class TelegramLink(Base):
    __tablename__ = "telegram_links"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="telegram_link")


class PasswordResetCode(Base):
    """A short-lived code pushed to a student's linked Telegram chat (auth/telegram_notify.py) so they
    can set a new password without an email/SMS provider - see auth/routes_auth.py's
    /password-reset/request and /confirm. code_hash, never the plain code, is stored at rest - the
    same bcrypt helpers (auth/security.py) used for real passwords, since a reset code is a short-lived
    credential too. Append-only in practice (a new request invalidates the previous row for that user
    rather than reusing it), same style as Payment/EsslceAttempt."""

    __tablename__ = "password_reset_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    platform: Mapped[str] = mapped_column(
        String, CheckConstraint("platform IN ('ios','android','web')")
    )
    push_token: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="devices")


class Textbook(Base):
    __tablename__ = "textbooks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    grade: Mapped[int] = mapped_column(
        SmallInteger, CheckConstraint("grade BETWEEN 9 AND 12")
    )
    subject: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    edition_year: Mapped[int | None] = mapped_column(SmallInteger)
    source_file_path: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="textbook")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    textbook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("textbooks.id", ondelete="CASCADE")
    )
    unit_or_chapter: Mapped[str | None] = mapped_column(String)
    section: Mapped[str | None] = mapped_column(String)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    text_excerpt: Mapped[str | None] = mapped_column(Text)
    vector_id: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )

    textbook: Mapped["Textbook"] = relationship(back_populates="chunks")


class ExamQuestionSubmission(Base):
    __tablename__ = "exam_question_submissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    grade: Mapped[int | None] = mapped_column(SmallInteger)
    subject: Mapped[str | None] = mapped_column(String)
    exam_year: Mapped[int | None] = mapped_column(SmallInteger)
    raw_text: Mapped[str | None] = mapped_column(Text)
    image_path: Mapped[str | None] = mapped_column(String)
    matched_question_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ExamQuestion(Base):
    __tablename__ = "exam_questions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    grade: Mapped[int | None] = mapped_column(SmallInteger)
    subject: Mapped[str | None] = mapped_column(String)
    exam_year: Mapped[int | None] = mapped_column(SmallInteger)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_embedding_id: Mapped[str | None] = mapped_column(String)
    times_asked: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    answers: Mapped[list["ExamAnswer"]] = relationship(back_populates="question")


class ExamAnswer(Base):
    __tablename__ = "exam_answers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    exam_question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exam_questions.id", ondelete="CASCADE")
    )
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    citation_chunk_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True))
    )
    verification_status: Mapped[str] = mapped_column(
        String,
        CheckConstraint(
            "verification_status IN ('auto_verified','needs_review','human_reviewed')"
        ),
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    question: Mapped["ExamQuestion"] = relationship(back_populates="answers")


class CreditLedgerEntry(Base):
    __tablename__ = "credit_ledger"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String)
    related_exam_question_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exam_questions.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="credit_entries")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    plan: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(
        String, CheckConstraint("status IN ('active','expired','cancelled')")
    )
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FreeActionUsage(Base):
    """One row per free AI action a non-subscribed student has used, across every gated feature -
    see payments/entitlement.py's check_entitlement/record_free_action, the single shared pool
    this backs. `resource_key` is non-null only for features that dedup repeat access to the same
    resource (notes: f"{grade}:{subject}:{unit}", elaborate: str(question_id)); features where
    every call is a genuinely new one (explain, ask, exam_solve) always pass None - Postgres never
    treats two NULLs as equal in a unique constraint, so those rows never collide/dedup, which is
    exactly the desired "always counts" behavior with no special-casing in application code."""

    __tablename__ = "free_action_usage"
    __table_args__ = (
        CheckConstraint(
            "feature IN ('notes','elaborate','ask','explain','exam_solve')",
            name="ck_free_action_usage_feature",
        ),
        UniqueConstraint("user_id", "feature", "resource_key", name="uq_free_action_usage"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    feature: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_key: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ReferralPayout(Base):
    """A student's request to be paid what they earned from referrals (payments/referral.py). The
    amount is fixed when the request is made: the whole balance available at that moment. A request
    is 'pending' until an admin sends the money by hand and marks it 'paid', or marks it 'rejected',
    which returns the amount to the student's balance."""

    __tablename__ = "referral_payouts"
    __table_args__ = (
        CheckConstraint("method IN ('telebirr','cbe')", name="ck_referral_payout_method"),
        CheckConstraint("status IN ('pending','paid','rejected')", name="ck_referral_payout_status"),
        CheckConstraint("amount_etb > 0", name="ck_referral_payout_amount"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # SET NULL, not CASCADE: a deleted account's payout records stay, as a record of money sent
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    amount_etb: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    account_number: Mapped[str] = mapped_column(String(32), nullable=False)
    account_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    # what the admin wrote when closing it: the transfer reference when paid, the reason when rejected
    admin_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User | None"] = relationship(foreign_keys=[user_id])


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # SET NULL, not CASCADE: a deleted account's payments stay (amount, dates, transaction id) as the
    # business's record of money received; only the link to the person goes
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    gateway: Mapped[str | None] = mapped_column(String)  # always 'manual' now - see esh_payments_manual_receipt
    gateway_tx_ref: Mapped[str | None] = mapped_column(String, unique=True)
    amount_etb: Mapped[float | None] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(
        String,
        CheckConstraint(
            "status IN ('initiated','pending','completed','failed','refunded')"
        ),
    )
    credits_granted: Mapped[int | None] = mapped_column(Integer)
    # Manual-receipt fields: a student submits a photo + the transaction id they claim it shows;
    # payments/receipt_verification.py tries to confirm both against what the photo actually says,
    # and only ever auto-completes the payment when that check is confident - otherwise it stays
    # 'pending' with verification_note explaining why, for a human admin to decide instead of guessing.
    receipt_photo_path: Mapped[str | None] = mapped_column(String)
    submitted_transaction_id: Mapped[str | None] = mapped_column(String)
    verification_method: Mapped[str | None] = mapped_column(String)  # 'auto' | 'manual'
    verification_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # explicit foreign_keys: payments now has two FKs to users (user_id, reviewed_by) - without
    # this, SQLAlchemy can't tell which one backs the student-facing "whose payment is this" side
    user: Mapped["User | None"] = relationship(back_populates="payments", foreign_keys=[user_id])


class School(Base):
    """A school students can belong to (growth/schools.py). Added by an admin from the bot."""

    __tablename__ = "schools"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FreeTrial(Base):
    """One free trial ever per phone/email and per Telegram account (growth/trial.py). Not linked to
    the user by a deleting foreign key: the record outlives the account, so deleting an account and
    signing up again with the same number does not give a second trial."""

    __tablename__ = "free_trials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identifier: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)  # normalized phone or email
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NudgeSent(Base):
    """A bot message sent at a chosen moment (growth/nudges.py), so each is sent once and a student
    gets at most one a day. `key` names the moment, e.g. "countdown:30" or "inactive:2026-11-16"."""

    __tablename__ = "nudges_sent"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_nudge_user_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    sent_on: Mapped[date] = mapped_column(Date, nullable=False)  # local date
