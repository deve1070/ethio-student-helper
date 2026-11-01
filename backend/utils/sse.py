"""Server-Sent Events formatting, shared by every route that streams progress
stages to the frontend instead of blocking on one request/response (routes_explain.py,
routes_notes.py). The SSE wire format is just a "data: <json>\\n\\n" line per event -
this is the one place that builds it, so every stream looks identical to the frontend's
single parser (frontend/src/lib/sse.ts)."""
import json


def format_sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"
