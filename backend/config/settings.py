from pydantic_settings import BaseSettings

from .constants import ALLOWED_TYPES, MAX_FILE_SIZE, MAX_TOTAL_SIZE


class Settings(BaseSettings):
    # Optional settings with defaults
    MAX_FILE_SIZE: int = MAX_FILE_SIZE
    MAX_TOTAL_SIZE: int = MAX_TOTAL_SIZE
    ALLOWED_TYPES: list = ALLOWED_TYPES

    # Vector store settings
    CHROMA_DB_PATH: str = "./chroma_db"
    CHROMA_COLLECTION_NAME: str = "documents"

    # Relational database (users, textbooks/chunks metadata, exam cache,
    # credits, payments — see docs/data-model-api.md)
    DATABASE_URL: str = (
        "postgresql+psycopg2://postgres:postgres@localhost:5432/ethio_student_helper"
    )

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
