"""Reshape export_logs for contact_reveal and employee-only audits.

Revision ID: 0156_export_logs_reshape
Revises: 0155_pkg_subscription_id
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text


revision = "0156_export_logs_reshape"
down_revision = "0155_pkg_subscription_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("ALTER TYPE export_type_enum ADD VALUE IF NOT EXISTS 'contact_reveal'"))
    op.execute(text("ALTER TYPE export_source_kind_enum ADD VALUE IF NOT EXISTS 'user'"))

    # Merge flat columns into details JSONB (preserve existing detail keys).
    op.execute(
        text(
            """
            UPDATE export_logs
            SET details = COALESCE(details, '{}'::jsonb)
                || jsonb_build_object(
                    'export_format', export_format::text,
                    'source_kind', source_kind::text,
                    'source_id', source_id
                )
                || '{"exported_participants": []}'::jsonb
            """
        )
    )

    op.execute(text("DELETE FROM export_logs WHERE employee_id IS NULL"))

    op.drop_constraint("ck_export_logs_actor", "export_logs", type_="check")

    op.drop_column("export_logs", "partner_id")
    op.drop_column("export_logs", "actor_name")
    op.drop_column("export_logs", "actor_role")
    op.drop_column("export_logs", "export_format")
    op.drop_column("export_logs", "source_kind")
    op.drop_column("export_logs", "source_id")
    op.drop_column("export_logs", "row_count")
    op.drop_column("export_logs", "ip_address")
    op.drop_column("export_logs", "user_agent")

    # Replace SET NULL FK with RESTRICT so employee_id can be NOT NULL.
    op.drop_constraint("export_logs_employee_id_fkey", "export_logs", type_="foreignkey")
    op.alter_column("export_logs", "employee_id", existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key(
        "export_logs_employee_id_fkey",
        "export_logs",
        "employee",
        ["employee_id"],
        ["employee_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
