from __future__ import annotations

from sqlalchemy.dialects import postgresql, sqlite

from apps.api.filters import (
    as_list,
    build_conditions,
    eq_any,
    relevance_order,
    text_search_condition,
)
from apps.api.models import Job


def _compile(condition, dialect) -> str:
    return str(condition.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))


def test_text_search_postgres_uses_tsvector():
    condition = text_search_condition("data engineer", "postgresql")
    compiled = _compile(condition, postgresql.dialect())
    assert "search_vector" in compiled
    assert "plainto_tsquery" in compiled
    assert "data engineer" in compiled


def test_text_search_sqlite_uses_ilike():
    condition = text_search_condition("data", "sqlite")
    compiled = _compile(condition, sqlite.dialect()).upper()
    assert "LIKE" in compiled
    assert "SEARCH_VECTOR" not in compiled


def test_text_search_empty_returns_none():
    assert text_search_condition("", "sqlite") is None
    assert text_search_condition("   ", "postgresql") is None
    assert text_search_condition(None, "postgresql") is None


def test_build_conditions_switches_on_dialect():
    postgres_condition = build_conditions(q="python", dialect_name="postgresql")[0]
    assert "plainto_tsquery" in _compile(postgres_condition, postgresql.dialect())

    sqlite_condition = build_conditions(q="python", dialect_name="sqlite")[0]
    assert "LIKE" in _compile(sqlite_condition, sqlite.dialect()).upper()


def test_relevance_order_compiles_on_postgres():
    compiled = _compile(relevance_order("python"), postgresql.dialect())
    assert "ts_rank" in compiled


def test_eq_any_and_as_list():
    assert as_list(" US ") == ["US"]
    assert as_list("") is None
    assert as_list(None) is None
    assert eq_any(Job.source, ["", None]) is None
    assert eq_any(Job.source, ["seek"]) is not None
