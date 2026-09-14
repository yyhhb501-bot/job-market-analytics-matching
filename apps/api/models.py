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

    # data governance: public platform data vs user-private local-collector data.
    # ``owner_device_id`` is NULL for public/platform rows and set for private
    # imported rows so per-device dedup and access isolation can be enforced.
    visibility: Mapped[str] = mapped_column(
        String(16), default="public", server_default="public", index=True
    )
    collection_mode: Mapped[str] = mapped_column(
        String(20), default="platform", server_default="platform", index=True
    )
    owner_device_id: Mapped[int | None] = mapped_column(
        bigint_pk(),
        ForeignKey("collector_devices.id", ondelete="SET NULL"),
        index=True,
    )

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
    # occupation taxonomy used by the market-compare feature
    occupation_group: Mapped[str | None] = mapped_column(String(60), index=True)
    seniority: Mapped[str | None] = mapped_column(String(20))

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )

    __table_args__ = (
        # Identity uniqueness is scoped by owner: public rows (owner NULL) dedup
        # among themselves, while every device's private imports dedup separately.
        Index(
            "uq_jobs_source_job_id",
            "source",
            "source_job_id",
            text("(coalesce(owner_device_id, 0))"),
            unique=True,
        ),
        Index("ix_jobs_source_first_seen", "source", "first_seen_at"),
        Index("ix_jobs_country_company", "country", "company_normalized"),
        Index("ix_jobs_location_active", "country", "state", "city", "is_active"),
        Index("ix_jobs_occupation_country", "occupation_group", "country"),
        Index(
            "uq_jobs_dedup_key_active",
            "dedup_key",
            text("(coalesce(owner_device_id, 0))"),
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


class Board(Base):
    """A public ATS board/company to poll.

    Replaces relying solely on ``config/ats_companies.json`` so boards can be
    discovered, verified, paused and managed at runtime.
    """

    __tablename__ = "boards"

    id: Mapped[int] = mapped_column(bigint_pk(), primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    board_token: Mapped[str] = mapped_column(String(255))
    company_name: Mapped[str | None] = mapped_column(String(255))
    company_domain: Mapped[str | None] = mapped_column(String(255), index=True)
    country: Mapped[str | None] = mapped_column(String(2), index=True)
    careers_url: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict | None] = mapped_column(json_type())
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    discovery_source: Mapped[str | None] = mapped_column(String(30))
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_job_count: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    discovered_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("provider", "board_token", name="uq_boards_provider_token"),
    )


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


class CollectorDevice(Base):
    """A user's local collector installation, authorised by a device token.

    Only the hash of the token is stored; the raw token is shown once at
    creation. ``owner_ref`` is the user/account identifier the device belongs
    to (an email or user id today, a foreign key once accounts exist).
    """

    __tablename__ = "collector_devices"

    id: Mapped[int] = mapped_column(bigint_pk(), primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120))
    owner_ref: Mapped[str] = mapped_column(String(255), index=True)
    platform: Mapped[str] = mapped_column(String(40), default="linkedin")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_prefix: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_collector_devices_token_hash", "token_hash", unique=True),)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<CollectorDevice id={self.id} owner={self.owner_ref!r}>"


class ImportBatch(Base):
    """One run of a local collector upload, for idempotency and monitoring."""

    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(bigint_pk(), primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        bigint_pk(), ForeignKey("collector_devices.id", ondelete="CASCADE"), index=True
    )
    owner_ref: Mapped[str] = mapped_column(String(255), index=True)
    source: Mapped[str] = mapped_column(String(50), default="linkedin_user_import")
    query: Mapped[str | None] = mapped_column(String(300))
    geo_id: Mapped[str | None] = mapped_column(String(50))
    collection_mode: Mapped[str] = mapped_column(String(20), default="user_local")
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="received", index=True)
    received_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("device_id", "idempotency_key", name="uq_import_batch_idempotency"),
    )


class JobImportProvenance(Base):
    """Links a stored job back to the device/batch that imported it."""

    __tablename__ = "job_import_provenance"

    id: Mapped[int] = mapped_column(bigint_pk(), primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        bigint_pk(), ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    batch_id: Mapped[int] = mapped_column(
        bigint_pk(), ForeignKey("import_batches.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[int] = mapped_column(
        bigint_pk(), ForeignKey("collector_devices.id", ondelete="CASCADE"), index=True
    )
    owner_ref: Mapped[str] = mapped_column(String(255), index=True)
    collection_mode: Mapped[str] = mapped_column(String(20), default="user_local")
    action: Mapped[str] = mapped_column(String(20), default="inserted")
    source_url: Mapped[str | None] = mapped_column(Text)
    collected_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("batch_id", "job_id", name="uq_import_provenance_batch_job"),
    )


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
