"""Cross-system progress metrics that legitimately span QuizQuestion-practice and ESSLCE (the two systems
stay separate at the data-model level, per the project's own system-boundaries rule - this router only
combines their already-independently-queried attempt DATES at the API layer, never their schemas)."""

from auth.dependencies import get_current_user
from db.models import User
from db.models_practice import QuizAttempt
from db.session import get_db
from exams.models import EsslceAttempt
from fastapi import APIRouter, Depends
from practice.selection import local_date, study_streak
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1/progress", tags=["progress"])


@router.get("/streak")
def streak(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Consecutive days with at least one attempt, in EITHER system - a student who practices from the
    textbook bank one day and an ESSLCE past paper the next should see that as one unbroken streak."""
    practice_dates = {
        local_date(row[0])
        for row in db.query(QuizAttempt.created_at).filter(QuizAttempt.user_id == user.id).all()
    }
    esslce_dates = {
        local_date(row[0])
        for row in db.query(EsslceAttempt.created_at).filter(EsslceAttempt.user_id == user.id).all()
    }
    return {"streak_days": study_streak(practice_dates | esslce_dates)}
