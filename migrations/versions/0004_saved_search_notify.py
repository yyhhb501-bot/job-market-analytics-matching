"""saved search notification fields

Revision ID: 0004_saved_search_notify
Revises: 0003_full_text
Create Date: 2026-01-04

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_saved_search_notify"
down_revision = "0003_full_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "saved_searches",
        sa.Column("frequency", sa.String(length=20), nullable=False, server_default="immediate"),
    )
    op.add_column("saved_searches", sa.Column("unsubscribe_token", sa.String(length=64)))
    op.add_column(
        "saved_searches", sa.Column("last_notified_at", sa.DateTime(timezone=True))
    )
    op.create_index(
        "ix_saved_searches_unsubscribe_token",
        "saved_searches",
        ["unsubscribe_token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_saved_searches_unsubscribe_token", table_name="saved_searches")
    op.drop_column("saved_searches", "last_notified_at")
    op.drop_column("saved_searches", "unsubscribe_token")
    op.drop_column("saved_searches", "frequency")
