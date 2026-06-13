
# alembic/env.py
#
# This version uses a SYNCHRONOUS engine for migrations.
# The error you got was because async_engine_from_config was being
# used with a psycopg2 (sync) driver URL — those two cannot mix.
#
# Rule of thumb:
#   App runtime  → async engine (asyncpg driver)
#   Alembic migrations → sync engine (psycopg2 driver)
#
# They are completely separate concerns. Your app never uses this
# file at runtime. Alembic never uses your app's async engine.

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
settings = get_settings()  

# ---------------------------------------------------------------------------
# 1. Alembic config + logging
# ---------------------------------------------------------------------------
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# 2. Import all models so Base.metadata knows about every table
# ---------------------------------------------------------------------------
# CRITICAL: Every model must be imported here.
# If a model isn't imported, autogenerate won't see its table.
import sys
sys.path.insert(0, os.getcwd())  # ensures `app` is importable from project root

from app.models.base import Base          # noqa: E402
from app.models.user import User         # noqa: F401
from app.models.analysis_result import AnalysisResult  # noqa: F401
from app.models.job_postings import JobPosting          # noqa: F401

target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# 3. Inject DATABASE_URL from .env via pydantic-settings
# ---------------------------------------------------------------------------

# Swap async driver → sync driver.
# asyncpg  = async, for the running FastAPI app.
# psycopg2 = sync, for Alembic migrations only.
db_url = settings.DATABASE_URL.replace(
    "postgresql+asyncpg://",
    "postgresql+psycopg2://",
)
config.set_main_option("sqlalchemy.url", db_url)


# ---------------------------------------------------------------------------
# 4. Offline mode — generate SQL without connecting
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# 5. Online mode — connect and apply migrations synchronously
# ---------------------------------------------------------------------------
def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,   # one connection, close it when done
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


# ---------------------------------------------------------------------------
# 6. Entry point
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()