"""Share cards: a short brag a student posts to their own chats from the bot, with their referral
link in it. A friend who signs up from it is the student's referral, and the signup is tagged
src=share, so /channel_stats counts these too."""

from datetime import timedelta
from urllib.parse import quote, urlencode

from config.settings import settings
from db.models import User
from db.models_practice import QuizAttempt
from exams.models import EsslceAttempt, MassChallenge
from practice.selection import local_date, study_streak, today_local


def signup_link(user: User) -> str:
    return f"{settings.WEB_APP_URL.rstrip('/')}/signup?" + urlencode({"ref": user.referral_code, "src": "share"})


def telegram_share_url(text: str, link: str) -> str:
    """Telegram's own share page: opens the chat picker with the link and text filled in."""
    return f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(text, safe='')}"


def _card(text: str, user: User) -> dict:
    link = signup_link(user)
    return {"text": text, "link": link, "share_url": telegram_share_url(text, link)}


def mass_card(db, user: User, challenge_id: int) -> dict | None:
    """Today's evening group result, or None if the student did not take part."""
    from api.routes_mass_challenge import MASS_MODES

    challenge = db.get(MassChallenge, challenge_id)
    if challenge is None:
        return None
    rows = (
        db.query(EsslceAttempt.is_correct)
        .filter(EsslceAttempt.user_id == user.id, EsslceAttempt.mass_challenge_id == challenge_id)
        .all()
    )
    if not rows:
        return None
    days = {
        local_date(ts)
        for (ts,) in db.query(EsslceAttempt.created_at).filter(
            EsslceAttempt.user_id == user.id, EsslceAttempt.mode.in_(MASS_MODES)
        )
    }
    streak = study_streak(days)
    correct = sum(1 for (ok,) in rows if ok)
    subject = challenge.subject.replace("_", " ").title()
    text = f"I got {correct}/{len(challenge.question_ids)} in tonight's ESSLCE {subject} practice"
    text += f" 🔥 {streak}-day streak." if streak > 1 else "."
    text += " Practise real past ESSLCE questions with me:"
    return _card(text, user)


def week_card(db, user: User) -> dict | None:
    """The last 7 days of practice, or None if there was none."""
    first_day = today_local() - timedelta(days=6)
    answered = correct = 0
    days = set()
    for model in (QuizAttempt, EsslceAttempt):
        for ok, ts in db.query(model.is_correct, model.created_at).filter(model.user_id == user.id):
            day = local_date(ts)
            if day >= first_day:
                days.add(day)
                answered += 1
                correct += bool(ok)
    if not answered:
        return None
    text = (
        f"This week I practised on {len(days)} of 7 days and answered {answered} ESSLCE-style questions, "
        f"{round(100 * correct / answered)}% correct. Getting ready for the national exam with Ethiopian Student Helper:"
    )
    return _card(text, user)
