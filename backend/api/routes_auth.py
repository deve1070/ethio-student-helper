"""
POST /v1/auth/signup — create an account (phone and/or email + password)
POST /v1/auth/login — exchange credentials for a bearer token
POST /v1/auth/telegram-link — link a Telegram user id to an account, so
  the bot can call every other endpoint with the same bearer-token
  scheme as web and mobile, instead of its own separate auth path
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from auth.security import create_access_token, hash_password, verify_password
from db.models import TelegramLink, User
from db.session import get_db

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: UUID


class SignupRequest(BaseModel):
    phone_number: str | None = None
    email: str | None = None
    password: str = Field(..., min_length=8)
    full_name: str | None = None
    grade_level: int | None = Field(None, ge=9, le=12)

    @model_validator(mode="after")
    def _identifier_required(self):
        if not self.phone_number and not self.email:
            raise ValueError("Provide phone_number or email.")
        return self


@router.post("/signup", response_model=TokenResponse)
def signup(request: SignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    existing = None
    if request.email:
        existing = db.query(User).filter(User.email == request.email).one_or_none()
    if existing is None and request.phone_number:
        existing = db.query(User).filter(User.phone_number == request.phone_number).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with this phone or email already exists.")

    user = User(
        phone_number=request.phone_number,
        email=request.email,
        full_name=request.full_name,
        grade_level=request.grade_level,
        password_hash=hash_password(request.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return TokenResponse(access_token=create_access_token(user.id), user_id=user.id)


class LoginRequest(BaseModel):
    identifier: str  # phone number or email
    password: str


def _find_user_by_identifier(db: Session, identifier: str) -> User | None:
    return (
        db.query(User)
        .filter((User.email == identifier) | (User.phone_number == identifier))
        .one_or_none()
    )


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = _find_user_by_identifier(db, request.identifier)
    if user is None or user.password_hash is None or not verify_password(request.password, user.password_hash):
        # Same error for "no such user" and "wrong password" — don't leak
        # which one it was; that's an account-enumeration side channel
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return TokenResponse(access_token=create_access_token(user.id), user_id=user.id)


class TelegramLinkRequest(BaseModel):
    telegram_user_id: int
    # Reuses ordinary login — the bot asks the student to log in once,
    # links the Telegram id to their account, then caches the token itself
    identifier: str
    password: str


@router.post("/telegram-link", response_model=TokenResponse)
def telegram_link(request: TelegramLinkRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = _find_user_by_identifier(db, request.identifier)
    if user is None or user.password_hash is None or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    link = db.get(TelegramLink, request.telegram_user_id)
    if link is None:
        db.add(TelegramLink(telegram_user_id=request.telegram_user_id, user_id=user.id))
    else:
        link.user_id = user.id  # re-linking to a different account overwrites, doesn't duplicate
    db.commit()

    return TokenResponse(access_token=create_access_token(user.id), user_id=user.id)
