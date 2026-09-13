"""saved search webhook kind

Revision ID: 0009_webhook_kind
Revises: 0008_saved_search_webhook
Create Date: 2026-01-09

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_webhook_kind"
down_revision = "0008_saved_search_webhook"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "saved_searches",
        sa.Column("webhook_kind", sa.String(length=20), nullable=False, server_default="generic"),
    )


def downgrade() -> None:
    op.drop_column("saved_searches", "webhook_kind")
