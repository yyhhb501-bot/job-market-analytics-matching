"""boards table

Revision ID: 0013_boards
Revises: 0012_occupation
Create Date: 2026-01-13

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_boards"
down_revision = "0012_occupation"
branch_labels = None
depends_on = None

BIGINT_PK = sa.BigInteger().with_variant(sa.Integer, "sqlite")
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "boards",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("board_token", sa.String(length=255), nullable=False),
        sa.Column("company_name", sa.String(length=255)),
        sa.Column("company_domain", sa.String(length=255)),
        sa.Column("country", sa.String(length=2)),
        sa.Column("careers_url", sa.Text()),
        sa.Column("config", JSON_TYPE),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("discovery_source", sa.String(length=30)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_job_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "board_token", name="uq_boards_provider_token"),
    )
    op.create_index("ix_boards_provider", "boards", ["provider"])
    op.create_index("ix_boards_enabled", "boards", ["enabled"])
    op.create_index("ix_boards_company_domain", "boards", ["company_domain"])
    op.create_index("ix_boards_country", "boards", ["country"])


def downgrade() -> None:
    op.drop_table("boards")
