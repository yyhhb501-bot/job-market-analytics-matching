"""per-board job lifecycle columns

Revision ID: 0011_board_lifecycle
Revises: 0010_integrity_lifecycle
Create Date: 2026-01-11

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_board_lifecycle"
down_revision = "0010_integrity_lifecycle"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def upgrade() -> None:
    op.add_column("jobs", sa.Column("last_seen_run_id", BIGINT))
    op.add_column(
        "jobs",
        sa.Column("missing_runs", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_jobs_last_seen_run_id", "jobs", ["last_seen_run_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_last_seen_run_id", table_name="jobs")
    op.drop_column("jobs", "missing_runs")
    op.drop_column("jobs", "last_seen_run_id")
