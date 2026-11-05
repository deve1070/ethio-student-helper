"""Study Notes & Formula Sheets: an on-demand, LLM-generated hierarchical breakdown of a textbook unit,
cached PER (grade, subject, unit) - same pattern as exams.models.EsslceElaboration. The first student to
open a topic pays the LLM call; everyone after is served this cached row for free."""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from db.models import Base


class StudyNote(Base):
    __tablename__ = "study_notes"
    __table_args__ = (UniqueConstraint("grade", "subject", "unit", name="uq_study_note"),)

    id = Column(Integer, primary_key=True)
    grade = Column(SmallInteger, nullable=False)
    subject = Column(String(64), nullable=False)
    unit = Column(String(255), nullable=False)
    overview = Column(Text, nullable=False)  # 1-2 sentence summary of the whole unit
    sections = Column(JSON, nullable=False)  # list[{"number", "heading", "summary", "examples", "citation"}]
    # - see notes.store._numbered_sections for how "number" (e.g. "3.1", "3.1.2") is assigned. "examples"
    # (list[str], each a full worked example with LaTeX) is only ever populated for a calculation subject
    # (notes.store.CALC_UNIT_PROMPT) - empty for every other subject.
    is_calculation = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class StudyNoteView(Base):
    """Records that ONE student has opened a unit's Study Note - unlike StudyNote above (a global cache,
    shared by every student who ever asked for that unit), this is per-student, so it's the only signal
    anywhere in the app for "has this student actually studied X" independent of practice-attempt history
    (a student could ace practice from outside knowledge without ever opening notes, or read the notes and
    not yet have practiced). Used by studyplan/profile.py's curriculum-coverage calculation. Recorded by
    api/routes_notes.py the first time `/note` successfully serves this (user, grade, subject, unit)."""

    __tablename__ = "study_note_views"
    __table_args__ = (UniqueConstraint("user_id", "grade", "subject", "unit", name="uq_study_note_view"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    grade = Column(SmallInteger, nullable=False)
    subject = Column(String(64), nullable=False)
    unit = Column(String(255), nullable=False)
    first_viewed_at = Column(DateTime(timezone=True), server_default=func.now())
