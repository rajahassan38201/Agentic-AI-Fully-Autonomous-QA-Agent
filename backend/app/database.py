"""SQLAlchemy engine, session factory, and table creation."""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

# Columns added after the initial schema. create_all() never ALTERs existing
# tables, so we add any missing ones idempotently on startup (Postgres).
_MIGRATIONS = [
    "ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS input_tokens INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS output_tokens INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS cache_read_tokens INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS cache_write_tokens INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS has_video BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS video BYTEA",
]


def init_db() -> None:
    """Create tables if they don't exist, then apply lightweight column migrations."""
    from . import models  # noqa: F401  (ensures models are registered)

    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        for stmt in _MIGRATIONS:
            conn.execute(text(stmt))
