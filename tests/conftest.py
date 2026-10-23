"""Test fixtures. Tests run entirely on in-memory SQLite.

Opt-in integration fixtures (``pg_*`` / ``real_redis``) activate when the
``TEST_POSTGRES_URL`` / ``TEST_REDIS_URL`` environment variables are set; they
are skipped otherwise. The Postgres fixtures build their schema with real
Alembic migrations instead of ``Base.metadata.create_all``.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ["AUTO_CREATE_TABLES"] = "false"
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
# Keep rate-limit tests deterministic and independent of a local Redis.
os.environ["RATE_LIMIT_BACKEND"] = "memory"
# require_api_key fails closed when API_KEY is unset (503), so tests run with a
# key configured and the client fixtures below attach it by default.
os.environ["API_KEY"] = "test-api-key"

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from apps.api import (
    membership_models,  # noqa: E402,F401  (register users foreign keys)
    models,  # noqa: E402,F401  (register tables)
)
from apps.api.database import Base, get_db  # noqa: E402

TEST_POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL")

REPO_ROOT = Path(__file__).resolve().parent.parent

requires_postgres = pytest.mark.skipif(
    not TEST_POSTGRES_URL, reason="TEST_POSTGRES_URL not set"
)
requires_redis = pytest.mark.skipif(not TEST_REDIS_URL, reason="TEST_REDIS_URL not set")


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def session(session_factory):
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(session_factory):
    from fastapi.testclient import TestClient

    from apps.api.main import app

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        test_client.headers["X-API-Key"] = os.environ["API_KEY"]
        yield test_client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Opt-in real-service fixtures (Postgres via Alembic migrations, Redis).
# ---------------------------------------------------------------------------


def _truncate_all_tables(engine) -> None:
    """Reset every non-Alembic table between tests."""
    from sqlalchemy import inspect

    inspector = inspect(engine)
    tables = [t for t in inspector.get_table_names() if t != "alembic_version"]
    if not tables:
        return
    quoted = ", ".join(f'"{t}"' for t in tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session")
def pg_engine():
    if not TEST_POSTGRES_URL:
        pytest.skip("TEST_POSTGRES_URL not set")

    from alembic import command
    from alembic.config import Config

    from apps.api.config import get_settings

    # Alembic's env.py reads DATABASE_URL via get_settings() (lru_cached).
    original_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_POSTGRES_URL
    get_settings.cache_clear()
    try:
        alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
        command.upgrade(alembic_cfg, "head")
    finally:
        if original_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_url
        get_settings.cache_clear()

    engine = create_engine(TEST_POSTGRES_URL)
    _truncate_all_tables(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def pg_session_factory(pg_engine):
    return sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def pg_session(pg_engine, pg_session_factory):
    _truncate_all_tables(pg_engine)
    db = pg_session_factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def pg_client(pg_engine, pg_session_factory):
    from fastapi.testclient import TestClient

    from apps.api.main import app

    _truncate_all_tables(pg_engine)

    def override_get_db():
        db = pg_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        test_client.headers["X-API-Key"] = os.environ["API_KEY"]
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def settings_env():
    """Context manager to override env vars + the cached Settings object.

    ``require_api_key`` / ``rate_limit`` read ``get_settings()`` per request, so
    tests must clear the ``lru_cache`` and restore afterwards.
    """
    from contextlib import contextmanager

    from apps.api.config import get_settings

    @contextmanager
    def _override(**env):
        originals = {name: os.environ.get(name) for name in env}
        for name, value in env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        get_settings.cache_clear()
        try:
            yield get_settings()
        finally:
            for name, value in originals.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            get_settings.cache_clear()

    return _override


@pytest.fixture
def real_redis():
    if not TEST_REDIS_URL:
        pytest.skip("TEST_REDIS_URL not set")
    import redis

    client = redis.Redis.from_url(TEST_REDIS_URL)
    client.flushdb()
    yield client
    client.flushdb()
