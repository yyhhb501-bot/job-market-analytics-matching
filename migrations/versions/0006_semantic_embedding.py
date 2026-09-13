"""job semantic embedding

Revision ID: 0006_semantic_embedding
Revises: 0005_enrichment
Create Date: 2026-01-06

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_semantic_embedding"
down_revision = "0005_enrichment"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB, "postgresql")


def upgrade() -> None:
    op.add_column("jobs", sa.Column("embedding", JSON_TYPE))


def downgrade() -> None:
    op.drop_column("jobs", "embedding")
