"""local collector import gateway: devices, batches, provenance, visibility

Revision ID: 0014_import_gateway
Revises: 0013_boards
Create Date: 2026-01-14

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_import_gateway"
down_revision = "0013_boards"
branch_labels = None
depends_on = None

BIGINT_PK = sa.BigInteger().with_variant(sa.Integer, "sqlite")
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB, "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    op.create_table(
        "collector_devices",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("owner_ref", sa.String(length=255), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=False, server_default="linkedin"),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_collector_devices_owner_ref", "collector_devices", ["owner_ref"])
    op.create_index(
        "ix_collector_devices_token_hash", "collector_devices", ["token_hash"], unique=True
    )

    op.add_column(
        "jobs",
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default="public"),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "collection_mode", sa.String(length=20), nullable=False, server_default="platform"
        ),
    )
    op.add_column("jobs", sa.Column("owner_device_id", BIGINT_PK, nullable=True))
    op.create_index("ix_jobs_visibility", "jobs", ["visibility"])
    op.create_index("ix_jobs_collection_mode", "jobs", ["collection_mode"])
    op.create_index("ix_jobs_owner_device_id", "jobs", ["owner_device_id"])
    if is_postgres:
        op.create_foreign_key(
            "fk_jobs_owner_device",
            "jobs",
            "collector_devices",
            ["owner_device_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Re-scope identity/dedup uniqueness by owner so each device's private
    # imports dedup independently while public rows keep deduping together.
    op.drop_index("uq_jobs_dedup_key_active", table_name="jobs")
    if is_postgres:
        op.drop_constraint("uq_jobs_source_job_id", "jobs", type_="unique")
    op.create_index(
        "uq_jobs_source_job_id",
        "jobs",
        ["source", "source_job_id", sa.text("(coalesce(owner_device_id, 0))")],
        unique=True,
    )
    op.create_index(
        "uq_jobs_dedup_key_active",
        "jobs",
        ["dedup_key", sa.text("(coalesce(owner_device_id, 0))")],
        unique=True,
        postgresql_where=sa.text("duplicate_of IS NULL"),
        sqlite_where=sa.text("duplicate_of IS NULL"),
    )

    op.create_table(
        "import_batches",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("device_id", BIGINT_PK, sa.ForeignKey("collector_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_ref", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="linkedin_user_import"),
        sa.Column("query", sa.String(length=300)),
        sa.Column("geo_id", sa.String(length=50)),
        sa.Column("collection_mode", sa.String(length=20), nullable=False, server_default="user_local"),
        sa.Column("idempotency_key", sa.String(length=80)),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="received"),
        sa.Column("received_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("device_id", "idempotency_key", name="uq_import_batch_idempotency"),
    )
    op.create_index("ix_import_batches_device_id", "import_batches", ["device_id"])
    op.create_index("ix_import_batches_owner_ref", "import_batches", ["owner_ref"])
    op.create_index("ix_import_batches_status", "import_batches", ["status"])

    op.create_table(
        "job_import_provenance",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("job_id", BIGINT_PK, sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("batch_id", BIGINT_PK, sa.ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", BIGINT_PK, sa.ForeignKey("collector_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_ref", sa.String(length=255), nullable=False),
        sa.Column("collection_mode", sa.String(length=20), nullable=False, server_default="user_local"),
        sa.Column("action", sa.String(length=20), nullable=False, server_default="inserted"),
        sa.Column("source_url", sa.Text()),
        sa.Column("collected_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("batch_id", "job_id", name="uq_import_provenance_batch_job"),
    )
    op.create_index("ix_job_import_provenance_job_id", "job_import_provenance", ["job_id"])
    op.create_index("ix_job_import_provenance_batch_id", "job_import_provenance", ["batch_id"])
    op.create_index("ix_job_import_provenance_device_id", "job_import_provenance", ["device_id"])
    op.create_index("ix_job_import_provenance_owner_ref", "job_import_provenance", ["owner_ref"])


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    op.drop_table("job_import_provenance")
    op.drop_table("import_batches")

    op.drop_index("uq_jobs_dedup_key_active", table_name="jobs")
    op.drop_index("uq_jobs_source_job_id", table_name="jobs")
    if is_postgres:
        op.create_unique_constraint(
            "uq_jobs_source_job_id", "jobs", ["source", "source_job_id"]
        )
    # On SQLite nothing else is needed: the table-level UNIQUE constraint from
    # 0001 (uq_jobs_source_job_id) still exists there — SQLite cannot drop it
    # without a table rebuild, so 0014's upgrade left it in place.
    op.create_index(
        "uq_jobs_dedup_key_active",
        "jobs",
        ["dedup_key"],
        unique=True,
        postgresql_where=sa.text("duplicate_of IS NULL"),
        sqlite_where=sa.text("duplicate_of IS NULL"),
    )

    op.drop_index("ix_jobs_owner_device_id", table_name="jobs")
    op.drop_index("ix_jobs_collection_mode", table_name="jobs")
    op.drop_index("ix_jobs_visibility", table_name="jobs")
    if is_postgres:
        op.drop_constraint("fk_jobs_owner_device", "jobs", type_="foreignkey")
    op.drop_column("jobs", "owner_device_id")
    op.drop_column("jobs", "collection_mode")
    op.drop_column("jobs", "visibility")

    op.drop_table("collector_devices")
