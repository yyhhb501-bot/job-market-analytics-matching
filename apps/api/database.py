"""Engine, session factory and declarative base."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from apps.api.config import get_settings


class Base(DeclarativeBase):
    pass


def build_engine(url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = build_engine(get_settings().database_url)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _SessionLocal


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a short-lived session."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def ensure_full_text_index(engine: Engine) -> None:
    """Create the PostgreSQL full-text column + GIN index (idempotent).

    SQLite and other engines are skipped; search falls back to ``ILIKE`` there.
    """
    if engine.dialect.name != "postgresql":
        return
    from apps.api.filters import SEARCH_VECTOR_EXPR

    statements = (
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS search_vector tsvector "
        f"GENERATED ALWAYS AS ({SEARCH_VECTOR_EXPR}) STORED",
        "CREATE INDEX IF NOT EXISTS ix_jobs_search_vector ON jobs USING gin (search_vector)",
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def create_all() -> None:
    from apps.api import (
        membership_models,  # noqa: F401 (ensure member table is registered)
        models,  # noqa: F401  (ensure models are registered)
    )

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    ensure_full_text_index(engine)
