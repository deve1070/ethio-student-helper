import os
from pathlib import Path

from dotenv import load_dotenv

# Same .env the backend reads (one token source, not duplicated) - this file lives in telegram_bot/,
# the .env lives in backend/, one directory over.
load_dotenv(Path(__file__).resolve().parent.parent / "backend" / ".env")

BACKEND_BASE_URL = os.environ.get("BACKEND_BASE_URL", "http://localhost:8000")
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
