"""Today's study plan: generated once per (user, calendar day) by api/routes_studyplan.py, then served
as-is for the rest of that day so a checked-off task doesn't lose its identity if the student's weak-area
signal shifts mid-day from further practice. Never a multi-day calendar - tomorrow's row doesn't exist
until tomorrow's first request generates it fresh from whatever the weak-area signal looks like then."""

from sqlalchemy import JSON, Column, Date, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from db.models import Base


class StudyPlanDay(Base):
    __tablename__ = "study_plan_days"
    __table_args__ = (UniqueConstraint("user_id", "plan_date", name="uq_study_plan_day"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_date = Column(Date, nullable=False)
    tasks = Column(JSON, nullable=False)  # list[dict] - see studyplan.plan.build_plan's shape
    created_at = Column(DateTime(timezone=True), server_default=func.now())
