"""Notification rebuild foundation: content columns, statuses, event bindings table.

Revision ID: 0176_notif_rebuild_foundation
Revises: 0175_authors_partner_only
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0176_notif_rebuild_foundation"
down_revision = "0175_authors_partner_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notification_services", sa.Column("template_name", sa.String(), nullable=True))
    op.add_column(
        "notification_services",
        sa.Column("template_variables", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("notification_services", sa.Column("email_subject", sa.String(), nullable=True))
    op.add_column("notification_services", sa.Column("email_body", sa.Text(), nullable=True))
    op.add_column("notification_services", sa.Column("email_html", sa.Text(), nullable=True))

    op.add_column("notifications", sa.Column("queue_id", sa.String(), nullable=True))
    op.add_column("notifications", sa.Column("event_code", sa.String(), nullable=True))
    op.add_column("notifications", sa.Column("recipient_type", sa.String(), nullable=True))

    op.create_table(
        "notification_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_code", sa.String(), nullable=False),
        sa.Column("event_name", sa.String(), nullable=False),
        sa.Column("recipient_type", sa.String(), nullable=False),
        sa.Column(
            "notification_services",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_code",
            "recipient_type",
            name="uq_notification_events_code_recipient",
        ),
    )


def downgrade() -> None:
    op.drop_table("notification_events")
    op.drop_column("notifications", "recipient_type")
    op.drop_column("notifications", "event_code")
    op.drop_column("notifications", "queue_id")
    op.drop_column("notification_services", "email_html")
    op.drop_column("notification_services", "email_body")
    op.drop_column("notification_services", "email_subject")
    op.drop_column("notification_services", "template_variables")
    op.drop_column("notification_services", "template_name")
