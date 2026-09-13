"""job summary source (extractive vs llm)

Revision ID: 0007_summary_source
Revises: 0006_semantic_embedding
Create Date: 2026-01-07

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_summary_source"
down_revision = "0006_semantic_embedding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("summary_source", sa.String(length=20)))


def downgrade() -> None:
    op.drop_column("jobs", "summary_source")
