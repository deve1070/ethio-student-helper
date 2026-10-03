"""SQLAlchemy models matching docs/data-model-api.md section 1.

Vector embeddings live in Chroma; this schema stores the relational data
(users, entitlements, payments) plus citation metadata that lets a vector
`chunk_id` resolve into a real "Biology Gr.11, Unit 4, p.112" reference.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone_number: Mapped[str | None] = mapped_column(String, unique=True)
    email: Mapped[str | None] = mapped_column(String, unique=True)
    full_name: Mapped[str | None] = mapped_column(String)
    grade_level: Mapped[int | None] = mapped_column(SmallInteger)
    password_hash: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    telegram_link: Mapped["TelegramLink | None"] = relationship(back_populates="user", uselist=False)
    devices: Mapped[list["Device"]] = relationship(back_populates="user")
    credit_entries: Mapped[list["CreditLedgerEntry"]] = relationship(back_populates="user")
    payments: Mapped[list["Payment"]] = relationship(back_populates="user")


class TelegramLink(Base):
    __tablename__ = "telegram_links"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="telegram_link")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String, CheckConstraint("platform IN ('ios','android','web')"))
    push_token: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="devices")


class Textbook(Base):
    __tablename__ = "textbooks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grade: Mapped[int] = mapped_column(SmallInteger, CheckConstraint("grade BETWEEN 9 AND 12"))
    subject: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    edition_year: Mapped[int | None] = mapped_column(SmallInteger)
    source_file_path: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="textbook")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    textbook_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("textbooks.id", ondelete="CASCADE"))
    unit_or_chapter: Mapped[str | None] = mapped_column(String)
    section: Mapped[str | None] = mapped_column(String)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    text_excerpt: Mapped[str | None] = mapped_column(Text)
    vector_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)

    textbook: Mapped["Textbook"] = relationship(back_populates="chunks")


class ExamQuestionSubmission(Base):
    __tablename__ = "exam_question_submissions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    grade: Mapped[int | None] = mapped_column(SmallInteger)
    subject: Mapped[str | None] = mapped_column(String)
    exam_year: Mapped[int | None] = mapped_column(SmallInteger)
    raw_text: Mapped[str | None] = mapped_column(Text)
    image_path: Mapped[str | None] = mapped_column(String)
    matched_question_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExamQuestion(Base):
    __tablename__ = "exam_questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grade: Mapped[int | None] = mapped_column(SmallInteger)
    subject: Mapped[str | None] = mapped_column(String)
    exam_year: Mapped[int | None] = mapped_column(SmallInteger)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_embedding_id: Mapped[str | None] = mapped_column(String)
    times_asked: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    answers: Mapped[list["ExamAnswer"]] = relationship(back_populates="question")


class ExamAnswer(Base):
    __tablename__ = "exam_answers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exam_question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exam_questions.id", ondelete="CASCADE")
    )
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    citation_chunk_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(UUID(as_uuid=True)))
    verification_status: Mapped[str] = mapped_column(
        String, CheckConstraint("verification_status IN ('auto_verified','needs_review','human_reviewed')")
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    question: Mapped["ExamQuestion"] = relationship(back_populates="answers")


class CreditLedgerEntry(Base):
    __tablename__ = "credit_ledger"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String)
    related_exam_question_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exam_questions.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="credit_entries")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    plan: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, CheckConstraint("status IN ('active','expired','cancelled')"))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    gateway: Mapped[str | None] = mapped_column(String)
    gateway_tx_ref: Mapped[str | None] = mapped_column(String, unique=True)
    amount_etb: Mapped[float | None] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(
        String, CheckConstraint("status IN ('initiated','pending','completed','failed','refunded')")
    )
    credits_granted: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="payments")
