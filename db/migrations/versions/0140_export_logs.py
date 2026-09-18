"""Add export_logs for staff data-export audit.

Revision ID: 0140_export_logs
Revises: 0139_eng_draft_slot
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0140_export_logs"
down_revision = "0139_eng_draft_slot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "export_logs",
        sa.Column("export_log_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employee.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "partner_id",
            sa.Integer(),
            sa.ForeignKey("partners.partner_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_name", sa.String(), nullable=False),
        sa.Column("actor_role", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("export_type", sa.String(64), nullable=False),
        sa.Column("export_format", sa.String(16), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "employee_id IS NOT NULL OR partner_id IS NOT NULL",
            name="ck_export_logs_actor",
        ),
    )
    op.create_index("ix_export_logs_created_at", "export_logs", ["created_at"])
    op.create_index("ix_export_logs_employee_id", "export_logs", ["employee_id"])


def downgrade() -> None:
    op.drop_index("ix_export_logs_employee_id", table_name="export_logs")
    op.drop_index("ix_export_logs_created_at", table_name="export_logs")
    op.drop_table("export_logs")
