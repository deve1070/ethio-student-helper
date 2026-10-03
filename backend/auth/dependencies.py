"""
FastAPI dependency that resolves the bearer token on a request into a
User row. Every protected route takes `user: User = Depends(get_current_user)`
instead of trusting a user_id in the request body — this closes the
trust gap flagged when payments and exam-solve first shipped (both
previously took a bare user_id from the client).
"""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError
from sqlalchemy.orm import Session

from auth.security import decode_access_token
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
