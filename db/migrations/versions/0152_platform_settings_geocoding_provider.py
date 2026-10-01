"""Add geocoding_provider enum column to platform_settings.

Revision ID: 0152_geocoding_provider
Revises: 0151_pbb_booking_id_active
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import ENUM


revision = "0152_geocoding_provider"
down_revision = "0151_pbb_booking_id_active"
branch_labels = None
depends_on = None

_COLUMN = "geocoding_provider"
_ENUM_NAME = "geocoding_provider"


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if not _table_exists(inspector, table_name):
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _enum_type_exists(connection, enum_name: str) -> bool:
    result = connection.execute(
        text("SELECT 1 FROM pg_type WHERE typname = :name"),
        {"name": enum_name},
    )
    return result.scalar() is not None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)

    if not _enum_type_exists(connection, _ENUM_NAME):
        geocoding_provider = ENUM(
            "google",
            "nominatim",
            name=_ENUM_NAME,
            create_type=True,
        )
        geocoding_provider.create(connection, checkfirst=True)

    if _table_exists(inspector, "platform_settings") and not _column_exists(
        inspector, "platform_settings", _COLUMN
    ):
        enum_type = ENUM(name=_ENUM_NAME, create_type=False)
        op.add_column(
            "platform_settings",
            sa.Column(
                _COLUMN,
                enum_type,
                nullable=False,
                server_default=sa.text("'google'"),
            ),
        )


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
