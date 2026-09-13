"""SQLAlchemy models. The unified ``jobs`` table is the heart of the platform."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.database import Base


def json_type():
    """JSONB on PostgreSQL, plain JSON everywhere else (e.g. SQLite tests)."""
    return JSON().with_variant(JSONB, "postgresql")


def bigint_pk():
    """BIGINT on PostgreSQL, INTEGER on SQLite so autoincrement keeps working."""
    return BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(bigint_pk(), primary_key=True, autoincrement=True)

    # identity / provenance
    source: Mapped[str] = mapped_column(String(50), index=True)
    source_job_id: Mapped[str] = mapped_column(String(255))
    canonical_url: Mapped[str | None] = mapped_column(Text)
    apply_url: Mapped[str | None] = mapped_column(Text)

    # content
    title: Mapped[str] = mapped_column(Text)
    title_normalized: Mapped[str | None] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(Text)
    company_normalized: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)

    # location / classification
    country: Mapped[str | None] = mapped_column(String(2), index=True)
    state: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(150))
    remote_type: Mapped[str | None] = mapped_column(String(20), index=True)
    employment_type: Mapped[str | None] = mapped_column(String(30), index=True)

    # compensation (always stored in the original currency)
    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_period: Mapped[str | None] = mapped_column(String(20))

    # lifecycle
    posted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    last_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    inactive_reason: Mapped[str | None] = mapped_column(String(30))
    # per-board lifecycle: which run last saw this row, and how many complete
    # board runs have missed it in a row.
    last_seen_run_id: Mapped[int | None] = mapped_column(bigint_pk(), index=True)
    missing_runs: Mapped[int] = mapped_column(Integer, default=0)

    # deduplication
    description_hash: Mapped[str | None] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    dedup_key: Mapped[str | None] = mapped_column(String(64), index=True)
    canonical_url_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    duplicate_of: Mapped[int | None] = mapped_column(
        bigint_pk(), ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )

    # raw source payload for re-processing / auditing
    raw_payload: Mapped[dict | None] = mapped_column(json_type())

    # enrichment (skills extraction + extractive summary + semantic embedding)
    skills: Mapped[list | None] = mapped_column(json_type())
    summary: Mapped[str | None] = mapped_column(Text)
    summary_source: Mapped[str | None] = mapped_column(String(20))
    embedding: Mapped[list | None] = mapped_column(json_type())

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("source", "source_job_id", name="uq_jobs_source_job_id"),
        Index("ix_jobs_source_first_seen", "source", "first_seen_at"),
        Index("ix_jobs_country_company", "country", "company_normalized"),
        Index(
            "uq_jobs_dedup_key_active",
            "dedup_key",
            unique=True,
            sqlite_where=text("duplicate_of IS NULL"),
            postgresql_where=text("duplicate_of IS NULL"),
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Job id={self.id} source={self.source} title={self.title!r}>"


class CollectorRun(Base):
    """Simple task-status table used for monitoring collector health."""

    __tablename__ = "collector_runs"

    id: Mapped[int] = mapped_column(bigint_pk(), primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    params: Mapped[dict | None] = mapped_column(json_type())
    jobs_seen: Mapped[int] = mapped_column(Integer, default=0)
    jobs_inserted: Mapped[int] = mapped_column(Integer, default=0)
    jobs_updated: Mapped[int] = mapped_column(Integer, default=0)
    jobs_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class SavedSearch(Base):
    """A stored filter set that can be re-run to surface newly seen jobs."""

    __tablename__ = "saved_searches"

    id: Mapped[int] = mapped_column(bigint_pk(), primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    keywords: Mapped[str | None] = mapped_column(String(300))
    country: Mapped[str | None] = mapped_column(String(2))
    source: Mapped[str | None] = mapped_column(String(50))
    city: Mapped[str | None] = mapped_column(String(150))
    state: Mapped[str | None] = mapped_column(String(100))
    remote_type: Mapped[str | None] = mapped_column(String(20))
    employment_type: Mapped[str | None] = mapped_column(String(30))
    min_salary: Mapped[float | None] = mapped_column(Float)
    notify_email: Mapped[str | None] = mapped_column(String(255))
    webhook_url: Mapped[str | None] = mapped_column(String(500))
    webhook_kind: Mapped[str] = mapped_column(String(20), default="generic")
    frequency: Mapped[str] = mapped_column(String(20), default="immediate")
    unsubscribe_token: Mapped[str | None] = mapped_column(String(64), index=True, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_notified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_match_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )

    def as_filters(self) -> dict:
        return {
            "keywords": self.keywords,
            "country": self.country,
            "source": self.source,
            "city": self.city,
            "state": self.state,
            "remote_type": self.remote_type,
            "employment_type": self.employment_type,
            "min_salary": self.min_salary,
        }


class SavedSearchMatch(Base):
    """A job that matched a saved search on a given run."""

    __tablename__ = "saved_search_matches"

    id: Mapped[int] = mapped_column(bigint_pk(), primary_key=True, autoincrement=True)
    saved_search_id: Mapped[int] = mapped_column(
        bigint_pk(), ForeignKey("saved_searches.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[int] = mapped_column(
        bigint_pk(), ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    matched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("saved_search_id", "job_id", name="uq_saved_search_match"),
    )
