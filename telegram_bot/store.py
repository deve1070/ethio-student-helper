import base64
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DIR = Path(
    os.environ.get("BOT_DATA_DIR") or Path(__file__).resolve().parent / "data"
)


def token_expiry(token: str):
    """Expiry time (unix seconds) read from a JWT's payload, or None. Does not verify the signature:
    the backend does that; we only want to know when to stop sending a dead token."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        return float(exp) if exp is not None else None
    except Exception:
        return None


def token_expired(token: str, now: float | None = None, margin: float = 60.0) -> bool:
    exp = token_expiry(token)
    return exp is not None and exp - margin <= (now if now is not None else time.time())


class Store:
    SECTIONS = ("sessions", "reminders", "prefs", "active")

    def __init__(self, path=None):
        self.path = Path(path) if path else DEFAULT_DIR / "state.json"
        self._lock = threading.RLock()
        self._data = self._load()
        with self._lock:
            expired = [u for u, t in self._data["sessions"].items() if token_expired(t)]
            for u in expired:
                del self._data["sessions"][u]
            if expired:
                self._save()

    # ---- file handling ---------------------------------------------------------------------------------------
    def _empty(self) -> dict:
        return {name: {} for name in self.SECTIONS}

    def _load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            data = self._empty()
            for name in self.SECTIONS:
                if isinstance(raw.get(name), dict):
                    data[name] = raw[name]
            return data
        except FileNotFoundError:
            return self._empty()
        except Exception:
            backup = self.path.with_name(f"{self.path.name}.corrupt-{int(time.time())}")
            try:
                self.path.rename(backup)
            except OSError:
                pass
            logger.warning(
                "Bot state file was unreadable; moved to %s and started empty", backup
            )
            return self._empty()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        fd, tmp = tempfile.mkstemp(
            dir=self.path.parent, prefix=".state-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # ---- sessions --------------------------------------------------------------------------------------------
    def get_token(self, uid: int):
        with self._lock:
            token = self._data["sessions"].get(str(uid))
            if token and token_expired(token):
                del self._data["sessions"][str(uid)]
                self._save()
                return None
            return token

    def set_token(self, uid: int, token: str) -> None:
        with self._lock:
            self._data["sessions"][str(uid)] = token
            self._save()

    def drop_token(self, uid: int) -> None:
        with self._lock:
            if self._data["sessions"].pop(str(uid), None) is not None:
                self._save()

    # ---- reminders -------------------------------------------------------------------------------------------
    def set_reminder(self, uid: int, chat_id: int, hhmm: str) -> None:
        with self._lock:
            self._data["reminders"][str(uid)] = {"time": hhmm, "chat_id": chat_id}
            self._save()

    def get_reminder(self, uid: int):
        with self._lock:
            return self._data["reminders"].get(str(uid))

    def drop_reminder(self, uid: int) -> None:
        with self._lock:
            if self._data["reminders"].pop(str(uid), None) is not None:
                self._save()

    def all_reminders(self) -> dict:
        with self._lock:
            return {int(u): dict(r) for u, r in self._data["reminders"].items()}

    # ---- what they practised last / when they were last active ---------------------------------------------------
    def set_pref(self, uid: int, grade: int, subject: str) -> None:
        with self._lock:
            new = {"grade": grade, "subject": subject}
            if (
                self._data["prefs"].get(str(uid)) != new
            ):  # only touch the disk when something changed
                self._data["prefs"][str(uid)] = new
                self._save()

    def get_pref(self, uid: int):
        with self._lock:
            return self._data["prefs"].get(str(uid))

    def mark_active(self, uid: int, day: str) -> None:
        with self._lock:
            if self._data["active"].get(str(uid)) != day:
                self._data["active"][str(uid)] = day
                self._save()

    def active_on(self, uid: int, day: str) -> bool:
        with self._lock:
            return self._data["active"].get(str(uid)) == day


_default = None
_default_lock = threading.Lock()


def get_store() -> Store:
    global _default
    with _default_lock:
        if _default is None:
            _default = Store()
        return _default


def set_store(store) -> None:
    """Replace the shared store (used by tests)."""
    global _default
    with _default_lock:
        _default = store
