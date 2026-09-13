"""postgresql full-text search vector

Revision ID: 0003_full_text
Revises: 0002_saved_searches
Create Date: 2026-01-03

"""
from __future__ import annotations

from alembic import op

revision = "0003_full_text"
down_revision = "0002_saved_searches"
branch_labels = None
depends_on = None

SEARCH_VECTOR_EXPR = (
    "to_tsvector('english', "
    "coalesce(title, '') || ' ' || coalesce(company, '') || ' ' || coalesce(description, ''))"
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS search_vector tsvector "
        f"GENERATED ALWAYS AS ({SEARCH_VECTOR_EXPR}) STORED"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_search_vector ON jobs USING gin (search_vector)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_jobs_search_vector")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS search_vector")
