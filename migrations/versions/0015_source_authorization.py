from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_source_authorization"
down_revision = "0014_import_gateway"
branch_labels = None
depends_on = None

BIGINT_PK = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def _drop_sqlite_expression_indexes() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.drop_index("uq_jobs_source_job_id", table_name="jobs")
        op.drop_index("uq_jobs_dedup_key_active", table_name="jobs")


def _restore_sqlite_expression_indexes() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.create_index(
            "uq_jobs_source_job_id", "jobs",
            ["source", "source_job_id", sa.text("(coalesce(owner_device_id, 0))")],
            unique=True,
        )
        op.create_index(
            "uq_jobs_dedup_key_active", "jobs",
            ["dedup_key", sa.text("(coalesce(owner_device_id, 0))")],
            unique=True, sqlite_where=sa.text("duplicate_of IS NULL"),
        )


def upgrade() -> None:
    _drop_sqlite_expression_indexes()
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("source_board_id", BIGINT_PK, nullable=True))
        batch.create_foreign_key(
            "fk_jobs_source_board", "boards", ["source_board_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_index("ix_jobs_source_board_id", ["source_board_id"])
    _restore_sqlite_expression_indexes()
    op.create_table(
        "source_authorizations",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_board_id", BIGINT_PK, sa.ForeignKey("boards.id", ondelete="RESTRICT")),
        sa.Column("evidence_ref", sa.Text(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("commercial_display", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("length(trim(source)) > 0", name="ck_source_authorizations_source"),
        sa.CheckConstraint(
            "length(trim(evidence_ref)) > 0", name="ck_source_authorizations_evidence"
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name="ck_source_authorizations_validity",
        ),
    )
    op.create_index(
        "ix_source_authorizations_scope", "source_authorizations", ["source", "source_board_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_source_authorizations_scope", table_name="source_authorizations")
    op.drop_table("source_authorizations")
    _drop_sqlite_expression_indexes()
    with op.batch_alter_table("jobs") as batch:
        batch.drop_index("ix_jobs_source_board_id")
        batch.drop_constraint("fk_jobs_source_board", type_="foreignkey")
        batch.drop_column("source_board_id")
    _restore_sqlite_expression_indexes()
