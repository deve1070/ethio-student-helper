import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError
from sqlalchemy.orm import Session

from auth.security import decode_access_token
from config.settings import settings
from db.models import User
from db.session import get_db

_bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        user_id = decode_access_token(credentials.credentials)
    except PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_bot_internal_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> None:
    """For the small number of bot-initiated backend calls that aren't on behalf of any one
    specific student (creating/fetching today's mass challenge, checking a join request's
    subscription eligibility, fetching a leaderboard to post) - see
    docs/dev_plans/mass_esslce_practice.md for why this exists instead of reusing a specific
    admin's own login session (that would make the whole feature silently stall if that admin's
    token ever expired with nobody noticing). Deliberately narrow: used only by
    api/routes_mass_challenge.py's three service-level endpoints, never a general service-account
    impersonation mechanism."""
    if not secrets.compare_digest(credentials.credentials, settings.BOT_INTERNAL_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid bot token")
