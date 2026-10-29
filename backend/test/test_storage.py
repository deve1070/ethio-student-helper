"""Tests for storage.py: local-disk fallback (no SUPABASE_URL, the only path local dev and every
other test in this suite actually exercise) and the Supabase Storage HTTP calls themselves, stubbed
so this never makes a real network call.
Run from backend/:   python test/test_storage.py"""

import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import storage

TMP = Path(tempfile.mkdtemp())

# ---- 1. local fallback (settings.SUPABASE_URL unset, matching every other test's real settings) ----
local_path = str(TMP / "sub" / "p01.jpg")
assert storage.download("exam-pages", local_path) is None  # nothing there yet - never a broken reference
storage.upload("exam-pages", local_path, b"fake-jpeg-bytes")
assert Path(local_path).read_bytes() == b"fake-jpeg-bytes"  # really wrote to disk, parent dir created
assert storage.download("exam-pages", local_path) == b"fake-jpeg-bytes"

# ---- 2. Supabase-configured path: real HTTP calls stubbed, never hits the network --------------------
calls = []


class FakeResponse:
    def __init__(self, status_code=200, content=b""):
        self.status_code = status_code
        self.content = content
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


def fake_post(url, **kw):
    calls.append(("POST", url, kw))
    return FakeResponse(200)


def fake_get(url, **kw):
    calls.append(("GET", url, kw))
    if "missing" in url:
        return FakeResponse(404)
    return FakeResponse(200, content=b"remote-bytes")


storage.httpx = types.SimpleNamespace(post=fake_post, get=fake_get)
storage.settings = types.SimpleNamespace(SUPABASE_URL="https://proj.supabase.co", SUPABASE_SERVICE_KEY="k")

storage.upload("receipts", "abc.jpg", b"real-photo-bytes", content_type="image/jpeg")
method, url, kw = calls[-1]
assert method == "POST" and url == "https://proj.supabase.co/storage/v1/object/receipts/abc.jpg"
assert kw["content"] == b"real-photo-bytes" and kw["headers"]["Authorization"] == "Bearer k"
assert kw["headers"]["x-upsert"] == "true"

assert storage.download("receipts", "abc.jpg") == b"remote-bytes"
assert storage.download("receipts", "missing.jpg") is None  # a real 404 - never raises, never guesses

print("STORAGE TESTS PASSED")
