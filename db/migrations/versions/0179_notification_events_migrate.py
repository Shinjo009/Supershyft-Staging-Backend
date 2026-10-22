"""Migrate defaults into notification_events; drop legacy event tables.

Revision ID: 0179_notification_events_migrate
Revises: 0178_eng_notif_event_code
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0179_notification_events_migrate"
down_revision = "0178_eng_notif_event_code"
branch_labels = None
depends_on = None

_RECIPIENT_BY_EVENT: dict[str, str] = {
    "onboarding": "onboarding_assistant",
    "consultation_booking_alert": "onboarding_assistant",
    "booking_guide": "partner_role",
    "pretest_guidelines": "participant",
    "questionnaire_reminder_before": "participant",
    "questionnaire_reminder_after": "participant",
    "blood_report_ready": "participant",
    "bioai_report_ready": "participant",
    "consultation_ready": "participant",
    "consultation_remainder": "participant",
    "report_ready": "participant",
    "otp_whatsapp": "participant",
    "otp_email": "participant",
    "support_query_raised": "onboarding_assistant",
    "healthians_booking_confirmed": "participant",
    "cpu_above_threshold": "admin",
}

_PLATFORM_SEEDS: list[tuple[str, str, str, list[dict]]] = [
    (
        "otp_whatsapp",
        "OTP WhatsApp",
        "participant",
        [{"service_key": "whatapi-otp"}],
    ),
    (
        "otp_email",
        "OTP Email",
        "participant",
        [{"service_key": "email-otp"}],
    ),
    (
        "support_query_raised",
        "Support Query Raised",
        "onboarding_assistant",
        [{"service_key": "support-query-whatsapp"}],
    ),
    (
        "healthians_booking_confirmed",
        "Healthians Booking Confirmed",
        "participant",
        [
            {"service_key": "booking-confirmation-whatsapp"},
            {"service_key": "booking-confirmation-email"},
        ],
    ),
    (
        "cpu_above_threshold",
        "CPU Above Threshold",
        "admin",
        [{"service_key": "cpu_above_threshold"}],
    ),
]


def _normalize_services(raw) -> list[dict]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return [{"service_key": raw}]
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if isinstance(item, str):
            out.append({"service_key": item})
        elif isinstance(item, dict) and item.get("service_key"):
            out.append({"service_key": str(item["service_key"])})
    return out


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(
        sa.text(
            """
            SELECT ane.event_code, ane.display_name, endef.notification_services
            FROM engagement_notification_defaults endef
            JOIN auto_notification_events ane ON ane.id = endef.notification_event_id
            """
        )
    ).fetchall()

    merged: dict[tuple[str, str], list[dict]] = {}
    names: dict[str, str] = {}
    for row in rows:
        event_code = row.event_code
        names[event_code] = row.display_name
        recipient = _RECIPIENT_BY_EVENT.get(event_code, "participant")
        services = _normalize_services(row.notification_services)
        if not services:
            continue
        key = (event_code, recipient)
        existing = merged.get(key, [])
        if len(services) > len(existing):
            merged[key] = services

    for (event_code, recipient), services in merged.items():
        conn.execute(
            sa.text(
                """
                INSERT INTO notification_events
                    (event_code, event_name, recipient_type, notification_services)
                VALUES (:event_code, :event_name, :recipient_type, CAST(:services AS jsonb))
                ON CONFLICT (event_code, recipient_type) DO UPDATE
                SET notification_services = EXCLUDED.notification_services,
                    event_name = EXCLUDED.event_name
                """
            ),
            {
                "event_code": event_code,
                "event_name": names.get(event_code, event_code),
                "recipient_type": recipient,
                "services": json.dumps(services),
            },
        )

    for event_code, event_name, recipient, services in _PLATFORM_SEEDS:
        conn.execute(
            sa.text(
                """
                INSERT INTO notification_events
                    (event_code, event_name, recipient_type, notification_services)
                VALUES (:event_code, :event_name, :recipient_type, CAST(:services AS jsonb))
                ON CONFLICT (event_code, recipient_type) DO NOTHING
                """
            ),
            {
                "event_code": event_code,
                "event_name": event_name,
                "recipient_type": recipient,
                "services": json.dumps(services),
            },
        )

    op.drop_table("engagement_notification_defaults")
    op.drop_table("auto_notification_events")


def downgrade() -> None:
    raise NotImplementedError("0179 downgrade not supported")
