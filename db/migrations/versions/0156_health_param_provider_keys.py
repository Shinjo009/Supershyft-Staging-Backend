"""Split health_parameters.external_parameter_code into provider-specific keys.

Revision ID: 0156_hp_provider_keys
Revises: 0155_pkg_subscription_id
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0156_hp_provider_keys"
down_revision = "0155_pkg_subscription_id"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("health_parameters", "healthians_parameter_key"):
        op.add_column(
            "health_parameters",
            sa.Column("healthians_parameter_key", sa.String(), nullable=True),
        )
    if not _has_column("health_parameters", "orangehealth_parameter_key"):
        op.add_column(
            "health_parameters",
            sa.Column("orangehealth_parameter_key", sa.String(), nullable=True),
        )

    if _has_column("health_parameters", "external_parameter_code"):
        op.execute(
            """
            UPDATE health_parameters
            SET healthians_parameter_key = external_parameter_code
            WHERE external_parameter_code IS NOT NULL
              AND (healthians_parameter_key IS NULL OR healthians_parameter_key = '')
            """
        )
        op.drop_column("health_parameters", "external_parameter_code")


def downgrade() -> None:
    if not _has_column("health_parameters", "external_parameter_code"):
        op.add_column(
            "health_parameters",
            sa.Column("external_parameter_code", sa.String(), nullable=True),
        )
    if _has_column("health_parameters", "healthians_parameter_key"):
        op.execute(
            """
            UPDATE health_parameters
            SET external_parameter_code = healthians_parameter_key
            WHERE healthians_parameter_key IS NOT NULL
            """
        )
    if _has_column("health_parameters", "orangehealth_parameter_key"):
        op.drop_column("health_parameters", "orangehealth_parameter_key")
    if _has_column("health_parameters", "healthians_parameter_key"):
        op.drop_column("health_parameters", "healthians_parameter_key")
