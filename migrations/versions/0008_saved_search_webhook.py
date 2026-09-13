"""saved search webhook url

Revision ID: 0008_saved_search_webhook
Revises: 0007_summary_source
Create Date: 2026-01-08

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_saved_search_webhook"
down_revision = "0007_summary_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("saved_searches", sa.Column("webhook_url", sa.String(length=500)))


def downgrade() -> None:
    op.drop_column("saved_searches", "webhook_url")
