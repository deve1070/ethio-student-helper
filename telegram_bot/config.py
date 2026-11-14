import os
from pathlib import Path

from dotenv import load_dotenv

# Same .env the backend reads (one token source, not duplicated) - this file lives in telegram_bot/,
# the .env lives in backend/, one directory over.
load_dotenv(Path(__file__).resolve().parent.parent / "backend" / ".env")

BACKEND_BASE_URL = os.environ.get("BACKEND_BASE_URL", "http://localhost:8000")
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
# Same public setting the backend reads for its Profile page link (config/settings.py).
TELEGRAM_GROUP_URL = os.environ.get("TELEGRAM_GROUP_URL", "https://t.me/ethiopian_student_helper")

# Daily mass-practice event (telegram_bot/mass_challenge.py). Same shared secret the backend
# checks in auth/dependencies.py's require_bot_internal_token - MUST match BOT_INTERNAL_TOKEN in
# any real deployment; this default is only safe for local dev.
BOT_INTERNAL_TOKEN = os.environ.get("BOT_INTERNAL_TOKEN", "dev-only-change-me")
# The subscriber-only private group's numeric chat id (negative for a group/supergroup); 0 means
# the feature is off (schedule_daily_event/schedule_sweep no-op rather than erroring).
TELEGRAM_PRIVATE_GROUP_ID = int(os.environ.get("TELEGRAM_PRIVATE_GROUP_ID", "0"))
# Parsed with reminders.parse_time() at schedule time, same as a student's own reminder time.
MASS_CHALLENGE_TIME = os.environ.get("MASS_CHALLENGE_TIME", "20:00")
# How long before MASS_CHALLENGE_TIME the one heads-up message goes out.
MASS_CHALLENGE_HEADSUP_MINUTES = int(os.environ.get("MASS_CHALLENGE_HEADSUP_MINUTES", "10"))
# How long after MASS_CHALLENGE_TIME the private streak reminder goes to students who took part
# yesterday but have not answered today (mass_challenge.send_streak_nudges).
MASS_CHALLENGE_NUDGE_MINUTES = int(os.environ.get("MASS_CHALLENGE_NUDGE_MINUTES", "60"))


def _topic_id(name: str) -> int | None:
    """A forum topic's own id (a thread, not a chat) - None posts to the group's General area
    instead. Found the same way the group's own chat id is: send a message in that topic, read it
    back from getUpdates."""
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else None


# Two separate topics, not one shared "Daily Mass Practice" thread - natural-stream and
# social-stream students answering different questions in the same thread at the same time was
# confusing to follow. stream="" (a common subject - English/SAT/Math, affecting everyone) posts
# to the natural topic, the one general "mass practice" space that already existed.
MASS_CHALLENGE_NATURAL_TOPIC_ID = _topic_id("MASS_CHALLENGE_NATURAL_TOPIC_ID")
MASS_CHALLENGE_SOCIAL_TOPIC_ID = _topic_id("MASS_CHALLENGE_SOCIAL_TOPIC_ID")
