"""
FastAPI entrypoint for the production backend. This is the single service
that the web app, Telegram bot, and mobile app all call — none of them
talk to the database, vector store, or agents directly.

app.py's Gradio UI is left in place as a local debugging tool for the
underlying retriever/agent logic; it is not part of the production path.

Run with: uvicorn main:app --reload
"""

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.rate_limit import limiter
from api.routes_auth import router as auth_router
from api.routes_esslce import router as esslce_router
from api.routes_exam import router as exam_router
from api.routes_explain import router as explain_router
from api.routes_payments import router as payments_router
from api.routes_practice import router as practice_router
from api.routes_progress import router as progress_router
from api.routes_notes import router as notes_router
from api.routes_studyplan import router as studyplan_router

app = FastAPI(title="Ethiopian Student Helper API", version="0.1.0")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.include_router(auth_router)
app.include_router(explain_router)
app.include_router(practice_router)
app.include_router(esslce_router)
app.include_router(payments_router)
app.include_router(progress_router)
app.include_router(studyplan_router)
app.include_router(notes_router)
# app.include_router(exam_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
