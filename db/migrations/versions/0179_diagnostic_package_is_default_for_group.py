"""Add is_default_for_group on diagnostic_package.

Revision ID: 0179_diag_pkg_default_group
Revises: 0178_diag_tg_healthians_code
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0179_diag_pkg_default_group"
down_revision = "0178_diag_tg_healthians_code"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("diagnostic_package", "is_default_for_group"):
        op.add_column(
            "diagnostic_package",
            sa.Column(
                "is_default_for_group",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    op.execute(
        """
        UPDATE diagnostic_package
        SET is_default_for_group = false
        """
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT diagnostic_package_id,
                   package_group_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY package_group_id
                       ORDER BY price ASC NULLS LAST, diagnostic_package_id ASC
                   ) AS rn
            FROM diagnostic_package
            WHERE package_group_id IS NOT NULL
        )
        UPDATE diagnostic_package dp
        SET is_default_for_group = true
        FROM ranked r
        WHERE dp.diagnostic_package_id = r.diagnostic_package_id
          AND r.rn = 1
        """
    )

    op.execute(
        """
        UPDATE diagnostic_package
        SET is_default_for_group = true
        WHERE package_group_id IS NULL
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_diagnostic_package_one_default_per_group
        ON diagnostic_package (package_group_id)
        WHERE is_default_for_group = true AND package_group_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_diagnostic_package_one_default_per_group")
    if _has_column("diagnostic_package", "is_default_for_group"):
        op.drop_column("diagnostic_package", "is_default_for_group")
