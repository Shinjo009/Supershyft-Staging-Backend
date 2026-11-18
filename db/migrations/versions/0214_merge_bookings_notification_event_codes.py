"""Rename booking/consultation notification event codes under bookings.blood_test.* and bookings.consultation.*."""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0214_bookings_event_merge"
down_revision = "0213_strict_eng_notif"
branch_labels = None
depends_on = None

_EVENT_CODE_RENAMES: tuple[tuple[str, str], ...] = (
    ("bookings.confirmed", "bookings.blood_test.confirmed"),
    ("bookings.rescheduled", "bookings.blood_test.rescheduled"),
    ("bookings.cancelled", "bookings.blood_test.cancelled"),
    ("bookings.phlebo_assigned", "bookings.blood_test.phlebo_assigned"),
    ("bookings.phlebo_reassigned", "bookings.blood_test.phlebo_reassigned"),
    ("bookings.phlebo_enroute", "bookings.blood_test.phlebo_enroute"),
    ("bookings.phlebo_delayed", "bookings.blood_test.phlebo_delayed"),
    ("bookings.sample_collected", "bookings.blood_test.sample_collected"),
    ("consultations.booked", "bookings.consultation.booked"),
    ("consultations.confirmed", "bookings.consultation.confirmed"),
    ("consultations.rescheduled", "bookings.consultation.rescheduled"),
    ("consultations.cancelled", "bookings.consultation.cancelled"),
    ("consultations.completed", "bookings.consultation.completed"),
    ("assistants.consultation_booked", "bookings.consultation.booked"),
    ("consultation_booking_alert", "bookings.consultation.booked"),
    ("consultation.booked", "bookings.consultation.booked"),
)

_CANONICAL_EVENT_NAMES: tuple[tuple[str, str], ...] = (
    ("bookings.blood_test.confirmed", "Booking confirmed"),
    ("bookings.blood_test.rescheduled", "Booking rescheduled"),
    ("bookings.blood_test.cancelled", "Booking cancelled"),
    ("bookings.blood_test.phlebo_assigned", "Phlebo assigned"),
    ("bookings.blood_test.phlebo_reassigned", "Phlebo reassigned"),
    ("bookings.blood_test.phlebo_enroute", "Phlebo en route"),
    ("bookings.blood_test.phlebo_delayed", "Phlebo delayed"),
    ("bookings.blood_test.sample_collected", "Sample collected"),
    ("bookings.consultation.booked", "Consultation booked"),
    ("bookings.consultation.confirmed", "Consultation confirmed"),
    ("bookings.consultation.rescheduled", "Consultation rescheduled"),
    ("bookings.consultation.cancelled", "Consultation cancelled"),
    ("bookings.consultation.completed", "Consultation completed"),
)

_OBSOLETE_EVENT_CODES: tuple[str, ...] = (
    "assistants.consultation_booked",
    "consultation_booking_alert",
    "consultation.booked",
)

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

    values_sql = ",\n".join(f"('{old}', '{new}')" for old, new in _EVENT_CODE_RENAMES)
    _drop_rename_collisions_notification_events(conn, values_sql)
    _drop_rename_collisions_engagement(conn, values_sql)

    for table in ("notification_events", "engagement_notifications"):
        conn.execute(
            text(
                f"""
                UPDATE {table} AS t
                SET event_code = m.new_code
                FROM (VALUES {values_sql}) AS m(old_code, new_code)
                WHERE t.event_code = m.old_code
                """
            )
        )

    names_sql = ",\n".join(f"('{code}', '{name}')" for code, name in _CANONICAL_EVENT_NAMES)
    for table in ("notification_events", "engagement_notifications"):
        conn.execute(
            text(
                f"""
                UPDATE {table} AS t
                SET event_name = m.display_name
                FROM (VALUES {names_sql}) AS m(event_code, display_name)
                WHERE t.event_code = m.event_code
                """
            )
        )

    conn.execute(
        text(
            """
            DELETE FROM notification_events AS a
            USING notification_events AS b
            WHERE a.id < b.id
              AND a.event_code = b.event_code
              AND a.recipient_type = b.recipient_type
              AND a.delivery_channel = b.delivery_channel
              AND a.condition_key = b.condition_key
              AND (
                (a.engagement_type_id IS NULL AND b.engagement_type_id IS NULL)
                OR a.engagement_type_id = b.engagement_type_id
              )
            """
        )
    )
    conn.execute(
        text(
            """
            DELETE FROM engagement_notifications AS a
            USING engagement_notifications AS b
            WHERE a.id < b.id
              AND a.engagement_id = b.engagement_id
              AND a.event_code = b.event_code
              AND a.recipient_type = b.recipient_type
              AND a.delivery_channel = b.delivery_channel
              AND a.condition_key = b.condition_key
            """
        )
    )

    obsolete = ", ".join(f"'{code}'" for code in _OBSOLETE_EVENT_CODES)
    conn.execute(text(f"DELETE FROM notification_events WHERE event_code IN ({obsolete})"))
    conn.execute(text(f"DELETE FROM engagement_notifications WHERE event_code IN ({obsolete})"))

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

    conn.execute(
        text(
            """
            DELETE FROM notification_services AS ns
            WHERE ns.is_active = false
              AND NOT EXISTS (
                SELECT 1 FROM notification_events ne
                WHERE ne.notification_services::text LIKE '%' || ns.service_key || '%'
              )
              AND NOT EXISTS (
                SELECT 1 FROM engagement_notifications en
                WHERE en.notification_services::text LIKE '%' || ns.service_key || '%'
              )
              AND NOT EXISTS (
                SELECT 1 FROM notifications n
                WHERE n.service_key = ns.service_key
              )
            """
        )
    )


def downgrade() -> None:
    pass