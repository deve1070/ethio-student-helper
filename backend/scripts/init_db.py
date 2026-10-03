"""
One-off bootstrap: creates every table from db/models.py directly via
SQLAlchemy metadata. Alembic is in requirements.txt but no migration
files exist yet — this is the fast path for local dev/testing. Switch to
real Alembic migrations (`alembic revision --autogenerate`) before this
touches a shared or production database.

Run as: python -m scripts.init_db
"""

from db.models import Base
from db.session import engine


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print("Tables created.")


if __name__ == "__main__":
    main()
