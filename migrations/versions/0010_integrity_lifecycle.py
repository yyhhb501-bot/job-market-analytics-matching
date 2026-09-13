"""job lifecycle columns, foreign keys, dedup unique index

Revision ID: 0010_integrity_lifecycle
Revises: 0009_webhook_kind
Create Date: 2026-01-10

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_integrity_lifecycle"
down_revision = "0009_webhook_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    op.add_column("jobs", sa.Column("closed_at", sa.DateTime(timezone=True)))
    op.add_column("jobs", sa.Column("inactive_reason", sa.String(length=30)))

    # Prevents two Celery workers inserting the same new job concurrently.
    op.create_index(
        "uq_jobs_dedup_key_active",
        "jobs",
        ["dedup_key"],
        unique=True,
        postgresql_where=sa.text("duplicate_of IS NULL"),
        sqlite_where=sa.text("duplicate_of IS NULL"),
    )

    if is_postgres:
        op.create_foreign_key(
            "fk_jobs_duplicate_of",
            "jobs",
            "jobs",
            ["duplicate_of"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_foreign_key(
            "fk_saved_search_matches_search",
            "saved_search_matches",
            "saved_searches",
            ["saved_search_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_saved_search_matches_job",
            "saved_search_matches",
            "jobs",
            ["job_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.drop_constraint("fk_saved_search_matches_job", "saved_search_matches", type_="foreignkey")
        op.drop_constraint("fk_saved_search_matches_search", "saved_search_matches", type_="foreignkey")
        op.drop_constraint("fk_jobs_duplicate_of", "jobs", type_="foreignkey")

    op.drop_index("uq_jobs_dedup_key_active", table_name="jobs")
    op.drop_column("jobs", "inactive_reason")
    op.drop_column("jobs", "closed_at")
