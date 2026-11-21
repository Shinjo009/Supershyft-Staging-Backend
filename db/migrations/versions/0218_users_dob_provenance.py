"""Add users.dob_provenance and users.dob_estimate_reference_year.

Revision ID: 0218_users_dob_provenance
Revises: 0217_notifications_event_code
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0218_users_dob_provenance"
down_revision = "0217_notifications_event_code"
branch_labels = None
depends_on = None


def _column_exists(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if table_name not in inspector.get_table_names():
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)

    if not _column_exists(inspector, "users", "dob_provenance"):
        op.add_column(
            "users",
            sa.Column("dob_provenance", sa.String(length=32), nullable=True),
        )

    if not _column_exists(inspector, "users", "dob_estimate_reference_year"):
        op.add_column(
            "users",
            sa.Column("dob_estimate_reference_year", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)

    if _column_exists(inspector, "users", "dob_estimate_reference_year"):
        op.drop_column("users", "dob_estimate_reference_year")

    if _column_exists(inspector, "users", "dob_provenance"):
        op.drop_column("users", "dob_provenance")