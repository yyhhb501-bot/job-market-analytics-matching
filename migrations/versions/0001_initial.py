"""initial schema: jobs + collector_runs

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB, "postgresql")
BIGINT_PK = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_job_id", sa.String(length=255), nullable=False),
        sa.Column("canonical_url", sa.Text()),
        sa.Column("apply_url", sa.Text()),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("title_normalized", sa.Text()),
        sa.Column("company", sa.Text()),
        sa.Column("company_normalized", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("country", sa.String(length=2)),
        sa.Column("state", sa.String(length=100)),
        sa.Column("city", sa.String(length=150)),
        sa.Column("remote_type", sa.String(length=20)),
        sa.Column("employment_type", sa.String(length=30)),
        sa.Column("salary_min", sa.Float()),
        sa.Column("salary_max", sa.Float()),
        sa.Column("salary_currency", sa.String(length=3)),
        sa.Column("salary_period", sa.String(length=20)),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("description_hash", sa.String(length=64)),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("dedup_key", sa.String(length=64)),
        sa.Column("canonical_url_hash", sa.String(length=64)),
        sa.Column("duplicate_of", BIGINT_PK),
        sa.Column("raw_payload", JSON_TYPE),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("source", "source_job_id", name="uq_jobs_source_job_id"),
    )
    op.create_index("ix_jobs_source", "jobs", ["source"])
    op.create_index("ix_jobs_country", "jobs", ["country"])
    op.create_index("ix_jobs_remote_type", "jobs", ["remote_type"])
    op.create_index("ix_jobs_employment_type", "jobs", ["employment_type"])
    op.create_index("ix_jobs_is_active", "jobs", ["is_active"])
    op.create_index("ix_jobs_content_hash", "jobs", ["content_hash"])
    op.create_index("ix_jobs_dedup_key", "jobs", ["dedup_key"])
    op.create_index("ix_jobs_canonical_url_hash", "jobs", ["canonical_url_hash"])
    op.create_index("ix_jobs_duplicate_of", "jobs", ["duplicate_of"])
    op.create_index("ix_jobs_source_first_seen", "jobs", ["source", "first_seen_at"])
    op.create_index("ix_jobs_country_company", "jobs", ["country", "company_normalized"])

    op.create_table(
        "collector_runs",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("params", JSON_TYPE),
        sa.Column("jobs_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_duplicate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_collector_runs_source", "collector_runs", ["source"])
    op.create_index("ix_collector_runs_status", "collector_runs", ["status"])


def downgrade() -> None:
    op.drop_table("collector_runs")
    op.drop_table("jobs")
