"""Add forked_from_group_id on diagnostic_test_groups for package-scoped copies.

Revision ID: 0159_test_group_forked_from
Revises: 0158_diagnostic_package_group
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0159_test_group_forked_from"
down_revision = "0158_diagnostic_package_group"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "diagnostic_test_groups",
        sa.Column("forked_from_group_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_diagnostic_test_groups_forked_from_group_id",
        "diagnostic_test_groups",
        "diagnostic_test_groups",
        ["forked_from_group_id"],
        ["group_id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_diagnostic_test_groups_forked_from_group_id",
        "diagnostic_test_groups",
        ["forked_from_group_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_diagnostic_test_groups_forked_from_group_id", table_name="diagnostic_test_groups")
    op.drop_constraint(
        "fk_diagnostic_test_groups_forked_from_group_id",
        "diagnostic_test_groups",
        type_="foreignkey",
    )
    op.drop_column("diagnostic_test_groups", "forked_from_group_id")
