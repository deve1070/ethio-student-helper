"""Supabase Storage (S3-compatible object storage) for files that must survive a Render redeploy -
exam diagram photos (exams/store.py's question_page_image) and payment receipt photos
(api/routes_payments.py). Render's web-service disk is wiped on every redeploy; Supabase's free-tier
Storage (1GB) holds these instead, alongside the same account's free-tier Postgres.

Local dev never sets SUPABASE_URL, so every function here falls back to plain local-disk reads/writes
at the given path - the exact behavior this project always had before Supabase existed, so nothing
about running locally changes.
"""

from pathlib import Path

import httpx

from config.settings import settings


def _configured() -> bool:
    return bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY)


def upload(bucket: str, path: str, data: bytes, content_type: str = "image/jpeg") -> None:
    if not _configured():
        local = Path(path)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(data)
        return
    url = f"{settings.SUPABASE_URL}/storage/v1/object/{bucket}/{path}"
    resp = httpx.post(
        url,
        content=data,
        headers={
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
            "Content-Type": content_type,
            "x-upsert": "true",
        },
        timeout=30,
    )
    resp.raise_for_status()


def download(bucket: str, path: str, timeout: float = 30) -> bytes | None:
    """None on any miss (not configured and no local file, or a real 404) - never a broken reference
    shown to a student, matching question_page_image's existing never-guess contract.

    timeout defaults to a generous 30s (a student is waiting on this one specific photo), but a
    caller checking EXISTENCE for many questions at once (exams/store.py's _diagram_image_exists)
    should pass something much shorter - confirmed live that a slow/unreachable Storage call
    blocking the full 30s, once per question, in a single-worker deployment, takes the whole
    service down for everyone else for minutes while one listing request waits its way through."""
    if not _configured():
        local = Path(path)
        return local.read_bytes() if local.is_file() else None
    url = f"{settings.SUPABASE_URL}/storage/v1/object/{bucket}/{path}"
    resp = httpx.get(
        url, headers={"Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"}, timeout=timeout
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.content
