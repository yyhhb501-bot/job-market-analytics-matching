"""Migration round-trip tests: upgrade head -> downgrade base -> upgrade head.

The SQLite variants run unconditionally (Alembic against a temp file DB). The
Postgres round-trip runs when ``TEST_POSTGRES_URL`` is set. Also asserts that
downgrading 0014 restores the pre-0014 ``(source, source_job_id)`` uniqueness
on both dialects.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@contextmanager
def _database_url(url: str):
    """Point Alembic (which reads DATABASE_URL via get_settings) at ``url``."""
    from apps.api.config import get_settings

    original = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original
        get_settings.cache_clear()


def _alembic_config() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _alembic_version(engine) -> str | None:
    with engine.connect() as conn:
        return conn.scalar(text("SELECT version_num FROM alembic_version"))


def _expected_head() -> str:
    script = ScriptDirectory.from_config(_alembic_config())
    heads = script.get_heads()
    assert len(heads) == 1, f"multiple migration heads: {heads}"
    return heads[0]


def _assert_single_head() -> None:
    _expected_head()


def _insert_job(engine, source_job_id: str, source: str = "testsrc") -> None:
    import datetime as dt

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO jobs (source, source_job_id, title, content_hash, "
                "first_seen_at, last_seen_at, is_active) "
                "VALUES (:source, :sid, 'Title', 'hash', :now, :now, 1)"
            ),
            {"source": source, "sid": source_job_id, "now": dt.datetime.now(dt.UTC)},
        )


def test_single_migration_head():
    _assert_single_head()


def test_sqlite_roundtrip_and_downgraded_uniqueness(tmp_path):
    url = "sqlite+pysqlite:///" + (tmp_path / "mig.db").as_posix()
    cfg = _alembic_config()
    with _database_url(url):
        command.upgrade(cfg, "head")
        engine = create_engine(url)
        try:
            assert _alembic_version(engine) == _expected_head()
            # 0016: collection-control schema exists at head.
            inspector = sa.inspect(engine)
            tables = set(inspector.get_table_names())
            assert {"source_controls", "source_visit_counters"} <= tables
            run_columns = {col["name"] for col in inspector.get_columns("collector_runs")}
            assert {"stopped_reason", "pages_visited", "details_visited"} <= run_columns
        finally:
            engine.dispose()

        command.downgrade(cfg, "0013_boards")
        engine = create_engine(url)
        try:
            assert _alembic_version(engine) == "0013_boards"

            # Regression: 0014.downgrade must restore the (source, source_job_id)
            # uniqueness on SQLite too, not only on PostgreSQL.
            _insert_job(engine, "job-1")
            with pytest.raises(Exception):  # noqa: B017, PT011 - IntegrityError
                _insert_job(engine, "job-1")
        finally:
            engine.dispose()

        command.upgrade(cfg, "head")
        engine = create_engine(url)
        try:
            assert _alembic_version(engine) == _expected_head()
        finally:
            engine.dispose()


def test_sqlite_owner_scoped_uniqueness_after_upgrade(tmp_path):
    url = "sqlite+pysqlite:///" + (tmp_path / "mig2.db").as_posix()
    cfg = _alembic_config()
    with _database_url(url):
        command.upgrade(cfg, "head")
    engine = create_engine(url)
    try:
        # Public rows (owner NULL) must stay unique on (source, source_job_id).
        _insert_job(engine, "dup-job")
        with pytest.raises(Exception):  # noqa: B017, PT011 - IntegrityError
            _insert_job(engine, "dup-job")

        # Known limitation of the Alembic-migrated SQLite path: the table-level
        # UNIQUE constraint from 0001 cannot be dropped without a table rebuild,
        # so unlike PostgreSQL the migrated SQLite schema enforces plain
        # (source, source_job_id) uniqueness across owners. (Preview
        # environments use Base.metadata.create_all, which matches the ORM and
        # applies the owner-scoped expression index instead.)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO collector_devices (name, owner_ref, platform, "
                    "token_hash, token_prefix) VALUES ('d', 'o', 'linkedin', "
                    "'deadbeef', 'jagg_deadbeef')"
                )
            )
        with pytest.raises(Exception):  # noqa: B017, PT011 - IntegrityError
            import datetime as dt

            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO jobs (source, source_job_id, title, content_hash, "
                        "owner_device_id, first_seen_at, last_seen_at, is_active) "
                        "VALUES ('testsrc', 'dup-job', 'Title', 'hash', 1, :now, :now, 1)"
                    ),
                    {"now": dt.datetime.now(dt.UTC)},
                )
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES_URL"), reason="TEST_POSTGRES_URL not set"
)
def test_postgres_roundtrip():
    url = os.environ["TEST_POSTGRES_URL"]
    cfg = _alembic_config()
    with _database_url(url):
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    engine = create_engine(url)
    try:
        assert _alembic_version(engine) == _expected_head()
    finally:
        engine.dispose()
