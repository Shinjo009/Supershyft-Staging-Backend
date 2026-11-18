"""Rename legacy consultation reminder binding codes; delete non-catalog event slots."""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0215_reminder_notif_cleanup"
down_revision = "0214_bookings_event_merge"
branch_labels = None
depends_on = None

_REMINDER_EVENT_CODE_RENAMES: tuple[tuple[str, str], ...] = (
    ("consultations.ready_to_book", "reminders.consultation_ready_to_book"),
    ("consultation_ready", "reminders.consultation_ready_to_book"),
    ("consultation.ready", "reminders.consultation_ready_to_book"),
    ("consultations.reminder", "reminders.consultation_reminder"),
    ("consultation_remainder", "reminders.consultation_reminder"),
    ("consultation.reminder", "reminders.consultation_reminder"),
)

_REMINDER_EVENT_NAMES: tuple[tuple[str, str], ...] = (
    ("reminders.consultation_ready_to_book", "Ready to book consultation"),
    ("reminders.consultation_reminder", "Consultation reminder"),
)

_NON_CATALOG_EVENT_CODES: tuple[str, ...] = ("consultation_done",)


def _drop_rename_collisions_engagement(conn, values_sql: str) -> None:
    conn.execute(
        text(
            f"""
            DELETE FROM engagement_notifications AS victim
            USING (VALUES {values_sql}) AS m(old_code, new_code)
            WHERE victim.event_code = m.old_code
              AND EXISTS (
                SELECT 1 FROM engagement_notifications AS keeper
                WHERE keeper.engagement_id = victim.engagement_id
                  AND keeper.recipient_type = victim.recipient_type
                  AND keeper.delivery_channel = victim.delivery_channel
                  AND keeper.condition_key = victim.condition_key
                  AND keeper.id <> victim.id
                  AND (
                    keeper.event_code = m.new_code
                    OR (
                      keeper.event_code IN (
                        SELECT r.old_code
                        FROM (VALUES {values_sql}) AS r(old_code, new_code)
                        WHERE r.new_code = m.new_code
                      )
                      AND keeper.id < victim.id
                    )
                  )
              )
            """
        )
    )


def _drop_rename_collisions_notification_events(conn, values_sql: str) -> None:
    conn.execute(
        text(
            f"""
            DELETE FROM notification_events AS victim
            USING (VALUES {values_sql}) AS m(old_code, new_code)
            WHERE victim.event_code = m.old_code
              AND EXISTS (
                SELECT 1 FROM notification_events AS keeper
                WHERE keeper.recipient_type = victim.recipient_type
                  AND keeper.delivery_channel = victim.delivery_channel
                  AND keeper.condition_key = victim.condition_key
                  AND (
                    (keeper.engagement_type_id IS NULL AND victim.engagement_type_id IS NULL)
                    OR keeper.engagement_type_id = victim.engagement_type_id
                  )
                  AND keeper.id <> victim.id
                  AND (
                    keeper.event_code = m.new_code
                    OR (
                      keeper.event_code IN (
                        SELECT r.old_code
                        FROM (VALUES {values_sql}) AS r(old_code, new_code)
                        WHERE r.new_code = m.new_code
                      )
                      AND keeper.id < victim.id
                    )
                  )
              )
            """
        )
    )


def upgrade() -> None:
    conn = op.get_bind()

    reminder_values_sql = ",\n".join(f"('{old}', '{new}')" for old, new in _REMINDER_EVENT_CODE_RENAMES)
    _drop_rename_collisions_notification_events(conn, reminder_values_sql)
    _drop_rename_collisions_engagement(conn, reminder_values_sql)
    for table in ("notification_events", "engagement_notifications"):
        conn.execute(
            text(
                f"""
                UPDATE {table} AS t
                SET event_code = m.new_code
                FROM (VALUES {reminder_values_sql}) AS m(old_code, new_code)
                WHERE t.event_code = m.old_code
                """
            )
        )

    reminder_names_sql = ",\n".join(f"('{code}', '{name}')" for code, name in _REMINDER_EVENT_NAMES)
    for table in ("notification_events", "engagement_notifications"):
        conn.execute(
            text(
                f"""
                UPDATE {table} AS t
                SET event_name = m.display_name
                FROM (VALUES {reminder_names_sql}) AS m(event_code, display_name)
                WHERE t.event_code = m.event_code
                """
            )
        )

    non_catalog = ", ".join(f"'{code}'" for code in _NON_CATALOG_EVENT_CODES)
    conn.execute(text(f"DELETE FROM notification_events WHERE event_code IN ({non_catalog})"))
    conn.execute(text(f"DELETE FROM engagement_notifications WHERE event_code IN ({non_catalog})"))


def downgrade() -> None:
    pass