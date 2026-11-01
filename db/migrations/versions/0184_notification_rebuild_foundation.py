"""Notification rebuild foundation: catalog bindings table and additive columns.

Revision ID: 0184_notif_rebuild
Revises: 0183_redcliffe

Unique on notification_events: (event_code, recipient_type) only.
filters JSONB is reserved for future branching; uniqueness with NULL filters is deferred.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0184_notif_rebuild"
down_revision = "0183_redcliffe"
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

    op.add_column("engagement_notifications", sa.Column("event_code", sa.String(), nullable=True))
    op.add_column("engagement_notifications", sa.Column("recipient_type", sa.String(), nullable=True))
    op.create_index(
        "ix_engagement_notifications_eng_event_recipient",
        "engagement_notifications",
        ["engagement_id", "event_code", "recipient_type"],
    )

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
        sa.Column("custom_contacts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_code", "recipient_type", name="uq_notification_events_code_recipient"),
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE engagement_notifications AS en
            SET event_code = ane.event_code
            FROM auto_notification_events AS ane
            WHERE en.notification_event_id = ane.id
              AND en.event_code IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_table("notification_events")
    op.drop_index("ix_engagement_notifications_eng_event_recipient", table_name="engagement_notifications")
    op.drop_column("engagement_notifications", "recipient_type")
    op.drop_column("engagement_notifications", "event_code")
    op.drop_column("notifications", "recipient_type")
    op.drop_column("notifications", "event_code")
    op.drop_column("notifications", "queue_id")
    op.drop_column("notification_services", "email_html")
    op.drop_column("notification_services", "email_body")
    op.drop_column("notification_services", "email_subject")
    op.drop_column("notification_services", "template_variables")
    op.drop_column("notification_services", "template_name")
