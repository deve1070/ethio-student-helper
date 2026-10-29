from pydantic_settings import BaseSettings

from .constants import ALLOWED_TYPES, MAX_FILE_SIZE, MAX_TOTAL_SIZE


class Settings(BaseSettings):
    # Optional settings with defaults
    MAX_FILE_SIZE: int = MAX_FILE_SIZE
    MAX_TOTAL_SIZE: int = MAX_TOTAL_SIZE
    ALLOWED_TYPES: list = ALLOWED_TYPES

    # Relational database (users, textbooks/chunks metadata, exam cache,
    # credits, payments — see docs/data-model-api.md). In production this is
    # a Supabase Postgres connection string, set via the DATABASE_URL env var.
    DATABASE_URL: str = (
        "postgresql+psycopg2://postgres:postgres@localhost:5432/ethio_student_helper"
    )

    # Same database as DATABASE_URL, but on the psycopg3 driver langchain-postgres
    # requires (SQLAlchemy's own engine above stays on psycopg2 — the two drivers
    # coexist fine, each on its own connection string scheme).
    VECTOR_DATABASE_URL: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/ethio_student_helper"
    )

    # Supabase Storage (exam diagram photos, payment receipts) — empty locally,
    # where exams/store.py and routes_payments.py fall back to reading/writing
    # local disk directly instead.
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    # CORS — the Vercel frontend origin(s), comma-separated. Localhost is always
    # allowed for local dev regardless of this setting.
    ALLOWED_ORIGINS: str = ""

    # Payments: manual receipt + admin approval (Chapa dropped — no TIN/business
    # registration, see esh_payments_manual_receipt memory). TELEGRAM_BOT_TOKEN is
    # read here (not just by telegram_bot/config.py) so the backend can push a
    # receipt-needs-review notification straight to an admin's Telegram chat.
    TELEGRAM_BOT_TOKEN: str = ""
    RECEIPTS_DIR: str = "receipts"

    # Auth — JWT_SECRET_KEY MUST be overridden via environment in any
    # real deployment; this default is only safe for local dev
    JWT_SECRET_KEY: str = "dev-only-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = (
        60 * 24 * 14
    )  # 2 weeks — students shouldn't have to re-login often

    # Retrieval settings
    VECTOR_SEARCH_K: int = 10
    HYBRID_RETRIEVER_WEIGHTS: list = [0.4, 0.6]

    # LLM + embeddings providers — Groq for chat generation (fast, free
    # tier), Gemini for embeddings (Groq doesn't serve embedding models).
    # Get free keys at console.groq.com and aistudio.google.com.
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GEMINI_API_KEY: str = ""
    GEMINI_EMBEDDING_MODEL: str = "models/gemini-embedding-001"

    # Logging settings
    LOG_LEVEL: str = "INFO"

    # New cache settings with type annotations
    CACHE_DIR: str = "document_cache"
    CACHE_EXPIRE_DAYS: int = 7

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # .env is shared with telegram_bot/config.py (e.g. TELEGRAM_BOT_TOKEN),
        # which this Settings class doesn't declare a field for and doesn't need to


settings = Settings()
