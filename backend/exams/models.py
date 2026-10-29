"""Tables for the national exam (ESSLCE) bank.

NAMES: everything here is prefixed esslce_ / Esslce on purpose. The project already has an `exam_questions` table and an
`ExamQuestion` class (the exam SOLVER's answer cache, in db/models.py); defining the same names again makes SQLAlchemy
refuse to start ("Table 'exam_questions' is already defined").
 Separate from the practice-question tables on purpose:
exam questions are for Grade 12 exam takers and are tied to a paper (subject, stream, year, round, region,
delivery_mode) and an item number; practice questions are generated for Grades 9-12 and are tied to a textbook chunk.

Nothing here references quiz_questions or the exam-solver cache. Links to textbooks are SUGGESTIONS (esslce_topic_links), not provenance.

The declarative Base is imported from your project; if yours lives elsewhere, change the one import below.
Create the tables once with:   python -m exams.cli create-tables      (or add an Alembic migration from these)
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

try:
    from db.models import (
        Base,
    )  # <- ADJUST if your Base is defined in db/session.py or db/base.py
except ImportError:  # pragma: no cover
    from db.session import Base

REVIEW_STATES = ("needs_key", "needs_review", "approved", "rejected")


class EsslcePaper(Base):
    __tablename__ = "esslce_papers"
    id = Column(Integer, primary_key=True)
    subject = Column(String(64), nullable=False, index=True)
    stream = Column(
        String(32), nullable=False, default=""
    )  # "natural_science" | "social_science" | "" (common paper)
    year_ec = Column(Integer, nullable=False)
    year_gc = Column(Integer)
    round = Column(
        String(16), nullable=False, default=""
    )  # "" or e.g. "first" / "second" when a year has several
    region = Column(
        String(32), nullable=False, default=""
    )  # "" (national) | e.g. "tigray" - EAES occasionally gives a region its own sitting, not every year
    delivery_mode = Column(
        String(16), nullable=False, default=""
    )  # "" (paper) | "online" - introduced alongside paper delivery starting 2018, not every year
    booklet_code = Column(String(16))  # which printed/shuffled copy was photographed; same
    # questions reordered for anti-cheating, NOT a distinct paper - never part of identity
    source_file = Column(String(255))
    source_sha256 = Column(String(64))
    source_dir = Column(String(500))  # the extract output folder (p01.jpg, p02.jpg, ...), so a question
    # that needs a figure/table the vision model couldn't transcribe can show the real source photo instead
    # of being silently withheld - set once at load time, never guessed or reconstructed from a naming convention
    page_count = Column(Integer)
    expected_first = Column(Integer, default=1)
    expected_last = Column(Integer)
    duration_minutes = Column(Integer)  # time allowed in a mock exam; NULL = untimed
    status = Column(
        String(16), nullable=False, default="extracted"
    )  # extracted | in_review | published
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint(
            "subject", "stream", "year_ec", "round", "region", "delivery_mode",
            name="uq_exam_paper",
        ),
    )

    questions = relationship(
        "EsslceQuestion",
        back_populates="paper",
        cascade="all, delete-orphan",
        order_by="EsslceQuestion.item_no",
    )
    passages = relationship(
        "EsslcePassage", back_populates="paper", cascade="all, delete-orphan"
    )


class EsslcePassage(Base):
    __tablename__ = "esslce_passages"
    id = Column(Integer, primary_key=True)
    paper_id = Column(
        Integer,
        ForeignKey("esslce_papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    passage_key = Column(String(16), nullable=False)  # "P1", "P2"
    title = Column(String(255))
    text = Column(
        Text, nullable=False
    )  # paragraphs separated by blank lines, numbered "(1)"...
    source_note = Column(String(255))
    paper = relationship("EsslcePaper", back_populates="passages")
    __table_args__ = (
        UniqueConstraint("paper_id", "passage_key", name="uq_exam_passage"),
    )


class EsslceQuestion(Base):
    __tablename__ = "esslce_questions"
    id = Column(Integer, primary_key=True)
    paper_id = Column(
        Integer,
        ForeignKey("esslce_papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_no = Column(Integer, nullable=False)
    part = Column(String(120))
    section = Column(Text)  # the section heading with its instructions
    stem = Column(Text, nullable=False)
    options = Column(JSON, nullable=False)  # four strings, PRINTED order (A, B, C, D)
    underlined = Column(JSON)  # underlined words/phrases in the stem
    passage_id = Column(Integer, ForeignKey("esslce_passages.id", ondelete="SET NULL"))
    printed_page = Column(Integer)  # page of the booklet, to find the photo
    has_diagram = Column(Boolean, nullable=False, default=False)
    diagram_note = Column(Text)
    answer_index = Column(Integer)  # 0-3 in printed order; NULL until resolved
    answer_source = Column(String(32))  # "official_key" | "manual" | "ai_derived" ; never guessed
    explanation = Column(Text)
    supporting_quote = Column(Text)  # verbatim quote an AI-derived answer was cited from,
    # for a human reviewer to check against the source; NULL for official_key/manual
    verification_code = Column(Text)  # for a calculation subject: the sympy/math code that was actually
    # EXECUTED to check the AI-derived answer (not just trusted) - NULL unless that path resolved it
    verification_output = Column(Text)  # what that code printed, for a human reviewer to compare
    review_status = Column(String(16), nullable=False, default="needs_key")
    flags = Column(JSON)  # why a reviewer should look (list of strings)
    skill_tags = Column(JSON)  # e.g. ["conditionals", "reported speech"]
    reviewed_by = Column(String(64))
    reviewed_at = Column(DateTime)
    paper = relationship("EsslcePaper", back_populates="questions")
    passage = relationship("EsslcePassage")
    links = relationship(
        "EsslceTopicLink",
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="EsslceTopicLink.rank",
    )
    __table_args__ = (UniqueConstraint("paper_id", "item_no", name="uq_exam_question"),)


class EsslceTopicLink(Base):
    """A textbook chunk that LOOKS related to a question (search result), kept with its score. Suggestion only."""

    __tablename__ = "esslce_topic_links"
    id = Column(Integer, primary_key=True)
    question_id = Column(
        Integer,
        ForeignKey("esslce_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rank = Column(Integer, nullable=False)
    score = Column(Float)  # vector distance; lower = closer
    textbook_id = Column(
        String(36)
    )  # the textbook's UUID as text; deliberately no FK: re-ingesting must not break links
    vector_id = Column(String(64))
    grade = Column(Integer)
    unit = Column(String(255))
    section = Column(String(255))
    verified = Column(
        Boolean, nullable=False, default=False
    )  # a human confirmed the link
    question = relationship("EsslceQuestion", back_populates="links")


class EsslceAttempt(Base):
    """One student's answer to one question. Append-only (like QuizAttempt) - no unique constraint,
    so practice.selection.pick_questions' "latest attempt by timestamp" logic works unmodified."""

    __tablename__ = "esslce_attempts"
    id = Column(Integer, primary_key=True)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id = Column(
        Integer, ForeignKey("esslce_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    paper_id = Column(
        Integer, ForeignKey("esslce_papers.id", ondelete="CASCADE"), nullable=False, index=True
    )  # denormalized: avoids a join to ask "has this student finished paper X"
    chosen_index = Column(Integer, nullable=False)
    is_correct = Column(Boolean, nullable=False)
    mode = Column(
        String(16), nullable=False, default="practice"
    )  # "practice" | "exam" - informational only, never gates server behavior
    created_at = Column(DateTime, server_default=func.now())


class EsslceElaboration(Base):
    """A deeper, on-demand explanation ("I still don't get it, explain more") for one question - cached
    PER QUESTION, not per student, since the content doesn't depend on who's asking. The first student to
    request it pays the LLM-call cost; everyone after is served this cached row for free."""

    __tablename__ = "esslce_elaborations"
    id = Column(Integer, primary_key=True)
    question_id = Column(
        Integer,
        ForeignKey("esslce_questions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    content = Column(Text, nullable=False)  # LaTeX for a calculation subject, plain grounded prose otherwise
    is_calculation = Column(
        Boolean, nullable=False, default=False
    )  # tells the caller whether `content` needs latex_render, same convention as EsslceQuestion.explanation
    citation = Column(JSON)  # {textbook, grade, subject, unit_or_chapter, section, page_start, page_end} -
    # deterministically looked up from the Chunk the grounding quote actually came from, NEVER written by
    # the LLM itself (a page number is exactly the kind of fact an LLM should never be trusted to state on
    # its own). NULL for a calculation-subject elaboration (no textbook excerpt involved) or a
    # reading-comprehension question (grounded in the exam's own passage, not a textbook).
    created_at = Column(DateTime, server_default=func.now())
