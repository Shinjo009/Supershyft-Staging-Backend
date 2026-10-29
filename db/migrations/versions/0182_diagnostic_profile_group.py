"""Add diagnostic_profile_group and profile-group fields on diagnostic_test_groups.

Revision ID: 0182_diagnostic_profile_group
Revises: 0181_camp_onboarding_camp_code
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0182_diagnostic_profile_group"
down_revision = "0181_camp_onboarding_camp_code"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    op.create_table(
        "diagnostic_profile_group",
        sa.Column("profile_group_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("profile_group_id"),
    )

    op.add_column(
        "diagnostic_test_groups",
        sa.Column("profile_group_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_diagnostic_test_groups_profile_group_id",
        "diagnostic_test_groups",
        "diagnostic_profile_group",
        ["profile_group_id"],
        ["profile_group_id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_diagnostic_test_groups_profile_group_id",
        "diagnostic_test_groups",
        ["profile_group_id"],
    )

    if not _has_column("diagnostic_test_groups", "test_group_image"):
        op.add_column(
            "diagnostic_test_groups",
            sa.Column("test_group_image", sa.String(), nullable=True),
        )

    if not _has_column("diagnostic_test_groups", "diagnostic_provider"):
        op.add_column(
            "diagnostic_test_groups",
            sa.Column(
                "diagnostic_provider",
                sa.Enum(
                    "healthians",
                    "Healthians",
                    "HealthLabs",
                    "orange_health",
                    name="diagnostic_provider_enum",
                    create_type=False,
                ),
                nullable=True,
            ),
        )

    if _has_column("diagnostic_test_groups", "healthians_group_code"):
        op.alter_column(
            "diagnostic_test_groups",
            "healthians_group_code",
            new_column_name="external_test_group_code",
        )
    elif not _has_column("diagnostic_test_groups", "external_test_group_code"):
        op.add_column(
            "diagnostic_test_groups",
            sa.Column("external_test_group_code", sa.String(), nullable=True),
        )

    if not _has_column("diagnostic_test_groups", "is_default_for_group"):
        op.add_column(
            "diagnostic_test_groups",
            sa.Column(
                "is_default_for_group",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    op.execute(
        """
        INSERT INTO diagnostic_profile_group (created_at)
        SELECT now() FROM diagnostic_test_groups
        """
    )
    op.execute(
        """
        WITH numbered_tg AS (
            SELECT group_id,
                   ROW_NUMBER() OVER (ORDER BY group_id) AS rn
            FROM diagnostic_test_groups
        ),
        numbered_pg AS (
            SELECT profile_group_id,
                   ROW_NUMBER() OVER (ORDER BY profile_group_id) AS rn
            FROM diagnostic_profile_group
        )
        UPDATE diagnostic_test_groups tg
        SET profile_group_id = pg.profile_group_id,
            is_default_for_group = true
        FROM numbered_tg nt
        JOIN numbered_pg pg ON nt.rn = pg.rn
        WHERE tg.group_id = nt.group_id
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX uq_diagnostic_test_group_profile_provider
        ON diagnostic_test_groups (profile_group_id, diagnostic_provider)
        WHERE profile_group_id IS NOT NULL AND diagnostic_provider IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_diagnostic_test_group_one_default_per_profile
        ON diagnostic_test_groups (profile_group_id)
        WHERE is_default_for_group = true AND profile_group_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_diagnostic_test_group_one_default_per_profile")
    op.execute("DROP INDEX IF EXISTS uq_diagnostic_test_group_profile_provider")

    if _has_column("diagnostic_test_groups", "is_default_for_group"):
        op.drop_column("diagnostic_test_groups", "is_default_for_group")

    if _has_column("diagnostic_test_groups", "external_test_group_code"):
        op.alter_column(
            "diagnostic_test_groups",
            "external_test_group_code",
            new_column_name="healthians_group_code",
        )

    if _has_column("diagnostic_test_groups", "diagnostic_provider"):
        op.drop_column("diagnostic_test_groups", "diagnostic_provider")

    if _has_column("diagnostic_test_groups", "test_group_image"):
        op.drop_column("diagnostic_test_groups", "test_group_image")

    op.drop_index("ix_diagnostic_test_groups_profile_group_id", table_name="diagnostic_test_groups")
    op.drop_constraint(
        "fk_diagnostic_test_groups_profile_group_id",
        "diagnostic_test_groups",
        type_="foreignkey",
    )
    op.drop_column("diagnostic_test_groups", "profile_group_id")
    op.drop_table("diagnostic_profile_group")
