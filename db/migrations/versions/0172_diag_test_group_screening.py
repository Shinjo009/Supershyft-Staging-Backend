"""Add allergy and cancer screening flags to diagnostic_test_groups.

Revision ID: 0172_diag_test_group_screening
Revises: 0171_ep_booker_relation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0172_diag_test_group_screening"
down_revision = "0171_ep_booker_relation"
branch_labels = None
depends_on = None


def _column_exists(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if table_name not in inspector.get_table_names():
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '60s'"))
    connection = op.get_bind()
    inspector = inspect(connection)

    if not _column_exists(inspector, "diagnostic_test_groups", "has_allergy_screening"):
        op.add_column(
            "diagnostic_test_groups",
            sa.Column("has_allergy_screening", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
    if not _column_exists(inspector, "diagnostic_test_groups", "has_cancer_screening"):
        op.add_column(
            "diagnostic_test_groups",
            sa.Column("has_cancer_screening", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '15s'"))
    op.execute(
        sa.text("ALTER TABLE diagnostic_test_groups DROP COLUMN IF EXISTS has_cancer_screening")
    )
    op.execute(
        sa.text("ALTER TABLE diagnostic_test_groups DROP COLUMN IF EXISTS has_allergy_screening")
    )
