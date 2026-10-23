from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_collector_controls"
down_revision = "0015_source_authorization"
branch_labels = None
depends_on = None

BIGINT_PK = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    run_columns = {column["name"] for column in inspector.get_columns("collector_runs")}
    additions = (
        sa.Column("stopped_reason", sa.String(30), nullable=True),
        sa.Column("pages_visited", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("details_visited", sa.Integer(), nullable=False, server_default="0"),
    )
    missing = [column for column in additions if column.name not in run_columns]
    if missing:
        with op.batch_alter_table("collector_runs") as batch:
            for column in missing:
                batch.add_column(column)

    if not inspector.has_table("source_controls"):
        op.create_table(
            "source_controls",
            sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
            sa.Column("source", sa.String(50), nullable=False),
            sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("pause_reason", sa.String(30)),
            sa.Column("paused_at", sa.DateTime(timezone=True)),
            sa.Column("resume_after", sa.DateTime(timezone=True)),
            sa.Column("note", sa.Text()),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
            ),
        )
        inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("source_controls")}
    if "ix_source_controls_source" not in existing_indexes:
        op.create_index("ix_source_controls_source", "source_controls", ["source"], unique=True)
    if "ix_source_controls_paused" not in existing_indexes:
        op.create_index("ix_source_controls_paused", "source_controls", ["paused"])

    if not inspector.has_table("source_visit_counters"):
        op.create_table(
            "source_visit_counters",
            sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
            sa.Column("source", sa.String(50), nullable=False),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("page_visits", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("detail_visits", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
            ),
            sa.UniqueConstraint("source", "day", name="uq_source_visit_counters_source_day"),
        )
        inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("source_visit_counters")}
    if "ix_source_visit_counters_source" not in existing_indexes:
        op.create_index("ix_source_visit_counters_source", "source_visit_counters", ["source"])
    if "ix_source_visit_counters_day" not in existing_indexes:
        op.create_index("ix_source_visit_counters_day", "source_visit_counters", ["day"])


def downgrade() -> None:
    op.drop_index("ix_source_visit_counters_day", table_name="source_visit_counters")
    op.drop_index("ix_source_visit_counters_source", table_name="source_visit_counters")
    op.drop_table("source_visit_counters")
    op.drop_index("ix_source_controls_paused", table_name="source_controls")
    op.drop_index("ix_source_controls_source", table_name="source_controls")
    op.drop_table("source_controls")
    with op.batch_alter_table("collector_runs") as batch:
        batch.drop_column("details_visited")
        batch.drop_column("pages_visited")
        batch.drop_column("stopped_reason")
