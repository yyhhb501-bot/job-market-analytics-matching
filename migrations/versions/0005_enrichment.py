"""job enrichment fields (skills + summary)

Revision ID: 0005_enrichment
Revises: 0004_saved_search_notify
Create Date: 2026-01-05

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_enrichment"
down_revision = "0004_saved_search_notify"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB, "postgresql")


def upgrade() -> None:
    op.add_column("jobs", sa.Column("skills", JSON_TYPE))
    op.add_column("jobs", sa.Column("summary", sa.Text()))


def downgrade() -> None:
    op.drop_column("jobs", "summary")
    op.drop_column("jobs", "skills")
