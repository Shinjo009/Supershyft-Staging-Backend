"""Backfill notification_services content from n8n + migrate event bindings.

Revision ID: 0187_notif_backfill
Revises: 0186_engine_staging_bindings
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from modules.notifications.migration_0187_bindings import (
    EVENT_DEFAULT_RECIPIENT,
    extract_service_keys_from_json,
    map_legacy_event_code,
    merge_service_keys,
    services_json_for_keys,
)
from modules.notifications.notification_content_backfill import apply_notification_content_backfill_sync

revision = "0187_notif_backfill"
down_revision = "0186_engine_staging_bindings"
branch_labels = None
depends_on = None


def _migrate_engagement_notifications(conn) -> None:
    conn.execute(
        sa.text(
            """
            UPDATE engagement_notifications AS en
            SET event_code = CASE
                WHEN ane.event_code = 'onboarding' THEN 'onboarding.completed'
                WHEN ane.event_code = 'pretest_guidelines' THEN 'collection.reminder.pretest'
                WHEN ane.event_code = 'questionnaire_reminder_before' THEN 'assessment.reminder.before'
                WHEN ane.event_code = 'questionnaire_reminder_after' THEN 'assessment.reminder.after'
                WHEN ane.event_code = 'blood_report_ready' THEN 'report.blood.ready'
                WHEN ane.event_code = 'bioai_report_ready' THEN 'report.bioai.ready'
                WHEN ane.event_code = 'consultation_ready' THEN 'consultation.ready'
                WHEN ane.event_code = 'consultation_remainder' THEN 'consultation.reminder'
                WHEN ane.event_code = 'consultation_booking_alert' THEN 'consultation.booked'
                WHEN ane.event_code = 'booking_guide' THEN 'collection.reminder.booking_guide'
                WHEN ane.event_code = 'report_ready' THEN 'report.vifc.ready'
                ELSE ane.event_code
            END
            FROM auto_notification_events AS ane
            WHERE en.notification_event_id = ane.id
              AND (en.event_code IS NULL OR en.event_code = ane.event_code)
            """
        )
    )
    for legacy, new_code in (
        ("onboarding", "onboarding.completed"),
        ("pretest_guidelines", "collection.reminder.pretest"),
        ("questionnaire_reminder_before", "assessment.reminder.before"),
        ("questionnaire_reminder_after", "assessment.reminder.after"),
        ("blood_report_ready", "report.blood.ready"),
        ("bioai_report_ready", "report.bioai.ready"),
        ("consultation_ready", "consultation.ready"),
        ("consultation_remainder", "consultation.reminder"),
        ("consultation_booking_alert", "consultation.booked"),
        ("booking_guide", "collection.reminder.booking_guide"),
        ("report_ready", "report.vifc.ready"),
    ):
        conn.execute(
            sa.text("UPDATE engagement_notifications SET event_code = :new WHERE event_code = :old"),
            {"old": legacy, "new": new_code},
        )
    for event_code, recipient in EVENT_DEFAULT_RECIPIENT.items():
        conn.execute(
            sa.text(
                """
                UPDATE engagement_notifications
                SET recipient_type = :recipient
                WHERE event_code = :event_code AND recipient_type IS NULL
                """
            ),
            {"event_code": event_code, "recipient": recipient},
        )


def _upsert_notification_event(
    conn,
    *,
    event_code: str,
    event_name: str,
    recipient_type: str,
    service_keys: list[str],
) -> None:
    if not service_keys:
        return
    conn.execute(
        sa.text(
            """
            INSERT INTO notification_events
                (event_code, event_name, recipient_type, notification_services, is_active)
            VALUES
                (:event_code, :event_name, :recipient_type, CAST(:services AS jsonb), true)
            ON CONFLICT (event_code, recipient_type) DO UPDATE SET
                event_name = EXCLUDED.event_name,
                notification_services = EXCLUDED.notification_services,
                is_active = true
            """
        ),
        {
            "event_code": event_code,
            "event_name": event_name,
            "recipient_type": recipient_type,
            "services": services_json_for_keys(service_keys),
        },
    )


def _migrate_global_bindings(conn) -> None:
    aggregated: dict[tuple[str, str], list[str]] = {}

    default_rows = conn.execute(
        sa.text(
            """
            SELECT ane.event_code, def_row.notification_services
            FROM engagement_notification_defaults AS def_row
            JOIN auto_notification_events AS ane ON ane.id = def_row.notification_event_id
            """
        )
    ).fetchall()
    for row in default_rows:
        mapped = map_legacy_event_code(row.event_code)
        recipient = EVENT_DEFAULT_RECIPIENT.get(mapped, "participant")
        keys = extract_service_keys_from_json(row.notification_services)
        if not mapped or not keys:
            continue
        bucket = aggregated.setdefault((mapped, recipient), [])
        aggregated[(mapped, recipient)] = merge_service_keys(bucket, keys)

    for (event_code, recipient_type), keys in aggregated.items():
        _upsert_notification_event(
            conn,
            event_code=event_code,
            event_name=event_code.replace(".", " ").title(),
            recipient_type=recipient_type,
            service_keys=keys,
        )

    support_csv = conn.execute(
        sa.text("SELECT default_support_query_notification FROM platform_settings LIMIT 1")
    ).scalar()
    support_keys = [
        k.strip()
        for k in str(support_csv or "").split(",")
        if k.strip()
    ] or ["support-svc-a", "support-svc-b"]

    hardcoded: list[tuple[str, str, str, list[str]]] = [
        ("auth.otp.sent", "OTP sent", "participant", ["whatapi-otp", "email-otp"]),
        ("auth.otp.sent", "OTP sent", "employee", ["whatapi-otp", "email-otp"]),
        ("auth.otp.sent", "OTP sent", "partner", ["whatapi-otp", "email-otp"]),
        ("payment.gift.sent.booker", "Gift sent to booker", "booker", [
            "family-onboard-sender-whatsapp",
            "family-onboard-sender-email",
        ]),
        ("payment.gift.sent.member", "Gift sent to member", "family_member", [
            "family-onboard-receiver-whatsapp",
            "family-onboard-receiver-email",
        ]),
        ("collection.confirmed", "Collection confirmed", "participant", [
            "booking-confirmation-whatsapp",
            "booking-confirmation-email",
        ]),
        ("collection.phlebo.assigned", "Phlebo assigned", "participant", [
            "phlebo-assigned-whatsapp",
            "phlebo-assigned-email",
        ]),
        ("collection.phlebo.reassigned", "Phlebo reassigned", "participant", [
            "phlebo-reassigned-whatsapp",
            "phlebo-reassigned-email",
        ]),
        ("collection.phlebo.enroute", "Phlebo enroute", "participant", [
            "phlebo-enroute-whatsapp",
            "phlebo-enroute-email",
        ]),
        ("collection.phlebo.delayed", "Phlebo delayed", "participant", [
            "phlebo-delay-whatsapp",
            "phlebo-delay-email",
        ]),
        ("support.ticket.created", "Support ticket created", "admin", support_keys),
        ("system.cpu.alert", "CPU overload alert", "admin", ["cpu_above_threshold"]),
        ("consultation.booked", "Consultation booked", "oa.expert", ["consultation-booking-alert-whatsapp"]),
        ("consultation.reminder", "Consultation reminder", "participant", ["consultation-remainder-whatsapp"]),
        ("consultation.ready", "Consultation ready", "participant", ["book-doctor-consultation-whatsapp"]),
        ("collection.reminder.pretest", "Pretest reminder", "participant", ["pretest-whatsapp"]),
        ("collection.reminder.booking_guide", "Booking guide", "oa.phlebo", ["send-phlebo-booking-guide-whatsapp"]),
        ("assessment.reminder.before", "Assessment before", "participant", ["assessment-reminder-whatsapp-metsights-v2"]),
        ("assessment.reminder.after", "Assessment after", "participant", ["assessment-reminder-whatsapp-metsights-v2"]),
        ("report.blood.ready", "Blood report ready", "participant", ["send-blood-report-whatsapp"]),
        ("report.bioai.ready", "BioAI report ready", "participant", ["send-bioai-whatsapp"]),
        ("report.vifc.ready", "VIFC report ready", "participant", ["send-reports-email"]),
        ("onboarding.completed", "Onboarding completed", "oa.all", ["welcome-whatsapp", "welcome-email"]),
    ]
    for event_code, event_name, recipient_type, keys in hardcoded:
        _upsert_notification_event(
            conn,
            event_code=event_code,
            event_name=event_name,
            recipient_type=recipient_type,
            service_keys=keys,
        )


def upgrade() -> None:
    conn = op.get_bind()
    apply_notification_content_backfill_sync(conn)
    _migrate_engagement_notifications(conn)
    _migrate_global_bindings(conn)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE notification_services
            SET template_name = NULL,
                template_variables = NULL,
                email_subject = NULL,
                email_body = NULL,
                email_html = NULL
            WHERE service_key NOT IN ('whatapi-otp', 'email-otp')
            """
        )
    )
