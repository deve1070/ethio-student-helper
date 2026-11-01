"""
FastAPI entrypoint for the production backend. This is the single service
that the web app, Telegram bot, and mobile app all call — none of them
talk to the database, vector store, or agents directly.

app.py's Gradio UI is left in place as a local debugging tool for the
underlying retriever/agent logic; it is not part of the production path.

Run with: uvicorn main:app --reload
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import create_engine, text

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
from config.settings import settings
from utils.logging import logger

# A deployment that reaches this point with the dev-only secret would sign JWTs an
# attacker could forge from the public source alone, so refuse to boot rather than
# serve traffic insecurely.
if settings.ENVIRONMENT == "production" and settings.JWT_SECRET_KEY == "dev-only-change-me":
    raise RuntimeError("JWT_SECRET_KEY is still the dev default - set a real secret before running in production")

if settings.ENVIRONMENT == "production" and not settings.TELEGRAM_BOT_TOKEN:
    logger.warning(
        "TELEGRAM_BOT_TOKEN is unset in production - pending payment receipts will never "
        "reach an admin for approval (payments/admin_notify.py silently skips the Telegram push)."
    )

if settings.SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(dsn=settings.SENTRY_DSN, environment=settings.ENVIRONMENT, traces_sample_rate=0.0)

app = FastAPI(title="Ethiopian Student Helper API", version="0.1.0")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"Unhandled error on {request.method} {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# The Telegram bot and mobile app call this API directly (no browser involved, so no
# origin to check); the web frontend is the only caller CORS applies to, and it's a
# separate origin from this service on Vercel/Render. Local dev origins are only added
# outside production, so the Vite dev server works without any env var set.
_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
if settings.ENVIRONMENT != "production":
    _origins += ["http://localhost:5173", "http://127.0.0.1:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(explain_router)
app.include_router(practice_router)
app.include_router(esslce_router)
app.include_router(payments_router)
app.include_router(progress_router)
app.include_router(studyplan_router)
app.include_router(notes_router)
app.include_router(exam_router)

# Built once, reused by every /health call below instead of opening a fresh connection
# pool per request.
_health_engines = {
    "database": create_engine(settings.DATABASE_URL),
    "vector_database": create_engine(settings.VECTOR_DATABASE_URL),
}


@app.get("/health")
def health() -> dict:
    for name, engine in _health_engines.items():
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as e:
            logger.error(f"Health check: {name} unreachable: {e}")
            return JSONResponse(status_code=503, content={"status": "error", "detail": f"{name} unreachable"})
    return {"status": "ok"}
