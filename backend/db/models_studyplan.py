"""This week's study plan: generated once per (user, week_start_date) by api/routes_studyplan.py from
studyplan/profile.py + studyplan/planner.py (+ studyplan/coach.py for the rationale text), then served
as-is for the rest of that week so a checked-off task doesn't lose its identity if the student's
weak-area signal shifts mid-week from further practice - same reasoning the old per-day model used, now
over a real multi-day horizon. Regenerated early (before the week is up) if the student's exam_date,
stream, or subjects_selected has changed since profile_snapshot was captured - see
_profile_is_stale in api/routes_studyplan.py."""

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from db.models import Base


class StudyPlanWeek(Base):
    __tablename__ = "study_plan_weeks"
    __table_args__ = (UniqueConstraint("user_id", "week_start_date", name="uq_study_plan_week"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    week_start_date = Column(Date, nullable=False)
    days = Column(JSON, nullable=False)  # list[list[dict]] - see studyplan.planner.build_week_plan's shape
    day_rationales = Column(JSON, nullable=False, default=list)  # list[str], same length as `days`
    weekly_note = Column(Text, nullable=False, default="")
    realistic = Column(Boolean, nullable=False, default=True)
    shortfall_minutes = Column(Integer, nullable=False, default=0)
    profile_snapshot = Column(JSON, nullable=False)  # studyplan.profile.build_profile's output this plan
    # was generated from - compared against the LIVE profile on each request to detect a real change
    # (exam_date/stream/subjects_selected), not just staleness, so a week-long cache never silently goes
    # stale the way the old one-day cache never had to worry about.
    created_at = Column(DateTime(timezone=True), server_default=func.now())
