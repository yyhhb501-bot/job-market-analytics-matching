"""Add member accounts with verified phone numbers."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_phone_members"
down_revision = "0016_collector_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("phone_e164", sa.String(length=16), nullable=False),
            sa.Column(
                "phone_verified", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("password_hash", sa.String(length=255), nullable=True),
            sa.Column("password_salt", sa.String(length=64), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
            ),
        )
        inspector = sa.inspect(bind)
    user_indexes = {index["name"] for index in inspector.get_indexes("users")}
    for name, columns in (
        ("ix_users_phone_e164", ["phone_e164"]),
        ("ix_users_email", ["email"]),
        ("ix_users_stripe_customer_id", ["stripe_customer_id"]),
    ):
        if name not in user_indexes:
            op.create_index(name, "users", columns, unique=True)

    saved_columns = {column["name"] for column in inspector.get_columns("saved_searches")}
    if "owner_user_id" not in saved_columns:
        # SQLite cannot ALTER columns/constraints: batch mode rebuilds the table.
        with op.batch_alter_table("saved_searches") as batch:
            batch.add_column(sa.Column("owner_user_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_saved_searches_owner_user_id_users",
                "users",
                ["owner_user_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch.create_index("ix_saved_searches_owner_user_id", ["owner_user_id"])
        return

    # Column already present (e.g. created from ORM metadata): add whatever is
    # still missing without touching the column itself.
    has_owner_foreign_key = any(
        foreign_key["referred_table"] == "users"
        and foreign_key["constrained_columns"] == ["owner_user_id"]
        for foreign_key in sa.inspect(bind).get_foreign_keys("saved_searches")
    )
    if not has_owner_foreign_key:
        with op.batch_alter_table("saved_searches") as batch:
            batch.create_foreign_key(
                "fk_saved_searches_owner_user_id_users",
                "users",
                ["owner_user_id"],
                ["id"],
                ondelete="CASCADE",
            )
    saved_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("saved_searches")
    }
    if "ix_saved_searches_owner_user_id" not in saved_indexes:
        op.create_index("ix_saved_searches_owner_user_id", "saved_searches", ["owner_user_id"])


def downgrade() -> None:
    with op.batch_alter_table("saved_searches") as batch:
        batch.drop_index("ix_saved_searches_owner_user_id")
        batch.drop_constraint(
            "fk_saved_searches_owner_user_id_users", type_="foreignkey"
        )
        batch.drop_column("owner_user_id")
    op.drop_index("ix_users_stripe_customer_id", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_phone_e164", table_name="users")
    op.drop_table("users")
