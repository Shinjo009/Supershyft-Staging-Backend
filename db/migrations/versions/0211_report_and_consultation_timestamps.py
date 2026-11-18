"""Add report_received_at and consultation_done_at timestamps for command KPIs.

Revision ID: 0211_report_consult_ts
Revises: 0210_merge_0209_heads
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0211_report_consult_ts"
down_revision = "0210_merge_0209_heads"
branch_labels = None
depends_on = None


def _column_exists(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if table_name not in inspector.get_table_names():
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)

    if not _column_exists(inspector, "participant_blood_bookings", "report_received_at"):
        op.add_column(
            "participant_blood_bookings",
            sa.Column("report_received_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _column_exists(inspector, "individual_health_report", "report_received_at"):
        op.add_column(
            "individual_health_report",
            sa.Column("report_received_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _column_exists(inspector, "consultation_bookings", "consultation_done_at"):
        op.add_column(
            "consultation_bookings",
            sa.Column("consultation_done_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
