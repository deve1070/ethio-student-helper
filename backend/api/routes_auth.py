import random
import re
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy.orm import Session

from accounts.deletion import DeletionBlocked, check_can_delete, delete_account
from api.rate_limit import limiter
from auth.dependencies import get_current_user, require_admin
from auth.identifiers import normalize_email, normalize_identifier, normalize_phone
from auth.referral import generate_referral_code
from auth.security import create_access_token, hash_password, verify_password
from auth.telegram_notify import send_text
from payments.entitlement import has_active_subscription
from config.constants import (
    COMMON_SUBJECTS,
    NATURAL_ONLY_SUBJECTS,
    SOCIAL_ONLY_SUBJECTS,
    subject_visible,
)
from config.settings import settings
from db.models import PasswordResetCode, TelegramLink, User
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
    referral_code: str | None = Field(None, max_length=16)
    # the ?src= tag of the link the student arrived by; a malformed one is dropped, never an error
    signup_source: str | None = Field(None, max_length=64)

    @model_validator(mode="after")
    def _identifier_required(self):
        if not self.phone_number and not self.email:
            raise ValueError("Provide phone_number or email.")
        return self


@router.post("/signup", response_model=TokenResponse)
@limiter.limit("5/hour")  # a low ceiling on account creation deters signup/spam abuse
def signup(request: Request, body: SignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email = normalize_email(body.email) if body.email else None
    phone_number = None
    if body.phone_number:
        try:
            phone_number = normalize_phone(body.phone_number)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    existing = None
    if email:
        existing = db.query(User).filter(User.email == email).one_or_none()
    if existing is None and phone_number:
        existing = db.query(User).filter(User.phone_number == phone_number).one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="An account with this phone or email already exists.",
        )

    referred_by_user_id = None
    if body.referral_code:
        referrer = (
            db.query(User)
            .filter(User.referral_code == body.referral_code.strip().upper())
            .one_or_none()
        )
        if referrer is None:
            raise HTTPException(status_code=400, detail="That referral code doesn't exist.")
        referred_by_user_id = referrer.id

    user = User(
        phone_number=phone_number,
        email=email,
        full_name=body.full_name,
        grade_level=body.grade_level,
        password_hash=hash_password(body.password),
        referral_code=generate_referral_code(db),
        referred_by_user_id=referred_by_user_id,
        signup_source=clean_signup_source(body.signup_source),
    )
    db.add(user)
    db.commit()
    db.refresh(user)  # phone number or email

    return TokenResponse(access_token=create_access_token(user.id), user_id=user.id)


class LoginRequest(BaseModel):
    identifier: str
    password: str


def _find_user_by_identifier(db: Session, identifier: str) -> User | None:
    identifier = normalize_identifier(identifier)
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


class PasswordResetRequestBody(BaseModel):
    identifier: str


class PasswordResetRequestResponse(BaseModel):
    status: Literal["code_sent", "no_telegram_link"]


@router.post("/password-reset/request", response_model=PasswordResetRequestResponse)
@limiter.limit("5/minute")  # same brute-force exposure class as /login
def request_password_reset(
    request: Request, body: PasswordResetRequestBody, db: Session = Depends(get_db)
) -> PasswordResetRequestResponse:
    """Telegram-based reset only: this app has no email/SMS provider, so the reset code can only ever
    go somewhere real if the student has linked their Telegram account at least once (the bot's own
    /login does this as a side effect). "no_telegram_link" covers BOTH "no account with this identifier"
    and "account exists but isn't linked" - deliberately the same response either way, so this endpoint
    doesn't confirm or deny that an account exists, only whether Telegram-based reset is available."""
    user = _find_user_by_identifier(db, body.identifier)
    if user is None:
        return PasswordResetRequestResponse(status="no_telegram_link")

    code = f"{random.randint(0, 999_999):06d}"
    sent = send_text(
        db,
        user,
        f"Your Ethiopian Student Helper password reset code is {code}. It expires in "
        f"{settings.PASSWORD_RESET_CODE_EXPIRE_MINUTES} minutes. If you didn't request this, ignore it.",
    )
    if not sent:
        # never promise a code that didn't actually go out - same response as "not linked at all"
        return PasswordResetRequestResponse(status="no_telegram_link")

    # Only one active code at a time - a fresh request invalidates whatever was outstanding, so an
    # old, still-unexpired code can't be used after the student asked for a new one.
    db.query(PasswordResetCode).filter(
        PasswordResetCode.user_id == user.id, PasswordResetCode.used_at.is_(None)
    ).update({"used_at": datetime.now(timezone.utc)})
    db.add(
        PasswordResetCode(
            user_id=user.id,
            code_hash=hash_password(code),
            expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=settings.PASSWORD_RESET_CODE_EXPIRE_MINUTES),
        )
    )
    db.commit()
    return PasswordResetRequestResponse(status="code_sent")


class PasswordResetConfirmBody(BaseModel):
    identifier: str
    code: str
    new_password: str = Field(..., min_length=8)


@router.post("/password-reset/confirm", response_model=TokenResponse)
@limiter.limit("5/minute")
def confirm_password_reset(
    request: Request, body: PasswordResetConfirmBody, db: Session = Depends(get_db)
) -> TokenResponse:
    invalid = HTTPException(status_code=401, detail="Invalid or expired code.")
    user = _find_user_by_identifier(db, body.identifier)
    if user is None:
        raise invalid

    reset = (
        db.query(PasswordResetCode)
        .filter(
            PasswordResetCode.user_id == user.id,
            PasswordResetCode.used_at.is_(None),
            PasswordResetCode.expires_at > datetime.now(timezone.utc),
        )
        .order_by(PasswordResetCode.created_at.desc())
        .first()
    )
    if reset is None or not verify_password(body.code.strip(), reset.code_hash):
        raise invalid

    reset.used_at = datetime.now(timezone.utc)
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id), user_id=user.id)


_SOURCE = re.compile(r"^[a-z0-9_-]{1,32}$")


def clean_signup_source(raw: str | None) -> str | None:
    value = (raw or "").strip().lower()
    return value if _SOURCE.match(value) else None


class SourceCount(BaseModel):
    source: str  # "(none)" for students who arrived without a ?src= tag
    signups: int
    subscribed: int  # of those, how many have an active subscription now


class SignupSourcesResponse(BaseModel):
    days: int
    sources: list[SourceCount]


@router.get("/signup-sources", response_model=SignupSourcesResponse)
def signup_sources(
    days: int = 30, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> SignupSourcesResponse:
    """Admin: signups in the last `days` days by where they came from, and how many now subscribe -
    how the bot's /channel_stats tells whether the channel posts bring students in."""
    days = max(1, min(days, 365))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.query(User.id, User.signup_source).filter(User.created_at >= since).all()
    counts: dict[str, list[int]] = {}
    for uid, source in rows:
        c = counts.setdefault(source or "(none)", [0, 0])
        c[0] += 1
        c[1] += has_active_subscription(db, uid)
    return SignupSourcesResponse(
        days=days,
        sources=[
            SourceCount(source=s, signups=n, subscribed=paid)
            for s, (n, paid) in sorted(counts.items(), key=lambda kv: -kv[1][0])
        ],
    )


class PublicConfigResponse(BaseModel):
    telegram_channel_url: str | None
    telegram_bot_url: str | None
    web_app_url: str
    subscription_price_etb: float
    referral_reward_etb: float
    payment_telebirr_number: str
    payment_cbe_account: str


@router.get("/public-config", response_model=PublicConfigResponse)
def public_config() -> PublicConfigResponse:
    """Unauthenticated: the forgot-password page needs the links before a student has a session, and
    the bot reads the price and payment accounts here so they are set in one place (config/settings.py)."""
    return PublicConfigResponse(
        telegram_channel_url=settings.TELEGRAM_CHANNEL_URL or None,
        telegram_bot_url=settings.TELEGRAM_BOT_URL or None,
        web_app_url=settings.WEB_APP_URL,
        subscription_price_etb=settings.SUBSCRIPTION_PRICE_ETB,
        referral_reward_etb=settings.REFERRAL_REWARD_ETB,
        payment_telebirr_number=settings.PAYMENT_TELEBIRR_NUMBER,
        payment_cbe_account=settings.PAYMENT_CBE_ACCOUNT,
    )


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
    referral_code: str
    telegram_channel_url: str | None
    telegram_bot_url: str | None
    private_group_url: str | None  # the subscriber-only practice group; None unless subscribed
    telegram_linked: bool


def _profile_response(db: Session, user: User) -> ProfileResponse:
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
        referral_code=user.referral_code,
        telegram_channel_url=settings.TELEGRAM_CHANNEL_URL or None,
        telegram_bot_url=settings.TELEGRAM_BOT_URL or None,
        private_group_url=(
            settings.TELEGRAM_PRIVATE_GROUP_URL or None if has_active_subscription(db, user.id) else None
        ),
        telegram_linked=db.query(TelegramLink).filter(TelegramLink.user_id == user.id).first() is not None,
    )


@router.get("/me", response_model=ProfileResponse)
def me(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ProfileResponse:
    return _profile_response(db, user)


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
        bad = [s for s in body.subjects_selected if not subject_visible(s, user.stream)]
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
    return _profile_response(db, user)


class DeleteAccountRequest(BaseModel):
    password: str


@router.post("/me/delete")
@limiter.limit("5/minute")  # it checks a password, so the same guessing limit as /login
def delete_me(
    request: Request,
    body: DeleteAccountRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Permanently deletes the logged-in student's account (accounts/deletion.py says what is kept).
    The password is asked again so a phone left unlocked can't be used to delete someone's account."""
    if user.password_hash is None or not verify_password(body.password, user.password_hash):
        # 403, not 401: the web app treats 401 as an expired login and logs the student out
        raise HTTPException(status_code=403, detail="That password is not correct.")
    try:
        check_can_delete(db, user)
    except DeletionBlocked as e:
        raise HTTPException(status_code=409, detail=str(e))
    delete_account(db, user)
    return {"deleted": True}
