import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy import pool

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Importing every model module registers its tables on the one shared Base
# (db/models.py) before target_metadata is read below - autogenerate only sees
# tables whose module has actually been imported.
import db.models  # noqa: E402
import db.models_practice  # noqa: E402
import db.models_studyplan  # noqa: E402
import exams.models  # noqa: E402
import notes.models  # noqa: E402
from config.settings import settings  # noqa: E402
from db.models import Base  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The app's own DATABASE_URL (from .env/Render env vars) is the single source of
# truth for the connection - alembic.ini is never given a real connection string.
# Not routed through config.set_main_option/get_main_option: that goes through
# configparser's % interpolation, which raises on a URL-encoded password (this
# project's DATABASE_URL contains a literal "%40"), so the URL is kept in a plain
# module variable instead.
db_url = settings.DATABASE_URL

target_metadata = Base.metadata

# langchain_postgres owns these two tables directly (PGVector creates/manages them
# itself, see retriever/vectorstore.py) - they hold the entire vector store
# (textbooks/exam_questions/esslce_exams collections) and are never declared on
# this project's own Base. Without this filter, autogenerate sees them as
# "extra" tables not in target_metadata and proposes DROP TABLE for both on every
# future revision, which would delete all embeddings if that revision were ever
# applied.
_EXTERNALLY_MANAGED_TABLES = {"langchain_pg_collection", "langchain_pg_embedding"}


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and name in _EXTERNALLY_MANAGED_TABLES:
        return False
    return True


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = create_engine(db_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
