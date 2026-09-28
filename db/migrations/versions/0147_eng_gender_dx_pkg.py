"""Optional male and female diagnostic packages on one engagement.

A camp stores either diagnostic_package_id, or both gender columns with the
unisex column null. B2C rows keep a single diagnostic_package_id.

Revision id must be <= 32 chars (alembic_version.version_num).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "0147_eng_gender_dx_pkg"
down_revision = "0146_load_prev_carried_forward"
branch_labels = None
depends_on = None

_PACKAGE_CHOICE_SQL = """
(
    diagnostic_package_id IS NOT NULL
    AND diagnostic_package_id_male IS NULL
    AND diagnostic_package_id_female IS NULL
)
OR (
    diagnostic_package_id IS NULL
    AND diagnostic_package_id_male IS NOT NULL
    AND diagnostic_package_id_female IS NOT NULL
)
OR (
    diagnostic_package_id IS NULL
    AND diagnostic_package_id_male IS NULL
    AND diagnostic_package_id_female IS NULL
)
"""


def _column_exists(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if table_name not in inspector.get_table_names():
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)
    if "engagements" not in inspector.get_table_names():
        return

    if not _column_exists(inspector, "engagements", "diagnostic_package_id_male"):
        op.add_column(
            "engagements",
            sa.Column(
                "diagnostic_package_id_male",
                sa.Integer(),
                sa.ForeignKey("diagnostic_package.diagnostic_package_id"),
                nullable=True,
            ),
        )
    if not _column_exists(inspector, "engagements", "diagnostic_package_id_female"):
        op.add_column(
            "engagements",
            sa.Column(
                "diagnostic_package_id_female",
                sa.Integer(),
                sa.ForeignKey("diagnostic_package.diagnostic_package_id"),
                nullable=True,
            ),
        )

    if _column_exists(inspector, "engagements", "diagnostic_package_id"):
        op.alter_column(
            "engagements",
            "diagnostic_package_id",
            existing_type=sa.Integer(),
            nullable=True,
        )

    inspector = inspect(connection)
    existing = {c["name"] for c in inspector.get_check_constraints("engagements")}
    if "ck_engagements_dx_pkg_choice" not in existing:
        op.create_check_constraint(
            "ck_engagements_dx_pkg_choice",
            "engagements",
            _PACKAGE_CHOICE_SQL,
        )


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
