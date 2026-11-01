"""Notification cutover: drop n8n-era columns and legacy event tables.

Revision ID: 0188_notification_cutover
Revises: 0187_notif_backfill
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0188_notification_cutover"
down_revision = "0187_notif_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF to_regclass('public.auto_notification_events') IS NOT NULL
                 AND to_regclass('public.engagement_notifications') IS NOT NULL THEN
                UPDATE engagement_notifications AS en
                SET event_code = ane.event_code
                FROM auto_notification_events AS ane
                WHERE en.notification_event_id = ane.id
                  AND (en.event_code IS NULL OR btrim(en.event_code) = '');
              END IF;
            END $$
            """
        )
    )

    conn.execute(
        sa.text(
            """
            UPDATE engagement_notifications
            SET recipient_type = 'participant'
            WHERE recipient_type IS NULL OR btrim(recipient_type) = ''
            """
        )
    )

    conn.execute(
        sa.text(
            """
            DELETE FROM engagement_notifications
            WHERE event_code IS NULL OR btrim(event_code) = ''
            """
        )
    )

    conn.execute(
        sa.text(
            "ALTER TABLE engagement_notifications DROP CONSTRAINT IF EXISTS uq_engagement_notification_event"
        )
    )
    conn.execute(
        sa.text(
            "ALTER TABLE engagement_notifications DROP CONSTRAINT IF EXISTS "
            "engagement_notifications_notification_event_id_fkey"
        )
    )
    conn.execute(
        sa.text(
            """
            ALTER TABLE engagement_notifications
            DROP COLUMN IF EXISTS notification_event_id
            """
        )
    )

    conn.execute(
        sa.text(
            """
            ALTER TABLE engagement_notifications
            ALTER COLUMN event_code SET NOT NULL,
            ALTER COLUMN recipient_type SET NOT NULL
            """
        )
    )

    conn.execute(
        sa.text("DROP INDEX IF EXISTS ix_engagement_notifications_eng_event_recipient")
    )
    conn.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_engagement_notifications_eng_event_recipient
            ON engagement_notifications (engagement_id, event_code, recipient_type)
            """
        )
    )

    for col in (
        "webhook_path",
        "require_blood_report_url",
        "require_bio_ai_report_url",
        "require_participant_detail",
        "require_otp",
        "require_session_details",
        "require_external_link",
    ):
        conn.execute(
            sa.text(f"ALTER TABLE notification_services DROP COLUMN IF EXISTS {col}")
        )

    conn.execute(sa.text("DROP TABLE IF EXISTS engagement_notification_defaults"))
    conn.execute(sa.text("DROP TABLE IF EXISTS auto_notification_events"))


def downgrade() -> None:
    raise NotImplementedError("0188 cutover downgrade is staging-only manual restore from git")
