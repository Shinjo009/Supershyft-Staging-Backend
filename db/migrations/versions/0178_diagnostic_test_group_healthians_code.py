"""Add healthians_group_code to diagnostic_test_groups.

Revision ID: 0178_diag_tg_healthians_code
Revises: 0177_superclub_perm
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0178_diag_tg_healthians_code"
down_revision = "0177_superclub_perm"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("diagnostic_test_groups", "healthians_group_code"):
        op.add_column(
            "diagnostic_test_groups",
            sa.Column("healthians_group_code", sa.String(), nullable=True),
        )


def downgrade() -> None:
    if _has_column("diagnostic_test_groups", "healthians_group_code"):
        op.drop_column("diagnostic_test_groups", "healthians_group_code")
