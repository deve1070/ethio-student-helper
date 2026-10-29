"""Study Notes & Formula Sheets: an on-demand, LLM-generated hierarchical breakdown of a textbook unit,
cached PER (grade, subject, unit) - same pattern as exams.models.EsslceElaboration. The first student to
open a topic pays the LLM call; everyone after is served this cached row for free."""

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, SmallInteger, String, Text, UniqueConstraint, func

from db.models import Base


class StudyNote(Base):
    __tablename__ = "study_notes"
    __table_args__ = (UniqueConstraint("grade", "subject", "unit", name="uq_study_note"),)

    id = Column(Integer, primary_key=True)
    grade = Column(SmallInteger, nullable=False)
    subject = Column(String(64), nullable=False)
    unit = Column(String(255), nullable=False)
    overview = Column(Text, nullable=False)  # 1-2 sentence summary of the whole unit
    sections = Column(JSON, nullable=False)  # list[{"number", "heading", "summary", "citation"}] - see
    # notes.store._numbered_sections for how "number" (e.g. "3.1", "3.1.2") is assigned
    key_formulas = Column(JSON)  # list[str] of LaTeX fragments - only ever set for a calculation subject
    worked_example = Column(Text)  # plain prose + LaTeX - only ever set for a calculation subject
    is_calculation = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
