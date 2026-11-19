"""Schools and ambassadors (growth/schools.py). Students list schools to pick theirs on Profile;
admins add schools and name ambassadors from the bot; the bot reads the weekly ranking."""

from auth.dependencies import get_current_user, require_admin, require_bot_internal_token
from auth.identifiers import normalize_identifier
from auth.telegram_notify import send_text
from config.settings import settings
from db.models import School, User
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException
from growth.schools import find_school, weekly_ranking
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1/schools", tags=["schools"])


class SchoolOut(BaseModel):
    id: int
    name: str


@router.get("", response_model=list[SchoolOut])
def list_schools(db: Session = Depends(get_db), _user: User = Depends(get_current_user)) -> list[SchoolOut]:
    return [SchoolOut(id=s.id, name=s.name) for s in db.query(School).order_by(School.name)]


class NewSchool(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)


@router.post("", response_model=SchoolOut)
def add_school(body: NewSchool, db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> SchoolOut:
    name = " ".join(body.name.split())
    if find_school(db, name) is not None:
        raise HTTPException(status_code=409, detail=f"{name} is already in the list.")
    school = School(name=name)
    db.add(school)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"{name} is already in the list.")
    return SchoolOut(id=school.id, name=school.name)


class AmbassadorRequest(BaseModel):
    identifier: str  # the student's phone or email
    school: str  # the school's id or name


@router.post("/ambassador")
def make_ambassador(body: AmbassadorRequest, db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> dict:
    school = find_school(db, body.school)
    if school is None:
        raise HTTPException(status_code=404, detail="No such school. Add it first with /add_school.")
    identifier = normalize_identifier(body.identifier)
    student = db.query(User).filter(or_(User.phone_number == identifier, User.email == identifier)).one_or_none()
    if student is None:
        raise HTTPException(status_code=404, detail="No student with that phone or email.")
    student.is_ambassador = True
    student.school_id = school.id
    db.commit()
    send_text(
        db,
        student,
        f"🎓 You're now the Ethiopian Student Helper ambassador for {school.name}. Share your code "
        f"{student.referral_code}: students who sign up with it join {school.name} on the weekly top-schools "
        f"ranking, and you earn {settings.REFERRAL_REWARD_ETB:g} ETB for each one who subscribes.",
    )
    return {"student_name": student.full_name or identifier, "school": school.name, "referral_code": student.referral_code}


@router.get("/overview")
def overview(db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> dict:
    """Admin: every school with its student count and ambassadors."""
    counts = dict(db.query(User.school_id, func.count(User.id)).filter(User.school_id.isnot(None)).group_by(User.school_id))
    ambassadors: dict = {}
    for u in db.query(User).filter(User.is_ambassador.is_(True)):
        ambassadors.setdefault(u.school_id, []).append(u.full_name or u.phone_number or u.email)
    return {
        "schools": [
            {"id": s.id, "name": s.name, "students": counts.get(s.id, 0), "ambassadors": ambassadors.get(s.id, [])}
            for s in db.query(School).order_by(School.name)
        ]
    }


@router.get("/weekly-ranking", dependencies=[Depends(require_bot_internal_token)])
def ranking(db: Session = Depends(get_db)) -> dict:
    return {"schools": weekly_ranking(db)}
