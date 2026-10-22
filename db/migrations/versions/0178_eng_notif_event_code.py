"""Add event_code to engagement_notifications; drop notification_event_id FK.

Revision ID: 0178_eng_notif_event_code
Revises: 0177_whatapi_provider
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0178_eng_notif_event_code"
down_revision = "0177_whatapi_provider"
branch_labels = None
depends_on = None


def _drop_unique_on_engagement_and_event_id() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            WHERE t.relname = 'engagement_notifications'
              AND c.contype = 'u'
              AND pg_get_constraintdef(c.oid) LIKE '%notification_event_id%'
            """
        )
    ).fetchall()
    for (conname,) in rows:
        op.drop_constraint(conname, "engagement_notifications", type_="unique")
    op.execute(
        sa.text(
            "ALTER TABLE engagement_notifications "
            "DROP CONSTRAINT IF EXISTS uq_engagement_notification_event"
        )
    )


def upgrade() -> None:
    conn = op.get_bind()
    has_event_code = conn.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'engagement_notifications'
              AND column_name = 'event_code'
            """
        )
    ).scalar()

    if not has_event_code:
        op.add_column(
            "engagement_notifications",
            sa.Column("event_code", sa.String(), nullable=True),
        )

    has_notification_event_id = conn.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'engagement_notifications'
              AND column_name = 'notification_event_id'
            """
        )
    ).scalar()

    if has_notification_event_id:
        op.execute(
            sa.text(
                """
                UPDATE engagement_notifications en
                SET event_code = ane.event_code
                FROM auto_notification_events ane
                WHERE en.notification_event_id = ane.id
                  AND (en.event_code IS NULL OR en.event_code = '')
                """
            )
        )

    op.alter_column("engagement_notifications", "event_code", nullable=False)

    _drop_unique_on_engagement_and_event_id()
    op.execute(
        sa.text(
            "ALTER TABLE engagement_notifications "
            "DROP CONSTRAINT IF EXISTS uq_engagement_notification_event_code"
        )
    )
    op.create_unique_constraint(
        "uq_engagement_notification_event_code",
        "engagement_notifications",
        ["engagement_id", "event_code"],
    )

    if has_notification_event_id:
        op.execute(
            sa.text(
                "ALTER TABLE engagement_notifications "
                "DROP CONSTRAINT IF EXISTS engagement_notifications_notification_event_id_fkey"
            )
        )
        op.drop_column("engagement_notifications", "notification_event_id")


def downgrade() -> None:
    op.add_column(
        "engagement_notifications",
        sa.Column("notification_event_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "engagement_notifications_notification_event_id_fkey",
        "engagement_notifications",
        "auto_notification_events",
        ["notification_event_id"],
        ["id"],
    )
    op.execute(
        sa.text(
            """
            UPDATE engagement_notifications en
            SET notification_event_id = ane.id
            FROM auto_notification_events ane
            WHERE en.event_code = ane.event_code
            """
        )
    )
    op.alter_column("engagement_notifications", "notification_event_id", nullable=False)
    op.drop_constraint("uq_engagement_notification_event_code", "engagement_notifications", type_="unique")
    op.create_unique_constraint(
        "engagement_notifications_engagement_id_notification_event_id_key",
        "engagement_notifications",
        ["engagement_id", "notification_event_id"],
    )
    op.drop_column("engagement_notifications", "event_code")
