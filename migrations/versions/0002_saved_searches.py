"""saved searches and matches

Revision ID: 0002_saved_searches
Revises: 0001_initial
Create Date: 2026-01-02

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_saved_searches"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

BIGINT_PK = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def upgrade() -> None:
    op.create_table(
        "saved_searches",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("keywords", sa.String(length=300)),
        sa.Column("country", sa.String(length=2)),
        sa.Column("source", sa.String(length=50)),
        sa.Column("city", sa.String(length=150)),
        sa.Column("state", sa.String(length=100)),
        sa.Column("remote_type", sa.String(length=20)),
        sa.Column("employment_type", sa.String(length=30)),
        sa.Column("min_salary", sa.Float()),
        sa.Column("notify_email", sa.String(length=255)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_match_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_saved_searches_is_active", "saved_searches", ["is_active"])

    op.create_table(
        "saved_search_matches",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("saved_search_id", BIGINT_PK, nullable=False),
        sa.Column("job_id", BIGINT_PK, nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("saved_search_id", "job_id", name="uq_saved_search_match"),
    )
    op.create_index("ix_saved_search_matches_saved_search_id", "saved_search_matches", ["saved_search_id"])
    op.create_index("ix_saved_search_matches_job_id", "saved_search_matches", ["job_id"])


def downgrade() -> None:
    op.drop_table("saved_search_matches")
    op.drop_table("saved_searches")
