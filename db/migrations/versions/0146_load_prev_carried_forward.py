"""Carried-forward questionnaire responses and engagement category allow-list.

Revision ID: 0146_load_prev_carried_forward
Revises: 0145_participant_blood_bookings
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "0146_load_prev_carried_forward"
down_revision = "0145_participant_blood_bookings"
branch_labels = None
depends_on = None


def _column_exists(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if table_name not in inspector.get_table_names():
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)

    if not _column_exists(inspector, "questionnaire_responses", "is_carried_forward"):
        op.add_column(
            "questionnaire_responses",
            sa.Column(
                "is_carried_forward",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    if not _column_exists(inspector, "engagements", "load_prev_questionnaire_category_keys"):
        op.add_column(
            "engagements",
            sa.Column(
                "load_prev_questionnaire_category_keys",
                sa.ARRAY(sa.String()),
                nullable=True,
            ),
        )


def downgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)

    if _column_exists(inspector, "engagements", "load_prev_questionnaire_category_keys"):
        op.drop_column("engagements", "load_prev_questionnaire_category_keys")

    if _column_exists(inspector, "questionnaire_responses", "is_carried_forward"):
        op.drop_column("questionnaire_responses", "is_carried_forward")
