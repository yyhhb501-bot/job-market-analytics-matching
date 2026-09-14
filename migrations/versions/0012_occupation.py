"""occupation grouping + compare indexes

Revision ID: 0012_occupation
Revises: 0011_board_lifecycle
Create Date: 2026-01-12

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_occupation"
down_revision = "0011_board_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("occupation_group", sa.String(length=60)))
    op.add_column("jobs", sa.Column("seniority", sa.String(length=20)))
    op.create_index("ix_jobs_occupation_group", "jobs", ["occupation_group"])
    op.create_index(
        "ix_jobs_location_active", "jobs", ["country", "state", "city", "is_active"]
    )
    op.create_index(
        "ix_jobs_occupation_country", "jobs", ["occupation_group", "country"]
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_occupation_country", table_name="jobs")
    op.drop_index("ix_jobs_location_active", table_name="jobs")
    op.drop_index("ix_jobs_occupation_group", table_name="jobs")
    op.drop_column("jobs", "seniority")
    op.drop_column("jobs", "occupation_group")
