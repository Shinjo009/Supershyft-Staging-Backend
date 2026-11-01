"""Notification rebuild foundation: catalog bindings table and additive columns.

Revision ID: 0184_notif_rebuild
Revises: 0183_redcliffe

Unique on notification_events: (event_code, recipient_type) only.
filters JSONB is reserved for future branching; uniqueness with NULL filters is deferred.

Uses IF NOT EXISTS so staging DBs with partial legacy rebuild columns can upgrade safely.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0184_notif_rebuild"
down_revision = "0183_redcliffe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    for stmt in (
        "ALTER TABLE notification_services ADD COLUMN IF NOT EXISTS template_name VARCHAR",
        "ALTER TABLE notification_services ADD COLUMN IF NOT EXISTS template_variables JSONB",
        "ALTER TABLE notification_services ADD COLUMN IF NOT EXISTS email_subject VARCHAR",
        "ALTER TABLE notification_services ADD COLUMN IF NOT EXISTS email_body TEXT",
        "ALTER TABLE notification_services ADD COLUMN IF NOT EXISTS email_html TEXT",
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS queue_id VARCHAR",
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS event_code VARCHAR",
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS recipient_type VARCHAR",
        "ALTER TABLE engagement_notifications ADD COLUMN IF NOT EXISTS event_code VARCHAR",
        "ALTER TABLE engagement_notifications ADD COLUMN IF NOT EXISTS recipient_type VARCHAR",
    ):
        conn.execute(sa.text(stmt))

    conn.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_engagement_notifications_eng_event_recipient
            ON engagement_notifications (engagement_id, event_code, recipient_type)
            """
        )
    )

    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS notification_events (
                id SERIAL PRIMARY KEY,
                event_code VARCHAR NOT NULL,
                event_name VARCHAR NOT NULL,
                recipient_type VARCHAR NOT NULL,
                notification_services JSONB NOT NULL,
                custom_contacts JSONB,
                filters JSONB,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_notification_events_code_recipient
                    UNIQUE (event_code, recipient_type)
            )
            """
        )
    )

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
