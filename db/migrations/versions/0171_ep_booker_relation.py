"""Add booker_relation to engagement_participants.

Revision ID: 0171_ep_booker_relation
Revises: 0170_drop_family_onboards
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0171_ep_booker_relation"
down_revision = "0170_drop_family_onboards"
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

    if not _column_exists(inspector, "engagement_participants", "booker_relation"):
        op.add_column(
            "engagement_participants",
            sa.Column("booker_relation", sa.String(length=32), nullable=True),
        )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '15s'"))
    op.execute(
        sa.text("ALTER TABLE engagement_participants DROP COLUMN IF EXISTS booker_relation")
    )
