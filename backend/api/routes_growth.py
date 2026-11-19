"""Messages that bring students back and in: the daily nudges (growth/nudges.py), the share cards
(growth/share.py), and the student's own switch for the nudges."""

from auth.dependencies import get_current_user, require_bot_internal_token
from db.models import User
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException
from growth.nudges import due_nudges
from growth.share import mass_card, week_card
from practice.selection import today_local
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Literal

router = APIRouter(prefix="/v1/growth", tags=["growth"])


@router.post("/nudges", dependencies=[Depends(require_bot_internal_token)])
def nudges(db: Session = Depends(get_db)) -> dict:
    """The bot's daily call: today's messages, at most one per student, recorded as sent."""
    return {"nudges": due_nudges(db, today_local())}


class NudgesSetting(BaseModel):
    off: bool


@router.post("/nudges-setting")
def nudges_setting(body: NudgesSetting, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    user.nudges_off = body.off
    db.commit()
    return {"off": user.nudges_off}


class ShareCard(BaseModel):
    text: str
    link: str  # the student's referral signup link
    share_url: str  # Telegram's share page with both filled in


@router.get("/share", response_model=ShareCard)
def share(
    kind: Literal["mass", "week"],
    challenge_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ShareCard:
    card = mass_card(db, user, challenge_id) if kind == "mass" and challenge_id else week_card(db, user) if kind == "week" else None
    if card is None:
        raise HTTPException(status_code=404, detail="Nothing to share yet - practise first.")
    return ShareCard(**card)
