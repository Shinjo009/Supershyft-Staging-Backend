"""Saved user addresses (max 3 per user) with backfill from users.* location.

Revision ID: 0147_user_addresses
Revises: 0146_load_prev_carried_forward
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text


revision = "0147_user_addresses"
down_revision = "0146_load_prev_carried_forward"
branch_labels = None
depends_on = None


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _index_exists(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    if table_name not in inspector.get_table_names():
        return False
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)

    if not _table_exists(inspector, "user_addresses"):
        op.create_table(
            "user_addresses",
            sa.Column("user_address_id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.user_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("address_line1", sa.String(), nullable=True),
            sa.Column("address_line2", sa.String(), nullable=True),
            sa.Column("landmark", sa.String(), nullable=True),
            sa.Column("city", sa.String(), nullable=True),
            sa.Column("state", sa.String(), nullable=True),
            sa.Column("pincode", sa.String(), nullable=True),
            sa.Column("address", sa.String(), nullable=True),
            sa.Column(
                "is_default",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("user_address_id"),
        )

    inspector = inspect(connection)
    if not _index_exists(inspector, "user_addresses", "ix_user_addresses_user_id"):
        op.create_index("ix_user_addresses_user_id", "user_addresses", ["user_id"])

    if not _index_exists(inspector, "user_addresses", "uq_user_addresses_one_default"):
        op.create_index(
            "uq_user_addresses_one_default",
            "user_addresses",
            ["user_id"],
            unique=True,
            postgresql_where=sa.text("is_default IS TRUE"),
        )

    connection.execute(
        text(
            """
            INSERT INTO user_addresses (
                user_id,
                address_line1,
                address_line2,
                landmark,
                city,
                state,
                pincode,
                address,
                is_default,
                created_at,
                updated_at
            )
            SELECT
                u.user_id,
                NULLIF(btrim(split_part(coalesce(u.address, ''), ',', 1)), ''),
                NULLIF(btrim(split_part(coalesce(u.address, ''), ',', 2)), ''),
                NULLIF(btrim(split_part(coalesce(u.address, ''), ',', 3)), ''),
                u.city,
                u.state,
                u.pin_code,
                u.address,
                TRUE,
                now(),
                now()
            FROM users u
            WHERE NOT EXISTS (
                SELECT 1
                FROM user_addresses ua
                WHERE ua.user_id = u.user_id
            )
            AND (
                (u.address IS NOT NULL AND btrim(u.address) <> '')
                OR (u.city IS NOT NULL AND btrim(u.city) <> '')
                OR (u.pin_code IS NOT NULL AND btrim(u.pin_code) <> '')
            )
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)
    if _index_exists(inspector, "user_addresses", "uq_user_addresses_one_default"):
        op.drop_index("uq_user_addresses_one_default", table_name="user_addresses")
    if _index_exists(inspector, "user_addresses", "ix_user_addresses_user_id"):
        op.drop_index("ix_user_addresses_user_id", table_name="user_addresses")
    if _table_exists(inspector, "user_addresses"):
        op.drop_table("user_addresses")
