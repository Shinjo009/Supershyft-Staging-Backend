"""Add diagnostic_package_group and package_group_id on diagnostic_package.

Revision ID: 0158_diagnostic_package_group
Revises: 0157_merge_export_logs_hp_keys
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0158_diagnostic_package_group"
down_revision = "0157_merge_export_logs_hp_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "diagnostic_package_group",
        sa.Column("package_group_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("package_group_id"),
    )

    op.add_column(
        "diagnostic_package",
        sa.Column("package_group_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_diagnostic_package_package_group_id",
        "diagnostic_package",
        "diagnostic_package_group",
        ["package_group_id"],
        ["package_group_id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_diagnostic_package_package_group_id",
        "diagnostic_package",
        ["package_group_id"],
    )

    op.execute(
        """
        INSERT INTO diagnostic_package_group (created_at)
        SELECT now() FROM diagnostic_package
        """
    )
    op.execute(
        """
        WITH numbered_pkgs AS (
            SELECT diagnostic_package_id,
                   ROW_NUMBER() OVER (ORDER BY diagnostic_package_id) AS rn
            FROM diagnostic_package
        ),
        numbered_groups AS (
            SELECT package_group_id,
                   ROW_NUMBER() OVER (ORDER BY package_group_id) AS rn
            FROM diagnostic_package_group
        )
        UPDATE diagnostic_package dp
        SET package_group_id = ng.package_group_id
        FROM numbered_pkgs np
        JOIN numbered_groups ng ON np.rn = ng.rn
        WHERE dp.diagnostic_package_id = np.diagnostic_package_id
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX uq_diagnostic_package_group_provider
        ON diagnostic_package (package_group_id, diagnostic_provider)
        WHERE package_group_id IS NOT NULL AND diagnostic_provider IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("uq_diagnostic_package_group_provider", table_name="diagnostic_package")
    op.drop_index("ix_diagnostic_package_package_group_id", table_name="diagnostic_package")
    op.drop_constraint("fk_diagnostic_package_package_group_id", "diagnostic_package", type_="foreignkey")
    op.drop_column("diagnostic_package", "package_group_id")
    op.drop_table("diagnostic_package_group")
