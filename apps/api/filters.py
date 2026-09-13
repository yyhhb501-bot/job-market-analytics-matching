"""Reusable job filter compilation shared by search and saved-search alerts.

Free-text search uses PostgreSQL full-text search (``search_vector`` generated
column + GIN index) when available and falls back to ``ILIKE`` everywhere else
(SQLite in tests, other engines).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, text

from apps.api.models import Job

# Kept in sync with the generated column created by migration 0003 and
# ``database.ensure_full_text_index``.
SEARCH_VECTOR_EXPR = (
    "to_tsvector('english', "
    "coalesce(title, '') || ' ' || coalesce(company, '') || ' ' || coalesce(description, ''))"
)
SEARCH_INDEX_NAME = "ix_jobs_search_vector"


def eq_any(column, values: list[str] | None):
    if not values:
        return None
    cleaned = [value for value in values if value]
    if not cleaned:
        return None
    return column.in_(cleaned)


def text_search_condition(q: str | None, dialect_name: str):
    """Full-text condition: tsvector match on PostgreSQL, else ILIKE."""
    if not q or not q.strip():
        return None
    query = q.strip()
    if dialect_name == "postgresql":
        return text("jobs.search_vector @@ plainto_tsquery('english', :fts_query)").bindparams(
            fts_query=query
        )
    pattern = f"%{query}%"
    return or_(
        Job.title.ilike(pattern),
        Job.company.ilike(pattern),
        Job.description.ilike(pattern),
    )


def relevance_order(q: str):
    """``ORDER BY ts_rank(...) DESC`` expression (PostgreSQL only)."""
    return text(
        "ts_rank(jobs.search_vector, plainto_tsquery('english', :fts_query)) DESC"
    ).bindparams(fts_query=q)


def build_conditions(
    *,
    q: str | None = None,
    sources: list[str] | None = None,
    countries: list[str] | None = None,
    states: list[str] | None = None,
    cities: list[str] | None = None,
    companies: list[str] | None = None,
    remote_types: list[str] | None = None,
    employment_types: list[str] | None = None,
    min_salary: float | None = None,
    posted_after: datetime | None = None,
    first_seen_after: datetime | None = None,
    dialect_name: str = "sqlite",
) -> list:
    conditions = []

    def add(condition) -> None:
        if condition is not None:
            conditions.append(condition)

    add(text_search_condition(q, dialect_name))
    add(eq_any(Job.source, sources))
    if countries:
        conditions.append(Job.country.in_([c.upper() for c in countries if c]))
    add(eq_any(Job.state, states))
    add(eq_any(Job.city, cities))
    add(eq_any(Job.company_normalized, companies))
    add(eq_any(Job.remote_type, remote_types))
    add(eq_any(Job.employment_type, employment_types))
    if min_salary is not None:
        conditions.append(func.coalesce(Job.salary_max, Job.salary_min) >= min_salary)
    if posted_after is not None:
        conditions.append(Job.posted_at >= posted_after)
    if first_seen_after is not None:
        conditions.append(Job.first_seen_at > first_seen_after)
    return conditions


def as_list(value: str | None) -> list[str] | None:
    """Accept a single filter value and turn it into the list ``build_conditions`` wants."""
    if value is None:
        return None
    text_value = value.strip()
    return [text_value] if text_value else None
