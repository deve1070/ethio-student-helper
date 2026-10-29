from datetime import date, datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy.orm import Session

from api.rate_limit import limiter
from auth.dependencies import get_current_user
from auth.security import create_access_token, hash_password, verify_password
from config.constants import COMMON_SUBJECTS, NATURAL_ONLY_SUBJECTS, SOCIAL_ONLY_SUBJECTS
from db.models import TelegramLink, User
from db.session import get_db

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: UUID


class SignupRequest(BaseModel):
    phone_number: str | None = None
    email: EmailStr | None = None
    password: str = Field(..., min_length=8)
    full_name: str | None = None
    grade_level: int | None = Field(None, ge=9, le=12)

    @model_validator(mode="after")
    def _identifier_required(self):
        if not self.phone_number and not self.email:
            raise ValueError("Provide phone_number or email.")
        return self


@router.post("/signup", response_model=TokenResponse)
@limiter.limit("5/hour")  # a low ceiling on account creation deters signup/spam abuse
def signup(request: Request, body: SignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    existing = None
    if body.email:
        existing = db.query(User).filter(User.email == body.email).one_or_none()
    if existing is None and body.phone_number:
        existing = (
            db.query(User)
            .filter(User.phone_number == body.phone_number)
            .one_or_none()
        )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="An account with this phone or email already exists.",
        )

    user = User(
        phone_number=body.phone_number,
        email=body.email,
        full_name=body.full_name,
        grade_level=body.grade_level,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)  # phone number or email

    return TokenResponse(access_token=create_access_token(user.id), user_id=user.id)


class LoginRequest(BaseModel):
    identifier: str
    password: str


def _find_user_by_identifier(db: Session, identifier: str) -> User | None:
    return (
        db.query(User)
        .filter((User.email == identifier) | (User.phone_number == identifier))
        .one_or_none()
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")  # throttles password-guessing; a real user mistyping a few times is unaffected
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = _find_user_by_identifier(db, body.identifier)
    if (
        user is None
        or user.password_hash is None
        or not verify_password(body.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return TokenResponse(access_token=create_access_token(user.id), user_id=user.id)


class TelegramLinkRequest(BaseModel):
    telegram_user_id: int

    identifier: str
    password: str


@router.post("/telegram-link", response_model=TokenResponse)
@limiter.limit("5/minute")  # same credential check as /login, same brute-force exposure
def telegram_link(
    request: Request, body: TelegramLinkRequest, db: Session = Depends(get_db)
) -> TokenResponse:
    user = _find_user_by_identifier(db, body.identifier)
    if (
        user is None
        or user.password_hash is None
        or not verify_password(body.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    link = db.get(TelegramLink, body.telegram_user_id)
    if link is None:
        db.add(TelegramLink(telegram_user_id=body.telegram_user_id, user_id=user.id))
    else:
        link.user_id = (
            user.id
        )  # re-linking to a different account overwrites, doesn't duplicate
    db.commit()

    return TokenResponse(access_token=create_access_token(user.id), user_id=user.id)


@router.get("/streams")
def streams() -> dict:
    """The static natural/social/common subject partition (config.constants, confirmed directly by the
    user - see memory esh_stream_subject_mapping), so the onboarding wizard's subject picker never needs
    its own hardcoded copy that could drift from this one."""
    return {
        "natural_only": sorted(NATURAL_ONLY_SUBJECTS),
        "social_only": sorted(SOCIAL_ONLY_SUBJECTS),
        "common": sorted(COMMON_SUBJECTS),
    }


class ProfileResponse(BaseModel):
    user_id: UUID
    full_name: str | None
    email: str | None
    phone_number: str | None
    grade_level: int | None
    stream: str | None
    subjects_selected: list[str] | None
    exam_date: date | None
    daily_goal_minutes: int | None
    onboarding_completed: bool


def _profile_response(user: User) -> ProfileResponse:
    return ProfileResponse(
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        phone_number=user.phone_number,
        grade_level=user.grade_level,
        stream=user.stream,
        subjects_selected=user.subjects_selected,
        exam_date=user.exam_date,
        daily_goal_minutes=user.daily_goal_minutes,
        onboarding_completed=user.onboarding_completed_at is not None,
    )


@router.get("/me", response_model=ProfileResponse)
def me(user: User = Depends(get_current_user)) -> ProfileResponse:
    return _profile_response(user)


class UpdateProfileRequest(BaseModel):
    grade_level: int | None = Field(None, ge=9, le=12)
    stream: Literal["natural_science", "social_science"] | None = None
    subjects_selected: list[str] | None = Field(None, max_length=12)
    exam_date: date | None = None
    daily_goal_minutes: int | None = Field(None, ge=15, le=480)


@router.patch("/me", response_model=ProfileResponse)
def update_me(
    body: UpdateProfileRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ProfileResponse:
    """Called incrementally by the onboarding wizard (one step at a time) and later by Profile settings.
    Any call here - including one that only sets fields already set, or none at all (an explicit "skip
    for now") - marks onboarding as seen, so the app never re-prompts a student who already made a choice,
    even the choice to skip."""
    if body.grade_level is not None:
        user.grade_level = body.grade_level
    if body.stream is not None:
        user.stream = body.stream
    if body.subjects_selected is not None:
        allowed = COMMON_SUBJECTS | (
            NATURAL_ONLY_SUBJECTS if user.stream == "natural_science"
            else SOCIAL_ONLY_SUBJECTS if user.stream == "social_science"
            else NATURAL_ONLY_SUBJECTS | SOCIAL_ONLY_SUBJECTS  # no stream yet (grade 9/10): anything goes
        )
        bad = [s for s in body.subjects_selected if s not in allowed]
        if bad:
            raise HTTPException(
                status_code=400,
                detail=f"Not valid for stream '{user.stream or 'none'}': {', '.join(bad)}.",
            )
        user.subjects_selected = body.subjects_selected
    if body.exam_date is not None:
        user.exam_date = body.exam_date
    if body.daily_goal_minutes is not None:
        user.daily_goal_minutes = body.daily_goal_minutes
    if user.onboarding_completed_at is None:
        user.onboarding_completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return _profile_response(user)
